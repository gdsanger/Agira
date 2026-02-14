"""
First AID Service - Wraps ExtendedRAGPipelineService for context-based AI support.

This service provides:
- Project-wide RAG context retrieval
- Source aggregation (Items, GitHub Issues/PRs, Attachments)
- Agent-based transformations for documentation, KB articles, flashcards, etc.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from core.services.rag.extended_service import build_extended_context
from core.services.agents.agent_service import AgentService
from core.models import Item, Attachment, ExternalIssueMapping, Project

User = get_user_model()
logger = logging.getLogger(__name__)


@dataclass
class FirstAIDSource:
    """Represents a source document for First AID."""
    id: int
    type: str  # 'item', 'github_issue', 'github_pr', 'attachment'
    title: str
    description: str
    project_name: Optional[str] = None
    url: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'description': self.description,
            'project_name': self.project_name,
            'url': self.url,
        }


class FirstAIDService:
    """Service for First AID (First AI Documentation) feature."""
    
    def __init__(self):
        """Initialize the First AID service."""
        self.agent_service = AgentService()
    
    def get_project_sources(self, project_id: int, user: User) -> Dict[str, List[FirstAIDSource]]:
        """
        Retrieve all sources for a project.
        
        Args:
            project_id: Project ID
            user: Current user for permission checking
            
        Returns:
            Dictionary with categorized sources (items, github_issues, github_prs, attachments)
        """
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            logger.warning(f"Project {project_id} not found")
            return {
                'items': [],
                'github_issues': [],
                'github_prs': [],
                'attachments': [],
            }
        
        # Get Items
        items = Item.objects.filter(project=project).select_related('type', 'project')
        item_sources = [
            FirstAIDSource(
                id=item.id,
                type='item',
                title=f"{item.project.short}-{item.item_id}: {item.title}",
                description=item.description[:200] if item.description else '',
                project_name=item.project.name,
                url=f'/items/{item.id}/',
            )
            for item in items[:50]  # Limit to 50 for MVP
        ]
        
        # Get GitHub Issues
        github_issues = ExternalIssueMapping.objects.filter(
            item__project=project,
            kind='Issue'
        ).select_related('item', 'item__project')
        github_issue_sources = [
            FirstAIDSource(
                id=mapping.id,
                type='github_issue',
                title=f"GH Issue #{mapping.external_number}: {mapping.external_title or mapping.item.title}",
                description=mapping.item.description[:200] if mapping.item.description else '',
                project_name=project.name,
                url=mapping.external_url,
            )
            for mapping in github_issues[:50]  # Limit to 50 for MVP
        ]
        
        # Get GitHub PRs
        github_prs = ExternalIssueMapping.objects.filter(
            item__project=project,
            kind='PR'
        ).select_related('item', 'item__project')
        github_pr_sources = [
            FirstAIDSource(
                id=mapping.id,
                type='github_pr',
                title=f"GH PR #{mapping.external_number}: {mapping.external_title or mapping.item.title}",
                description=mapping.item.description[:200] if mapping.item.description else '',
                project_name=project.name,
                url=mapping.external_url,
            )
            for mapping in github_prs[:50]  # Limit to 50 for MVP
        ]
        
        # Get Attachments
        # Get attachments from both project and items
        from django.contrib.contenttypes.models import ContentType
        project_ct = ContentType.objects.get_for_model(Project)
        item_ct = ContentType.objects.get_for_model(Item)
        
        attachments = Attachment.objects.filter(
            content_type__in=[project_ct, item_ct],
            object_id__in=[project.id] + list(items.values_list('id', flat=True))
        ).filter(is_deleted=False)
        
        attachment_sources = [
            FirstAIDSource(
                id=att.id,
                type='attachment',
                title=att.original_name,
                description=f"{att.file_type} - {att.size_bytes // 1024}KB",
                project_name=project.name,
                url=f'/items/attachments/{att.id}/view/',
            )
            for att in attachments[:50]  # Limit to 50 for MVP
        ]
        
        return {
            'items': item_sources,
            'github_issues': github_issue_sources,
            'github_prs': github_pr_sources,
            'attachments': attachment_sources,
        }
    
    def chat(self, project_id: int, question: str, user: User) -> Dict[str, Any]:
        """
        Process a chat question using the RAG pipeline.
        
        Args:
            project_id: Project ID for context scoping
            question: User's question
            user: Current user
            
        Returns:
            Dictionary with answer, sources, and metadata
        """
        try:
            # Build extended RAG context for the project
            context = build_extended_context(
                query=question,
                project_id=project_id,
                max_results=10,
                enable_optimization=True,
            )
            
            # Generate answer using agent service
            agent = self.agent_service.get_agent('rag-answer-agent.yml')
            if not agent:
                # Fallback: use a simple prompt
                answer = self._generate_answer_fallback(question, context)
            else:
                # Use the agent to generate answer
                answer = self.agent_service.execute_agent(
                    agent_filename='rag-answer-agent.yml',
                    variables={
                        'question': question,
                        'context': context.summary if context else '',
                        'layer_a': '\n'.join([f"- {item['title']}" for item in context.layer_a]) if context else '',
                        'layer_b': '\n'.join([f"- {item['title']}" for item in context.layer_b]) if context else '',
                        'layer_c': '\n'.join([f"- {item['title']}" for item in context.layer_c]) if context else '',
                    },
                    user=user,
                )
            
            return {
                'answer': answer if isinstance(answer, str) else answer.get('response', ''),
                'sources': context.all_items if context else [],
                'summary': context.summary if context else '',
                'stats': context.stats if context else {},
            }
        except Exception as e:
            logger.error(f"Error in FirstAID chat: {e}", exc_info=True)
            return {
                'answer': f"Sorry, I encountered an error: {str(e)}",
                'sources': [],
                'summary': '',
                'stats': {},
            }
    
    def _generate_answer_fallback(self, question: str, context: Any) -> str:
        """
        Fallback answer generation when agent is not available.
        
        Args:
            question: User's question
            context: RAG context
            
        Returns:
            Generated answer
        """
        from core.services.ai.router import AIRouter
        
        router = AIRouter()
        
        # Build prompt
        prompt = f"""Based on the following context, answer the question.

