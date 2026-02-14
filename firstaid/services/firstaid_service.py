"""
First AID Service - Wraps ExtendedRAGPipelineService for context-based AI support.

This service provides:
- Project-wide RAG context retrieval
- Source aggregation (Items, GitHub Issues/PRs, Attachments)
- Agent-based transformations for documentation, KB articles, flashcards, etc.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import models
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
    
    def _build_external_title(self, mapping, project, prefix: str) -> str:
        """
        Build a title for an external GitHub issue or PR.
        
        Args:
            mapping: ExternalIssueMapping instance
            project: Project instance
            prefix: Prefix to use (e.g., 'GH Issue' or 'GH PR')
            
        Returns:
            Formatted title string
        """
        # Get number defensively
        number = getattr(mapping, 'number', None)
        title = mapping.item.title if mapping.item else ''
        
        # Build reference
        if number:
            # Try to build full repo reference if available
            github_owner = getattr(project, 'github_owner', '')
            github_repo = getattr(project, 'github_repo', '')
            
            if github_owner and github_repo:
                ref = f"{github_owner}/{github_repo}#{number}"
            else:
                ref = f"#{number}"
            
            return f"{prefix} {ref}: {title}"
        else:
            return f"{prefix}: {title}"
    
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
                title=f"#{item.id}: {item.title}",
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
                title=self._build_external_title(mapping, project, 'GH Issue'),
                description=mapping.item.description[:200] if mapping.item.description else '',
                project_name=project.name,
                url=getattr(mapping, 'html_url', ''),
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
                title=self._build_external_title(mapping, project, 'GH PR'),
                description=mapping.item.description[:200] if mapping.item.description else '',
                project_name=project.name,
                url=getattr(mapping, 'html_url', ''),
            )
            for mapping in github_prs[:50]  # Limit to 50 for MVP
        ]
        
        # Get Attachments
        # Get attachments linked to project or items
        from core.models import AttachmentLink
        from django.contrib.contenttypes.models import ContentType
        
        project_ct = ContentType.objects.get_for_model(Project)
        item_ct = ContentType.objects.get_for_model(Item)
        
        # Get all attachment links for project and items
        item_ids = list(items.values_list('id', flat=True))
        attachment_links = AttachmentLink.objects.filter(
            models.Q(target_content_type=project_ct, target_object_id=project.id) |
            models.Q(target_content_type=item_ct, target_object_id__in=item_ids)
        ).select_related('attachment')
        
        # Extract unique attachments
        seen_attachments = set()
        attachment_sources = []
        for link in attachment_links:
            if link.attachment.id not in seen_attachments and not link.attachment.is_deleted:
                seen_attachments.add(link.attachment.id)
                attachment_sources.append(
                    FirstAIDSource(
                        id=link.attachment.id,
                        type='attachment',
                        title=link.attachment.original_name,
                        description=f"{link.attachment.file_type} - {link.attachment.size_bytes // 1024}KB",
                        project_name=project.name,
                        url=f'/items/attachments/{link.attachment.id}/view/',
                    )
                )
                if len(attachment_sources) >= 50:  # Limit to 50 for MVP
                    break
        
        return {
            'items': item_sources,
            'github_issues': github_issue_sources,
            'github_prs': github_pr_sources,
            'attachments': attachment_sources,
        }
    
    def chat(self, project_id: int, question: str, user: User, chat_history: Optional[List[Dict]] = None, max_content_length: Optional[int] = None) -> Dict[str, Any]:
        """
        Process a chat question using the RAG pipeline.
        
        Args:
            project_id: Project ID for context scoping
            question: User's question
            user: Current user
            chat_history: Optional chat history (list of message dicts with 'role' and 'content')
            max_content_length: Optional max content length for RAG pipeline (thinking level)
            
        Returns:
            Dictionary with answer, sources, and metadata
        """
        try:
            # Process chat history if provided
            # Strategy: Last 5 pairs (10 messages) are sent fully, older messages are summarized
            chat_summary = ""
            chat_keywords = []
            recent_transcript = ""
            
            if chat_history and len(chat_history) > 0:
                # Separate recent (last 5 pairs = 10 messages) from older history
                if len(chat_history) <= 10:
                    # All history is recent - send fully, no summary needed
                    recent_messages = chat_history
                    older_messages = []
                else:
                    # Split: older messages for summary, recent for full transcript
                    recent_messages = chat_history[-10:]  # Last 5 pairs (10 messages)
                    older_messages = chat_history[:-10]   # Everything before that
                
                # Build recent transcript (last 5 pairs, always sent fully)
                if recent_messages:
                    recent_text = []
                    for msg in recent_messages:
                        role = msg.get('role', 'user')
                        content = msg.get('content', '')
                        recent_text.append(f"{role.upper()}: {content}")
                    recent_transcript = '\n'.join(recent_text)
                    logger.info(f"Recent transcript: {len(recent_messages)} messages")
                
                # Summarize only older messages (if any)
                if older_messages:
                    # Build older history text for summarization
                    older_text = []
                    for msg in older_messages:
                        role = msg.get('role', 'user')
                        content = msg.get('content', '')
                        older_text.append(f"{role.upper()}: {content}")
                    
                    older_str = '\n'.join(older_text)
                    
                    # Use chat-summary-agent to generate summary and keywords
                    try:
                        agent_response = self.agent_service.execute_agent(
                            filename='chat-summary-agent.yml',
                            input_text=older_str,
                            user=user,
                        )
                        
                        # Parse JSON response
                        summary_data = json.loads(agent_response)
                        chat_summary = summary_data.get('summary', '')
                        chat_keywords = summary_data.get('keywords', [])
                        
                        logger.info(f"Older chat summary generated: {len(chat_summary)} chars, {len(chat_keywords)} keywords")
                    except Exception as e:
                        logger.warning(f"Failed to generate chat summary: {e}", exc_info=True)
            
            # Build enhanced query with chat context for RAG retrieval
            # Note: The RECENT_CHAT_TRANSCRIPT, CHAT_SUMMARY and KEYWORDS markers are used by the RAG pipeline
            # to understand the conversation context. The question-optimization-agent
            # processes these markers to improve semantic search.
            enhanced_query = question
            context_parts = []
            if recent_transcript:
                context_parts.append(f"RECENT_CHAT_TRANSCRIPT:\n{recent_transcript}")
            if chat_summary:
                context_parts.append(f"OLDER_CHAT_SUMMARY:\n{chat_summary}")
            if chat_keywords:
                context_parts.append(f"KEYWORDS:\n{', '.join(chat_keywords)}")
            
            if context_parts:
                enhanced_query = f"{question}\n\n" + "\n\n".join(context_parts)
            
            # Build extended RAG context for the project.
            # MAX_CONTENT_LENGTH from RAG config remains in effect unless a custom
            # max_content_length is explicitly provided by caller.
            context = build_extended_context(
                query=enhanced_query,
                project_id=project_id,
                max_content_length=max_content_length,
            )
            
            # Use question-answering-agent as default
            agent_filename = 'question-answering-agent.yml'
            
            # Build input text with question and context for the answering agent
            input_parts = [f"Frage: {question}"]
            
            # Add chat context if available
            # Note: We provide the recent transcript and older summary to the answering agent.
            # Recent messages (last 5 pairs) are sent in full for better context.
            if recent_transcript:
                input_parts.append(f"\nLetzte Konversation (5 Nachrichten-Paare):\n{recent_transcript}")
            if chat_summary:
                input_parts.append(f"\nÄltere Chat-Zusammenfassung: {chat_summary}")
            if chat_keywords:
                input_parts.append(f"\nRelevante Keywords: {', '.join(chat_keywords)}")
            
            if context:
                if hasattr(context, 'summary') and context.summary:
                    input_parts.append(f"\nKontext-Zusammenfassung: {context.summary}")

                # Include full LLM context text (all selected A/B/C snippets with content),
                # not only titles.
                if hasattr(context, 'to_context_text'):
                    input_parts.append("\nVollständiger Kontext aus der Wissensdatenbank:")
                    input_parts.append(context.to_context_text())
            
            input_text = '\n'.join(input_parts)
            
            # Execute the agent to generate answer
            answer = self.agent_service.execute_agent(
                filename=agent_filename,
                input_text=input_text,
                user=user,
            )
            
            return {
                'answer': answer if isinstance(answer, str) else str(answer),
                'sources': [item.to_dict() for item in context.all_items] if context and hasattr(context, 'all_items') else [],
                'summary': context.summary if context and hasattr(context, 'summary') else '',
                'stats': context.stats if context and hasattr(context, 'stats') else {},
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
        Fallback answer generation when agent execution fails.
        This should only be used in error cases, not normal operation.
        
        Args:
            question: User's question
            context: RAG context
            
        Returns:
            Generated answer
        """
        # Return context summary if available
        if context and hasattr(context, 'summary') and context.summary:
            return f"Based on the available context: {context.summary}"
        return "I don't have enough information to answer this question based on the current project context."
    
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
        return f"# Knowledge Base Article\n\n## Context\n\n{context[:500]}..."
    
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
        return f"# Documentation\n\n## Overview\n\n{context[:500]}..."
    
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
        return [
            {'question': 'Sample Question', 'answer': f'Context preview: {context[:100]}...'},
        ]
