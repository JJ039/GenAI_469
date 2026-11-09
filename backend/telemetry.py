"""Per-run deterministic tool instrumentation; no global cross-run logs."""
from contextvars import ContextVar
from functools import wraps
import time

TOOL_LOG = ContextVar("tool_log", default=None)


def tracked_tool(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        log = TOOL_LOG.get()
        start = time.monotonic()
        event = {"tool": function.__module__ + "." + function.__name__}
        try:
            result = function(*args, **kwargs)
            event["valid"] = True
            return result
        except Exception as exc:
            event.update(valid=False, error_type=type(exc).__name__)
            raise
        finally:
            if log is not None:
                event["elapsed_seconds"] = time.monotonic() - start
                log.append(event)
    return wrapper
