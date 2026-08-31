"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from superqode.providers.harness_catalog import CONNECT_MENU_DEFAULT


@pytest.fixture(autouse=True)
def _default_connect_menu(monkeypatch):
    """Keep connect IA on the compiled default unless a test opts out.

    ``parse_connect_menu_flag`` also reads ``~/.superqode/config.json``. Pinning
    the env here stops a developer's local ``connect_menu`` from flipping every
    existing-harness assertion. Tests covering the legacy IA set ``v1``
    explicitly.
    """
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", CONNECT_MENU_DEFAULT)


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
    from superqode.providers import models as model_db
    from superqode.providers.models import clear_effective_models_cache

    # Live models.dev data leaks the same way. ``set_live_models`` flips a
    # module global, so one test that loads live data changes what every later
    # test sees from ``get_model_info``. That is how a builtin-catalogue
    # assertion started failing only in a full run, and only where models.dev
    # was reachable. Each test starts on the builtin catalogue and puts the
    # previous state back afterwards.
    # Suppressing the autoload matters as much as clearing the flag: without
    # it a test reads whatever models.dev cache happens to sit in the running
    # user's home directory, so an assertion about builtin metadata passes or
    # fails according to the machine. A test that wants the autoload sets the
    # flag back itself, as tests/test_live_models.py does.
    live_state = (
        model_db._use_live_data,
        model_db._live_models,
        model_db._live_autoload_attempted,
    )
    model_db._use_live_data = False
    model_db._live_models = None
    model_db._live_autoload_attempted = True
    clear_effective_models_cache()
    yield
    clear_devin_cli_cache()
    clear_antigravity_cli_cache()
    (
        model_db._use_live_data,
        model_db._live_models,
        model_db._live_autoload_attempted,
    ) = live_state
    clear_effective_models_cache()
