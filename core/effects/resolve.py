"""Resolving the callables named in device definitions.

Device definitions name their update signals and response models by fully
qualified import path, e.g.::

    update:
      function: laura.utils.signals.Sinusoid
      period: 10.0

so the classes themselves can be built here without knowing where they came
from. Any importable class works, provided the path names it and the
remaining entries are its arguments.
"""

import inspect
from importlib import import_module
from typing import Any, Callable, Dict


def resolve(path: str) -> type:
    """Import the class named by a fully qualified `path`.

    Raises `LookupError` if the path does not name an importable class. Note
    that this imports the named module, so only resolve paths from definitions
    you trust.
    """
    if "." not in path:
        raise LookupError(
            f"'{path}' is not a fully qualified import path, e.g. 'mypackage.signals.Sinusoid'"
        )

    module_name, _, attr = path.rpartition(".")
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise LookupError(f"Cannot import module '{module_name}' for '{path}': {exc}")

    obj = getattr(module, attr, None)
    if obj is None:
        raise LookupError(f"Module '{module_name}' has no attribute '{attr}'")
    if not isinstance(obj, type):
        raise LookupError(f"'{path}' is not a class, got {type(obj).__name__}")

    return obj


def build(spec: Dict[str, Any], key: str) -> Callable:
    """Instantiate the class named by ``spec[key]``, passing the rest as arguments.

    ``build({"model": "mypackage.dynamics.FirstOrder", "tau": 0.5}, "model")``
    returns ``FirstOrder(tau=0.5)``. Raises `LookupError` if the class cannot be
    resolved, or `TypeError` if the arguments do not suit it.
    """
    if key not in spec:
        raise LookupError(f"Definition {spec} has no '{key}' key")
    return resolve(spec[key])(**{k: v for k, v in spec.items() if k != key})


def call_signal(signal: Callable, **context) -> Any:
    """Call `signal` with whichever of the `context` values it accepts.

    Signals need different inputs -- a sinusoid is a function of time `t`, while
    a random walk steps on from the current `value` -- so a caller driving
    signals generically cannot know what to pass. It supplies everything it
    knows about (``t``, ``value`` and ``dt``) and this passes on the subset that
    `signal` declares.
    """
    parameters = inspect.signature(signal).parameters
    if any(p.kind is p.VAR_KEYWORD for p in parameters.values()):
        return signal(**context)
    return signal(**{k: v for k, v in context.items() if k in parameters})
