"""Tests for debug/production mode configuration."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from django_agent_runtime.conf import (
    AgentRuntimeSettings,
    runtime_settings,
    reset_settings,
    is_debug,
    should_swallow_exceptions,
    configure,
    _get_debug_from_env,
)


class TestAgentRuntimeSettings:
    """Tests for AgentRuntimeSettings dataclass."""
    
    def test_default_swallow_exceptions(self):
        """Default should be to swallow exceptions (production mode)."""
        settings = AgentRuntimeSettings()
        assert settings.SWALLOW_EXCEPTIONS is True
    
    def test_explicit_swallow_exceptions_false(self):
        """Can explicitly set SWALLOW_EXCEPTIONS to False."""
        settings = AgentRuntimeSettings(SWALLOW_EXCEPTIONS=False)
        assert settings.SWALLOW_EXCEPTIONS is False


class TestDebugFromEnv:
    """Tests for _get_debug_from_env function."""
    
    def test_env_not_set(self, monkeypatch):
        """Returns False when env var is not set."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        assert _get_debug_from_env() is False
    
    def test_env_set_to_1(self, monkeypatch):
        """Returns True when env var is '1'."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "1")
        assert _get_debug_from_env() is True
    
    def test_env_set_to_true(self, monkeypatch):
        """Returns True when env var is 'true'."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "true")
        assert _get_debug_from_env() is True
    
    def test_env_set_to_TRUE(self, monkeypatch):
        """Returns True when env var is 'TRUE' (case insensitive)."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "TRUE")
        assert _get_debug_from_env() is True
    
    def test_env_set_to_yes(self, monkeypatch):
        """Returns True when env var is 'yes'."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "yes")
        assert _get_debug_from_env() is True
    
    def test_env_set_to_on(self, monkeypatch):
        """Returns True when env var is 'on'."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "on")
        assert _get_debug_from_env() is True
    
    def test_env_set_to_0(self, monkeypatch):
        """Returns False when env var is '0'."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "0")
        assert _get_debug_from_env() is False
    
    def test_env_set_to_false(self, monkeypatch):
        """Returns False when env var is 'false'."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "false")
        assert _get_debug_from_env() is False
    
    def test_env_set_to_random_string(self, monkeypatch):
        """Returns False when env var is a random string."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "random")
        assert _get_debug_from_env() is False


class TestIsDebug:
    """Tests for is_debug function."""
    
    def setup_method(self):
        """Reset settings before each test."""
        reset_settings()
    
    def teardown_method(self):
        """Reset settings after each test."""
        reset_settings()
    
    def test_default_is_not_debug(self, monkeypatch):
        """Default is not debug mode."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        assert is_debug() is False
    
    def test_env_var_enables_debug(self, monkeypatch):
        """Environment variable enables debug mode."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "1")
        assert is_debug() is True
    
    def test_settings_swallow_false_enables_debug(self, monkeypatch):
        """SWALLOW_EXCEPTIONS=False enables debug mode."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(swallow_exceptions=False)
        assert is_debug() is True
    
    def test_env_var_takes_precedence(self, monkeypatch):
        """Environment variable takes precedence over settings."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "1")
        # Even with swallow_exceptions=True, env var wins
        configure(swallow_exceptions=True)
        assert is_debug() is True


class TestShouldSwallowExceptions:
    """Tests for should_swallow_exceptions function."""
    
    def setup_method(self):
        """Reset settings before each test."""
        reset_settings()
    
    def teardown_method(self):
        """Reset settings after each test."""
        reset_settings()
    
    def test_default_swallows_exceptions(self, monkeypatch):
        """Default is to swallow exceptions (production mode)."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        assert should_swallow_exceptions() is True
    
    def test_debug_mode_does_not_swallow(self, monkeypatch):
        """Debug mode does not swallow exceptions."""
        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "1")
        assert should_swallow_exceptions() is False
    
    def test_configure_debug_true(self, monkeypatch):
        """configure(debug=True) disables exception swallowing."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(debug=True)
        assert should_swallow_exceptions() is False
    
    def test_configure_debug_false(self, monkeypatch):
        """configure(debug=False) enables exception swallowing."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(debug=False)
        assert should_swallow_exceptions() is True


class TestConfigure:
    """Tests for configure function."""
    
    def setup_method(self):
        """Reset settings before each test."""
        reset_settings()
    
    def teardown_method(self):
        """Reset settings after each test."""
        reset_settings()
    
    def test_configure_debug_true(self, monkeypatch):
        """configure(debug=True) sets debug mode."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(debug=True)
        
        settings = runtime_settings()
        assert settings.DEBUG_MODE is True
        assert settings.SWALLOW_EXCEPTIONS is False
    
    def test_configure_debug_false(self, monkeypatch):
        """configure(debug=False) sets production mode."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(debug=False)
        
        settings = runtime_settings()
        assert settings.DEBUG_MODE is False
        assert settings.SWALLOW_EXCEPTIONS is True
    
    def test_configure_swallow_exceptions_explicit(self, monkeypatch):
        """Can explicitly set swallow_exceptions independent of debug."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        # Debug mode but still swallow exceptions
        configure(debug=True, swallow_exceptions=True)
        
        settings = runtime_settings()
        assert settings.DEBUG_MODE is True
        assert settings.SWALLOW_EXCEPTIONS is True
    
    def test_configure_only_swallow_exceptions(self, monkeypatch):
        """Can configure only swallow_exceptions."""
        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(swallow_exceptions=False)

        settings = runtime_settings()
        assert settings.SWALLOW_EXCEPTIONS is False


