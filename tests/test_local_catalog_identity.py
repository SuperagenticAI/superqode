from types import SimpleNamespace

from superqode.local import workbench


def test_recommendation_cards_have_unique_model_tags_and_prefer_main_role(monkeypatch):
    rows = [
        SimpleNamespace(name=name, role=role, commands=[("Ollama", "ollama pull fixture:8b")])
        for name, role in [("Utility alias", "utility"), ("Coding model", "main")]
    ]
    monkeypatch.setattr(workbench, "search_models", lambda *a, **k: rows)
    result = workbench.search("")
    assert len(result) == 1 and result[0]["id"] == "fixture:8b"
    assert result[0]["role"] == "main"


def test_lmstudio_search_does_not_inherit_previous_mlx_format(monkeypatch):
    from superqode.providers.huggingface import fetch

    def search(query, *, kind, limit):
        assert kind == "gguf"
        return [fetch.HubModel(id="publisher/model-GGUF")]

    monkeypatch.setattr(fetch, "search_hub", search)
    result = workbench.search("fixture", source="lmstudio", kind="mlx")
    assert result[0]["format"] == "gguf"
    assert "lmstudio" in result[0]["engines"] and "mlx" not in result[0]["engines"]
