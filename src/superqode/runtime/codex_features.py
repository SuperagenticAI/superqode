"""Version-gated Codex controls and structured composer inputs."""

from __future__ import annotations

import re


class CodexFeatures:
    async def set_turn_options(self, options):
        self._require_idle()
        allowed = {"outputSchema", "summary", "serviceTier", "clientUserMessageId"}
        if not isinstance(options, dict) or options.keys() - allowed:
            raise ValueError(
                "Turn options accept outputSchema, summary, serviceTier and clientUserMessageId"
            )
        await self._ensure_started()
        for key in options:
            self.capabilities.require("turn/start", key)
        self.capabilities.validate("turn/start", {"threadId": "pending", "input": [], **options})
        if options.get("outputSchema") is not None:
            from jsonschema import Draft202012Validator

            Draft202012Validator.check_schema(options["outputSchema"])
        self._require_idle()
        self._next_turn_options = dict(options)
        return {"nextTurn": self._next_turn_options}

    async def set_mediated_profile(self):
        self._require_idle()
        self._preflight_policy()
        await self._ensure_started()
        self.capabilities.require("turn/start", "approvalsReviewer")
        self._require_idle()
        self.set_sandbox_backend("workspace-write")
        self._next_turn_sandbox = None
        self.set_approval_policy("on-request")
        return {
            "approvalPolicy": "on-request",
            "approvalsReviewer": "user",
            "sandbox": "workspace-write",
            "hostEnforcement": "received approval requests only",
        }

    async def _check_resume_goal(self, thread_id):
        # Shared listeners may have autonomous goals running independently of
        # this client's turn stream. Do not activate one through resume/fork.
        if self.codex_server and self.capabilities.supports("thread/goal/get"):
            from .codex_transport import CodexRPCError

            try:
                result = await self._timed_request("thread/goal/get", {"threadId": thread_id})
            except CodexRPCError as exc:
                if "goals feature is disabled" in str(exc):
                    return
                raise
            if (result.get("goal") or {}).get("status") == "active":
                raise RuntimeError(
                    "This Codex thread has an active autonomous goal. Pause it in Codex before attaching it to SuperQode."
                )

    async def attach_server(self, endpoint):
        self._require_idle()
        from .codex_daemon import local_codex_endpoint

        endpoint = None if endpoint == "stdio" else local_codex_endpoint(endpoint)
        self._preflight_policy()
        async with self._turn_lock:
            saved = self._thread_id if self._thread_persisted else self._resume_thread_id
            await self.aclose()
            self._closed = False
            self._failure = None
            self._thread_id = None
            self._resume_thread_id = saved
            self.codex_server = endpoint
            self._session_consents.clear()
            await self._ensure_started()
            return {"server": self.app_server_source, "resumeThreadId": saved}

    async def select_permission_profile(self, profile):
        self._require_idle()
        await self._ensure_started()
        self.capabilities.require("turn/start", "permissions")
        cursor = None
        while True:
            result = await self.inspect("permissions", cursor=cursor)
            match = next(
                (item for item in result.get("data", []) if item.get("id") == profile), None
            )
            if match:
                if match.get("allowed") is not True:
                    raise ValueError("Codex managed requirements forbid this permission profile")
                break
            cursor = result.get("nextCursor")
            if not cursor:
                raise ValueError(f"Unknown Codex permission profile: {profile}")
        self._require_idle()
        self._preflight_policy()
        self._permission_profile = profile
        self.sandbox_backend = None
        return {"profile": profile, "applies": "next turn"}

    async def mcp_login(self, name):
        self._require_idle()
        await self._ensure_started()
        self.capabilities.require("mcpServer/oauth/login")
        return await self._timed_request(
            "mcpServer/oauth/login",
            {"name": name, **({"threadId": self._thread_id} if self._thread_id else {})},
        )

    async def thread_history(self, *, cursor=None):
        await self.ensure_thread()
        if self.capabilities.supports("thread/items/list") and not getattr(
            self, "_history_paging_unavailable", False
        ):
            from .codex_transport import CodexRPCError

            try:
                return await self._timed_request(
                    "thread/items/list",
                    {
                        "threadId": self._thread_id,
                        "limit": 50,
                        "sortDirection": "desc",
                        **({"cursor": cursor} if cursor else {}),
                    },
                )
            except CodexRPCError as exc:
                if exc.code != -32601 and "not supported yet" not in str(exc).lower():
                    raise
                self._history_paging_unavailable = True
        if cursor:
            raise ValueError("This Codex version does not support paginated tool history")
        return await self.read_thread(include_turns=True)

    async def _composer_input(self, prompt):
        inputs = [{"type": "text", "text": prompt, "text_elements": []}]
        skill_names = set(re.findall(r"(?<![\w\\])\$([\w][\w.-]*)", prompt))
        app_names = set(re.findall(r"(?<![\w\\])@([\w][\w.-]*)", prompt))
        if not skill_names and not app_names:
            return inputs
        # Names resolve only against Codex's catalogs. No invented paths or
        # shell expansion, and ordinary @file references remain plain text.
        found = set()
        if skill_names and self.capabilities.supports("skills/list"):
            result = await self._mention_catalog("skills")
            for group in result.get("data", []):
                for skill in group.get("skills", []):
                    name, path = skill.get("name"), skill.get("path")
                    if name in skill_names and path and skill.get("enabled", True):
                        if name in found:
                            raise ValueError(
                                f"Ambiguous Codex skill ${name}; use an explicit skill path in Codex"
                            )
                        inputs.append({"type": "skill", "name": name, "path": path})
                        found.add(name)
        wanted_apps = app_names | (skill_names - found)
        if wanted_apps and self.capabilities.supports("app/list"):
            cursor, matched = None, {}
            while True:
                result = await self._mention_catalog("apps", cursor=cursor)
                for app in result.get("data", []):
                    name, app_id = app.get("name", ""), app.get("id", "")
                    slug = re.sub(r"[^\w.-]+", "-", name.lower()).strip("-")
                    aliases = {app_id, slug}
                    requested = wanted_apps & aliases
                    if (
                        not requested
                        or app.get("isAccessible") is not True
                        or app.get("isEnabled") is not True
                    ):
                        continue
                    for alias in requested:
                        if alias in matched and matched[alias] != app_id:
                            raise ValueError(f"Ambiguous Codex app mention {alias}")
                        matched[alias] = app_id
                    inputs.append({"type": "mention", "name": name, "path": "app://" + app_id})
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            # Codex recognizes $app-slug; SuperQode also accepts @app-slug.
            for alias in app_names & matched.keys():
                inputs[0]["text"] = re.sub(
                    r"(?<![\w\\])@" + re.escape(alias) + r"(?![\w.-])",
                    "$" + alias,
                    inputs[0]["text"],
                )
        return inputs

    async def _mention_catalog(self, topic, *, cursor=None):
        # Optional catalogs must not abort an otherwise valid prompt.
        import time

        cache = getattr(self, "_mention_catalog_cache", {})
        self._mention_catalog_cache = cache
        key = (self._thread_id, topic, cursor)
        cached = cache.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        try:
            result = await self.inspect(topic, cursor=cursor)
        except Exception:
            result = {"data": []}
        cache[key] = (time.monotonic(), result)
        return result

    @property
    def context_usage(self):
        last = self.token_usage.get("last") or {}
        used = last.get("totalTokens")
        window = self.token_usage.get("modelContextWindow")
        return {
            "used": used,
            "window": window,
            "percent": min(100, round(100 * used / window, 1))
            if isinstance(used, int) and isinstance(window, int) and window > 0
            else None,
        }
