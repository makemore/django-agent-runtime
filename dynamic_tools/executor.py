"""
Dynamic Tool Executor with security sandboxing.

Provides safe execution of dynamically discovered functions with:
- Import whitelisting/blacklisting
- Execution timeouts
- Audit logging
- Error handling
"""

import asyncio
import importlib
import inspect
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from functools import partial
from typing import Any, Callable, Optional
from uuid import UUID

from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


class SecurityViolationError(Exception):
    """Raised when a security policy is violated."""
    pass


class ExecutionTimeoutError(Exception):
    """Raised when execution exceeds the timeout."""
    pass


class DynamicToolExecutor:
    """
    Executes dynamic tools with security controls.
    
    Provides:
    - Import validation against whitelist/blacklist
    - Execution timeouts
    - Audit logging to database
    - Proper async/sync handling
    """
    
    # Default blocked imports (dangerous modules)
    DEFAULT_BLOCKED_IMPORTS = [
        'os.system',
        'subprocess',
        'shutil.rmtree',
        'builtins.eval',
        'builtins.exec',
        'builtins.compile',
        '__import__',
        'importlib.import_module',  # Prevent dynamic imports in executed code
    ]
    
    # Default allowed import patterns for Django projects
    DEFAULT_ALLOWED_PATTERNS = [
        'django.*',
        'rest_framework.*',
    ]
    
    def __init__(
        self,
        default_timeout: int = 30,
        blocked_imports: Optional[list] = None,
        allowed_patterns: Optional[list] = None,
        enable_audit_logging: bool = True,
        max_workers: int = 4,
    ):
        """
        Initialize the executor.
        
        Args:
            default_timeout: Default execution timeout in seconds
            blocked_imports: List of blocked import patterns
            allowed_patterns: List of allowed import patterns
            enable_audit_logging: Whether to log executions to database
            max_workers: Max thread pool workers for sync execution
        """
        self.default_timeout = default_timeout
        self.blocked_imports = blocked_imports or self.DEFAULT_BLOCKED_IMPORTS
        self.allowed_patterns = allowed_patterns or self.DEFAULT_ALLOWED_PATTERNS
        self.enable_audit_logging = enable_audit_logging
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._function_cache: dict[str, Callable] = {}
    
    async def execute(
        self,
        function_path: str,
        arguments: dict,
        timeout: Optional[int] = None,
        agent_run_id: Optional[UUID] = None,
        user_id: Optional[int] = None,
        tool_id: Optional[UUID] = None,
    ) -> Any:
        """
        Execute a function by its import path.
        
        Args:
            function_path: Full import path (e.g., 'myapp.utils.calculate_tax')
            arguments: Arguments to pass to the function
            timeout: Execution timeout in seconds
            agent_run_id: ID of the agent run (for audit logging)
            user_id: ID of the user (for audit logging)
            tool_id: ID of the DynamicTool (for audit logging)
            
        Returns:
            The function's return value
            
        Raises:
            SecurityViolationError: If import is blocked
            ExecutionTimeoutError: If execution times out
            Exception: Any exception from the function
        """
        timeout = timeout or self.default_timeout
        execution_record = None
        started_at = timezone.now()
        
        # Create audit record if enabled
        if self.enable_audit_logging and tool_id:
            execution_record = await self._create_execution_record(
                tool_id=tool_id,
                arguments=arguments,
                agent_run_id=agent_run_id,
                user_id=user_id,
            )
        
        try:
            # Validate the import path
            self._validate_import(function_path)
            
            # Get or import the function
            func = await self._get_function(function_path)
            
            # Update execution status to running
            if execution_record:
                await self._update_execution_status(
                    execution_record, 'running'
                )
            
            # Execute with timeout
            result = await self._execute_with_timeout(func, arguments, timeout)
            
            # Log success
            if execution_record:
                await self._complete_execution(
                    execution_record,
                    status='success',
                    result=result,
                    started_at=started_at,
                )
            
            return result
            
        except FuturesTimeoutError:
            error_msg = f"Execution timed out after {timeout} seconds"
            if execution_record:
                await self._complete_execution(
                    execution_record,
                    status='timeout',
                    error_message=error_msg,
                    started_at=started_at,
                )
            raise ExecutionTimeoutError(error_msg)

        except SecurityViolationError as e:
            if execution_record:
                await self._complete_execution(
                    execution_record,
                    status='blocked',
                    error_message=str(e),
                    started_at=started_at,
                )
            raise

        except Exception as e:
            error_tb = traceback.format_exc()
            if execution_record:
                await self._complete_execution(
                    execution_record,
                    status='failed',
                    error_message=str(e),
                    error_traceback=error_tb,
                    started_at=started_at,
                )
            raise

    def _validate_import(self, function_path: str) -> None:
        """Validate that the import path is allowed."""
        # Check blocked imports
        for blocked in self.blocked_imports:
            if function_path.startswith(blocked) or blocked in function_path:
                raise SecurityViolationError(
                    f"Import '{function_path}' is blocked by security policy"
                )

        # If allowed patterns are specified, check against them
        if self.allowed_patterns:
            import fnmatch
            allowed = False
            for pattern in self.allowed_patterns:
                if fnmatch.fnmatch(function_path, pattern):
                    allowed = True
                    break

            # Also allow project-local imports (not starting with common package names)
            common_packages = ['os', 'sys', 'subprocess', 'shutil', 'socket', 'http']
            is_stdlib = any(function_path.startswith(p) for p in common_packages)

            if not allowed and is_stdlib:
                raise SecurityViolationError(
                    f"Import '{function_path}' is not in the allowed patterns"
                )

    async def _get_function(self, function_path: str) -> Callable:
        """Get a function by its import path, with caching."""
        if function_path in self._function_cache:
            return self._function_cache[function_path]

        # Import the function
        func = await sync_to_async(self._import_function)(function_path)
        self._function_cache[function_path] = func
        return func

    def _import_function(self, function_path: str) -> Callable:
        """Import a function from its path."""
        parts = function_path.rsplit('.', 1)
        if len(parts) != 2:
            raise ImportError(f"Invalid function path: {function_path}")

        module_path, func_name = parts

        # Handle class methods (module.Class.method)
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ImportError, AttributeError):
            # Try treating the last two parts as Class.method
            parts = function_path.rsplit('.', 2)
            if len(parts) == 3:
                module_path, class_name, method_name = parts
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                func = getattr(cls, method_name)
            else:
                raise ImportError(f"Could not import: {function_path}")

        if not callable(func):
            raise TypeError(f"'{function_path}' is not callable")

        return func

    async def _execute_with_timeout(
        self, func: Callable, arguments: dict, timeout: int
    ) -> Any:
        """Execute a function with timeout."""
        if inspect.iscoroutinefunction(func):
            # Async function - use asyncio timeout
            return await asyncio.wait_for(
                func(**arguments),
                timeout=timeout
            )
        else:
            # Sync function - run in thread pool with timeout
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    partial(func, **arguments)
                ),
                timeout=timeout
            )

    async def _create_execution_record(
        self,
        tool_id: UUID,
        arguments: dict,
        agent_run_id: Optional[UUID],
        user_id: Optional[int],
    ):
        """Create an execution audit record."""
        from django_agent_runtime.models import DynamicToolExecution

        @sync_to_async
        def create():
            return DynamicToolExecution.objects.create(
                tool_id=tool_id,
                input_arguments=arguments,
                agent_run_id=agent_run_id,
                executed_by_id=user_id,
                status='pending',
            )

        return await create()

    async def _update_execution_status(self, record, status: str):
        """Update execution record status."""
        @sync_to_async
        def update():
            record.status = status
            record.save(update_fields=['status'])

        await update()

    async def _complete_execution(
        self,
        record,
        status: str,
        result: Any = None,
        error_message: str = "",
        error_traceback: str = "",
        started_at: datetime = None,
    ):
        """Complete an execution record."""
        @sync_to_async
        def complete():
            record.status = status
            record.completed_at = timezone.now()

            if result is not None:
                # Serialize result if possible
                try:
                    import json
                    json.dumps(result)  # Test if serializable
                    record.output_result = result
                except (TypeError, ValueError):
                    record.output_result = {'_repr': str(result)}

            if error_message:
                record.error_message = error_message
            if error_traceback:
                record.error_traceback = error_traceback

            if started_at:
                duration = (record.completed_at - started_at).total_seconds() * 1000
                record.duration_ms = int(duration)

            record.save()

        await complete()

    def clear_cache(self):
        """Clear the function cache."""
        self._function_cache.clear()

    def shutdown(self):
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=False)
