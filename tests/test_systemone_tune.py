"""Tuning must preserve the decision contract and keep test labels sealed."""

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace

import pytest
from click.testing import CliRunner
from textual.app import App
from textual.widgets import Input, Select, Static

from superqode.commands.harness import harness
from superqode.harness.loader import load_harness_spec
from superqode.systemone import tune
from superqode.systemone.client import StubSystemOneClient
from superqode.systemone.pack import load_pack
from superqode.widgets.systemone_tune import SystemOneTuneScreen


def examples(n=12):
    return [
        {
            "id": str(i),
            "state": f"Example task {i}",
            "label": "review" if i % 2 else "cheap",
            "split": "",
            "group": "",
            "rationale": "reviewed boundary",
        }
        for i in range(n)
    ]


def prepare(tmp_path, rows=None):
    out = tmp_path / "run"
    tune.prepare_run(
        tune.TuneOptions(reflection_lm="fake/model", max_evals=30), rows or examples(), out
    )
    return out


class CandidateClient:
    name = "test"

    async def evaluate(self, state, questions):
        improved = "improved criteria" in json.dumps(questions)
        index = int(state["task"].split()[-1])
        label = ("review" if index % 2 else "cheap") if improved else "cheap"
        return await StubSystemOneClient({"route": {"choice": label, "confidence": 0.99}}).evaluate(
            state, questions
        )


def improve(**kwargs):
    assert "test_set" not in kwargs
    candidate = dict(kwargs["seed_candidate"])
    candidate[next(iter(candidate))] = "improved criteria"
    for row in kwargs["dataset"] + kwargs["valset"]:
        assert row["split"] != "test"
        kwargs["evaluator"](candidate, row)
    return SimpleNamespace(best_candidate=candidate)


def test_codec_preserves_nested_structure_and_policy():
    pack = load_pack("factory_route")
    codec = tune.PackCodec(pack)
    assert codec.decode(codec.seed) == pack
    changed = dict(codec.seed)
    changed[next(iter(changed))] = "Better instruction"
    result = codec.decode(changed)
    assert result.decision_policy == pack.decision_policy
    assert result.state_schema == pack.state_schema
    assert result.questions["route"].options == pack.questions["route"].options
    assert result.content_hash() != pack.content_hash()
    with pytest.raises(ValueError, match="preserve"):
        codec.decode({**changed, "decision_policy": "relax"})
    with pytest.raises(ValueError, match="characters"):
        codec.decode({key: "" for key in codec.seed})


def test_round_trip_stages_loadable_harness_and_seals_test(tmp_path):
    out = prepare(tmp_path)
    manifest = tune.load_run(out)
    sealed = {row["id"] for row in manifest["examples"] if row["split"] == "test"}
    seen = set()

    def optimizer(**kwargs):
        seen.update(row["id"] for row in kwargs["dataset"] + kwargs["valset"])
        return improve(**kwargs)

    report = tune.run_tune(out, client=CandidateClient(), optimizer=optimizer)
    assert not seen & sealed
    assert report["candidate"]["score"] == 1
    assert report["pilot"] and not report["eligible"]
    assert report["heldout_evals"] == 2 * len(sealed)
    spec = load_harness_spec(report["candidate_harness"])
    assert load_pack(spec.systemone.pack).content_hash() == report["candidate_pack_hash"]
    assert tune.load_run(out)["pack"] == manifest["pack"]
    assert tune.run_tune(out) == report  # Completed runs never call a provider again.


def test_errors_never_qualify_for_adoption(tmp_path):
    out = prepare(tmp_path)
    report = tune.run_tune(
        out, client=StubSystemOneClient(error=RuntimeError("private error")), optimizer=improve
    )
    assert report["candidate"]["errors"] == report["candidate"]["total"]
    assert not report["eligible"] and not report["gate_passed"]
    assert "private error" not in (out / "evaluations.json").read_text()


def test_abstention_does_not_count_as_correct(tmp_path):
    out = prepare(tmp_path)
    client = StubSystemOneClient({"route": {"choice": "review", "confidence": 0.1}})
    report = tune.run_tune(out, client=client, optimizer=improve)
    assert report["candidate"]["score"] == 0
    assert report["candidate"]["coverage"] == 0
    assert report["candidate"]["abstentions"] > 0


def test_invalid_candidate_is_rejected_before_client_call(tmp_path):
    out = prepare(tmp_path)
    client = StubSystemOneClient()

    def invalid(**kwargs):
        kwargs["evaluator"]({"threshold": "0"}, kwargs["dataset"][0])

    with pytest.raises(ValueError, match="preserve"):
        tune.run_tune(out, client=client, optimizer=invalid)
    assert not client.calls
    assert tune.load_run(out)["status"] == "failed"


