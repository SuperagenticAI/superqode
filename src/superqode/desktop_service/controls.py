"""One stdin reader routes independent permission decisions and live steering."""

import asyncio
import inspect
import json
import queue
import sys
import threading


class InputRouter:
    def __init__(self, emit):
        self.emit = emit
        self.loop = asyncio.get_running_loop()
        self.decisions = queue.Queue()
        self.steer = None
        threading.Thread(target=self.read, daemon=True).start()

    def bind(self, runtime):
        self.steer = getattr(runtime, "steer", None) or getattr(
            getattr(runtime, "loop", None), "steer", None
        )
        self.emit("control_capabilities", {"steer": callable(self.steer)})

    def read(self):
        try:
            for line in sys.stdin:
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if data.get("operation") == "steer":
                    asyncio.run_coroutine_threadsafe(self.deliver(data), self.loop)
                else:
                    self.decisions.put(data)
        except (OSError, ValueError):
            pass
        finally:
            self.decisions.put(None)

    async def deliver(self, data):
        identity = data.get("request_id")
        try:
            if not callable(self.steer):
                raise ValueError("This runtime does not support live steering")
            accepted = self.steer(str(data.get("text") or ""))
            if inspect.isawaitable(accepted):
                accepted = await accepted
            self.emit(
                "steering",
                {
                    "request_id": identity,
                    "accepted": accepted is True,
                    "text": data.get("text"),
                    "message": "Accepted by the active runtime"
                    if accepted
                    else "The runtime is idle; send this as a new message",
                },
            )
        except Exception as exc:
            self.emit("steering", {"request_id": identity, "accepted": False, "message": str(exc)})

    def decision(self, identity):
        while True:
            item = self.decisions.get()
            if item is None:
                raise RuntimeError("Desktop disconnected while awaiting a permission decision")
            if item.get("request_id") == identity:
                return item


_router = None


def inbox(emit):
    global _router
    if _router is None or _router.loop is not asyncio.get_running_loop():
        _router = InputRouter(emit)
    return _router
