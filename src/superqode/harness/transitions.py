"""Pure transition planning shared by connection and harness selection flows."""

from dataclasses import asdict, dataclass

from .execution_contract import execution_contract


@dataclass(frozen=True)
class RouteTransition:
    source_runtime: str
    target_runtime: str
    target_connector: str
    continuity: str
    requires_acknowledgement: bool
    reasons: tuple[str, ...]

    def to_dict(self):
        return asdict(self)

    @property
    def details(self) -> tuple[str, ...]:
        return (
            *self.reasons,
            *execution_contract(
                runtime=self.target_runtime,
                connector=self.target_connector,
                continuity=self.continuity,
            ).lines(),
        )


def plan_transition(
    source_runtime: str, target_runtime: str, *, connector="", continuity="", active=False
) -> RouteTransition:
    reasons = []
    if active and source_runtime != target_runtime:
        if target_runtime in {"pipy", "codegem"} and source_runtime not in {"pipy", "codegem"}:
            reasons.append(
                "The selected route runs tools with host permissions and has no interactive tool approval or tool sandbox."
            )
        elif source_runtime in {"builtin", "core"} and (
            connector in {"acp", "external-cli"} or target_runtime not in {"builtin", "core", ""}
        ):
            reasons.append(
                "Execution controls move to the selected adapter. SuperQode's current approval and sandbox settings may not apply."
            )
    if active and continuity in {"fresh-session", "context-replay"}:
        reasons.append(
            "A fresh runtime or transcript replay does not transfer the previous agent's internal runtime state."
        )
    return RouteTransition(
        source_runtime, target_runtime, connector, continuity, bool(reasons), tuple(reasons)
    )
