# AI Core Service Documentation

## Overview

The AI Core Service provides a unified interface for interacting with multiple AI providers (OpenAI, Gemini) in Agira. It offers:

- **Multi-provider support**: OpenAI and Gemini (Claude can be added later)
- **Unified API**: Consistent interface regardless of provider
- **Automatic logging**: All API calls logged to `AIJobsHistory`
- **Cost tracking**: Automatic cost calculation based on token usage
- **Flexible routing**: Smart model selection based on configuration

## Architecture

### Package Structure

```
agira/core/services/ai/
├── __init__.py          # Package exports
├── router.py            # Main AIRouter class
├── base_provider.py     # Base provider interface
├── openai_provider.py   # OpenAI implementation
├── gemini_provider.py   # Gemini implementation
├── pricing.py           # Cost calculation
└── schemas.py           # Data classes for requests/responses
```

### Database Models

#### AIProvider
Stores provider configuration:
- `name`: Display name
- `provider_type`: OpenAI, Gemini, or Claude
- `api_key`: Encrypted API key
- `organization_id`: Optional (for OpenAI organization)
- `active`: Enable/disable provider

#### AIModel
Stores model configuration and pricing:
- `provider`: Foreign key to AIProvider
- `name`: Display name
- `model_id`: Provider-specific model identifier (e.g., "gpt-4", "gemini-pro")
- `input_price_per_1m_tokens`: Price per 1M input tokens
- `output_price_per_1m_tokens`: Price per 1M output tokens
- `active`: Enable/disable model
- `is_default`: Use as default for this provider

#### AIJobsHistory
Logs every AI API call:
- `agent`: Agent name (default: "core.ai")
- `user`: Optional user reference
- `provider`: Provider used
- `model`: Model used
- `status`: Pending, Completed, or Error
- `client_ip`: Optional client IP
- `input_tokens`: Input token count
- `output_tokens`: Output token count
- `costs`: Calculated cost in USD
- `timestamp`: When the call was made
- `duration_ms`: Duration in milliseconds
- `error_message`: Error details if failed

## Usage

### Basic Usage

```python
from core.services.ai import AIRouter

# Initialize router
router = AIRouter()

# Simple text generation
response = router.generate(
    prompt="Explain quantum computing in simple terms",
    user=request.user,  # Optional
    client_ip=request.META.get('REMOTE_ADDR')  # Optional
)

print(response.text)
print(f"Cost: ${response.costs}")
print(f"Tokens: {response.input_tokens} in, {response.output_tokens} out")
```

### Chat Conversation

```python
from core.services.ai import AIRouter

router = AIRouter()

messages = [
    {'role': 'system', 'content': 'You are a helpful assistant.'},
    {'role': 'user', 'content': 'What is the capital of France?'},
    {'role': 'assistant', 'content': 'The capital of France is Paris.'},
    {'role': 'user', 'content': 'What is its population?'}
]

response = router.chat(
    messages=messages,
    temperature=0.7,
    max_tokens=500
)

print(response.text)
```

### Explicit Provider/Model Selection

```python
# Use specific provider
response = router.generate(
    prompt="Hello world",
    provider_type="OpenAI"
)

# Use specific model
response = router.generate(
    prompt="Hello world",
    provider_type="OpenAI",
    model_id="gpt-4"
)
```

### Custom Agent Tracking

```python
# Track calls from a specific agent
response = router.chat(
    messages=[{'role': 'user', 'content': 'Analyze this code'}],
    agent="code_analyzer_v1",
    user=current_user
)
```

## Model Selection Logic

The router uses intelligent model selection:

1. **Explicit selection**: If `provider_type` + `model_id` are both provided, use that exact model
2. **Provider-based**: If only `provider_type` is provided, use the default model for that provider (or first active)
3. **Smart default**: If nothing specified:
   - Try OpenAI default model
   - Try Gemini default model
   - Use any active model (OpenAI first, then Gemini)

## Cost Calculation

Costs are calculated automatically when:
- Token counts are available from the provider
- Pricing is configured in the AIModel

Formula:
```
cost = (input_tokens / 1_000_000 * input_price_per_1m) + 
       (output_tokens / 1_000_000 * output_price_per_1m)
```

If any required data is missing, `costs` will be `None`.

## Logging & Audit Trail

Every API call creates an entry in `AIJobsHistory`:

1. **Job Creation**: Status set to "Pending" with timestamp
2. **Execution**: API call to provider
3. **Completion**: Status updated to "Completed" or "Error"
   - Token counts recorded
   - Duration calculated
   - Costs computed
   - Error message saved (if failed)

This provides a complete audit trail for:
- Cost tracking and budgeting
- Usage analytics
- Debugging and error analysis
- User activity monitoring

## Configuration

### Admin Setup

1. **Add Provider** (Django Admin → AI Providers):
   - Name: "OpenAI Production"
   - Provider Type: OpenAI
   - API Key: sk-...
   - Organization ID: (optional)
   - Active: ✓

2. **Add Model** (Django Admin → AI Models):
   - Provider: OpenAI Production
   - Name: GPT-4 Turbo
   - Model ID: gpt-4-turbo-preview
   - Input Price: 10.00 (per 1M tokens)
   - Output Price: 30.00 (per 1M tokens)
   - Active: ✓
   - Is Default: ✓

3. **Repeat** for Gemini or other providers

### Security

- API keys are encrypted in the database
- Keys are never exposed in logs or exceptions
- Access control via Django permissions

## Error Handling

```python
from core.services.ai import AIRouter
from core.services.exceptions import ServiceNotConfigured

router = AIRouter()

try:
    response = router.generate(prompt="Hello")
except ServiceNotConfigured as e:
    # No active models configured
    print(f"Service not configured: {e}")
except Exception as e:
    # API error, network issue, etc.
    print(f"AI request failed: {e}")
```

Common exceptions:
- `ServiceNotConfigured`: No active models or provider not found
- Provider-specific errors (network, quota, invalid request, etc.)

## Provider-Specific Notes

### OpenAI
- Supports all GPT models (gpt-3.5-turbo, gpt-4, etc.)
- Token counts always available
- Optional organization ID support

### Gemini
- Supports Gemini models (gemini-pro, gemini-pro-vision, etc.)
- Token counts may not always be available
- System messages converted to system_instruction
- Role mapping: assistant → model

## Future Enhancements

- Claude provider support
- Embeddings API
- Streaming responses
- Automatic retries with exponential backoff
- Rate limiting
- Token usage alerts
- Cost budgets per user/project