Question: {question}

Context:
{context.summary if context else 'No context available.'}

Answer the question concisely and accurately based on the context provided."""
        
        try:
            response = router.generate_text(
                provider='openai',
                model='gpt-4',
                prompt=prompt,
                temperature=0.7,
            )
            return response
        except Exception as e:
            logger.error(f"Error in fallback answer generation: {e}", exc_info=True)
            return "I'm sorry, I couldn't generate an answer at this time."
    
    def generate_kb_article(self, project_id: int, context: str, user: User) -> str:
        """
        Generate a Knowledge Base article from context.
        
        Args:
            project_id: Project ID
            context: Chat context or selected sources
            user: Current user
            
        Returns:
            Markdown-formatted KB article
        """
        try:
            agent = self.agent_service.get_agent('kb-article-generator.yml')
            if not agent:
                return self._generate_kb_article_fallback(context)
            
            result = self.agent_service.execute_agent(
                agent_filename='kb-article-generator.yml',
                variables={'context': context},
                user=user,
            )
            return result if isinstance(result, str) else result.get('response', '')
        except Exception as e:
            logger.error(f"Error generating KB article: {e}", exc_info=True)
            return f"Error generating KB article: {str(e)}"
    
    def _generate_kb_article_fallback(self, context: str) -> str:
        """Fallback KB article generation."""
        from core.services.ai.router import AIRouter
        
        router = AIRouter()
        prompt = f"""Generate a comprehensive Knowledge Base article based on the following context.

Context:
{context}

Please create a well-structured KB article in Markdown format with:
- Clear title
- Summary/Overview section
- Detailed sections with subsections as needed
- Code examples if applicable
- References

