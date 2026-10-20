"""Cancelable, in-memory native authentication operations; never a persisted task."""

import asyncio
import threading
import uuid


class AuthenticationActions:
    def __init__(self):
        self.actions = {}
        self.lock = threading.RLock()

    def start(self, operation):
        identity = uuid.uuid4().hex
        record = {"state": "running", "messages": [], "result": None, "loop": None, "task": None}
        with self.lock:
            if sum(r["state"] == "running" for r in self.actions.values()) >= 4:
                raise ValueError("Finish or cancel another sign-in first")
            self.actions[identity] = record

        def status(message):
            with self.lock:
                record["messages"] = (record["messages"] + [str(message)])[-60:]

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
                    record["loop"].call_soon_threadsafe(record["task"].cancel)
                else:
                    record["cancel_requested"] = True
        return {"ok": True}
