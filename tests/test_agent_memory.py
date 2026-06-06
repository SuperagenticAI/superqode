"""Tests for the provider-neutral agent memory layer."""

import json

from superqode.memory import (
    LocalAgentMemoryProvider,
    SpecMemProvider,
    available_memory_providers,
    create_memory_provider,
    load_memory_config,
)


def test_local_agent_memory_remember_search_forget(tmp_path):
    memory_path = tmp_path / "memory.json"
    provider = LocalAgentMemoryProvider(project_root=tmp_path, path=memory_path)

    record = provider.remember(
        "Use pnpm in this repo; do not use npm.",
        kind="preference",
        tags=("tooling",),
    )

    assert memory_path.exists()
    assert provider.status().record_count == 1
    results = provider.search("pnpm")
    assert results[0].record.id == record.id
    assert results[0].record.kind == "preference"

    assert provider.forget(record.id[:6]) is True
    assert provider.search("pnpm") == []


def test_specmem_provider_searches_agent_experience_pack(tmp_path):
    specmem = tmp_path / ".specmem"
    specmem.mkdir()
    (specmem / "agent_context.md").write_text(
        "# Context\nCheckout flow requires payment smoke tests.",
        encoding="utf-8",
    )

    provider = SpecMemProvider(project_root=tmp_path)

    status = provider.status()
    assert status.available is True
    assert status.record_count == 1
    results = provider.search("checkout payment")
    assert results
    assert results[0].provider == "specmem"
    assert "Checkout flow" in results[0].record.content


def test_available_memory_providers_reports_local_and_specmem(tmp_path):
    statuses = available_memory_providers(tmp_path)
    providers = {status.provider for status in statuses}

    assert providers == {"local", "specmem", "mem0", "cognee", "supermemory"}
    assert {status.provider: status.enabled for status in statuses}["local"] is True
    assert {status.provider: status.enabled for status in statuses}["mem0"] is False


def test_memory_config_enables_optional_provider(tmp_path):
    (tmp_path / "superqode.yaml").write_text(
        """
memory:
  default_provider: local
  providers:
    mem0:
      enabled: true
      api_key_env: TEST_MEM0_API_KEY
      user_id: demo-user
""",
        encoding="utf-8",
    )

    config = load_memory_config(tmp_path)
    assert config.default_provider == "local"
    assert config.provider("mem0").enabled is True
    assert config.provider("mem0").get("api_key_env") == "TEST_MEM0_API_KEY"

    status = create_memory_provider("mem0", project_root=tmp_path).status()
    assert status.provider == "mem0"
    assert status.enabled is True
    assert status.available is False
    assert "TEST_MEM0_API_KEY" in status.detail or "install" in status.detail
    json.dumps(status.to_dict())
