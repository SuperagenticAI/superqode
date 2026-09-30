"""Optional real-server check. Never enabled by normal CI or saved credentials."""

import os

import pytest

from superqode.providers.connection_diagnostics import check_model_connection
from superqode.providers.dynamic import resolve_provider_def
from superqode.providers.registry import ProviderCategory


@pytest.mark.asyncio
async def test_opt_in_live_connection():
    provider = os.getenv("SUPERQODE_LIVE_CONNECTION_PROVIDER", "").strip()
    model = os.getenv("SUPERQODE_LIVE_CONNECTION_MODEL", "").strip()
    if not provider or not model:
        pytest.skip("Set an explicit live provider and model to enable this check")
    definition = resolve_provider_def(provider)
    assert definition is not None, "Unsupported live provider"
    infer = os.getenv("SUPERQODE_LIVE_CONNECTION_INFER") == "1"
    if definition.category != ProviderCategory.LOCAL and not infer:
        pytest.skip("Cloud live verification requires explicit inference opt-in")
    result = await check_model_connection(provider, model, infer=infer)
    assert result.status == ("verified" if infer else "reachable"), result.message
