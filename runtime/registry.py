"""
Runtime registry for discovering and managing agent runtimes.

This module provides Django-specific discovery features on top of
agent_runtime_core's registry:
- Settings-based discovery via RUNTIME_REGISTRY
- Entry-point based discovery for plugins

The actual registry is in agent_runtime_core.registry.
This module adds Django-specific autodiscovery.
"""

import logging

# Import core registry functions
from agent_runtime_core.registry import (
    register_runtime,
    get_runtime,
    list_runtimes,
    unregister_runtime,
    clear_registry as _core_clear_registry,
)

logger = logging.getLogger(__name__)

# Track whether we've run autodiscovery
_discovered = False

# Re-export core registry functions
__all__ = [
    "register_runtime",
    "get_runtime",
    "list_runtimes",
    "unregister_runtime",
    "clear_registry",
    "autodiscover_runtimes",
]


def clear_registry() -> None:
    """Clear all registered runtimes. Useful for testing."""
    global _discovered
    _core_clear_registry()
    _discovered = False


def autodiscover_runtimes() -> None:
    """
    Auto-discover runtimes from settings and entry points.

    Called automatically when Django starts (in apps.py ready()).
    Uses agent_runtime_core's registry for actual registration.
    """
    global _discovered
    if _discovered:
        return

    _discovered = True

    # Discover from settings
    _discover_from_settings()

    # Discover from entry points
    _discover_from_entry_points()


def _normalize_import_path(path: str) -> str:
    """
    Normalize an import path to use dots instead of colons.

    Supports both formats:
    - 'myapp.agents:register_agents' (colon separator)
    - 'myapp.agents.register_agents' (all dots)

    Args:
        path: Import path in either format

    Returns:
        Normalized path using dots (e.g., 'myapp.agents.register_agents')
    """
    if ':' in path:
        # Convert 'module.path:attribute' to 'module.path.attribute'
        module_path, attribute = path.rsplit(':', 1)
        return f"{module_path}.{attribute}"
    return path


def _discover_from_settings() -> None:
    """Discover runtimes from DJANGO_AGENT_RUNTIME['RUNTIME_REGISTRY']."""
    from django_agent_runtime.conf import runtime_settings, should_swallow_exceptions

    settings = runtime_settings()

    for path in settings.RUNTIME_REGISTRY:
        try:
            from django.utils.module_loading import import_string

            # Normalize path to support both colon and dot separators
            dotted_path = _normalize_import_path(path)
            register_func = import_string(dotted_path)
            register_func()
            logger.info(f"Loaded runtime registry from: {path}")
        except Exception as e:
            # In debug mode, re-raise exceptions immediately
            if not should_swallow_exceptions():
                logger.error(f"Failed to load runtime registry {path} (debug mode - re-raising): {e}")
                raise
            logger.error(f"Failed to load runtime registry {path}: {e}")


def _discover_from_entry_points() -> None:
    """Discover runtimes from entry points."""
    from django_agent_runtime.conf import should_swallow_exceptions

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
                # In debug mode, re-raise exceptions immediately
                if not should_swallow_exceptions():
                    logger.error(f"Failed to load entry point {ep.name} (debug mode - re-raising): {e}")
                    raise
                logger.error(f"Failed to load entry point {ep.name}: {e}")
    except Exception as e:
        # Don't re-raise "no entry points" errors even in debug mode
        logger.debug(f"No entry points found: {e}")

