import concurrent.futures
import json
import os
import subprocess
import sys

import pytest

from superqode.harness.context_artifacts import ContextArtifactStore


def test_reopen_unicode_pages_scope_and_redaction(tmp_path):
    path = tmp_path / "evidence.sqlite"
    store = ContextArtifactStore(path)
    original = "API_KEY=hidden\n" + "漢字🙂" * 9000
    artifact = store.put("session", "entry", original, metadata={"tool": "read_file"})
    assert "hidden" not in path.read_bytes().decode("utf8", errors="ignore")
    store = ContextArtifactStore(path)
    parts, offset = [], 0
    while True:
        page = store.read_page("session", artifact.reference, offset=offset, limit=5000)
        assert len(page.text.encode()) <= 48000
        parts.append(page.text)
        offset = page.next_offset
        if page.eof:
            break
    assert "".join(parts) == "API_KEY=[redacted]\n" + "漢字🙂" * 9000
    with pytest.raises(LookupError):
        store.read_page("other-session", artifact.reference)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from superqode.harness.context_artifacts import ContextArtifactStore; import sys,json; print(json.dumps(ContextArtifactStore(sys.argv[1]).read_page('session',sys.argv[2]).to_dict()))",
            str(path),
            artifact.reference,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["digest"] == artifact.digest
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_atomic_idempotency_and_conflict(tmp_path):
    store = ContextArtifactStore(tmp_path / "e.sqlite")

    def put(_):
        return store.put("owner", "entry", "same").reference

    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        refs = list(pool.map(put, range(12)))
    assert len(set(refs)) == 1
    with pytest.raises(ValueError):
        store.put("owner", "entry", "different")
    a = store.put("owner", "branch-2:entry", "different")
    store.bind_alias("owner", "old-call", refs[0])
    with pytest.raises(ValueError):
        store.bind_alias("owner", "old-call", a.reference)


def test_owner_quota_counts_utf8_metadata_bytes(tmp_path):
    metadata = {"label": "漢" * 30}
    size = 1 + len(json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode())
    store = ContextArtifactStore(tmp_path / "e.sqlite", max_scope_bytes=size * 2 - 1)
    store.put("owner", "one", "a", metadata=metadata)
    with pytest.raises(ValueError):
        store.put("owner", "two", "b", metadata=metadata)


def test_denial_rechecked_and_integrity(tmp_path):
    allowed = True
    store = ContextArtifactStore(tmp_path / "e.sqlite", authorize=lambda meta, text: allowed)
    artifact = store.put("owner", "entry", "body")
    allowed = False
    with pytest.raises(PermissionError):
        store.describe("owner", artifact.reference)
    with pytest.raises(PermissionError):
        store.read_page("owner", artifact.reference)
    allowed = True
    with store._connect() as db:
        db.execute("UPDATE context_artifacts SET content='tampered'")
    with pytest.raises(ValueError):
        store.read_page("owner", artifact.reference)


@pytest.mark.parametrize("offset,limit", [(True, 1), (0, True), (-1, 5), (0, 0), (0, 2.5)])
def test_invalid_pages(tmp_path, offset, limit):
    store = ContextArtifactStore(tmp_path / "e.sqlite")
    a = store.put("owner", "entry", "body")
    with pytest.raises(ValueError):
        store.read_page("owner", a.reference, offset=offset, limit=limit)


def test_quota_expiry_deletion_and_alias(tmp_path):
    store = ContextArtifactStore(tmp_path / "e.sqlite", max_artifact_bytes=100, max_scope_bytes=110)
    with pytest.raises(ValueError):
        store.put("owner", "oversize", "a" * 101)
    a = store.put("owner", "one", "a" * 100)
    with pytest.raises(ValueError):
        store.put("owner", "two", "a" * 20)
    store.bind_alias("owner", "old", a.reference)
    assert store.resolve_alias("owner", "old") == a.reference
    assert store.delete("owner", a.reference)
    with pytest.raises(LookupError):
        store.read_page("owner", a.reference)
    import time

    b = store.put("owner", "expires", "body", expires_at=time.time() + 100)
    assert store.expire(now=time.time() + 200) == 1
    with pytest.raises(LookupError):
        store.describe("owner", b.reference)


def test_current_governance_blocks_original_pipy_read_alias(tmp_path):
    from superqode.governance import (
        ContextualPolicyEngine,
        ContextualPolicyRule,
        CredentialBroker,
        GovernanceBundle,
        PolicyLayer,
        governance_scope,
    )

    store = ContextArtifactStore(tmp_path / "e.sqlite")
    artifact = store.put(
        "owner",
        "entry",
        "previously allowed",
        metadata={"tool": "read", "arguments": {"path": "secrets.txt"}},
    )
    layer = PolicyLayer(
        "new policy",
        "test",
        rules=(
            ContextualPolicyRule(
                "revoked",
                "deny",
                tools=("read_file",),
                argument_patterns={"path": ("secrets.txt",)},
            ),
        ),
    )
    with governance_scope(GovernanceBundle(ContextualPolicyEngine([layer]), CredentialBroker())):
        with pytest.raises(PermissionError):
            store.read_page("owner", artifact.reference)


def test_reader_keeps_read_group_for_shell_evidence(tmp_path):
    from superqode.governance import (
        ContextualPolicyEngine,
        ContextualPolicyRule,
        CredentialBroker,
        GovernanceBundle,
        PolicyLayer,
        governance_scope,
    )

    store = ContextArtifactStore(tmp_path / "e.sqlite")
    record = store.put(
        "owner", "call", "output", metadata={"tool": "bash", "arguments": {"command": "pwd"}}
    )
    rule = ContextualPolicyRule("reader_revoked", "deny", tool_groups=("read",))
    with governance_scope(
        GovernanceBundle(
            ContextualPolicyEngine([PolicyLayer("new", "test", rules=(rule,))]), CredentialBroker()
        )
    ):
        with pytest.raises(PermissionError):
            store.read_page("owner", record.reference)


def test_committed_artifact_survives_abrupt_writer_exit(tmp_path):
    path = tmp_path / "evidence.sqlite"
    script = "from superqode.harness.context_artifacts import ContextArtifactStore; import os,sys; a=ContextArtifactStore(sys.argv[1]).put('owner','entry','committed'); print(a.reference,flush=True); os._exit(17)"
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)], capture_output=True, text=True
    )
    assert result.returncode == 17
    assert ContextArtifactStore(path).read_page("owner", result.stdout.strip()).text == "committed"


def test_interrupted_transaction_does_not_publish_artifact(tmp_path):
    path = tmp_path / "evidence.sqlite"
    store = ContextArtifactStore(path)
    script = "import sqlite3,os,sys; db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE'); db.execute(\"INSERT INTO context_artifacts VALUES ('ctx_bad','owner','entry','hash',4,4,0,NULL,'{}','body')\"); os._exit(17)"
    result = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True)
    assert result.returncode == 17
    with pytest.raises(LookupError):
        store.read_page("owner", "ctx_bad")
