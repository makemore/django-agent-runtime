"""
Management command to run agent workers.

Usage:
    ./manage.py runagent
    ./manage.py runagent --processes 4 --concurrency 20
    ./manage.py runagent --queue redis --agent-keys my-agent,other-agent
    ./manage.py runagent --noreload  # Disable auto-reload in DEBUG mode
"""

import asyncio
import logging
import multiprocessing
import os
import signal
import sys
import uuid
from datetime import datetime
from typing import Optional

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand
from django.utils import autoreload

logger = logging.getLogger(__name__)

# Check DEBUG mode
DEBUG = getattr(django_settings, 'DEBUG', False)


def debug_print(msg: str):
    """Print debug message if Django DEBUG is True."""
    if DEBUG:
        print(f"[agent-worker] {msg}", flush=True)


class Command(BaseCommand):
    help = "Run agent workers to process agent runs"

    # Validation is called explicitly each time the worker restarts with autoreload
    requires_system_checks = []
    suppressed_base_arguments = {"--verbosity", "--traceback"}

    def add_arguments(self, parser):
        parser.add_argument(
            "--processes",
            type=int,
            default=None,
            help="Number of worker processes (default: from settings or 1)",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=None,
            help="Async concurrency per process (default: from settings or 10)",
        )
        parser.add_argument(
            "--queue",
            type=str,
            default=None,
            choices=["postgres", "redis_streams"],
            help="Queue backend (default: from settings)",
        )
        parser.add_argument(
            "--agent-keys",
            type=str,
            default=None,
            help="Comma-separated list of agent keys to process (default: all)",
        )
        parser.add_argument(
            "--lease-ttl-seconds",
            type=int,
            default=None,
            help="Lease TTL in seconds (default: from settings)",
        )
        parser.add_argument(
            "--run-timeout-seconds",
            type=int,
            default=None,
            help="Run timeout in seconds (default: from settings)",
        )
        parser.add_argument(
            "--max-attempts",
            type=int,
            default=None,
            help="Max retry attempts (default: from settings)",
        )
        parser.add_argument(
            "--worker-id",
            type=str,
            default=None,
            help="Worker ID (default: auto-generated)",
        )
        parser.add_argument(
            "--noreload",
            action="store_true",
            help="Disable auto-reload when code changes (only applies in DEBUG mode)",
        )
        parser.add_argument(
            "--skip-checks",
            action="store_true",
            help="Skip system checks.",
        )

    def handle(self, *args, **options):
        # In DEBUG mode with autoreload enabled, use Django's autoreloader
        use_reloader = DEBUG and not options.get("noreload", False)

        if use_reloader:
            # Note: autoreload only works well with single process mode
            if options.get("processes") and options["processes"] > 1:
                self.stdout.write(
                    self.style.WARNING(
                        "Auto-reload is not compatible with multi-process mode. "
                        "Using --noreload or set processes=1 for auto-reload."
                    )
                )
                self._run_inner(*args, **options)
            else:
                # Force single process for autoreload
                options["processes"] = 1
                autoreload.run_with_reloader(self._run_inner, *args, **options)
        else:
            self._run_inner(*args, **options)

    def _run_inner(self, *args, **options):
        """Inner run method - called directly or via autoreloader."""
        # If an exception was silenced in ManagementUtility.execute in order
        # to be raised in the child process, raise it now.
        if DEBUG and not options.get("noreload", False):
            autoreload.raise_last_exception()

        if not options.get("skip_checks", False):
            self.check(display_num_errors=True)

        from django_agent_runtime.conf import runtime_settings

        settings = runtime_settings()

        # Get configuration
        processes = options["processes"] or settings.DEFAULT_PROCESSES
        concurrency = options["concurrency"] or settings.DEFAULT_CONCURRENCY
        queue_backend = options["queue"] or settings.QUEUE_BACKEND
        agent_keys = options["agent_keys"]
        if agent_keys:
            agent_keys = [k.strip() for k in agent_keys.split(",")]

        # Print startup info
        now = datetime.now().strftime("%B %d, %Y - %X")
        quit_command = "CTRL-BREAK" if sys.platform == "win32" else "CONTROL-C"

        self.stdout.write(f"{now}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting agent runtime with {processes} process(es), "
                f"{concurrency} concurrent tasks each"
            )
        )
        self.stdout.write(f"Queue backend: {queue_backend}")
        if agent_keys:
            self.stdout.write(f"Agent keys: {agent_keys}")

        if DEBUG:
            if not options.get("noreload", False):
                self.stdout.write(
                    self.style.WARNING("DEBUG mode: auto-reload enabled (use --noreload to disable)")
                )
            else:
                self.stdout.write(self.style.WARNING("DEBUG mode: verbose logging enabled"))

        self.stdout.write(f"Quit with {quit_command}.")

        if processes == 1:
            # Single process mode - run directly
            self._run_worker(
                worker_num=0,
                concurrency=concurrency,
                queue_backend=queue_backend,
                agent_keys=agent_keys,
                options=options,
            )
        else:
            # Multi-process mode
            self._run_multiprocess(
                processes=processes,
                concurrency=concurrency,
                queue_backend=queue_backend,
                agent_keys=agent_keys,
                options=options,
            )

    def _run_multiprocess(
        self,
        processes: int,
        concurrency: int,
        queue_backend: str,
        agent_keys: Optional[list[str]],
        options: dict,
    ):
        """Run multiple worker processes."""
        workers = []

        def signal_handler(signum, frame):
            self.stdout.write("\nShutting down workers...")
            for p in workers:
                p.terminate()
            for p in workers:
                p.join(timeout=30)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        for i in range(processes):
            p = multiprocessing.Process(
                target=self._run_worker,
                args=(i, concurrency, queue_backend, agent_keys, options),
            )
            p.start()
            workers.append(p)
            self.stdout.write(f"Started worker process {i} (PID: {p.pid})")

        # Wait for all workers
        for p in workers:
            p.join()

    def _run_worker(
        self,
        worker_num: int,
        concurrency: int,
        queue_backend: str,
        agent_keys: Optional[list[str]],
        options: dict,
    ):
        """Run a single worker process."""
        # Generate worker ID
        worker_id = options.get("worker_id") or f"worker-{worker_num}-{uuid.uuid4().hex[:8]}"
        
        debug_print(f"Worker {worker_id} starting...")

        # Run the async worker loop
        asyncio.run(
            self._async_worker_loop(
                worker_id=worker_id,
                concurrency=concurrency,
                queue_backend=queue_backend,
                agent_keys=agent_keys,
                options=options,
            )
        )

    async def _async_worker_loop(
        self,
        worker_id: str,
        concurrency: int,
        queue_backend: str,
        agent_keys: Optional[list[str]],
        options: dict,
    ):
        """Main async worker loop."""
        from django_agent_runtime.conf import runtime_settings
        from django_agent_runtime.runtime.queue import get_queue
        from django_agent_runtime.runtime.events import get_event_bus
        from django_agent_runtime.runtime.runner import AgentRunner
        from django_agent_runtime.runtime.tracing import get_trace_sink

        settings = runtime_settings()

        # Initialize queue
        queue_kwargs = {"lease_ttl_seconds": options.get("lease_ttl_seconds") or settings.LEASE_TTL_SECONDS}
        if queue_backend == "redis_streams":
            queue_kwargs["redis_url"] = settings.REDIS_URL

        queue = get_queue(queue_backend, **queue_kwargs)
        debug_print(f"Queue initialized: {queue_backend}")

        # Initialize event bus
        event_bus_kwargs = {}
        if settings.EVENT_BUS_BACKEND == "redis":
            event_bus_kwargs["redis_url"] = settings.REDIS_URL
            event_bus_kwargs["persist_to_db"] = True
            event_bus_kwargs["persist_token_deltas"] = settings.PERSIST_TOKEN_DELTAS

        event_bus = get_event_bus(settings.EVENT_BUS_BACKEND, **event_bus_kwargs)
        debug_print(f"Event bus initialized: {settings.EVENT_BUS_BACKEND}")

        # Initialize trace sink
        trace_sink = get_trace_sink()

        # Create runner
        runner = AgentRunner(
            worker_id=worker_id,
            queue=queue,
            event_bus=event_bus,
            trace_sink=trace_sink,
        )

        print(f"[agent-worker] Worker {worker_id} ready, polling for runs...", flush=True)

        # Semaphore for concurrency control
        semaphore = asyncio.Semaphore(concurrency)

        # Shutdown event
        shutdown_event = asyncio.Event()

        # Handle signals (only works in main thread)
        loop = asyncio.get_event_loop()

        def handle_shutdown():
            print(f"[agent-worker] Worker {worker_id} shutting down...", flush=True)
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_shutdown)
            except (NotImplementedError, RuntimeError):
                # NotImplementedError: Windows doesn't support add_signal_handler
                # RuntimeError: Can't set signal handler when not in main thread
                #              (happens with autoreload - Django handles signals for us)
                pass

        # Background task for lease recovery
        recovery_task = asyncio.create_task(
            self._lease_recovery_loop(queue, shutdown_event)
        )

        # Main processing loop
        active_tasks: set[asyncio.Task] = set()
        poll_count = 0

        try:
            while not shutdown_event.is_set():
                # Wait for semaphore slot
                await semaphore.acquire()

                if shutdown_event.is_set():
                    semaphore.release()
                    break

                # Try to claim a run
                runs = await queue.claim(
                    worker_id=worker_id,
                    agent_keys=agent_keys,
                    batch_size=1,
                )

                if not runs:
                    semaphore.release()
                    poll_count += 1
                    # Log every 60 polls (roughly every minute at 1s interval)
                    if DEBUG and poll_count % 60 == 0:
                        debug_print(f"Polling... (no runs in queue)")
                    # No work available, wait a bit
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(),
                            timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

                # Reset poll count when we get work
                poll_count = 0

                # Process the run
                run = runs[0]
                print(f"[agent-worker] Claimed run {run.run_id} (agent={run.agent_key})", flush=True)

                async def process_run(r):
                    try:
                        await runner.run_once(r)
                        debug_print(f"Run {r.run_id} completed")
                    except Exception as e:
                        print(f"[agent-worker] ERROR processing run {r.run_id}: {e}", flush=True)
                    finally:
                        semaphore.release()

                task = asyncio.create_task(process_run(run))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)

        finally:
            # Wait for active tasks to complete
            if active_tasks:
                print(f"[agent-worker] Waiting for {len(active_tasks)} active tasks...", flush=True)
                await asyncio.gather(*active_tasks, return_exceptions=True)

            # Cancel recovery task
            recovery_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass

            # Cleanup
            await queue.close()
            await event_bus.close()

            print(f"[agent-worker] Worker {worker_id} stopped", flush=True)

    async def _lease_recovery_loop(self, queue, shutdown_event: asyncio.Event):
        """Periodically recover expired leases."""
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=60.0,  # Check every minute
                )
            except asyncio.TimeoutError:
                pass

            if shutdown_event.is_set():
                break

            try:
                recovered = await queue.recover_expired_leases()
                if recovered:
                    print(f"[agent-worker] Recovered {recovered} expired leases", flush=True)
            except Exception as e:
                print(f"[agent-worker] Error recovering leases: {e}", flush=True)
