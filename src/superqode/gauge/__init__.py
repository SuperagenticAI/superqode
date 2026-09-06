"""SuperGauge Agent Quality Record emission.

SuperQode already holds almost everything a release record needs. `harness eval`
produces per-task results with a held-in/held-out split and usage aggregates,
`governance` decides at five policy phases, `promotion` keeps a digest-pinned
ledger with an actor and a rollback snapshot, and `harness.protocol` stores an
event ledger per run.

This package projects that state into the record format published at
https://github.com/SuperagenticAI/supergauge, so a release decision leaves an
artifact a third party can check. It computes nothing new: where a value is
absent from the underlying run, the field is omitted and the record reaches a
lower conformance level, which is the honest outcome.
"""

from .record import (
    SUPERGAUGE_VERSION,
    AgentQualityRecord,
    build_record,
    record_from_eval,
)
from .levels import LEVELS, check_levels, highest_level
from .sources import (
    ledger_evidence,
    policy_decisions,
    policy_decisions_from_ledger,
    promotion_evidence,
)

__all__ = [
    "SUPERGAUGE_VERSION",
    "AgentQualityRecord",
    "build_record",
    "record_from_eval",
    "LEVELS",
    "check_levels",
    "highest_level",
    "ledger_evidence",
    "policy_decisions",
    "policy_decisions_from_ledger",
    "promotion_evidence",
]
