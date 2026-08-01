"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_progress_state(tmp_path, monkeypatch):
    """Keep milestone state out of the real home directory.

    Progress is deliberately global (it tracks the user, not the repository),
    so without this a test run would rewrite the developer's own ladder and
    every reveal assertion would depend on which tests ran before it.
    """
    from superqode.app.progress import clear_progress_cache

    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "superqode-state"))
    clear_progress_cache()
    yield
    clear_progress_cache()


@pytest.fixture(autouse=True)
def _clear_cli_probe_caches():
    """Keep the memoized vendor-CLI probes from leaking across tests.

    ``probe_devin_cli`` and ``probe_antigravity_cli`` memoize their result so
    the TUI does not fork a subprocess per completion keystroke. Tests
    monkeypatch ``shutil.which``/``subprocess.run`` to describe different
    machines, so each one needs a cold cache to actually exercise its probe.
    """
    from superqode.runtime.antigravity_status import clear_antigravity_cli_cache
    from superqode.runtime.devin_status import clear_devin_cli_cache

    clear_devin_cli_cache()
    clear_antigravity_cli_cache()
    from superqode.providers.models import clear_effective_models_cache

    clear_effective_models_cache()
    yield
    clear_devin_cli_cache()
    clear_antigravity_cli_cache()
    clear_effective_models_cache()
