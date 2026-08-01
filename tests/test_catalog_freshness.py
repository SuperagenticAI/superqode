"""Catalogue data stays current without the user ever waiting for it.

The rule: a read never touches the network, refresh is always a background
timer, and neither blocks. The ACP registry broke that rule by never
refreshing itself at all, so a cache could sit untouched for months.
"""

from __future__ import annotations

import os
import pathlib
from datetime import UTC, datetime
from unittest import mock

from superqode.app.mixins.model_catalog import ModelCatalogMixin


def _with_cache_age(seconds_old: float):
    """Pretend both cache files were written this long ago."""
    stamp = datetime.now(UTC).timestamp() - seconds_old
    fake = os.stat_result((0,) * 7 + (0, int(stamp), 0))
    return mock.patch.object(pathlib.Path, "stat", return_value=fake)


class _StatusStub(ModelCatalogMixin):
    _welcome_active = True

    def __init__(self, **status):
        self._catalog_status = dict(status)
        self.lines: list[str] = []

    def query_one(self, *args, **kwargs):
        return self

    def add_meta(self, text, icon="·"):
        self.lines.append(text)


# --- the refresh happens on a timer, off the read path -----------------------


def test_the_registry_refreshes_on_the_same_schedule_as_models_dev():
    """models.dev already did this; the agent registry silently did not."""
    source = pathlib.Path("src/superqode/app_main.py").read_text(encoding="utf-8")

    for call in (
        "self.set_timer(0.5, self._start_models_dev_refresh)",
        "self.set_interval(60 * 60, self._start_models_dev_refresh)",
        "self.set_timer(0.5, self._start_acp_registry_refresh)",
        "self.set_interval(60 * 60, self._start_acp_registry_refresh)",
    ):
        assert call in source, call


def test_refreshes_run_as_background_workers():
    """A fetch on the path a screen is drawn on is how a screen gets slow."""
    calls = []

    class WorkerStub(ModelCatalogMixin):
        def run_worker(self, work, **kwargs):
            calls.append(kwargs)

    stub = WorkerStub()
    stub._start_acp_registry_refresh()

    assert calls and calls[0]["exclusive"] is True
    assert calls[0]["exit_on_error"] is False


async def test_a_failed_refresh_leaves_the_cache_alone():
    """Offline is normal. It must not clear anything or raise."""

    class FailingStub(ModelCatalogMixin):
        _catalog_status: dict = {}

    stub = FailingStub()
    stub._catalog_status = {}
    with mock.patch(
        "superqode.providers.acp_registry.get_acp_registry_agents",
        side_effect=OSError("offline"),
    ):
        await stub._load_acp_registry_data()

    assert stub._catalog_status.get("agents") is None


# --- the status line is honest ------------------------------------------------


def test_cache_age_reads_as_plain_english():
    for seconds, expected in (
        (60, "updated just now"),
        (20 * 60, "updated 20m ago"),
        (3 * 3600, "cached, 3h old"),
        (9 * 86400, "cached, 9d old"),
    ):
        with _with_cache_age(seconds):
            assert ModelCatalogMixin._catalog_cache_age() == expected


def test_no_cache_at_all_says_bundled_rather_than_failing():
    def boom(self, *args, **kwargs):
        raise OSError("no cache here")

    with mock.patch.object(pathlib.Path, "stat", boom):
        assert ModelCatalogMixin._catalog_cache_age() == "using bundled lists"


def test_the_status_line_reports_what_it_actually_has():
    with _with_cache_age(60):
        stub = _StatusStub(agents=38)
        stub._report_catalog_freshness()

    assert stub.lines
    line = stub.lines[0]
    assert "38 ACP agents" in line
    assert "updated just now" in line


def test_an_offline_launch_still_reports_rather_than_alarms():
    """No agent count because the fetch failed; the line still makes sense."""
    with _with_cache_age(3 * 3600):
        stub = _StatusStub()
        stub._report_catalog_freshness()

    assert stub.lines
    assert "cached, 3h old" in stub.lines[0]
    assert "fail" not in stub.lines[0].lower()
    assert "error" not in stub.lines[0].lower()


def test_nothing_is_said_when_there_is_nothing_to_say():
    """No providers and no agents means no line, not an empty one."""
    stub = _StatusStub()
    with mock.patch.object(
        ModelCatalogMixin, "_catalog_freshness_providers", staticmethod(lambda: 0)
    ):
        stub._report_catalog_freshness()

    assert stub.lines == []


def test_status_line_stays_off_once_welcome_is_gone():
    """Pickers replace the home screen; the timer must not append under them."""
    stub = _StatusStub(agents=38)
    stub._welcome_active = False
    stub._report_catalog_freshness()
    assert stub.lines == []


def test_status_line_stays_off_while_a_picker_owns_the_viewport():
    """A late catalogue line yanks scroll and hides the highlighted row."""
    stub = _StatusStub(agents=38)
    stub._awaiting_byok_provider = True
    stub._report_catalog_freshness()
    assert stub.lines == []


def test_the_status_line_never_raises_out():
    """It runs on a launch timer, so a failure here would break startup."""

    class Broken(ModelCatalogMixin):
        _welcome_active = True
        _catalog_status: dict = {}

        def query_one(self, *args, **kwargs):
            raise RuntimeError("no log widget")

    Broken()._report_catalog_freshness()
