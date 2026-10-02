"""Optional W&B Weave tracing.

`op` behaves like `weave.op` when WANDB_API_KEY is set and the `weave` package is
installed; otherwise it returns the function unchanged so the pipeline still runs.
"""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

from schema import load_env

F = TypeVar("F", bound=Callable[..., Any])

_weave: Any = None
_initialized = False


def init() -> Any:
    """Initialize Weave once. Returns the weave module, or None when tracing is disabled."""
    global _weave, _initialized
    if _initialized:
        return _weave
    _initialized = True
    load_env()
    if not os.environ.get("WANDB_API_KEY"):
        return None
    try:
        import weave  # type: ignore
    except ImportError:
        print("[tracing] weave not installed; tracing disabled")
        return None
    try:
        weave.init(os.environ.get("WEAVE_PROJECT", "stadium-sentinel"))
    except Exception as err:
        print(f"[tracing] weave init failed; tracing disabled: {err}")
        return None
    _weave = weave
    return _weave


def op(fn: F) -> F:
    weave = init()
    if weave is None:
        return fn
    return weave.op()(fn)  # type: ignore[return-value]
