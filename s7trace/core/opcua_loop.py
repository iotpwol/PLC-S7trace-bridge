"""asyncua's synchronous client runs an asyncio loop in a helper thread (`asyncua.sync.ThreadLoop`). That thread is NOT a daemon and is only
stopped by a successful `disconnect()` - a probe of an unreachable OPC UA server (connection wizard) or a failed connect left it running, and
then the Python process never ended after the window / test run was closed. `make_daemon` marks every such thread as a daemon (idempotent)."""
from __future__ import annotations


def make_daemon() -> None:
    try:
        from asyncua import sync
    except Exception:                                   # the optional library is not installed
        return
    cls = sync.ThreadLoop
    if getattr(cls, "_s7trace_daemon", False):
        return
    orig = cls.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.daemon = True

    cls.__init__ = init
    cls._s7trace_daemon = True
