# django-agent-runtime

[![PyPI version](https://badge.fury.io/py/django-agent-runtime.svg)](https://badge.fury.io/py/django-agent-runtime)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2+](https://img.shields.io/badge/django-4.2+-green.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-ready Django app for AI agent execution. Provides everything you need to run AI agents in production: database models, REST API, real-time streaming, background workers, and more.

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

### 3. Include URLs

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    ...
    path('api/agents/', include('django_agent_runtime.urls')),
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
from django_agent_runtime.models import Conversation

conversation = Conversation.objects.create(
    user=request.user,
    title="My Chat",
    metadata={"source": "web"},
)
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
| `LANGFUSE_ENABLED` | bool | `False` | Enable Langfuse tracing |

## Event Types

| Event | Description |
|-------|-------------|
| `run.started` | Run execution began |
| `run.succeeded` | Run completed successfully |
| `run.failed` | Run failed with error |
| `run.cancelled` | Run was cancelled |
| `run.timed_out` | Run exceeded timeout |
| `tool.call` | Tool was invoked |
| `tool.result` | Tool returned result |
| `assistant.message` | LLM generated message |
| `step.completed` | Agent step completed |
| `checkpoint` | State checkpoint saved |

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

## Frontend Integration

### JavaScript SSE Client

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

## Related Packages

- [agent-runtime-core](https://pypi.org/project/agent-runtime-core/) - The framework-agnostic core library (used internally)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) for details.
