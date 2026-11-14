"""Explicit opt-in paid-account smoke checks; never enabled by ordinary tests."""

import os

import pytest

from superqode.systemone.providers import get_provider
from superqode.systemone.connectivity import check_connection
from test_systemone_provider_apis import CLIENTS, MODELS


@pytest.mark.integration
@pytest.mark.parametrize("provider,model", MODELS)
async def test_live_native_decision_endpoint(provider, model, tmp_path):
    definition = get_provider(provider)
    if os.environ.get("SUPERQODE_TEST_LIVE_DECISIONS") != "1":
        pytest.skip("Paid API smoke is opt-in: SUPERQODE_TEST_LIVE_DECISIONS=1")
    key = os.environ.get(definition.api_key_env, "").strip()
    if not key:
        pytest.skip(f"{definition.api_key_env} is not configured")
    result = await check_connection(
        CLIENTS[provider](
            api_key=key, model=model, timeout_ms=10000, record_dir=tmp_path / provider / model
        )
    )
    assert result["provider"] == provider and result["status"] == "connected"
    assert result["checked_primitives"] == ["noul", "choice", "score"]
