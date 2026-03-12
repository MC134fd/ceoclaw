"""
Thread-safe in-memory event bus for streaming run events to SSE clients.

Events are keyed by run_id.  Callers emit structured dicts; SSE consumers
poll get_events() in an async loop.  cleanup() should be called once a
consumer has finished reading a completed run.
"""

import threading
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
_done: dict[str, bool] = {}


def emit(run_id: str, event: dict[str, Any]) -> None:
    """Append *event* to the event list for *run_id*."""
    with _lock:
        _events[run_id].append(event)


def get_events(run_id: str, start_idx: int = 0) -> list[dict[str, Any]]:
    """Return events for *run_id* starting at *start_idx* (non-destructive)."""
    with _lock:
        evts = _events.get(run_id, [])
        return list(evts[start_idx:])


def mark_done(run_id: str) -> None:
    """Signal that no more events will be emitted for *run_id*."""
    with _lock:
        _done[run_id] = True


def is_done(run_id: str) -> bool:
    """Return True if *run_id* has been marked done."""
    with _lock:
        return _done.get(run_id, False)


def event_count(run_id: str) -> int:
    with _lock:
        return len(_events.get(run_id, []))


def cleanup(run_id: str) -> None:
    """Remove all stored events for *run_id* (call after consumer finishes)."""
    with _lock:
        _events.pop(run_id, None)
        _done.pop(run_id, None)
