from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_omnigent_agent_session_smoke_script():
    script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_omnigent_agent_sessions.py"

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Omnigent agent-session smoke passed" in result.stdout
