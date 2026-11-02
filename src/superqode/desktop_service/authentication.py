"""Cancelable, in-memory native authentication operations; never a persisted task."""

import asyncio
import threading
import uuid


class AuthenticationActions:
    def __init__(self):
        self.actions = {}
        self.lock = threading.RLock()
        self.closing = False

    def start(self, operation):
        identity = uuid.uuid4().hex
        record = {"state": "running", "messages": [], "result": None, "loop": None, "task": None}
        with self.lock:
            if self.closing:
                raise ValueError("The desktop engine is shutting down")
            if len(self.actions) > 100:
                for key in list(self.actions):
                    if self.actions[key]["state"] != "running":
                        del self.actions[key]
                    if len(self.actions) <= 60:
                        break
            if sum(r["state"] == "running" for r in self.actions.values()) >= 4:
                raise ValueError("Finish or cancel another sign-in first")
            self.actions[identity] = record

        def status(message):
            with self.lock:
                record["messages"] = (record["messages"] + [str(message)[:4000]])[-60:]

        async def execute():
            record["loop"] = asyncio.get_running_loop()
            record["task"] = asyncio.current_task()
            try:
                if record.get("cancel_requested"):
                    raise asyncio.CancelledError()
                record["result"] = await operation(status)
                record["state"] = "completed"
            except asyncio.CancelledError:
                record["state"] = "cancelled"
            except Exception as exc:
                record["state"] = "failed"
                status(str(exc))

        threading.Thread(target=lambda: asyncio.run(execute()), daemon=True).start()
        return {"id": identity}

    def poll(self, identity):
        with self.lock:
            record = self.actions.get(identity)
            if not record:
                raise ValueError("This sign-in operation no longer exists")
            return {key: record[key] for key in ("state", "messages", "result")}

    def cancel(self, identity):
        with self.lock:
            record = self.actions.get(identity)
            if record and record["state"] == "running":
                if record["loop"] and record["task"]:
                    if not record["loop"].is_closed():
                        record["loop"].call_soon_threadsafe(record["task"].cancel)
                else:
                    record["cancel_requested"] = True
        return {"ok": True}

    def begin_close(self):
        with self.lock:
            self.closing = True
            for identity in list(self.actions):
                self.cancel(identity)
