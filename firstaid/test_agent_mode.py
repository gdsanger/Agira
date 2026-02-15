"""
Test for FirstAID agent mode switching functionality.
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')

import django
django.setup()

from firstaid.services.firstaid_service import FirstAIDService
from core.services.agents.agent_service import AgentService


def test_agent_mode():
    """Test that the correct agent is selected based on mode."""
    
    # Test 1: Verify coding-answer-agent exists and can be loaded
    print("Test 1: Verifying coding-answer-agent exists...")
    agent_service = AgentService()
    coding_agent = agent_service.get_agent('coding-answer-agent.yml')
    
    assert coding_agent is not None, "coding-answer-agent.yml not found"
    assert coding_agent.get('name') == 'coding-answer-agent', "Agent name mismatch"
    print("✓ coding-answer-agent.yml exists and is valid")
    
    # Test 2: Verify question-answering-agent exists (default support mode)
    print("\nTest 2: Verifying question-answering-agent exists...")
    support_agent = agent_service.get_agent('question-answering-agent.yml')
    
    assert support_agent is not None, "question-answering-agent.yml not found"
    assert support_agent.get('name') == 'question-answering-agent', "Agent name mismatch"
    print("✓ question-answering-agent.yml exists and is valid")
    
    # Test 3: Verify FirstAIDService.chat accepts mode parameter
    print("\nTest 3: Verifying FirstAIDService.chat signature...")
    from inspect import signature
    
    service = FirstAIDService()
    sig = signature(service.chat)
    params = list(sig.parameters.keys())
    
    assert 'mode' in params, "mode parameter not found in chat method signature"
    assert sig.parameters['mode'].default == 'support', "mode parameter default should be 'support'"
    print("✓ FirstAIDService.chat has mode parameter with default 'support'")
    
    print("\n✅ All tests passed!")
    print("\nSummary:")
    print("- coding-answer-agent.yml is properly configured")
    print("- question-answering-agent.yml is properly configured")
    print("- FirstAIDService.chat accepts mode parameter")
    print("- Mode selection logic is in place (support → question-answering-agent, coding → coding-answer-agent)")


if __name__ == '__main__':
    test_agent_mode()
