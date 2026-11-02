"""Hub identity checks without writing a token to the Hub cache or Git config."""

import os


def token(service):
    if service.credentials.get("huggingface"):
        return service.credentials["huggingface"]
    from huggingface_hub import get_token

    return get_token() or os.environ.get("HUGGINGFACE_API_KEY")


def status(service):
    configured = bool(token(service))
    return {
        "configured": configured,
        "source": "App session / Keychain"
        if service.credentials.get("huggingface")
        else "Existing Hub environment or token store"
        if configured
        else "Public access",
        "tokens_url": "https://huggingface.co/settings/tokens",
        "note": "Public downloads need no account. For gated weights, accept the publisher's conditions on the model page and use a token with access to that repository. Disconnecting here removes the app credential only.",
    }


def verify(service, value=None):
    from huggingface_hub import HfApi

    value = value or token(service)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 16000
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Enter a Hugging Face user access token")
    try:
        identity = HfApi(endpoint="https://huggingface.co", token=value.strip()).whoami()
    except Exception:
        # Vendor error text can contain request metadata; never echo credentials.
        raise ValueError(
            "Hugging Face could not verify this token. Check access, expiry and your network, then retry."
        ) from None
    name = identity.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Hugging Face did not return an account identity")
    return {
        "name": name[:200],
        "verified": True,
        "note": "Account verified. Repository access and publisher conditions are checked separately when reviewing a download.",
    }
