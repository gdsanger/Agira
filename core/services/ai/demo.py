"""
AI Core Service Example Usage

This script demonstrates how to use the AI Core Service in Agira.
Run this after setting up providers and models in Django admin.
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
django.setup()

from core.services.ai import AIRouter
from core.models import User


def example_generate():
    """Example: Simple text generation"""
    print("=" * 60)
    print("Example 1: Simple Text Generation")
    print("=" * 60)
    
    router = AIRouter()
    
    try:
        response = router.generate(
            prompt="Explain what Django is in one sentence.",
            agent="demo_script"
        )
        
        print(f"Response: {response.text}")
        print(f"Provider: {response.provider}")
        print(f"Model: {response.model}")
        print(f"Input tokens: {response.input_tokens}")
        print(f"Output tokens: {response.output_tokens}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def example_chat():
    """Example: Multi-turn conversation"""
    print("=" * 60)
    print("Example 2: Chat Conversation")
    print("=" * 60)
    
    router = AIRouter()
    
    messages = [
        {'role': 'system', 'content': 'You are a helpful Python expert.'},
        {'role': 'user', 'content': 'What is a Django model?'},
        {'role': 'assistant', 'content': 'A Django model is a Python class that defines the structure of a database table.'},
        {'role': 'user', 'content': 'Give me a simple example.'}
    ]
    
    try:
        response = router.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=200,
            agent="demo_chat"
        )
        
        print(f"Response: {response.text}")
        print(f"Provider: {response.provider}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def example_explicit_provider():
    """Example: Use specific provider"""
    print("=" * 60)
    print("Example 3: Explicit Provider Selection")
    print("=" * 60)
    
    router = AIRouter()
    
    try:
        # Use Gemini explicitly
        response = router.generate(
            prompt="Say hello in 3 different languages.",
            provider_type="Gemini",
            agent="demo_gemini"
        )
        
        print(f"Response: {response.text}")
        print(f"Provider: {response.provider}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def example_with_user():
    """Example: Track usage per user"""
    print("=" * 60)
    print("Example 4: User Tracking")
    print("=" * 60)
    
    router = AIRouter()
    
    # Get first user (or create one for demo)
    user = User.objects.first()
    
    if not user:
        print("No users found. Create a user first.")
        return
    
    try:
        response = router.generate(
            prompt="Write a haiku about coding.",
            user=user,
            client_ip="127.0.0.1",
            agent="demo_user_tracking"
        )
        
        print(f"Response: {response.text}")
        print(f"User: {user.username}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def show_recent_jobs():
    """Show recent AI jobs from history"""
    print("=" * 60)
    print("Recent AI Jobs History")
    print("=" * 60)
    
    from core.models import AIJobsHistory
    
    jobs = AIJobsHistory.objects.select_related('provider', 'model', 'user').order_by('-timestamp')[:5]
    
    for job in jobs:
        print(f"[{job.timestamp}] {job.agent}")
        print(f"  Provider: {job.provider.name if job.provider else 'N/A'}")
        print(f"  Model: {job.model.name if job.model else 'N/A'}")
        print(f"  Status: {job.status}")
        print(f"  Tokens: {job.input_tokens}/{job.output_tokens}")
        print(f"  Cost: ${job.costs if job.costs else 'N/A'}")
        print(f"  Duration: {job.duration_ms}ms")
        print()


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("AI Core Service - Example Usage")
    print("=" * 60 + "\n")
    
    # Check if providers are configured
    from core.models import AIProvider, AIModel
    
    providers = AIProvider.objects.filter(active=True).count()
    models = AIModel.objects.filter(active=True).count()
    
    print(f"Active Providers: {providers}")
    print(f"Active Models: {models}")
    print()
    
    if providers == 0 or models == 0:
        print("⚠️  No active providers or models configured!")
        print("Please configure AI providers and models in Django admin first.")
        print()
    else:
        # Run examples
        example_generate()
        example_chat()
        example_explicit_provider()
        example_with_user()
        show_recent_jobs()
    
    print("=" * 60)
    print("Demo complete!")
    print("=" * 60)
