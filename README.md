# django-agent-runtime

[![PyPI version](https://badge.fury.io/py/django-agent-runtime.svg)](https://badge.fury.io/py/django-agent-runtime)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2+](https://img.shields.io/badge/django-4.2+-green.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-ready Django app for AI agent execution. Provides everything you need to run AI agents in production: database models, REST API, real-time streaming, background workers, and more.

## Recent Updates

| Version | Date | Changes |
|---------|------|---------|
| **0.3.8** | 2025-01-14 | Add agent-frontend docs, agent framework options (OpenAI, Anthropic, LangGraph) |
| **0.3.7** | 2025-01-13 | Fix auto-reload signal handler in threaded mode |
| **0.3.6** | 2025-01-13 | Auto-reload for `runagent` in DEBUG mode (like Django's runserver) |
| **0.3.5** | 2025-01-13 | Added Recent Updates changelog to README |
| **0.3.4** | 2025-01-13 | Documentation updates for message history |
| **0.3.3** | 2025-01-13 | Added `conversation.get_message_history()` for retrieving full message sequences |
| **0.3.2** | 2025-01-13 | Event visibility system - filter events by `internal`/`debug`/`user` levels |
| **0.3.1** | 2025-01-12 | Anonymous session support for unauthenticated users |
| **0.3.0** | 2025-01-11 | ViewSet refactor - base classes for custom auth/permissions |

## Features

- 🔌 **Framework Agnostic** - Works with LangGraph, CrewAI, OpenAI Agents, or custom loops
- 🤖 **Model Agnostic** - OpenAI, Anthropic, or any provider via LiteLLM
- ⚡ **Production-Grade Concurrency** - Multi-process + async workers with `./manage.py runagent`
- 📊 **PostgreSQL Queue** - Reliable, lease-based job queue with automatic retries
- 🔄 **Real-Time Streaming** - Server-Sent Events (SSE) for live UI updates
- 🛡️ **Resilient** - Retries, cancellation, timeouts, and heartbeats built-in
- 📈 **Observable** - Optional Langfuse integration for tracing
- 🧩 **Installable** - Drop-in Django app, ready in minutes

## Installation

```bash
pip install django-agent-runtime

# With LLM providers
pip install django-agent-runtime[openai]
pip install django-agent-runtime[anthropic]

# With Redis support (recommended for production)
pip install django-agent-runtime[redis]

# Everything
pip install django-agent-runtime[all]
```

## Quick Start

### 1. Add to Django Settings

```python
# settings.py
INSTALLED_APPS = [
    ...
    'rest_framework',
    'django_agent_runtime',
]

DJANGO_AGENT_RUNTIME = {
    # Queue & Events
    'QUEUE_BACKEND': 'postgres',      # or 'redis_streams'
    'EVENT_BUS_BACKEND': 'db',        # or 'redis'
    
    # LLM Configuration
    'MODEL_PROVIDER': 'openai',       # or 'anthropic', 'litellm'
    'DEFAULT_MODEL': 'gpt-4o',
    
    # Timeouts
    'LEASE_TTL_SECONDS': 30,
    'RUN_TIMEOUT_SECONDS': 900,
    
    # Agent Discovery
    'RUNTIME_REGISTRY': [
        'myapp.agents:register_agents',
    ],
}
```

### 2. Run Migrations

```bash
python manage.py migrate django_agent_runtime
```

### 3. Set Up API ViewSets and URLs

Create your own ViewSets by inheriting from the base classes and configure authentication:

```python
# myapp/api/views.py
from django_agent_runtime.api.views import BaseAgentRunViewSet, BaseAgentConversationViewSet
from rest_framework.permissions import IsAuthenticated

class AgentRunViewSet(BaseAgentRunViewSet):
    permission_classes = [IsAuthenticated]

class AgentConversationViewSet(BaseAgentConversationViewSet):
    permission_classes = [IsAuthenticated]
```

Then wire up your URLs:

```python
# myapp/api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django_agent_runtime.api.views import sync_event_stream, async_event_stream
from .views import AgentRunViewSet, AgentConversationViewSet

router = DefaultRouter()
router.register(r"conversations", AgentConversationViewSet, basename="conversation")
router.register(r"runs", AgentRunViewSet, basename="run")

urlpatterns = [
    path("", include(router.urls)),
    path("runs/<str:run_id>/events/", sync_event_stream, name="run-events"),
    path("runs/<str:run_id>/events/stream/", async_event_stream, name="run-stream"),
]
```

Include in your main urls.py:

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    ...
    path('api/agents/', include('myapp.api.urls')),
]
```

### 4. Create an Agent

```python
# myapp/agents.py
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime,
    RunContext,
    RunResult,
    EventType,
)
from django_agent_runtime.runtime.registry import register_runtime
from django_agent_runtime.runtime.llm import get_llm_client


class ChatAgent(AgentRuntime):
    """A simple conversational agent."""
    
    @property
    def key(self) -> str:
        return "chat-agent"
    
    async def run(self, ctx: RunContext) -> RunResult:
        # Get the LLM client
        llm = get_llm_client()
        
        # Generate a response
        response = await llm.generate(ctx.input_messages)
        
        # Emit event for real-time streaming
        await ctx.emit(EventType.ASSISTANT_MESSAGE, {
            "content": response.message["content"],
        })
        
        return RunResult(
            final_output={"response": response.message["content"]},
            final_messages=[response.message],
        )


def register_agents():
    """Called by django-agent-runtime on startup."""
    register_runtime(ChatAgent())
```

### 5. Start Workers

```bash
# Start agent workers (4 processes, 20 concurrent runs each)
python manage.py runagent --processes 4 --concurrency 20
```

## API Endpoints

### Create a Run

```http
POST /api/agents/runs/
Content-Type: application/json
Authorization: Token <your-token>

{
    "agent_key": "chat-agent",
    "messages": [
        {"role": "user", "content": "Hello! How are you?"}
    ]
}
```

**Response:**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "agent_key": "chat-agent",
    "status": "queued",
    "created_at": "2024-01-15T10:30:00Z"
}
```

### Stream Events (SSE)

```http
GET /api/agents/runs/{id}/events/
Accept: text/event-stream
```

**Event Stream:**
```
event: run.started
data: {"run_id": "550e8400...", "ts": "2024-01-15T10:30:01Z"}

event: assistant.message
data: {"content": "Hello! I'm doing well, thank you for asking!"}

event: run.succeeded
data: {"run_id": "550e8400...", "output": {...}}
```

### Get Run Status

```http
GET /api/agents/runs/{id}/
```

### Cancel a Run

```http
POST /api/agents/runs/{id}/cancel/
```

### List Conversations

```http
GET /api/agents/conversations/
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Django API    │────▶│   PostgreSQL    │────▶│   Workers       │
│   (REST/SSE)    │     │   Queue         │     │   (runagent)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                                               │
        │                                               ▼
        │                                       ┌─────────────────┐
        │                                       │   Your Agent    │
        │                                       │   (AgentRuntime)│
        │                                       └─────────────────┘
        │                                               │
        ▼                                               ▼
┌─────────────────┐                             ┌─────────────────┐
│   Frontend      │◀────────────────────────────│   Event Bus     │
│   (SSE Client)  │         Real-time           │   (DB/Redis)    │
└─────────────────┘                             └─────────────────┘
```

## Models

### Conversation

Groups related agent runs together:

```python
from django_agent_runtime.models import AgentConversation

conversation = AgentConversation.objects.create(
    user=request.user,
    agent_key="chat-agent",
    title="My Chat",
    metadata={"source": "web"},
)
```

#### Message History

Get the full message history across all runs in a conversation:

```python
# Get all messages (user, assistant, tool calls, tool results)
messages = conversation.get_message_history()

# Include messages from failed runs
messages = conversation.get_message_history(include_failed_runs=True)

# Get just the last assistant message
last_msg = conversation.get_last_assistant_message()
```

Returns messages in the framework-neutral format:
```python
[
    {"role": "user", "content": "What's the weather?"},
    {"role": "assistant", "content": None, "tool_calls": [...]},
    {"role": "tool", "content": "72°F sunny", "tool_call_id": "call_123"},
    {"role": "assistant", "content": "The weather is 72°F and sunny."},
]
```

### AgentRun

Represents a single agent execution:

```python
from django_agent_runtime.models import AgentRun

run = AgentRun.objects.create(
    conversation=conversation,
    agent_key="chat-agent",
    input={"messages": [...]},
)

# After completion, output contains final_messages
messages = run.output.get("final_messages", [])
```

### AgentEvent

Stores events emitted during runs:

```python
from django_agent_runtime.models import AgentEvent

events = AgentEvent.objects.filter(run=run).order_by('seq')
for event in events:
    print(f"{event.event_type}: {event.payload}")
```

## Building Agents with Tools

```python
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime, RunContext, RunResult, EventType,
    Tool, ToolRegistry,
)
from django_agent_runtime.runtime.llm import get_llm_client


def get_weather(location: str) -> str:
    """Get current weather for a location."""
    # Your weather API call here
    return f"Sunny, 72°F in {location}"


def search_database(query: str) -> list:
    """Search the database for relevant information."""
    # Your database search here
    return [{"title": "Result 1", "content": "..."}]


class ToolAgent(AgentRuntime):
    @property
    def key(self) -> str:
        return "tool-agent"
    
    def __init__(self):
        self.tools = ToolRegistry()
        self.tools.register(Tool.from_function(get_weather))
        self.tools.register(Tool.from_function(search_database))
    
    async def run(self, ctx: RunContext) -> RunResult:
        llm = get_llm_client()
        messages = list(ctx.input_messages)
        
        while True:
            response = await llm.generate(
                messages,
                tools=self.tools.to_openai_format(),
            )
            messages.append(response.message)
            
            if not response.tool_calls:
                break
            
            for tool_call in response.tool_calls:
                # Emit tool call event
                await ctx.emit(EventType.TOOL_CALL, {
                    "tool": tool_call["function"]["name"],
                    "arguments": tool_call["function"]["arguments"],
                })
                
                # Execute tool
                result = await self.tools.execute(
                    tool_call["function"]["name"],
                    tool_call["function"]["arguments"],
                )
                
                # Emit result event
                await ctx.emit(EventType.TOOL_RESULT, {
                    "tool_call_id": tool_call["id"],
                    "result": result,
                })
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": str(result),
                })
        
        return RunResult(
            final_output={"response": response.message["content"]},
            final_messages=messages,
        )
```

## Anonymous Sessions

django-agent-runtime supports anonymous sessions for unauthenticated users who have a session token. This is useful for public-facing chat interfaces.

### Setup

1. **Configure the anonymous session model** in your settings:

```python
DJANGO_AGENT_RUNTIME = {
    # ... other settings ...
    'ANONYMOUS_SESSION_MODEL': 'accounts.AnonymousSession',
}
```

2. **Create your anonymous session model** with required fields:

```python
# accounts/models.py
import uuid
from django.db import models
from django.utils import timezone

class AnonymousSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at
```

3. **Set up authentication** in your ViewSets:

```python
from rest_framework.authentication import TokenAuthentication
from django_agent_runtime.api.views import BaseAgentRunViewSet, BaseAgentConversationViewSet
from django_agent_runtime.api.permissions import (
    AnonymousSessionAuthentication,
    IsAuthenticatedOrAnonymousSession,
)

class AgentConversationViewSet(BaseAgentConversationViewSet):
    authentication_classes = [TokenAuthentication, AnonymousSessionAuthentication]
    permission_classes = [IsAuthenticatedOrAnonymousSession]

class AgentRunViewSet(BaseAgentRunViewSet):
    authentication_classes = [TokenAuthentication, AnonymousSessionAuthentication]
    permission_classes = [IsAuthenticatedOrAnonymousSession]
```

### Client Usage

Pass the session token via the `X-Anonymous-Token` header:

```bash
curl -X POST https://api.example.com/agent/runs/ \
  -H "X-Anonymous-Token: your-session-token" \
  -H "Content-Type: application/json" \
  -d '{"agent_key": "chat-agent", "messages": [{"role": "user", "content": "Hello!"}]}'
```

For SSE streaming (where headers can't be set), use a query parameter:

```javascript
const eventSource = new EventSource(
  `/api/agents/runs/${runId}/events/?anonymous_token=your-session-token`
);
```

## Event Visibility

Events have visibility levels that control what's shown to users in the UI:

| Level | Description |
|-------|-------------|
| `internal` | Never shown to UI (heartbeats, checkpoints) |
| `debug` | Shown only in debug mode (tool calls, tool results) |
| `user` | Always shown to users (messages, errors) |

### Configuration

```python
DJANGO_AGENT_RUNTIME = {
    'EVENT_VISIBILITY': {
        'run.started': 'internal',
        'run.failed': 'user',
        'assistant.message': 'user',
        'tool.call': 'debug',
        'tool.result': 'debug',
        'state.checkpoint': 'internal',
        'error': 'user',
    },
    'DEBUG_MODE': False,  # When True, 'debug' events become visible
}
```

### SSE Filtering

The SSE endpoint filters events by visibility:

```javascript
// Only user-visible events (default)
new EventSource(`/api/agents/runs/${runId}/events/`);

// Include debug events
new EventSource(`/api/agents/runs/${runId}/events/?include_debug=true`);

// Include all events (for debugging)
new EventSource(`/api/agents/runs/${runId}/events/?include_all=true`);
```

### Helper Methods

Agent runtimes can use convenience methods:

```python
async def run(self, ctx: RunContext) -> RunResult:
    # Emit a message always shown to users
    await ctx.emit_user_message("Processing your request...")

    # Emit an error shown to users
    await ctx.emit_error("Something went wrong", {"code": "ERR_001"})
```

## Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `QUEUE_BACKEND` | str | `"postgres"` | Queue backend: `postgres`, `redis_streams` |
| `EVENT_BUS_BACKEND` | str | `"db"` | Event bus: `db`, `redis` |
| `REDIS_URL` | str | `None` | Redis connection URL |
| `MODEL_PROVIDER` | str | `"openai"` | LLM provider: `openai`, `anthropic`, `litellm` |
| `DEFAULT_MODEL` | str | `"gpt-4o"` | Default model name |
| `LEASE_TTL_SECONDS` | int | `30` | Worker lease duration |
| `RUN_TIMEOUT_SECONDS` | int | `900` | Maximum run duration |
| `MAX_RETRIES` | int | `3` | Retry attempts on failure |
| `RUNTIME_REGISTRY` | list | `[]` | Agent registration functions |
| `ANONYMOUS_SESSION_MODEL` | str | `None` | Path to anonymous session model |
| `EVENT_VISIBILITY` | dict | See above | Event visibility configuration |
| `DEBUG_MODE` | bool | `False` | Show debug-level events in UI |
| `LANGFUSE_ENABLED` | bool | `False` | Enable Langfuse tracing |

## Event Types

| Event | Visibility | Description |
|-------|------------|-------------|
| `run.started` | internal | Run execution began |
| `run.succeeded` | internal | Run completed successfully |
| `run.failed` | user | Run failed with error |
| `run.cancelled` | user | Run was cancelled |
| `run.timed_out` | user | Run exceeded timeout |
| `run.heartbeat` | internal | Worker heartbeat |
| `tool.call` | debug | Tool was invoked |
| `tool.result` | debug | Tool returned result |
| `assistant.message` | user | LLM generated message |
| `assistant.delta` | user | Token streaming delta |
| `state.checkpoint` | internal | State checkpoint saved |
| `error` | user | Runtime error (distinct from run.failed) |

## Management Commands

### runagent

Start agent workers:

```bash
# Basic usage
python manage.py runagent

# With options
python manage.py runagent \
    --processes 4 \
    --concurrency 20 \
    --agent-keys chat-agent,tool-agent \
    --queue-poll-interval 1.0
```

#### Auto-Reload (Development)

In `DEBUG=True` mode, `runagent` automatically reloads when Python files change—just like Django's `runserver`:

```bash
# Auto-reload enabled by default in DEBUG mode
python manage.py runagent

# Disable auto-reload
python manage.py runagent --noreload
```

**Note:** Auto-reload only works in single-process mode. Multi-process mode (`--processes > 1`) automatically disables auto-reload.

## Frontend Integration

### agent-frontend (Recommended)

The easiest way to add a chat UI is with [agent-frontend](https://github.com/makemore/agent-frontend) - a zero-dependency, embeddable chat widget:

```html
<!-- Include the widget -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/makemore/agent-frontend@main/dist/chat-widget.css">
<script src="https://cdn.jsdelivr.net/gh/makemore/agent-frontend@main/dist/chat-widget.js"></script>

<!-- Initialize -->
<script>
  ChatWidget.init({
    backendUrl: 'https://your-api.com',
    agentKey: 'chat-agent',
    title: 'Support Chat',
    primaryColor: '#0066cc',
  });
</script>
```

Features:
- **Zero dependencies** - Pure vanilla JavaScript
- **SSE streaming** - Real-time token-by-token responses
- **CSS isolated** - Won't conflict with your existing styles
- **Dark mode** - Automatic based on system preferences
- **Session management** - Anonymous sessions out of the box
- **Demo flows** - Built-in auto-run mode for showcasing agent journeys

See the [agent-frontend documentation](https://github.com/makemore/agent-frontend) for full configuration options.

### Custom JavaScript SSE Client

If you're building your own UI:

```javascript
const eventSource = new EventSource('/api/agents/runs/550e8400.../events/');

eventSource.addEventListener('assistant.message', (event) => {
    const data = JSON.parse(event.data);
    appendMessage(data.content);
});

eventSource.addEventListener('run.succeeded', (event) => {
    eventSource.close();
    showComplete();
});

eventSource.addEventListener('run.failed', (event) => {
    const data = JSON.parse(event.data);
    showError(data.error);
    eventSource.close();
});
```

### React Hook Example

```typescript
function useAgentRun(runId: string) {
    const [events, setEvents] = useState<AgentEvent[]>([]);
    const [status, setStatus] = useState<'running' | 'complete' | 'error'>('running');

    useEffect(() => {
        const es = new EventSource(`/api/agents/runs/${runId}/events/`);

        es.onmessage = (event) => {
            const data = JSON.parse(event.data);
            setEvents(prev => [...prev, data]);

            if (data.type === 'run.succeeded') setStatus('complete');
            if (data.type === 'run.failed') setStatus('error');
        };

        return () => es.close();
    }, [runId]);

    return { events, status };
}
```

## Agent Framework Options

django-agent-runtime is framework-agnostic. You can build agents using:

### Option 1: Direct AgentRuntime (Simple)

Best for simple agents or when you want full control:

```python
from django_agent_runtime.runtime.interfaces import AgentRuntime, RunContext, RunResult

class MyAgent(AgentRuntime):
    @property
    def key(self) -> str:
        return "my-agent"

    async def run(self, ctx: RunContext) -> RunResult:
        # Your agent logic here
        ...
```

### Option 2: agent_runtime_framework (Journey-Based)

Best for multi-step conversational flows with state management:

```bash
pip install agent_runtime_framework
```

```python
from agent_runtime_framework.adapters import DjangoRuntimeAdapter
from agent_runtime_framework import BaseJourneyState, BaseJourneyTools, ToolSchema
from enum import Enum

class QuoteStep(str, Enum):
    WELCOME = "welcome"
    COLLECT_INFO = "collect_info"
    GENERATE_QUOTE = "generate_quote"
    COMPLETE = "complete"

class QuoteState(BaseJourneyState[QuoteStep]):
    step: QuoteStep = QuoteStep.WELCOME
    customer_name: str = ""
    coverage_type: str = ""
    # ... state fields

class QuoteTools(BaseJourneyTools[QuoteState]):
    async def save_customer_info(self, name: str, coverage: str) -> str:
        self.state.customer_name = name
        self.state.coverage_type = coverage
        self.state.step = QuoteStep.GENERATE_QUOTE
        await self._notify_state_change()
        return f"Got it, {name}! Generating your {coverage} quote..."

class QuoteAgent(DjangoRuntimeAdapter[QuoteState, QuoteTools, QuoteStep]):
    @property
    def key(self) -> str:
        return "quote-agent"

    def get_initial_state(self) -> QuoteState:
        return QuoteState()

    def get_system_prompt(self, state: QuoteState) -> str:
        prompts = {
            QuoteStep.WELCOME: "Welcome the user and ask what coverage they need.",
            QuoteStep.COLLECT_INFO: "Collect customer name and coverage type.",
            # ...
        }
        return prompts[state.step]

    def get_tool_schemas(self, state: QuoteState) -> list[ToolSchema]:
        # Return different tools based on current step
        ...

    def create_tools(self, state, ctx, backend_client) -> QuoteTools:
        return QuoteTools(state=state)

    async def execute_tool(self, tools, name: str, arguments: dict) -> str:
        return await getattr(tools, name)(**arguments)

# Register with django-agent-runtime
from django_agent_runtime.runtime.registry import register_runtime
register_runtime(QuoteAgent())
```

The adapter handles:
- Converting Django's `RunContext` to framework's `AgentContext`
- State persistence via Django's checkpoint system
- Event emission through Django's event bus
- Returning results in Django's `RunResult` format

See [agent_runtime_framework](https://github.com/makemore/agent-runtime-framework) for full documentation.

### Option 3: OpenAI Agents SDK

Use OpenAI's official Agents SDK with django-agent-runtime:

```python
from django_agent_runtime.runtime.interfaces import AgentRuntime, RunContext, RunResult, EventType
from agents import Agent, Runner

class OpenAIAgentRuntime(AgentRuntime):
    @property
    def key(self) -> str:
        return "openai-agent"

    def __init__(self):
        self.agent = Agent(
            name="Assistant",
            instructions="You are a helpful assistant.",
            model="gpt-4o",
        )

    async def run(self, ctx: RunContext) -> RunResult:
        # Convert messages to OpenAI format
        user_message = ctx.input_messages[-1]["content"]

        # Run the OpenAI agent
        result = await Runner.run(self.agent, user_message)

        # Emit the response
        await ctx.emit(EventType.ASSISTANT_MESSAGE, {
            "content": result.final_output,
        })

        return RunResult(
            final_output={"response": result.final_output},
            final_messages=[{"role": "assistant", "content": result.final_output}],
        )
```

### Option 4: Anthropic Claude with Tool Use

Use Anthropic's Claude directly:

```python
from django_agent_runtime.runtime.interfaces import AgentRuntime, RunContext, RunResult, EventType
import anthropic

class ClaudeAgent(AgentRuntime):
    @property
    def key(self) -> str:
        return "claude-agent"

    def __init__(self):
        self.client = anthropic.AsyncAnthropic()

    async def run(self, ctx: RunContext) -> RunResult:
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in ctx.input_messages
        ]

        response = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=messages,
        )

        content = response.content[0].text

        await ctx.emit(EventType.ASSISTANT_MESSAGE, {"content": content})

        return RunResult(
            final_output={"response": content},
            final_messages=[{"role": "assistant", "content": content}],
        )
```

### Option 5: LangGraph

Wrap LangGraph agents:

```python
from django_agent_runtime.runtime.interfaces import AgentRuntime, RunContext, RunResult, EventType
from langgraph.graph import StateGraph

class LangGraphRuntime(AgentRuntime):
    @property
    def key(self) -> str:
        return "langgraph-agent"

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        # Build your LangGraph here
        ...

    async def run(self, ctx: RunContext) -> RunResult:
        # Run the graph
        result = await self.graph.ainvoke({
            "messages": ctx.input_messages,
        })

        final_message = result["messages"][-1]
        await ctx.emit(EventType.ASSISTANT_MESSAGE, {
            "content": final_message.content,
        })

        return RunResult(
            final_output={"response": final_message.content},
            final_messages=result["messages"],
        )
```

## Related Packages

- [agent-frontend](https://github.com/makemore/agent-frontend) - Zero-dependency embeddable chat widget for AI agents
- [agent-runtime-framework](https://github.com/makemore/agent-runtime-framework) - Journey-based conversational agents with state management
- [agent-runtime-core](https://pypi.org/project/agent-runtime-core/) - The framework-agnostic core library (used internally)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) for details.
