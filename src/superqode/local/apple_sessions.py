"""Two idle native helpers per event loop, private to a gateway instance.

No listener, disk transcripts or shared daemon. Cancelled/failed requests destroy
their helper. Native transcript caches expire after 30 seconds and never cross
desktop worker processes. A helper is exclusively checked out for each request.
"""

import asyncio
from collections import OrderedDict
import weakref

_idle = weakref.WeakKeyDictionary()


async def stop(child):
    if child.returncode is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(child.wait(), 2)
    except asyncio.TimeoutError:
        try:
            child.kill()
        except ProcessLookupError:
            pass
        await child.wait()


async def acquire(key, spawn):
    pool = _idle.setdefault(asyncio.get_running_loop(), OrderedDict())
    previous = pool.pop(key, None) if key else None
    if previous:
        child, timer = previous
        timer.cancel()
        if child.returncode is None:
            return child
        await stop(child)
    return await spawn()


async def release(key, child):
    loop = asyncio.get_running_loop()
    pool = _idle.setdefault(loop, OrderedDict())
    if not key or child.returncode is not None:
        await stop(child)
        return
    old = pool.pop(key, None)
    if old:
        old[1].cancel()
        await stop(old[0])
    while len(pool) >= 2:
        _, (evicted, timer) = pool.popitem(last=False)
        timer.cancel()
        await stop(evicted)

    def expire():
        row = pool.pop(key, None)
        if row:
            loop.create_task(stop(row[0]))

    pool[key] = (child, loop.call_later(30, expire))


async def close():
    pool = _idle.pop(asyncio.get_running_loop(), {})
    for child, timer in pool.values():
        timer.cancel()
        await stop(child)