Output only the Markdown content."""
        
        try:
            return router.generate_text(
                provider='openai',
                model='gpt-4',
                prompt=prompt,
                temperature=0.7,
            )
        except Exception as e:
            logger.error(f"Error in fallback KB article generation: {e}", exc_info=True)
            return f"# Error\n\nCould not generate KB article: {str(e)}"
    
    def generate_documentation(self, project_id: int, context: str, user: User) -> str:
        """
        Generate documentation from context.
        
        Args:
            project_id: Project ID
            context: Chat context or selected sources
            user: Current user
            
        Returns:
            Markdown-formatted documentation
        """
        try:
            agent = self.agent_service.get_agent('documentation-generator.yml')
            if not agent:
                return self._generate_documentation_fallback(context)
            
            result = self.agent_service.execute_agent(
                agent_filename='documentation-generator.yml',
                variables={'context': context},
                user=user,
            )
            return result if isinstance(result, str) else result.get('response', '')
        except Exception as e:
            logger.error(f"Error generating documentation: {e}", exc_info=True)
            return f"Error generating documentation: {str(e)}"
    
    def _generate_documentation_fallback(self, context: str) -> str:
        """Fallback documentation generation."""
        from core.services.ai.router import AIRouter
        
        router = AIRouter()
        prompt = f"""Generate technical documentation based on the following context.

Context:
{context}

Please create well-structured technical documentation in Markdown format with:
- Clear title and description
- Table of Contents
- Getting Started section
- Detailed usage instructions
- API reference if applicable
- Examples
- Troubleshooting section

Output only the Markdown content."""
        
        try:
            return router.generate_text(
                provider='openai',
                model='gpt-4',
                prompt=prompt,
                temperature=0.5,
            )
        except Exception as e:
            logger.error(f"Error in fallback documentation generation: {e}", exc_info=True)
            return f"# Error\n\nCould not generate documentation: {str(e)}"
    
    def generate_flashcards(self, project_id: int, context: str, user: User) -> List[Dict[str, str]]:
        """
        Generate flashcards from context.
        
        Args:
            project_id: Project ID
            context: Chat context or selected sources
            user: Current user
            
        Returns:
            List of flashcards (each with 'question' and 'answer')
        """
        try:
            agent = self.agent_service.get_agent('flashcard-generator.yml')
            if not agent:
                return self._generate_flashcards_fallback(context)
            
            result = self.agent_service.execute_agent(
                agent_filename='flashcard-generator.yml',
                variables={'context': context},
                user=user,
            )
            
            # Parse result if it's a string
            if isinstance(result, str):
                import json
                try:
                    flashcards = json.loads(result)
                    return flashcards if isinstance(flashcards, list) else []
                except json.JSONDecodeError:
                    return [{'question': 'Error', 'answer': 'Could not parse flashcards'}]
            elif isinstance(result, dict):
                return result.get('flashcards', [])
            else:
                return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Error generating flashcards: {e}", exc_info=True)
            return [{'question': 'Error', 'answer': f'Could not generate flashcards: {str(e)}'}]
    
    def _generate_flashcards_fallback(self, context: str) -> List[Dict[str, str]]:
        """Fallback flashcard generation."""
        from core.services.ai.router import AIRouter
        import json
        
        router = AIRouter()
        prompt = f"""Generate flashcards based on the following context.

Context:
{context}

Please create 5-10 flashcards that cover the key concepts.
Output as a JSON array of objects, each with 'question' and 'answer' fields.
Example:
[
  {{"question": "What is X?", "answer": "X is..."}},
  {{"question": "How does Y work?", "answer": "Y works by..."}}
]

Output only the JSON array."""
        
        try:
            response = router.generate_text(
                provider='openai',
                model='gpt-4',
                prompt=prompt,
                temperature=0.7,
            )
            flashcards = json.loads(response)
            return flashcards if isinstance(flashcards, list) else []
        except Exception as e:
            logger.error(f"Error in fallback flashcard generation: {e}", exc_info=True)
            return [{'question': 'Error', 'answer': f'Could not generate flashcards: {str(e)}'}]
