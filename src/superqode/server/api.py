"""Local HTTP API for the SuperQode session switchboard."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from superqode.session.factory import SoftwareFactory
from superqode.session.switchboard import SessionSwitchboard


def run_session_api(
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    storage_dir: str = ".superqode/sessions",
    token: str | None = None,
) -> None:
    """Run the local switchboard API until interrupted."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "SuperQodeSessionAPI/0.1"

        def do_OPTIONS(self) -> None:
            self._send_json({"ok": True})

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _handle(self, method: str) -> None:
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=401)
                return
            parsed = urlparse(self.path)
            parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
            query = parse_qs(parsed.query)
            body = self._read_body() if method == "POST" else {}
            switchboard = SessionSwitchboard(storage_dir=storage_dir)
            try:
                result = self._route(method, parts, query, body, switchboard)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json(result)

        def _route(
            self,
            method: str,
            parts: list[str],
            query: dict[str, list[str]],
            body: dict[str, Any],
            switchboard: SessionSwitchboard,
        ) -> dict[str, Any] | list[dict[str, Any]]:
            if parts == ["health"]:
                return {"ok": True, "storage_dir": str(Path(storage_dir))}
            if method == "GET" and parts == ["sessions"]:
                return {"sessions": switchboard.list_sessions()}
            if method == "GET" and parts == ["sessions", "graph"]:
                return {"graph": switchboard.graph_tree()}
            if method == "GET" and parts == ["sessions", "active"]:
                active = switchboard.active()
                return {"active_session_id": active, "session": switchboard.info(active) if active else None}
            if method == "GET" and parts == ["factory", "routes"]:
                return {"routes": SoftwareFactory(storage_dir=storage_dir).routes()}
            if len(parts) >= 2 and parts[0] == "sessions":
                session_id = parts[1]
                if method == "GET" and len(parts) == 2:
                    return switchboard.info(session_id)
                if method == "GET" and len(parts) == 3 and parts[2] == "factory":
                    return SoftwareFactory(storage_dir=storage_dir).status(session_id)
                if method == "GET" and len(parts) == 4 and parts[2] == "factory" and parts[3] == "lineage":
                    return {"lineage": SoftwareFactory(storage_dir=storage_dir).lineage(session_id)}
                if method == "GET" and len(parts) == 3 and parts[2] == "history":
                    limit = int((query.get("limit") or ["20"])[0])
                    return switchboard.history(session_id, limit=limit)
                if method == "GET" and len(parts) == 3 and parts[2] == "children":
                    return {"children": switchboard.children(session_id)}
                if method == "POST" and len(parts) == 3 and parts[2] == "switch":
                    return switchboard.switch(session_id)
                if method == "POST" and len(parts) == 3 and parts[2] == "handoff":
                    target = str(body.get("target_session_id") or "")
                    if body.get("deliver"):
                        if not target:
                            raise ValueError("target_session_id is required when deliver=true")
                        return switchboard.handoff_to_session(
                            session_id,
                            target,
                            goal=str(body.get("goal") or ""),
                            reason=str(body.get("reason") or ""),
                        )
                    packet = switchboard.make_handoff(
                        session_id,
                        target_session_id=target,
                        target_agent=str(body.get("target_agent") or body.get("agent") or ""),
                        goal=str(body.get("goal") or ""),
                        reason=str(body.get("reason") or ""),
                    )
                    return packet.to_dict()
                if method == "POST" and len(parts) == 3 and parts[2] == "fork-agent":
                    return switchboard.fork_to_agent(
                        session_id,
                        agent=str(body.get("agent") or ""),
                        new_session_id=str(body.get("session_id") or ""),
                        title=str(body.get("title") or ""),
                        goal=str(body.get("goal") or ""),
                    )
                if method == "POST" and len(parts) == 4 and parts[2] == "factory":
                    factory = SoftwareFactory(storage_dir=storage_dir)
                    if parts[3] == "mode":
                        return factory.set_mode(
                            str(body.get("mode") or ""),
                            session_id=session_id,
                            reason=str(body.get("reason") or ""),
                        )
                    if parts[3] == "model":
                        return factory.switch_model(
                            str(body.get("model") or body.get("model_ref") or ""),
                            session_id=session_id,
                            runtime=str(body.get("runtime") or ""),
                            reason=str(body.get("reason") or ""),
                        )
                    if parts[3] == "harness":
                        return factory.switch_harness(
                            str(body.get("harness") or ""),
                            session_id=session_id,
                            reason=str(body.get("reason") or ""),
                        )
            raise KeyError("route not found")

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            if not raw.strip():
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _authorized(self) -> bool:
            if not token:
                return True
            auth = self.headers.get("Authorization") or ""
            if auth == f"Bearer {token}":
                return True
            parsed = urlparse(self.path)
            return (parse_qs(parsed.query).get("token") or [""])[0] == token

        def _send_json(self, payload: Any, *, status: int = 200) -> None:
            raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(raw)

    ThreadingHTTPServer((host, port), Handler).serve_forever()