class TestRegistryDebugMode:
    """Tests for registry respecting debug mode."""

    def setup_method(self):
        """Reset settings before each test."""
        reset_settings()

    def teardown_method(self):
        """Reset settings after each test."""
        reset_settings()

    def test_registry_swallows_errors_in_production(self, monkeypatch):
        """Registry swallows import errors in production mode."""
        from django_agent_runtime.runtime.registry import _discover_from_settings, clear_registry
        from django_agent_runtime import conf

        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(debug=False)
        clear_registry()

        # Mock settings to have a bad registry path
        original_runtime_settings = conf.runtime_settings
        mock_settings = MagicMock()
        mock_settings.RUNTIME_REGISTRY = ['nonexistent.module:register']
        monkeypatch.setattr(conf, 'runtime_settings', lambda: mock_settings)

        try:
            # Should not raise - errors are swallowed
            _discover_from_settings()
        finally:
            monkeypatch.setattr(conf, 'runtime_settings', original_runtime_settings)

    def test_registry_raises_errors_in_debug(self, monkeypatch):
        """Registry raises import errors in debug mode."""
        from django_agent_runtime.runtime.registry import _discover_from_settings, clear_registry
        from django_agent_runtime import conf

        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "1")
        clear_registry()

        # Mock settings to have a bad registry path
        original_runtime_settings = conf.runtime_settings
        mock_settings = MagicMock()
        mock_settings.RUNTIME_REGISTRY = ['nonexistent.module:register']
        monkeypatch.setattr(conf, 'runtime_settings', lambda: mock_settings)

        try:
            # Should raise in debug mode
            with pytest.raises(Exception):
                _discover_from_settings()
        finally:
            monkeypatch.setattr(conf, 'runtime_settings', original_runtime_settings)


class TestRunnerDebugMode:
    """Tests for runner respecting debug mode."""

    def setup_method(self):
        """Reset settings before each test."""
        reset_settings()

    def teardown_method(self):
        """Reset settings after each test."""
        reset_settings()

    @pytest.mark.asyncio
    async def test_completion_hook_swallows_errors_in_production(self, monkeypatch):
        """Completion hook swallows errors in production mode."""
        from django_agent_runtime.runtime.runner import AgentRunner
        from django_agent_runtime import conf
        from uuid import uuid4

        monkeypatch.delenv("DJANGO_AGENT_RUNTIME_DEBUG", raising=False)
        configure(debug=False)

        # Create a mock runner
        runner = AgentRunner(
            worker_id="test-worker",
            queue=MagicMock(),
            event_bus=MagicMock(),
        )

        # Mock the hook to raise an error
        def failing_hook(run_id, output):
            raise ValueError("Hook failed!")

        # Patch get_hook in conf module
        original_get_hook = conf.get_hook
        monkeypatch.setattr(conf, 'get_hook', lambda x: failing_hook)

        try:
            # Should not raise - errors are swallowed
            await runner._call_completion_hook(uuid4(), {"output": "test"})
        finally:
            monkeypatch.setattr(conf, 'get_hook', original_get_hook)

    @pytest.mark.asyncio
    async def test_completion_hook_raises_errors_in_debug(self, monkeypatch):
        """Completion hook raises errors in debug mode."""
        from django_agent_runtime.runtime.runner import AgentRunner
        from django_agent_runtime import conf
        from uuid import uuid4

        monkeypatch.setenv("DJANGO_AGENT_RUNTIME_DEBUG", "1")

        # Create a mock runner
        runner = AgentRunner(
            worker_id="test-worker",
            queue=MagicMock(),
            event_bus=MagicMock(),
        )

        # Mock the hook to raise an error
        def failing_hook(run_id, output):
            raise ValueError("Hook failed!")

        # Patch get_hook in conf module
        original_get_hook = conf.get_hook
        monkeypatch.setattr(conf, 'get_hook', lambda x: failing_hook)

        try:
            # Should raise in debug mode
            with pytest.raises(ValueError, match="Hook failed!"):
                await runner._call_completion_hook(uuid4(), {"output": "test"})
        finally:
            monkeypatch.setattr(conf, 'get_hook', original_get_hook)

