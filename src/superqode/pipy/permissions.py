"""PiPy's permission policy, stated rather than implied.

pi has no permission system: tools run with the permissions of the process that
launched it, and isolation is the user's job through a container or a VM. PiPy
matches that, which is the opposite of every other SuperQode harness.

This module exists so the choice is discoverable in code review and at runtime
rather than being an absence someone has to notice. Nothing here gates anything;
there is nothing to gate.

If you want approvals, a sandbox, an execution policy or network rules, switch
to the ``core`` or ``workbench`` harness. They exist for exactly that, and
``superqode.pipy`` deliberately does not import any of their machinery.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Shown wherever PiPy is offered, so nobody opts in unaware.
PURE_PERMISSIONS_NOTICE = (
    "PiPy runs tools with the permissions of the process that launched it. "
    "There are no approval prompts, no sandbox and no network policy on this "
    "harness, matching pi. Use core or workbench for SuperQode's policy stack, "
    "or run PiPy inside a container."
)


@dataclass(frozen=True, slots=True)
class PiPyPermissions:
    """A constant, for code that wants to assert the posture explicitly."""

    approvals: bool = False
    sandbox: bool = False
    network_policy: bool = False
    execution_policy: bool = False

    @property
    def notice(self) -> str:
        return PURE_PERMISSIONS_NOTICE


PURE_PI_PERMISSIONS = PiPyPermissions()


__all__ = ["PURE_PERMISSIONS_NOTICE", "PURE_PI_PERMISSIONS", "PiPyPermissions"]
