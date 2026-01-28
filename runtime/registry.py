"""
Runtime registry for discovering and managing agent runtimes.

This module provides Django-specific discovery features on top of
agent_runtime_core's registry:
- Settings-based discovery via RUNTIME_REGISTRY
- Entry-point based discovery for plugins
- Database fallback for agents defined in AgentDefinition models

The actual registry is in agent_runtime_core.registry.
This module adds Django-specific autodiscovery and database fallback.
"""

import logging

# Import core registry functions
from agent_runtime_core.registry import (
    register_runtime,
    get_runtime as _core_get_runtime,
    list_runtimes as _core_list_runtimes,
    unregister_runtime,
    clear_registry as _core_clear_registry,
)
from agent_runtime_core.interfaces import AgentRuntime

logger = logging.getLogger(__name__)

# Track whether we've run autodiscovery
_discovered = False

# Re-export core registry functions
__all__ = [
    "register_runtime",
    "get_runtime",
    "get_runtime_async",
    "list_runtimes",
    "list_runtimes_async",
    "unregister_runtime",
    "clear_registry",
    "autodiscover_runtimes",
]


def get_runtime(key: str) -> AgentRuntime:
    """
    Get a registered runtime by key, with database fallback.

    First checks the in-memory registry, then falls back to loading
    from the database (django_agent_studio) if available.

    Note: For async contexts, use get_runtime_async() instead.

    Args:
        key: The runtime key (agent slug)

    Returns:
        The runtime instance

    Raises:
        KeyError: If runtime not found in registry or database
    """
    # Try the core registry first
    try:
        return _core_get_runtime(key)
    except KeyError:
        pass

    # Try loading from database (AgentDefinition models)
    runtime = _load_from_database(key)
    if runtime:
        # Cache it in the registry for future lookups
        register_runtime(runtime, key=key)
        return runtime

    # Not found anywhere
    available = _core_list_runtimes()  # Use core to avoid async issues
    raise KeyError(f"Agent runtime not found: {key}. Available: {available}")


async def get_runtime_async(key: str) -> AgentRuntime:
    """
    Get a registered runtime by key, with database fallback (async version).

    First checks the in-memory registry, then falls back to loading
    from the database (AgentDefinition models) if available.

    Args:
        key: The runtime key (agent slug)

    Returns:
        The runtime instance

    Raises:
        KeyError: If runtime not found in registry or database
    """
    # Try the core registry first
    try:
        return _core_get_runtime(key)
    except KeyError:
        pass

    # Try loading from database (AgentDefinition models)
    runtime = await _load_from_database_async(key)
    if runtime:
        # Cache it in the registry for future lookups
        register_runtime(runtime, key=key)
        return runtime

    # Not found anywhere
    available = await list_runtimes_async()
    raise KeyError(f"Agent runtime not found: {key}. Available: {available}")


def list_runtimes() -> list[str]:
    """
    List all available runtime keys.

    Includes both registered runtimes and database-defined agents.

    Note: For async contexts, use list_runtimes_async() instead.

    Returns:
        List of runtime keys
    """
    keys = set(_core_list_runtimes())

    # Add database agents
    db_keys = _list_database_agents()
    keys.update(db_keys)

    return sorted(keys)


async def list_runtimes_async() -> list[str]:
    """
    List all available runtime keys (async version).

    Includes both registered runtimes and database-defined agents.

    Returns:
        List of runtime keys
    """
    keys = set(_core_list_runtimes())

    # Add database agents
    db_keys = await _list_database_agents_async()
    keys.update(db_keys)

    return sorted(keys)


def _load_from_database(key: str) -> AgentRuntime | None:
    """
    Try to load a runtime from the database.

    Prefers DynamicAgentRuntime from django_agent_studio (has memory support)
    and falls back to DatabaseAgentRuntime if studio is not installed.

    Args:
        key: The agent slug to look up

    Returns:
        AgentRuntime instance or None if not found
    """
    try:
        from django_agent_runtime.models import AgentDefinition

        # Look up by slug - use thread-safe query
        try:
            agent = AgentDefinition.objects.get(slug=key, is_active=True)
        except AgentDefinition.DoesNotExist:
            return None

        # Try DynamicAgentRuntime from django_agent_studio first (has memory support)
        try:
            from django_agent_studio.agents.dynamic import DynamicAgentRuntime
            runtime = DynamicAgentRuntime(agent)
            logger.info(f"Loaded agent runtime from database (DynamicAgentRuntime): {key}")
            return runtime
        except ImportError:
            pass

        # Fall back to DatabaseAgentRuntime (no memory support)
        from django_agent_runtime.runtime.database_runtime import DatabaseAgentRuntime
        runtime = DatabaseAgentRuntime.from_agent(agent)
        logger.info(f"Loaded agent runtime from database (DatabaseAgentRuntime): {key}")
        return runtime

    except ImportError:
        # Models not available
        return None
    except Exception as e:
        logger.warning(f"Error loading agent from database: {e}")
        return None


async def _load_from_database_async(key: str) -> AgentRuntime | None:
    """
    Try to load a runtime from the database (async version).

    Args:
        key: The agent slug to look up

    Returns:
        AgentRuntime instance or None if not found
    """
    from asgiref.sync import sync_to_async
    return await sync_to_async(_load_from_database, thread_sensitive=True)(key)


def _list_database_agents() -> list[str]:
    """
    List agent slugs from the database.

    Returns:
        List of agent slugs
    """
    try:
        from django_agent_runtime.models import AgentDefinition

        return list(
            AgentDefinition.objects.filter(is_active=True)
            .values_list('slug', flat=True)
        )
    except ImportError:
        return []
    except Exception as e:
        logger.warning(f"Error listing database agents: {e}")
        return []


async def _list_database_agents_async() -> list[str]:
    """
    List agent slugs from the database (async version).

    Returns:
        List of agent slugs
    """
    from asgiref.sync import sync_to_async
    return await sync_to_async(_list_database_agents, thread_sensitive=True)()


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

