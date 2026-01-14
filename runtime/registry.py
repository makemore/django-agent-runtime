"""
Runtime registry for discovering and managing agent runtimes.

Supports:
- Manual registration via register_runtime()
- Settings-based discovery via RUNTIME_REGISTRY
- Entry-point based discovery for plugins
"""

import logging
from typing import Callable, Optional, Type, Union

from django_agent_runtime.runtime.interfaces import AgentRuntime

logger = logging.getLogger(__name__)

# Global registry of agent runtimes
_runtimes: dict[str, AgentRuntime] = {}
_runtime_factories: dict[str, Callable[[], AgentRuntime]] = {}
_discovered = False


def _is_agent_runtime(obj) -> bool:
    """
    Check if an object is an AgentRuntime instance.

    Supports both django_agent_runtime.AgentRuntime and agent_runtime_core.AgentRuntime.
    Uses duck typing to check for required interface.
    """
    # Check for django_agent_runtime.AgentRuntime
    if isinstance(obj, AgentRuntime):
        return True

    # Duck-type check for agent_runtime_core.AgentRuntime or similar
    # Must have 'key' property and 'run' async method
    if hasattr(obj, 'key') and hasattr(obj, 'run') and callable(getattr(obj, 'run', None)):
        return True

    return False


def _is_agent_runtime_class(cls) -> bool:
    """
    Check if a class is an AgentRuntime subclass.

    Supports both django_agent_runtime.AgentRuntime and agent_runtime_core.AgentRuntime.
    """
    if not isinstance(cls, type):
        return False

    # Check for django_agent_runtime.AgentRuntime
    if issubclass(cls, AgentRuntime):
        return True

    # Check for agent_runtime_core.AgentRuntime by name
    for base in cls.__mro__:
        if base.__name__ == 'AgentRuntime':
            return True

    return False


def register_runtime(
    runtime: Union[AgentRuntime, Type[AgentRuntime], Callable[[], AgentRuntime]],
    key: Optional[str] = None,
) -> None:
    """
    Register an agent runtime.

    Args:
        runtime: Runtime instance, class, or factory function
        key: Optional key override (uses runtime.key if not provided)

    Examples:
        # Register an instance
        register_runtime(MyRuntime())

        # Register a class (will be instantiated)
        register_runtime(MyRuntime)

        # Register with custom key
        register_runtime(MyRuntime(), key="custom-key")

        # Register a factory
        register_runtime(lambda: MyRuntime(config=get_config()))
    """
    if _is_agent_runtime(runtime):
        # Instance provided
        runtime_key = key or runtime.key
        _runtimes[runtime_key] = runtime
        logger.info(f"Registered agent runtime: {runtime_key}")

    elif _is_agent_runtime_class(runtime):
        # Class provided - instantiate it
        instance = runtime()
        runtime_key = key or instance.key
        _runtimes[runtime_key] = instance
        logger.info(f"Registered agent runtime: {runtime_key}")

    elif callable(runtime):
        # Factory function provided
        if not key:
            raise ValueError("key is required when registering a factory function")
        _runtime_factories[key] = runtime
        logger.info(f"Registered agent runtime factory: {key}")

    else:
        raise TypeError(
            f"runtime must be AgentRuntime instance, class, or callable, got {type(runtime)}"
        )


def get_runtime(key: str) -> AgentRuntime:
    """
    Get a runtime by key.

    Args:
        key: Runtime key

    Returns:
        AgentRuntime instance

    Raises:
        KeyError: If runtime not found
    """
    # Check instances first
    if key in _runtimes:
        return _runtimes[key]

    # Check factories
    if key in _runtime_factories:
        instance = _runtime_factories[key]()
        _runtimes[key] = instance
        return instance

    raise KeyError(f"Agent runtime not found: {key}. Available: {list_runtimes()}")


def list_runtimes() -> list[str]:
    """List all registered runtime keys."""
    return list(set(_runtimes.keys()) | set(_runtime_factories.keys()))


def unregister_runtime(key: str) -> bool:
    """
    Unregister a runtime.

    Args:
        key: Runtime key

    Returns:
        True if removed, False if not found
    """
    removed = False
    if key in _runtimes:
        del _runtimes[key]
        removed = True
    if key in _runtime_factories:
        del _runtime_factories[key]
        removed = True
    return removed


def clear_registry() -> None:
    """Clear all registered runtimes. Useful for testing."""
    global _discovered
    _runtimes.clear()
    _runtime_factories.clear()
    _discovered = False


def autodiscover_runtimes() -> None:
    """
    Auto-discover runtimes from settings and entry points.

    Called automatically when Django starts (in apps.py ready()).
    """
    global _discovered
    if _discovered:
        return

    _discovered = True

    # Discover from settings
    _discover_from_settings()

    # Discover from entry points
    _discover_from_entry_points()


def _discover_from_settings() -> None:
    """Discover runtimes from DJANGO_AGENT_RUNTIME['RUNTIME_REGISTRY']."""
    from django_agent_runtime.conf import runtime_settings

    settings = runtime_settings()

    for dotted_path in settings.RUNTIME_REGISTRY:
        try:
            from django.utils.module_loading import import_string

            register_func = import_string(dotted_path)
            register_func()
            logger.info(f"Loaded runtime registry from: {dotted_path}")
        except Exception as e:
            logger.error(f"Failed to load runtime registry {dotted_path}: {e}")


def _discover_from_entry_points() -> None:
    """Discover runtimes from entry points."""
    try:
        from importlib.metadata import entry_points
    except ImportError:
        from importlib_metadata import entry_points

    try:
        eps = entry_points(group="django_agent_runtime.runtimes")
        for ep in eps:
            try:
                register_func = ep.load()
                register_func()
                logger.info(f"Loaded runtime from entry point: {ep.name}")
            except Exception as e:
                logger.error(f"Failed to load entry point {ep.name}: {e}")
    except Exception as e:
        logger.debug(f"No entry points found: {e}")

