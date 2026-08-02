"""Shared JSON-ish types for PiPy."""

from __future__ import annotations

from typing import Any

JSONPrimitive = str | int | float | bool | None
JSONValue = JSONPrimitive | dict[str, Any] | list[Any]
JSONObject = dict[str, Any]
