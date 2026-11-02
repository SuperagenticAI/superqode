import io
import urllib.request

import pytest

from superqode.local import workbench


def test_ollama_progress_requires_an_explicit_success_record(monkeypatch):
    events = []

    def response(*args, **kwargs):
        return io.BytesIO(b'{"status":"pulling","completed":10,"total":20}\n{"status":"success"}\n')

    monkeypatch.setattr(urllib.request, "urlopen", response)
    workbench._pull_ollama("fixture:8b", lambda kind, data: events.append((kind, data)))
    assert events[0] == (
        "progress",
        {"completed": 10, "total": 20, "unit": "B", "label": "pulling"},
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b'{"status":"pulling"}\n')
    )
    with pytest.raises(ValueError, match="without success"):
        workbench._pull_ollama("fixture:8b", lambda *a: None)


def test_hub_progress_callback_keeps_units_and_totals():
    from superqode.providers.huggingface.fetch import _progress_class

    progress = []
    bar = _progress_class(progress.append)(total=10, unit="B", leave=False)
    bar.update(10)
    bar.close()
    assert progress[-1]["completed"] == 10
    assert progress[-1]["total"] == 10 and progress[-1]["unit"] == "B"