def test_cancel_saves_state_and_prevents_further_calls(tmp_path):
    out = prepare(tmp_path)
    cancel = threading.Event()
    client = StubSystemOneClient()

    def cancelled(**kwargs):
        cancel.set()
        kwargs["evaluator"](kwargs["seed_candidate"], kwargs["dataset"][0])

    with pytest.raises(tune.TuneCancelled):
        tune.run_tune(out, client=client, optimizer=cancelled, cancel=cancel)
    assert not client.calls
    assert tune.load_run(out)["status"] == "cancelled"
    with pytest.raises(ValueError, match="already started"):
        tune.run_tune(out, client=client, optimizer=improve)


def test_label_save_is_resumable_and_redacted(tmp_path):
    rows = examples()
    rows[0]["label"] = None
    out = prepare(tmp_path, rows)
    with pytest.raises(ValueError, match="Review every"):
        tune.run_tune(out, client=StubSystemOneClient(), optimizer=improve)
    tune.save_label(out, "0", "review", "Correct route")
    restored = tune.load_run(out)
    assert next(row for row in restored["examples"] if row["id"] == "0")["label"] == "review"
    assert (out / "run.json").stat().st_mode & 0o777 == 0o600


def test_duplicate_input_rejected_across_splits():
    rows = examples()
    rows[-1]["state"] = rows[0]["state"]
    rows[-1]["split"] = "test"
    with pytest.raises(ValueError, match="Duplicate"):
        tune.normalize_examples(rows, load_pack("factory_route"))


def test_group_boundaries_preserved():
    rows = examples(30)
    for index, row in enumerate(rows):
        row["group"] = str(index // 3)
    split = tune.split_examples(tune.normalize_examples(rows, load_pack("factory_route")))
    owners = {}
    for name, members in split.items():
        for row in members:
            assert owners.setdefault(row["group"], name) == name


def test_explicit_group_leakage_rejected():
    rows = examples()
    for index, row in enumerate(rows):
        row["split"] = "test" if index % 3 == 0 else "train"
        row["group"] = "same session"
    with pytest.raises(ValueError, match="groups cannot cross"):
        tune.split_examples(tune.normalize_examples(rows, load_pack("factory_route")))


def test_import_csv_with_custom_columns(tmp_path):
    file = tmp_path / "rows.csv"
    file.write_text('request,route,rationale\n"review this patch",review,security\n')
    rows = tune.read_examples(file, input_column="request", label_column="route")
    assert rows[0]["state"] == "review this patch"
    assert rows[0]["label"] == "review"


def test_import_multiline_csv_preserves_input(tmp_path):
    file = tmp_path / "rows.csv"
    file.write_text('state,label\n"line one\nline two",review\n')
    assert tune.read_examples(file)[0]["state"] == "line one\nline two"


def test_saved_state_and_rationale_redact_credentials(tmp_path):
    rows = examples()
    rows[0]["state"] = {"task": "Review this change", "api_key": "private-key"}
    rows[0]["rationale"] = "API_KEY=private-rationale"
    out = prepare(tmp_path, rows)
    saved = (out / "run.json").read_text()
    assert "private-key" not in saved
    assert "private-rationale" not in saved
    assert "[redacted]" in saved


def test_unknown_labels_and_missing_splits_rejected():
    rows = examples()
    rows[0]["label"] = "imaginary"
    with pytest.raises(ValueError, match="Unknown label"):
        tune.normalize_examples(rows, load_pack("factory_route"))
    rows = examples()
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="every row"):
        tune.split_examples(tune.normalize_examples(rows, load_pack("factory_route")))


def test_refuse_overwrite(tmp_path):
    out = prepare(tmp_path)
    with pytest.raises(ValueError, match="never overwritten"):
        tune.prepare_run(tune.TuneOptions(), examples(), out)


def test_eligible_candidate_and_tamper_check(tmp_path):
    out = prepare(tmp_path, examples(160))

    def candidate_only(**kwargs):
        candidate = dict(kwargs["seed_candidate"])
        candidate[next(iter(candidate))] = "improved criteria"
        kwargs["evaluator"](candidate, kwargs["valset"][0])
        return SimpleNamespace(best_candidate=candidate)

    # Larger validation sets need enough budget even for the baseline.
    manifest = tune.load_run(out)
    manifest["options"]["max_evals"] = 120
    tune.write_json(out / "run.json", manifest)
    report = tune.run_tune(out, client=CandidateClient(), optimizer=candidate_only)
    assert report["eligible"]
    assert tune.candidate_use_path(report) == report["candidate_harness"]
    pack = out / "candidate-pack.yaml"
    pack.write_text(pack.read_text().replace("improved criteria", "unmeasured edit"))
    with pytest.raises(ValueError, match="question pack has changed"):
        tune.candidate_use_path(report)


