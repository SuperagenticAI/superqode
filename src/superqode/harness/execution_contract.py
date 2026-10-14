"""Conservative execution boundaries shared by route details and automation.

These describe the selected route, not a live sandbox attestation. Unknown
adapter boundaries stay unknown instead of inheriting the host's policy label.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExecutionContract:
    execution_location: str = "Adapter-defined; inspect active runtime"
    filesystem_isolation: str = "Not verified"
    network_isolation: str = "Not verified"
    approval_owner: str = "Adapter-defined"
    resume_kind: str = "Route-dependent"
    checkpoint_scope: str = "Not verified; do not assume file rollback"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def lines(self) -> tuple[str, ...]:
        return tuple(
            f"{key.replace('_', ' ').capitalize()}: {value}"
            for key, value in self.to_dict().items()
        )


def execution_contract(
    *, runtime: str = "", connector: str = "", continuity: str = ""
) -> ExecutionContract:
    resume = {
        "context-replay": "Transcript replay; runtime state is not transferred",
        "fresh-session": "Fresh runtime session",
        "native-resume": "Native session when supported by the selected adapter",
    }.get(continuity, continuity.replace("-", " ") or "Route-dependent")
    if runtime in {"pipy", "codegem"}:
        return ExecutionContract(
            "SuperQode host process",
            "Host account permissions; no tool sandbox",
            "Host network permissions",
            "Host process; no interactive tool approval",
            resume,
            "Conversation only; no file snapshot",
        )
    if connector in {"acp", "external-cli"} or runtime not in {"builtin", ""}:
        return ExecutionContract(resume_kind=resume)
    return ExecutionContract(
        "SuperQode host process unless an execution backend is configured",
        "Configured path policy; local mode is not OS isolation",
        "Configured execution policy; not independently attested",
        "SuperQode configured policy",
        resume,
        "Conversation; bounded Git task recovery when available",
    )
