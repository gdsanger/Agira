# AI Core Service

Unified AI service layer for Agira supporting multiple providers (OpenAI, Gemini).

## Quick Start

```python
from core.services.ai import AIRouter

router = AIRouter()

# Simple generation
response = router.generate(prompt="Explain Django models")
print(response.text)

# Chat conversation
messages = [
    {'role': 'user', 'content': 'What is Python?'}
]
response = router.chat(messages=messages)
print(response.text)
```

## Features

- ✅ Multi-provider support (OpenAI + Gemini)
- ✅ Unified API (chat + generate)
- ✅ Automatic job logging
- ✅ Cost tracking
- ✅ Smart model selection
- ✅ Encrypted API keys
- ✅ Error handling

## Files

- `router.py` - Main AIRouter class
- `base_provider.py` - Provider interface
- `openai_provider.py` - OpenAI implementation
- `gemini_provider.py` - Gemini implementation  
- `pricing.py` - Cost calculation
- `schemas.py` - Data classes
- `test_ai.py` - Tests
- `demo.py` - Example usage

## Configuration

1. Add providers in Django Admin → AI Providers
2. Add models in Django Admin → AI Models
3. Use the router in your code

## Documentation

See `/docs/services/ai.md` for complete documentation.
