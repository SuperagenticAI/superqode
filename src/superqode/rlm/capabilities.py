"""Host-only callback admission fences for revoked kernel generations."""

from contextvars import ContextVar

admission_guard = ContextVar("rlm_admission_guard", default=None)


def check_admission():
    guard = admission_guard.get()
    if guard is not None and not guard():
        raise PermissionError("Kernel generation was revoked; new work cannot be admitted")
