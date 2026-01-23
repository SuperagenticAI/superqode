import shutil

import pytest

from superqode.execution.linter import LinterRunner


@pytest.mark.asyncio
async def test_linter_runner_reports_missing_tool(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print('hello')\n")

    monkeypatch.setattr(shutil, "which", lambda _: None)

    runner = LinterRunner(tmp_path)
    result = await runner.run()

    assert result.findings
    assert any("linter unavailable" in f.get("title", "") for f in result.findings)
