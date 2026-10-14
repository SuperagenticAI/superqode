from types import SimpleNamespace

import pytest

from superqode.harness.transitions import plan_transition
from superqode.app.mixins.feedback import FeedbackMixin


@pytest.mark.parametrize("target", ["pipy", "codegem", "codex-cli", "claude-agent-sdk"])
def test_native_boundary_change_requires_review(target):
    plan = plan_transition("builtin", target, active=True)
    assert plan.requires_acknowledgement
    assert plan.details


def test_initial_selection_and_same_runtime_do_not_interrupt():
    assert not plan_transition("builtin", "codegem", active=False).requires_acknowledgement
    assert not plan_transition("codegem", "codegem", active=True).requires_acknowledgement


def test_context_replay_is_explicit():
    plan = plan_transition(
        "builtin", "acp", connector="acp", continuity="context-replay", active=True
    )
    assert plan.requires_acknowledgement
    assert any("runtime state" in reason for reason in plan.reasons)


class Host(FeedbackMixin):
    def __init__(self):
        self._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True, harness_runtime="builtin")
        )
        self.identity = 1
        self.is_busy = False
        self.notifications = []

    def _connection_fingerprint(self):
        return self.identity

    def push_screen(self, screen, callback):
        self.screen = screen
        self.callback = callback

    def notify(self, message, **kwargs):
        self.notifications.append(message)


def test_cancel_has_no_connection_side_effects():
    host = Host()
    calls = []
    assert host._review_route_transition("codegem", "", "", lambda: calls.append("applied"))
    host.callback(False)
    assert not calls
    assert host._pure_mode.session.connected
    assert host._pure_mode.session.harness_runtime == "builtin"


def test_accept_is_action_scoped_and_bound_to_current_source():
    host = Host()
    calls = []

    def apply():
        assert not host._review_route_transition("codegem", "", "", apply)
        calls.append("applied")

    assert host._review_route_transition("codegem", "", "", apply)
    host.callback(True)
    assert calls == ["applied"]
    assert host._route_transition_ack is None
    assert host._review_route_transition("codegem", "", "", apply)
    host.identity = 2
    host.callback(True)
    assert calls == ["applied"]
    assert host.notifications


def test_busy_source_refuses_delayed_acceptance():
    host = Host()
    calls = []
    host._review_route_transition("codegem", "", "", lambda: calls.append("applied"))
    host.is_busy = True
    host.callback(True)
    assert not calls


@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
async def test_mounted_route_review_escape_preserves_selection(size):
    from textual.app import App
    from superqode.widgets.route_transition import RouteTransitionScreen

    class ReviewApp(App):
        def on_mount(self):
            self.answers = []
            self.push_screen(
                RouteTransitionScreen(plan_transition("builtin", "codegem", active=True)),
                self.answers.append,
            )

    app = ReviewApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#route-keep")
        await pilot.press("escape")
        await pilot.pause()
        assert app.answers == [False]


async def test_mounted_route_review_explicit_accept():
    from textual.app import App
    from superqode.widgets.route_transition import RouteTransitionScreen

    class ReviewApp(App):
        def on_mount(self):
            self.answers = []
            self.push_screen(
                RouteTransitionScreen(plan_transition("builtin", "pipy", active=True)),
                self.answers.append,
            )

    app = ReviewApp()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#route-accept")
        await pilot.pause()
        assert app.answers == [True]


def test_nested_acp_dispatch_reuses_review_only_during_accepted_action():
    host = Host()
    calls = []

    def dispatch():
        assert not host._review_route_transition("acp", "acp", "context-replay", dispatch)
        # Profile dispatch calls the direct ACP handler synchronously.
        assert not host._review_route_transition("acp", "acp", "context-replay", dispatch)
        calls.append("connected")

    assert host._review_route_transition("acp", "acp", "context-replay", dispatch)
    host.callback(True)
    assert calls == ["connected"]
    assert host._route_transition_ack is None
    assert host._review_route_transition("acp", "acp", "context-replay", dispatch)
