"""Harness CLI command package."""

# Import command modules in this order to preserve Click help/registration order.

# ruff: noqa: F401, I001

from ._group import HARNESS_TEMPLATE_CHOICES, WORKFLOW_PRESET_CHOICES, harness

from ._helpers import (
    _harness_mcp_config_path,
    _harness_model_registry_check,
    _normalize_harness_model_id,
    _diff_dicts,
    _permission_config_to_dict,
)

from .lifecycle import (
    harness_list,
    harness_show,
    harness_use,
    harness_list_templates,
    harness_list_backends,
    harness_wizard,
    harness_init,
    harness_import_omnigent,
    harness_import_agent,
    harness_validate,
    harness_inspect,
    harness_compile,
    harness_explain,
    harness_diff,
    harness_doctor,
)

from .evaluation import (
    harness_test,
    harness_eval,
    harness_eval_packs,
    harness_auto_bench,
    _auto_bench_recommendation,
    _csv_tuple,
    harness_mine_failures,
)

from .bench import harness_bench, harness_bench_verify
from .promotion import harness_promote

from .logbook import (
    harness_logbook,
    harness_logbook_update,
    harness_logbook_show,
    harness_logbook_export,
    harness_logbook_prune,
)

from .candidates import (
    harness_audit_candidate,
    harness_candidates,
    harness_candidates_list,
    harness_candidates_show,
    harness_candidates_export,
)

from .optimization import (
    harness_improve,
    harness_optimize,
    harness_optimize_inspect,
    harness_optimize_ledger,
)

from .registry import (
    harness_registry,
    harness_registry_publish,
    harness_registry_list,
    harness_registry_install,
)

from .run_history import (
    harness_run,
    harness_events,
    harness_runs,
)

from .inbox import (
    harness_inbox,
    harness_inbox_add,
    harness_inbox_list,
    harness_inbox_recover,
    _execute_claimed_harness_input,
)

from .worker import (
    harness_drain,
    harness_worker,
)

from .evidence import harness_evidence

from .protocol import (
    harness_protocol,
    harness_protocol_list,
    harness_protocol_describe,
    harness_protocol_conformance,
)

from .observability import (
    harness_observability,
    harness_observability_status,
    harness_observability_export,
)

from .replay import (
    harness_replay,
    harness_fork,
    harness_graph,
)
