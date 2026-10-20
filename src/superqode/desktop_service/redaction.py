"""Redact app-managed credentials before desktop output is recorded."""

import json
import os


def redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact(key, secrets): redact(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    return value


def worker_secrets():
    variables = json.loads(os.environ.pop("SUPERQODE_DESKTOP_KEY_VARS", "[]"))
    return tuple(
        sorted(
            {os.environ[name] for name in variables if os.environ.get(name)}, key=len, reverse=True
        )
    )
