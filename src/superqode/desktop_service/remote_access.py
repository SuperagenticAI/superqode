"""Opt-in remote control over the existing engine, with local-only administration.

Device grants contain hashes, not bearer credentials. Pairing is short-lived,
requires a Mac-created invitation and must be approved over the local pipe.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid

from . import remote_network
from .redaction import redact

PERMISSIONS = {
    "read",
    "tasks",
    "evaluate",
    "optimize",
    "approve",
    "cancel",
    "steer",
    "review",
    "edit",
    "queue",
    "restore",
    "harness",
    "manage",
    "terminal",
    "git",
    "notifications",
}
DEFAULT_PERMISSIONS = ["read", "tasks", "approve", "cancel", "steer", "evaluate"]
PORT = 47831
PAIR_TTL = 300
DEVICE_TTL = 30 * 24 * 3600


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def text(value, label, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Enter {label} using at most {maximum} characters")
    return value.strip()


# Same ladder as Connect on the Mac: subscription, bring your own model,
# SuperQode harnesses, ACP agents, then remote agent protocols.
_CONNECTION_GROUPS = ("subscription", "model", "harness", "acp", "protocol")
_RUNTIME_ICONS = {
    "codex-cli": "codex",
    "codex-sdk": "codex",
    "claude-agent-sdk": "claude",
    "claude-code": "claude",
    "copilot-sdk": "copilot",
    "gemini-cli": "gemini",
    "factory": "factory-droid",
    "droid": "factory-droid",
    "opencode": "opencode",
    "antigravity-cli": "antigravity",
    "antigravity-sdk": "antigravity",
    "antigravity-managed": "antigravity",
}
_SUPERQODE_HARNESSES = {"core", "pipy", "codegem", "systemone", "no-tool"}


def connection_group(row, source):
    """Which Connect section a phone row belongs in."""
    if source == "harnesses.list":
        return "harness"
    identity = str(row.get("id") or "")
    kind = str(row.get("desktop_kind") or "")
    protocol = str(row.get("kind") or "")
    if (
        identity.startswith("remote:")
        or protocol in {"a2a", "uhp"}
        or kind in {"a2a", "uhp", "remote"}
    ):
        return "protocol"
    if kind == "attached" or identity.startswith("attach:"):
        return "model"
    if identity.startswith("connection:") or kind == "connection" or row.get("subscription_vendor"):
        return "subscription"
    if kind == "acp" or identity.startswith("acp:"):
        return "acp"
    return "harness"


def connection_icon_key(row):
    for key in ("icon_key", "agent_id", "subscription_vendor"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    identity = str(row.get("id") or "")
    for prefix in ("acp:", "connection:", "attach:", "vendor-key:", "remote:"):
        if identity.startswith(prefix):
            identity = identity[len(prefix) :]
            break
    runtime = str(row.get("runtime") or "")
    if runtime in _RUNTIME_ICONS:
        return _RUNTIME_ICONS[runtime]
    if identity in _RUNTIME_ICONS:
        return _RUNTIME_ICONS[identity]
    if identity in _SUPERQODE_HARNESSES:
        return "superqode"
    return identity


def connection_choice(row, source):
    """Fields the phone may show. Launch commands and environment stay on the Mac."""
    identity = row["id"]
    description = row.get("description") if isinstance(row.get("description"), str) else ""
    provider = row.get("provider") if isinstance(row.get("provider"), str) else ""
    model = row.get("model") if isinstance(row.get("model"), str) else ""
    kind = row.get("desktop_kind") if isinstance(row.get("desktop_kind"), str) else ""
    return {
        "id": identity,
        "name": row.get("name")
        if isinstance(row.get("name"), str) and row.get("name")
        else identity,
        "provider": provider or "agent",
        "model": model,
        "group": connection_group(row, source),
        "desktop_kind": kind,
        "icon_key": connection_icon_key(row),
        "description": description.strip()[:240],
    }


def order_connection_choices(choices):
    rank = {name: index for index, name in enumerate(_CONNECTION_GROUPS)}
    return sorted(
        choices,
        key=lambda row: (rank.get(row["group"], len(rank)), str(row["name"]).casefold(), row["id"]),
    )


class RemoteAccess:
    def __init__(self, service):
        self.service = service
        self.lock = threading.RLock()
        self.invitations = {}
        self.pairings = {}
        self.server = None
        self.stopping = False
        self.issue = ""
        service.db.executescript(
            """CREATE TABLE IF NOT EXISTS companion_devices(
              id TEXT PRIMARY KEY,name TEXT,token_hash TEXT UNIQUE,profiles TEXT,
              permissions TEXT,created REAL,expires REAL,revoked REAL,principal TEXT);
            CREATE TABLE IF NOT EXISTS companion_audit(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,device TEXT,action TEXT,project TEXT,
              job TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS companion_commands(
              device TEXT,key TEXT,signature TEXT,result TEXT,created REAL,
              PRIMARY KEY(device,key));"""
        )
        service.db.commit()
        rows = service._all("SELECT value FROM settings WHERE key='companion'")
        self.config = json.loads(rows[0]["value"]) if rows else {"profiles": [], "enabled": False}

    def _save(self):
        self.service._write(
            "INSERT OR REPLACE INTO settings VALUES('companion',?)", (json.dumps(self.config),)
        )

    def _audit(self, device, action, project="", job=""):
        self.service._write(
            "INSERT INTO companion_audit(device,action,project,job,created) VALUES(?,?,?,?,?)",
            (device, action, project, job, time.time()),
        )

    def _expire(self):
        now = time.time()
        self.invitations = {k: v for k, v in self.invitations.items() if v["expires"] > now}
        self.pairings = {k: v for k, v in self.pairings.items() if v["expires"] > now}

    def resume(self):
        if self.config.get("enabled"):
            try:
                self.start()
            except (ValueError, OSError, RuntimeError):
                self.issue = "Private remote access could not resume. Open Remote Access settings and verify Tailscale."

    def status(self):
        with self.lock:
            self._expire()
            return {
                "running": self.server is not None and self.server.running,
                "enabled": self.config.get("enabled", False),
                "private_url": self.config.get("private_url", ""),
                "port": PORT,
                "profiles": self.config.get("profiles", []),
                "issue": self.issue,
                "pairings": [
                    {
                        k: v
                        for k, v in p.items()
                        if k
                        in {
                            "id",
                            "name",
                            "principal",
                            "expires",
                            "state",
                            "profiles",
                            "permissions",
                        }
                    }
                    for p in self.pairings.values()
                    if p["state"] == "pending"
                ],
                "devices": self.service._all(
                    "SELECT id,name,created,expires,revoked,principal FROM companion_devices ORDER BY created DESC"
                ),
            }

    def validate_profile(self, raw):
        if not isinstance(raw, dict):
            raise ValueError("Choose an existing Mac connection")
        project = text(raw.get("project"), "a project")
        root = self.service.project(project)
        harness = text(raw.get("harness"), "a harness", 500)
        provider = text(raw.get("provider"), "a provider")
        model = raw.get("model") or ""
        if not isinstance(model, str) or len(model) > 500:
            raise ValueError("Choose a model on the Mac")
        local_only = raw.get("local_only") is not False
        native = next(
            (
                h
                for h in self.service.dispatch("harnesses.list", {"project": project})
                if h["id"] == harness and h.get("available")
            ),
            None,
        )
        route = next(
            (
                h
                for h in self.service.dispatch("routes.list", {"project": project})
                if h["id"] == harness and h.get("available")
            ),
            None,
        )
        if not native and not route:
            raise ValueError("Set up this harness or connection on the Mac first")
        if local_only:
            # Opaque agents own their routing; they cannot promise local inference.
            if (
                harness not in {"core", "no-tool"}
                or not native
                or native.get("runtime") != "builtin"
            ):
                raise ValueError(
                    "Local only currently requires Core or No-tool with a verified local model binding"
                )
            from .local_models import binding

            bindings = binding(self.service, project, harness, provider, model)
            endpoint = bindings[0]["endpoint"] if bindings else ""
            from urllib.parse import urlsplit

            if (
                provider not in {"ollama", "lmstudio", "mlx", "llamacpp", "ds4"}
                or not endpoint
                or urlsplit(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError(
                    "Use Local AI on the Mac to bind this model to a verified loopback engine first"
                )
        elif not route and not model:
            raise ValueError("Choose a model for this harness on the Mac")
        # Resolve native specs now; an invalid/missing spec must never fall back.
        if native:
            from superqode.harness.catalog import resolve_harness

            resolve_harness(harness, root=root)
        return {
            "id": text(raw.get("id") or uuid.uuid4().hex, "a connection ID"),
            "name": text(raw.get("name") or harness, "a connection name", 80),
            "project": project,
            "harness": harness,
            "provider": provider,
            "model": model,
            "local_only": local_only,
            "evaluation": bool(native),
            "reflection_model": str(raw.get("reflection_model") or "")[:500],
            "optimizer_model": str(raw.get("optimizer_model") or "")[:500],
            "native": bool(native),
            "enforces_controls": bool(native and native.get("enforces_session_controls")),
        }

    def handle(self, method, params):
        """Only reachable through the app's authenticated local management pipe."""
        if method == "remote.stop":
            with self.lock:
                self.config["enabled"] = False
                self._save()
            self.stop()
            return self.status()
        with self.lock:
            if method == "remote.status":
                return self.status()
            if method == "remote.network.check":
                return remote_network.inspect(PORT)
            if method == "remote.network.setup":
                return remote_network.setup(PORT)
            if method == "remote.profiles.save":
                return self._save_project_profile(params)
            if method == "remote.profiles.remove":
                self.config["profiles"] = [
                    p for p in self.config.get("profiles", []) if p["id"] != params["id"]
                ]
                self._save()
                return {"ok": True}
            if method == "remote.start":
                return self.start()
            if method == "remote.pairing.create":
                if not self.server or not self.server.running:
                    raise ValueError("Enable private remote access before pairing a phone")
                self._expire()
                profiles = params.get("profiles") or []
                allowed = {p["id"] for p in self.config.get("profiles", [])}
                permissions = params.get("permissions", DEFAULT_PERMISSIONS)
                if (
                    not isinstance(profiles, list)
                    or len(profiles) > 20
                    or not all(isinstance(p, str) and p in allowed for p in profiles)
                ):
                    raise ValueError("Choose the Mac connections this phone may use")
                if (
                    not isinstance(permissions, list)
                    or not permissions
                    or not all(p in PERMISSIONS for p in permissions)
                ):
                    raise ValueError("Choose supported remote permissions")
                if len(self.invitations) >= 5:
                    raise ValueError("Finish or wait for existing pairing invitations to expire")
                code = secrets.token_urlsafe(24)
                invitation = {
                    "profiles": profiles,
                    "permissions": sorted(set(permissions) | {"read"}),
                    "expires": time.time() + PAIR_TTL,
                }
                self.invitations[digest(code)] = invitation
                return {
                    "code": code,
                    "private_url": self.config["private_url"],
                    "expires": invitation["expires"],
                }
            if method in {"remote.pairing.approve", "remote.pairing.deny"}:
                self._expire()
                pairing = self.pairings.get(params.get("id"))
                if not pairing or pairing["state"] != "pending":
                    raise ValueError("This pairing request has expired or was already handled")
                pairing["state"] = "denied"
                if method.endswith("approve"):
                    identity = uuid.uuid4().hex
                    credential = "sqrc_" + secrets.token_urlsafe(32)
                    now = time.time()
                    self.service._write(
                        "INSERT INTO companion_devices VALUES(?,?,?,?,?,?,?,NULL,?)",
                        (
                            identity,
                            pairing["name"],
                            digest(credential),
                            json.dumps(pairing["profiles"]),
                            json.dumps(pairing["permissions"]),
                            now,
                            now + DEVICE_TTL,
                            pairing["principal"],
                        ),
                    )
                    pairing.update(state="approved", token=credential, device=identity)
                    self._audit(identity, "paired")
                return {"ok": True}
            if method == "remote.devices.revoke":
                self.service._write(
                    "UPDATE companion_devices SET revoked=? WHERE id=?", (time.time(), params["id"])
                )
                for pairing in self.pairings.values():
                    if pairing.get("device") == params["id"]:
                        pairing.pop("token", None)
                        pairing["state"] = "denied"
                self._audit(params["id"], "revoked")
                return {"ok": True}
            if method == "remote.audit":
                return self.service._all(
                    "SELECT * FROM companion_audit ORDER BY seq DESC LIMIT 100"
                )
        raise ValueError("Unknown remote management action")

    def start(self):
        with self.lock:
            if self.stopping:
                raise ValueError(
                    "Private remote access is still closing. Wait before restarting it."
                )
            network = remote_network.inspect(PORT)
            if not network["ready"]:
                raise ValueError(network["issue"])
            if self.service._closing:
                raise ValueError("The Mac engine is shutting down")
            if self.server and self.server.running:
                return self.status()
            from .remote_http import RemoteServer

            self.config.update(private_url=network["private_url"], enabled=True)
            self.server = RemoteServer(self, PORT)
            try:
                self.server.start()
            except BaseException:
                self.server = None
                self.config["enabled"] = False
                raise
            self.issue = ""
            self._save()
            return self.status()

    def stop(self):
        with self.lock:
            server = self.server
            self.stopping = True
            self.invitations.clear()
            self.pairings.clear()
        if server:
            server.stop()
        with self.lock:
            self.server = None
            self.stopping = False

    def request_pairing(self, code, name, principal):
        with self.lock:
            self._expire()
            invitation = self.invitations.pop(digest(text(code, "the pairing code", 100)), None)
            if not invitation:
                raise PermissionError(
                    "Pairing code expired or was already used. Create a new code on your Mac."
                )
            identity, claim = uuid.uuid4().hex, secrets.token_urlsafe(32)
            self.pairings[identity] = {
                **invitation,
                "id": identity,
                "name": text(name, "a device name", 80),
                "principal": principal,
                "claim_hash": digest(claim),
                "state": "pending",
            }
            return {"id": identity, "claim": claim, "expires": invitation["expires"]}

    def claim_pairing(self, identity, claim, principal):
        with self.lock:
            self._expire()
            pairing = self.pairings.get(identity)
            if (
                not pairing
                or pairing["principal"] != principal
                or not isinstance(claim, str)
                or not hmac.compare_digest(pairing["claim_hash"], digest(claim))
            ):
                raise PermissionError("Pairing expired. Create a new code on your Mac.")
            return {k: pairing[k] for k in ("state", "token", "device", "expires") if k in pairing}

    def authenticate(self, credential, principal):
        if (
            not isinstance(credential, str)
            or not credential.startswith("sqrc_")
            or len(credential) > 100
        ):
            raise PermissionError("Pair this device with the Mac to continue")
        rows = self.service._all(
            "SELECT * FROM companion_devices WHERE token_hash=? AND revoked IS NULL AND expires>?",
            (digest(credential), time.time()),
        )
        if not rows or not hmac.compare_digest(rows[0]["principal"].encode(), principal.encode()):
            raise PermissionError(
                "Device authorization expired or was revoked. Pair again on the Mac."
            )
        return rows[0]

    def profiles(self, device):
        allowed = json.loads(device["profiles"])
        return [p for p in self.config.get("profiles", []) if p["id"] in allowed]

    def _save_project_profile(self, params):
        """One shared connection per project. Later harness changes replace it in place."""
        profile = self.validate_profile(params)
        project = profile["project"]
        profile["id"] = "project:" + project
        existing = next(
            (p for p in self.config.get("profiles", []) if p["project"] == project), None
        )
        unchanged = existing and all(
            existing.get(key) == profile[key]
            for key in ("harness", "provider", "model", "local_only")
        )
        if unchanged:
            return existing
        source = params.get("source") if params.get("source") in {"mac", "phone"} else "mac"
        profile["source"] = source
        profile["revision"] = int((existing or {}).get("revision") or 0) + 1
        if existing:
            profile["reflection_model"] = profile["reflection_model"] or existing.get(
                "reflection_model", ""
            )
            profile["optimizer_model"] = profile["optimizer_model"] or existing.get(
                "optimizer_model", ""
            )
        others = [p for p in self.config.get("profiles", []) if p["project"] != project]
        if len(others) >= 20:
            raise ValueError("Use up to 20 remote connections")
        self.config["profiles"] = [*others, profile]
        self._grant_profile(profile["id"])
        self._save()
        return profile

    def connection_choices(self, project):
        """Phone harness list, in the same order as Connect on the Mac."""
        choices = []
        seen = set()
        for method in ("routes.list", "harnesses.list"):
            for row in self.service.dispatch(method, {"project": project}):
                if not isinstance(row, dict) or not row.get("available"):
                    continue
                identity = row.get("id")
                if not isinstance(identity, str) or not identity or identity in seen:
                    continue
                seen.add(identity)
                choices.append(connection_choice(row, method))
        return order_connection_choices(choices)

    def update_connection(self, device, params):
        """The phone changes the harness inside a project that was already shared."""
        project = text(params.get("project"), "a project")
        grant = next((p for p in self.profiles(device) if p["project"] == project), None)
        if not grant:
            raise PermissionError("This project is not shared with this device")
        harness = text(params.get("harness"), "a harness", 500)
        provider = params.get("provider") if isinstance(params.get("provider"), str) else ""
        model = params.get("model") if isinstance(params.get("model"), str) else ""
        return self._save_project_profile(
            {
                **grant,
                "harness": harness,
                "provider": provider or "agent",
                "model": model,
                "source": "phone",
            }
        )

    def _grant_profile(self, profile_id):
        """A connection shared after pairing becomes available to phones already approved."""
        for row in self.service._all(
            "SELECT id, profiles FROM companion_devices WHERE revoked IS NULL"
        ):
            allowed = json.loads(row["profiles"])
            if profile_id in allowed:
                continue
            self.service._write(
                "UPDATE companion_devices SET profiles=? WHERE id=?",
                (json.dumps([*allowed, profile_id]), row["id"]),
            )

    def clean(self, result):
        credentials = [*self.service.credentials.values(), *self.service.vendor_keys.values()]
        return redact(result, tuple(c for c in credentials if c))

    def rpc(self, device, method, params, key=""):
        from .remote_rpc import dispatch

        # Serialize authorization and execution against local revocation/profile changes.
        with self.lock:
            current = self.service._all(
                "SELECT * FROM companion_devices WHERE id=? AND revoked IS NULL AND expires>?",
                (device["id"], time.time()),
            )
            if not current:
                raise PermissionError("This device is no longer authorized")
            return self.clean(dispatch(self, current[0], method, params, key))