def test_regression_rejects_even_when_overall_score_improves(tmp_path):
    rows = examples(160)
    out = prepare(tmp_path, rows)
    manifest = tune.load_run(out)
    test_rows = [row for row in manifest["examples"] if row["split"] == "test"]
    regress_id = next(row["id"] for row in test_rows if row["label"] == "cheap")
    manifest["options"]["max_evals"] = 120
    tune.write_json(out / "run.json", manifest)

    class RegressClient(CandidateClient):
        async def evaluate(self, state, questions):
            if "improved criteria" in json.dumps(questions) and state["task"].endswith(
                " " + regress_id
            ):
                return await StubSystemOneClient(
                    {"route": {"choice": "review", "confidence": 0.99}}
                ).evaluate(state, questions)
            return await super().evaluate(state, questions)

    def candidate_only(**kwargs):
        candidate = dict(kwargs["seed_candidate"])
        candidate[next(iter(candidate))] = "improved criteria"
        return SimpleNamespace(best_candidate=candidate)

    report = tune.run_tune(out, client=RegressClient(), optimizer=candidate_only)
    assert report["improved"] and report["regressions"] == [regress_id]
    assert not report["eligible"]


def test_active_run_cannot_start_twice_or_change_labels(tmp_path):
    out = prepare(tmp_path)
    (out / "active.lock").write_text("123")
    with pytest.raises(ValueError, match="already active"):
        tune.run_tune(out)
    with pytest.raises(ValueError, match="labels are frozen"):
        tune.save_label(out, "0", "review")
    assert (out / "active.lock").exists()


def test_installer_targets_running_python_without_shell(monkeypatch):
    import subprocess
    import sys

    calls = []

    def install(command, **kwargs):
        calls.append(command)
        assert not kwargs.get("shell")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", install)
    assert "Restart" in tune.install_support()
    assert sys.executable in calls[0]
    assert tune.GEPA_REQUIREMENT in calls[0]
    assert "cloudpickle>=3" in calls[0]


def test_preflight_rejects_replay_and_offline(tmp_path, monkeypatch):
    out = prepare(tmp_path)
    monkeypatch.setenv("SUPERQODE_SYSTEMONE", "replay")
    with pytest.raises(ValueError, match="live Jev"):
        tune.preflight(tune.load_run(out), check_gepa=False)


