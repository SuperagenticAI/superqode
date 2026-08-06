"""Browser-style back: history, not hierarchy."""

from __future__ import annotations

from superqode.app.navigation import NavigationHistory


def _history_with(*keys):
    history = NavigationHistory()
    seen: list[str] = []
    for key in keys:
        history.visit(key, key.title(), lambda k=key: seen.append(k))
    return history, seen


def test_a_single_screen_has_nowhere_to_go_back_to():
    history, _ = _history_with("root")

    assert history.can_go_back is False
    assert history.back() is False
    assert history.previous_label == ""


def test_back_returns_to_the_previous_screen():
    history, seen = _history_with("root", "agents", "vendors")

    assert history.previous_label == "Agents"
    assert history.back() is True

    assert seen == ["agents"], "the previous screen was not redrawn"
    assert history.previous_label == "Root"


def test_back_walks_the_path_actually_taken():
    """Not the declared parent: the user may have arrived from anywhere."""
    history, seen = _history_with("root", "harness", "models", "plan")

    while history.back():
        pass

    assert seen == ["models", "harness", "root"]


def test_redrawing_the_same_screen_is_not_a_navigation_step():
    """Moving the highlight redraws the screen; that is not a visit."""
    history, seen = _history_with("root", "agents")
    history.visit("agents", "Agents", lambda: seen.append("agents-again"))

    assert history.back() is True
    assert seen == ["root"]
    assert history.can_go_back is False


def test_restoring_a_screen_does_not_record_it_again():
    """Otherwise back would push what it just popped and never move."""
    history = NavigationHistory()
    order: list[str] = []

    def draw(key):
        def _draw():
            order.append(key)
            # A real screen records itself as it draws.
            history.visit(key, key, draw(key))

        return _draw

    for key in ("root", "agents"):
        history.visit(key, key, draw(key))

    assert history.back() is True
    assert history.can_go_back is False
    assert order == ["root"]


def test_history_is_bounded():
    history = NavigationHistory(limit=5)
    for index in range(20):
        history.visit(f"screen-{index}", "s", lambda: None)

    assert len(history._stack) == 5


def test_clear_forgets_everything():
    history, _ = _history_with("root", "agents")
    history.clear()

    assert history.can_go_back is False


def test_back_from_a_result_returns_to_the_list_it_was_chosen_from():
    """Picking an agent draws a result, which is not a navigation step.

    Without this, back popped the list the user had just chosen from and
    landed them on the category screen above it, so returning to the agent
    listing or the subscriptions list was impossible.
    """
    drawn: list[str] = []
    history = NavigationHistory()
    history.visit("root", "Connect", lambda: drawn.append("root"))
    history.visit("agents", "Existing harnesses", lambda: drawn.append("agents"))
    history.visit("vendors", "Subscriptions", lambda: drawn.append("vendors"))

    history.detach()  # a subscription was chosen; its panel is on screen

    assert history.can_go_back is True
    assert history.previous_label == "Subscriptions"

    assert history.back() is True
    assert drawn[-1] == "vendors", "back must return to the list, not past it"

    assert history.back() is True
    assert drawn[-1] == "agents", "the list is still a step of its own"


def test_a_recorded_screen_clears_the_detached_mark():
    """Navigating on from a result makes the next screen a real step again."""
    drawn: list[str] = []
    history = NavigationHistory()
    history.visit("root", "Connect", lambda: drawn.append("root"))
    history.detach()
    history.visit("agents", "Existing harnesses", lambda: drawn.append("agents"))

    assert history.back() is True
    assert drawn[-1] == "root"


def test_detaching_during_a_restore_is_ignored():
    """A restore redraws a screen; that redraw is not a new result."""
    history = NavigationHistory()

    def restore_that_detaches():
        history.detach()

    history.visit("root", "Connect", lambda: None)
    history.visit("agents", "Existing harnesses", restore_that_detaches)
    history.visit("vendors", "Subscriptions", lambda: None)

    assert history.back() is True  # restores "agents", which calls detach()
    assert history.back() is True
    assert history.can_go_back is False, "a redraw must not add a step"
