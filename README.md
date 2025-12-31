# Django Agent Runtime

A production-ready, installable Django app for AI agent execution with multi-process + async concurrency.

## Features

- **Framework-agnostic**: Works with LangGraph, CrewAI, OpenAI Agents, or custom loops
- **Model-agnostic**: OpenAI, Anthropic, or any provider via LiteLLM
- **Production-grade concurrency**: Multi-process + async with `./manage.py runagent`
- **Lease-based queue**: PostgreSQL (baseline) or Redis Streams (recommended)
- **Event streaming**: SSE endpoint for real-time UI updates
- **Resilient**: Retries, cancellation, timeouts, heartbeats
- **Observable**: Optional Langfuse integration
- **Installable**: Ready to extract as a pip package

## Quick Start

### 1. Installation

```bash
# Add to INSTALLED_APPS
INSTALLED_APPS = [
    ...
    'django_agent_runtime',
]

# Run migrations
python manage.py migrate django_agent_runtime
```

### 2. Configuration

Add to your Django settings:

```python
DJANGO_AGENT_RUNTIME = {
    'QUEUE_BACKEND': 'postgres',  # or 'redis_streams'
    'EVENT_BUS_BACKEND': 'db',    # or 'redis'
    'REDIS_URL': 'redis://localhost:6379/0',
    
    # Timeouts
    'LEASE_TTL_SECONDS': 30,
    'RUN_TIMEOUT_SECONDS': 900,
    
    # LLM
    'MODEL_PROVIDER': 'openai',
    'DEFAULT_MODEL': 'gpt-4o',
    
    # Agent discovery
    'RUNTIME_REGISTRY': [
        'myapp.agents:register_agents',
    ],
}
```

### 3. Create an Agent

```python
# myapp/agents.py
from django_agent_runtime.runtime.interfaces import (
    AgentRuntime, RunContext, RunResult, EventType
)
from django_agent_runtime.runtime.registry import register_runtime
from django_agent_runtime.runtime.llm import get_llm_client


class MyAgent(AgentRuntime):
    @property
    def key(self) -> str:
        return "my-agent"
    
    async def run(self, ctx: RunContext) -> RunResult:
        llm = get_llm_client()
        
        response = await llm.generate(ctx.input_messages)
        
        await ctx.emit(EventType.ASSISTANT_MESSAGE, {
            "content": response.message["content"],
        })
        
        return RunResult(
            final_output={"response": response.message["content"]},
            final_messages=[response.message],
        )


def register_agents():
    register_runtime(MyAgent())
```

### 4. Include URLs

```python
# urls.py
urlpatterns = [
    path('api/agent-runtime/', include('django_agent_runtime.urls')),
]
```

### 5. Start Workers

```bash
# Start agent workers
python manage.py runagent --processes 4 --concurrency 20
```

## API Endpoints

### Create a Run

```http
POST /api/agent-runtime/runs/
Content-Type: application/json
Authorization: Token <token>

{
    "agent_key": "my-agent",
    "messages": [
        {"role": "user", "content": "Hello!"}
    ]
}
```

### Stream Events (SSE)

```http
GET /api/agent-runtime/runs/{id}/events/
Accept: text/event-stream
```

### Cancel a Run

```http
POST /api/agent-runtime/runs/{id}/cancel/
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Django API    │────▶│   Queue         │────▶│   Workers       │
│   (REST/SSE)    │     │   (PG/Redis)    │     │   (runagent)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                                ┌─────────────────┐
                                                │   Agent Runtime │
                                                │   (Your Code)   │
                                                └─────────────────┘
```

## Event Types

- `run.started` - Run execution began
- `run.succeeded` - Run completed successfully
- `run.failed` - Run failed with error
- `run.cancelled` - Run was cancelled
- `run.timed_out` - Run exceeded timeout
- `tool.call` - Tool was called
- `tool.result` - Tool returned result
- `assistant.message` - Assistant generated message
- `step.completed` - Agent step completed
- `checkpoint` - State checkpoint saved

## License

MIT