def test_cli_help_and_noninteractive_missing_data():
    runner = CliRunner()
    assert runner.invoke(harness, ["tune", "--help"]).exit_code == 0
    result = runner.invoke(harness, ["tune", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["status"] == "error"


def test_cli_completed_resume_has_no_model_calls(tmp_path):
    out = prepare(tmp_path)
    tune.run_tune(out, client=CandidateClient(), optimizer=improve)
    result = CliRunner().invoke(harness, ["tune", "--resume", str(out), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "completed"


def test_cli_unlabeled_data_persists_for_review(tmp_path):
    rows = examples()
    rows[0]["label"] = None
    data = tmp_path / "rows.json"
    data.write_text(json.dumps(rows))
    out = tmp_path / "saved"
    result = CliRunner().invoke(
        harness, ["tune", "--data", str(data), "--output", str(out), "--json"]
    )
    assert result.exit_code == 2
    assert "Unlabeled" in json.loads(result.output)["error"]
    assert tune.load_run(out)["status"] == "review"


def test_cli_json_live_round_trip(tmp_path, monkeypatch):
    out = prepare(tmp_path)
    monkeypatch.setattr(tune, "preflight", lambda *args, **kwargs: {})
    original = tune.run_tune
    monkeypatch.setattr(
        tune,
        "run_tune",
        lambda output, **kwargs: original(
            output, client=CandidateClient(), optimizer=improve, **kwargs
        ),
    )
    result = CliRunner().invoke(
        harness,
        ["tune", "--resume", str(out), "--reflection-lm", "fake/new-model", "--live", "--json"],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["candidate"]["score"] == 1
    assert report["reflection_model"] == "fake/new-model"


class TuneApp(App):
    def on_mount(self):
        self.push_screen(SystemOneTuneScreen())


@pytest.mark.asyncio
async def test_tui_prepares_demo_and_shows_explicit_start(tmp_path, monkeypatch):
    monkeypatch.setattr(tune, "new_output", lambda: tmp_path / "demo")
    app = TuneApp()
    async with app.run_test(size=(100, 48)) as pilot:
        screen = app.screen
        screen.prepare()
        await pilot.pause()
        assert screen.query_one("#tune-start").display
        assert not screen.query_one("#tune-use").display
        assert "small demos" in str(screen.query_one("#tune-status", Static).render()).lower()
        assert tune.load_run(tmp_path / "demo")["status"] == "review"


@pytest.mark.asyncio
async def test_tui_labels_and_resumes(tmp_path, monkeypatch):
    rows = examples()
    rows[0]["label"] = None
    out = prepare(tmp_path, rows)
    app = TuneApp()
    async with app.run_test(size=(100, 48)) as pilot:
        screen = app.screen
        screen.query_one("#tune-resume", Input).value = str(out)
        screen.prepare()
        await pilot.pause()
        assert screen.pending[0]["id"] == "0"
        screen.query_one("#tune-choice", Select).value = "cheap"
        screen.save()
        await pilot.pause()
        assert not screen.pending
        assert screen.query_one("#tune-start").display


@pytest.mark.asyncio
async def test_tui_completed_run_exposes_diff_but_not_pilot_adoption(tmp_path):
    out = prepare(tmp_path)
    await asyncio.to_thread(tune.run_tune, out, client=CandidateClient(), optimizer=improve)
    app = TuneApp()
    async with app.run_test(size=(100, 48)) as pilot:
        screen = app.screen
        screen.query_one("#tune-resume", Input).value = str(out)
        screen.prepare()
        await pilot.pause()
        assert screen.query_one("#tune-diff").display
        assert not screen.query_one("#tune-use").display


@pytest.mark.asyncio
async def test_tui_start_worker_produces_report(tmp_path, monkeypatch):
    out = prepare(tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(tune, "missing_tune_credentials", lambda **kwargs: [])
    monkeypatch.setattr(tune, "tuning_support_available", lambda: True)
    monkeypatch.setattr(
        tune,
        "preflight",
        lambda *args, **kwargs: {
            "model": "fake",
            "endpoint": "local test",
            "reflection_model": "fake",
        },
    )
    original = tune.run_tune
    main_thread = threading.get_ident()

    def run(output, **kwargs):
        assert threading.get_ident() != main_thread
        return original(output, client=CandidateClient(), optimizer=improve, **kwargs)

    monkeypatch.setattr(tune, "run_tune", run)
    app = TuneApp()
    async with app.run_test(size=(100, 48)) as pilot:
        screen = app.screen
        screen.query_one("#tune-resume", Input).value = str(out)
        screen.prepare()
        button = screen.query_one("#tune-start")
        button.scroll_visible(immediate=True)
        await pilot.pause()
        await pilot.click("#tune-start")
        await screen.workers.wait_for_complete()
        await pilot.pause()
        assert screen.report is not None
        assert screen.report["candidate"]["score"] == 1
        assert not screen.running


@pytest.mark.asyncio
async def test_hub_opens_tune_for_systemone():
    from superqode.app.harness_picker import HarnessPickerItem
    from superqode.widgets.harness_hub import HarnessHubScreen

    class HubApp(App):
        selection = None

        def on_mount(self):
            item = HarnessPickerItem(
                id="systemone",
                display_name="SystemOne",
                description="Decisions",
                runtime="builtin",
                source="built-in",
                group="SuperQode harnesses",
                available=True,
                issue="",
                continuity="same-session",
            )
            self.push_screen(HarnessHubScreen([item]), callback=self.selected)

        def selected(self, result):
            self.selection = result

    app = HubApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#hub-tune").display
        await pilot.click("#hub-tune")
        await pilot.pause()
        assert app.selection.action == "tune"
        assert app.selection.item_id == "systemone"


def test_real_gepa_api_with_local_reflector(tmp_path):
    pytest.importorskip("gepa.optimize_anything")
    out = prepare(tmp_path)
    reflections = []

    def local_reflection(prompt):
        reflections.append(prompt)
        return "```\nimproved criteria\n```"

    def actual_optimizer(**kwargs):
        kwargs["options"] = replace(kwargs["options"], reflection_lm=local_reflection)
        return tune._gepa_optimize(**kwargs)

    report = tune.run_tune(out, client=CandidateClient(), optimizer=actual_optimizer)
    assert reflections
    assert report["candidate"]["score"] == 1
    assert report["optimization_evals"] <= 30
