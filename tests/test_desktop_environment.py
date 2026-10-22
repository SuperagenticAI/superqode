from superqode.desktop_service.environment import job_environment, selected_providers


def test_model_worker_keeps_only_selected_credentials():
    env = job_environment(
        {
            "OPENAI_API_KEY": "host",
            "ANTHROPIC_API_KEY": "unrelated",
            "PATH": "/usr/bin",
            "OPENAI_API_BASE": "http://localhost",
        },
        {"OPENAI_API_KEY": "selected"},
        allowed={"OPENAI_API_KEY"},
    )
    assert env == {
        "OPENAI_API_KEY": "selected",
        "PATH": "/usr/bin",
        "OPENAI_API_BASE": "http://localhost",
    }


def test_check_cannot_opt_into_credentials():
    assert job_environment(
        {"OPENAI_API_KEY": "host", "PATH": "/usr/bin"},
        {"OPENAI_API_KEY": "saved"},
        check=True,
        allowed={"OPENAI_API_KEY"},
    ) == {"PATH": "/usr/bin"}


def test_explicit_optimizer_models_do_not_add_unrequested_default_providers():
    assert selected_providers(
        "optimization",
        {
            "provider": "ollama",
            "reflection_model": "gemini/example",
            "optimizer_model": "gemini/example",
        },
    ) == {"ollama", "gemini"}
