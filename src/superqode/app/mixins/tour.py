"""``:tour`` — the ownership ladder, scored against what you have actually done.

A scripted walkthrough that plays the same way for everybody is a slideshow, and
people close slideshows. This tour is a checklist instead: each rung declares a
milestone, and the screen marks it done the moment the real thing happens. So
running ``:tour`` after a session shows visible progress rather than replaying
step one, and the rungs the user already climbed never ask for their attention
again.

The ladder is the product's spine: use somebody else's agent, then keep your own
context across agents, then own the harness, then measure it.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from superqode.app.constants import THEME
from superqode.app.widgets import ConversationLog


@dataclass(frozen=True)
class TourStep:
    """One rung: what it is, why it matters, and the command that does it."""

    id: str
    milestone: str
    title: str
    why: str
    command: str
    detail: str


#: In climbing order. Every ``milestone`` here must exist in
#: :data:`superqode.app.progress.MILESTONES`, or the step can never complete.
TOUR_STEPS: tuple[TourStep, ...] = (
    TourStep(
        id="connect",
        milestone="connected",
        title="Connect something",
        why="A vendor agent, your own API key, or a local model. All three work.",
        command=":connect",
        detail=(
            "Three doors: an agent someone else built, a model you bring, or a "
            "harness you author. Start with whatever you already pay for."
        ),
    ),
    TourStep(
        id="work",
        milestone="task_completed",
        title="Get one task done",
        why="Everything after this is about keeping what that run taught you.",
        command="",
        detail=(
            "Just type what you want built. The session is durable from the "
            "first message, so nothing here is a throwaway experiment."
        ),
    ),
    TourStep(
        id="explore",
        milestone="explored",
        title="See the whole surface",
        why="Memory, sandboxes, evaluation and delivery are already installed.",
        command=":explore",
        detail=(
            "Every category with its live state on this machine. Rows are "
            "probes, not documentation, so what it shows is what you have."
        ),
    ),
    TourStep(
        id="memory",
        milestone="used_memory",
        title="Keep what it learned",
        why="Facts you store outlive the agent that learned them.",
        command=":memory remember",
        detail=(
            "Repository knowledge belongs to the repository, not to a vendor's "
            "chat history. It survives every agent and harness switch below."
        ),
    ),
    TourStep(
        id="switch",
        milestone="switched_harness",
        title="Swap the agent, keep the session",
        why="This is the part no single-vendor tool can do.",
        command=":harness switch",
        detail=(
            "Context replays into the new harness. Comparing two agents on the "
            "same task stops being a migration and becomes one command."
        ),
    ),
    TourStep(
        id="build",
        milestone="built_harness",
        title="Own the harness",
        why="Import the config this repository already has, and it is yours.",
        command=":connect build",
        detail=(
            "AGENTS.md or CLAUDE.md becomes a HarnessSpec you can read, diff "
            "and review. Model policy, tools and approvals stop being hidden."
        ),
    ),
    TourStep(
        id="eval",
        milestone="ran_eval",
        title="Measure it",
        why="Opinions about which agent is better are cheap. Scores are not.",
        command=":eval",
        detail=(
            "Tasks, rubrics and gates run against your repository. Once you "
            "have numbers, :harness optimize can improve against them."
        ),
    ),
)


def tour_state(milestones: set[str] | None = None) -> tuple[list[bool], int]:
    """Return per-step completion and the index of the first unfinished step.

    Returns ``len(TOUR_STEPS)`` as the index when every rung is done, which the
    renderer treats as the finished state.
    """
    if milestones is None:
        try:
            from superqode.app.progress import load_progress

            milestones = load_progress().milestones
        except Exception:  # noqa: BLE001 - the tour must render without state
            milestones = set()

    done = [step.milestone in milestones for step in TOUR_STEPS]
    current = next((index for index, ok in enumerate(done) if not ok), len(TOUR_STEPS))
    return done, current


class TourMixin:
    """The ``:tour`` command and its rendering."""

    def _tour_cmd(self, args: str, log: ConversationLog) -> None:
        """Show the ladder, or act on one step.

        ``:tour`` renders progress, ``:tour next`` runs the current step's
        command, and ``:tour <n>`` opens one rung's card without running it.
        """
        argument = (args or "").strip().lower()
        done, current = tour_state()

        if argument in ("next", "go", "start"):
            if current >= len(TOUR_STEPS):
                self._render_tour(log, focus=len(TOUR_STEPS) - 1)
                return
            command = TOUR_STEPS[current].command
            if not command:
                self._render_tour(log, focus=current)
                return
            log.clear()
            self._handle_command(command, log)
            return

        focus = current if current < len(TOUR_STEPS) else len(TOUR_STEPS) - 1
        if argument.isdigit():
            index = int(argument) - 1
            if 0 <= index < len(TOUR_STEPS):
                focus = index
        elif argument:
            match = next((i for i, step in enumerate(TOUR_STEPS) if argument in step.id), None)
            if match is not None:
                focus = match

        self._record_milestone("toured")
        self._render_tour(log, focus=focus, done=done, current=current)

    def _render_tour(
        self,
        log: ConversationLog,
        *,
        focus: int,
        done: list[bool] | None = None,
        current: int | None = None,
    ) -> None:
        if done is None or current is None:
            done, current = tour_state()
        finished = current >= len(TOUR_STEPS)
        completed = sum(1 for ok in done if ok)

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("From someone else's agent to your own factory\n", style=f"bold {THEME['text']}")
        t.append(
            f"  {completed} of {len(TOUR_STEPS)} done. Each rung is marked when you "
            "actually do it, not when you read it.\n\n",
            style=THEME["muted"],
        )

        title_width = max(len(step.title) for step in TOUR_STEPS) + 2
        for index, step in enumerate(TOUR_STEPS):
            is_done = done[index]
            is_focus = index == focus
            if is_done:
                mark, mark_style = "✓", THEME["success"]
            elif index == current:
                mark, mark_style = "▸", THEME["cyan"]
            else:
                mark, mark_style = "○", THEME["dim"]

            title_style = THEME["muted"] if is_done else THEME["text"]
            if is_focus and not is_done:
                title_style = THEME["success"]

            t.append(f"  {mark} ", style=f"bold {mark_style}")
            t.append(f"{index + 1}. ", style=THEME["dim"])
            t.append(f"{step.title:<{title_width}}", style=f"bold {title_style}")
            t.append(step.why, style=THEME["muted"])
            t.append("\n", style="")

            if is_focus:
                t.append(f"      {step.detail}\n", style=THEME["dim"])
                if step.command:
                    t.append("      ", style="")
                    t.append(step.command, style=f"bold {THEME['cyan']}")
                    t.append("\n", style=THEME["muted"])
                else:
                    t.append("      type your request in the box below\n", style=THEME["cyan"])

        t.append("\n", style="")
        if finished:
            t.append("  ✓ ", style=f"bold {THEME['success']}")
            t.append("You have the whole loop. ", style=f"bold {THEME['text']}")
            t.append(":work", style=f"bold {THEME['cyan']}")
            t.append(" runs it across repositories.\n", style=THEME["muted"])
        else:
            t.append("  💡 ", style=THEME["muted"])
            t.append(":tour next", style=THEME["cyan"])
            t.append(" run the current step  ", style=THEME["dim"])
            t.append(":tour 5", style=THEME["cyan"])
            t.append(" read any step  ", style=THEME["dim"])
            t.append(":explore", style=THEME["cyan"])
            t.append(" see everything at once\n", style=THEME["dim"])

        log.write(t)


__all__ = ["TOUR_STEPS", "TourMixin", "TourStep", "tour_state"]
