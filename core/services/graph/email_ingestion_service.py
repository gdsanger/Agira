"""
Email ingestion service for Agira.

This service fetches emails from Microsoft Graph API, processes them,
and creates items in Agira projects with AI-powered classification.
"""

import logging
import json
import re
import secrets
import string
from typing import Optional, Dict, Any, List, Tuple
from django.db import transaction
from django.utils import timezone

from core.models import (
    Item,
    ItemType,
    Project,
    User,
    Organisation,
    UserOrganisation,
    UserRole,
    ItemStatus,
    ItemComment,
    CommentKind,
    CommentVisibility,
)
from core.services.config import get_graph_config
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled, ServiceError
from core.services.graph.client import get_client
from core.services.agents.agent_service import AgentService

logger = logging.getLogger(__name__)


def extract_issue_id_from_subject(subject: str) -> Optional[int]:
    """
    Extract issue ID from email subject.
    
    Looks for pattern [AGIRA-{id}] in the subject line.
    
    Args:
        subject: Email subject line
        
    Returns:
        Issue ID as integer if found, None otherwise
        
    Example:
        >>> extract_issue_id_from_subject("[AGIRA-123] Test Subject")
        123
        >>> extract_issue_id_from_subject("Re: [AGIRA-456] Another Subject")
        456
        >>> extract_issue_id_from_subject("Regular Subject")
        None
    """
    if not subject:
        return None
    
    # Pattern matches [AGIRA-{digits}] anywhere in the subject
    # This handles replies like "Re: [AGIRA-123] Original Subject"
    pattern = r'\[AGIRA-(\d+)\]'
    match = re.search(pattern, subject)
    
    if match:
        try:
            return int(match.group(1))
        except (ValueError, IndexError):
            return None
    
    return None


class EmailIngestionService:
    """Service for ingesting emails and creating items."""
    
    # Category to mark processed emails
    PROCESSED_CATEGORY = "Agira-Processed"
    
    # Fallback project name
    FALLBACK_PROJECT_NAME = "Incoming"
    
    def __init__(self):
        """Initialize the email ingestion service."""
        self.config = get_graph_config()
        if self.config is None or not self.config.enabled:
            raise ServiceDisabled("Graph API service is not enabled")
        
        if not self.config.default_mail_sender:
            raise ServiceNotConfigured(
                "Graph API is enabled but default_mail_sender is not configured"
            )
        
        self.client = get_client()
        self.agent_service = AgentService()
        self.mailbox = self.config.default_mail_sender
    
    def process_inbox(self, max_messages: int = 50, dry_run: bool = False) -> Dict[str, Any]:
        """
        Process emails from the inbox.
        
        Args:
            max_messages: Maximum number of messages to process
            dry_run: If True, don't actually create items or mark emails
            
        Returns:
            Dictionary with processing statistics
        """
        stats = {
            "fetched": 0,
            "processed": 0,
            "errors": 0,
            "skipped": 0,
        }
        
        try:
            # Fetch unprocessed messages from inbox
            # Filter out messages that already have the processed category
            filter_query = f"not(categories/any(c:c eq '{self.PROCESSED_CATEGORY}'))"
            
            messages = self.client.get_inbox_messages(
                user_upn=self.mailbox,
                top=max_messages,
                filter_query=filter_query,
            )
            
            stats["fetched"] = len(messages)
            logger.info(f"Fetched {len(messages)} unprocessed messages")
            
            for message in messages:
                try:
                    if dry_run:
                        logger.info(f"[DRY RUN] Would process: {message.get('subject', 'No subject')}")
                        stats["processed"] += 1
                    else:
                        self._process_message(message)
                        stats["processed"] += 1
                        
                except Exception as e:
                    logger.error(f"Error processing message {message.get('id')}: {e}")
                    stats["errors"] += 1
            
            logger.info(f"Processing complete. Stats: {stats}")
            
        except Exception as e:
            logger.error(f"Error in process_inbox: {e}")
            stats["errors"] += 1
        
        return stats
    
    def _process_message(self, message: Dict[str, Any]) -> Optional[Item]:
        """
        Process a single email message.
        
        If the subject contains an issue ID (format: [AGIRA-{id}]), the email is
        added as a comment to the existing item. Otherwise, a new item is created.
        
        Args:
            message: Message dictionary from Graph API
            
        Returns:
            Item instance (existing or newly created) or None
        """
        message_id = message.get("id")
        subject = message.get("subject", "No Subject")
        
        logger.info(f"Processing message: {subject}")
        
        # Extract sender information
        from_data = message.get("from", {})
        from_email_data = from_data.get("emailAddress", {})
        sender_email = from_email_data.get("address", "").lower()
        sender_name = from_email_data.get("name", "")
        
        if not sender_email:
            logger.warning(f"Message {message_id} has no sender email, skipping")
            return None
        
        # Extract email body
        body_data = message.get("body", {})
        body_content = body_data.get("content", "")
        body_type = body_data.get("contentType", "text")  # "text" or "html"
        
        # Store original body for user_input field (prioritize HTML over text)
        original_body = body_content
        
        # Convert HTML to Markdown if needed
        if body_type.lower() == "html":
            body_markdown = self._convert_html_to_markdown(body_content)
        else:
            body_markdown = body_content
        
        # Check if this is a reply to an existing issue
        issue_id = extract_issue_id_from_subject(subject)
        
        if issue_id is not None:
            # Try to find the existing item
            try:
                item = Item.objects.get(id=issue_id)
                logger.info(f"Found existing item {issue_id} for reply")
                
                # Add email as comment to existing item
                return self._add_email_as_comment(
                    item=item,
                    sender_email=sender_email,
                    sender_name=sender_name,
                    subject=subject,
                    body=body_markdown,
                    message=message,
                )
                
            except Item.DoesNotExist:
                logger.warning(
                    f"Issue ID {issue_id} found in subject but item does not exist. "
                    f"Creating new item instead."
                )
                # Fall through to create new item
        
        # No valid issue ID found or item doesn't exist - create new item
        try:
            # Create item in database transaction
            with transaction.atomic():
                # Get or create user and organization
                user, organisation = self._get_or_create_user_and_org(
                    email=sender_email,
                    name=sender_name,
                )
                
                # Classify email to project and type
                project, item_type = self._classify_email(
                    sender_email=sender_email,
                    subject=subject,
                    body=body_markdown,
                )
                
                # Create item
                item = Item.objects.create(
                    project=project,
                    title=subject,
                    description=body_markdown,
                    user_input=original_body,
                    type=item_type,
                    requester=user,
                    organisation=organisation,
                    status=ItemStatus.INBOX,
                )
                
                logger.info(
                    f"Created item {item.id} in project '{project.name}' "
                    f"from email by {sender_email}"
                )
            
            # After transaction commits successfully, send confirmation email
            # This is done outside the transaction to avoid holding locks
            try:
                self._send_confirmation_email(item)
            except Exception as e:
                logger.error(f"Failed to send confirmation email for item {item.id}: {e}")
                # Don't raise - email sending failure shouldn't prevent marking as processed
            
            # Mark message as processed
            # Done after transaction to avoid duplicate processing if DB transaction fails
            try:
                self.client.add_category_to_message(
                    user_upn=self.mailbox,
                    message_id=message_id,
                    category=self.PROCESSED_CATEGORY,
                )
                
                # Optionally mark as read
                if not message.get("isRead", False):
                    self.client.mark_message_as_read(
                        user_upn=self.mailbox,
                        message_id=message_id,
                    )
            except Exception as e:
                logger.error(f"Failed to mark message {message_id} as processed: {e}")
                # Don't raise - item was created successfully
            
            return item
                
        except Exception as e:
            logger.error(f"Error creating item from message {message_id}: {e}")
            raise
    
    def _convert_html_to_markdown(self, html_content: str) -> str:
        """
        Convert HTML email body to Markdown using AI agent.
        
        Args:
            html_content: HTML content string
            
        Returns:
            Markdown formatted string
        """
        try:
            markdown = self.agent_service.execute_agent(
                filename="html-to-markdown-converter.yml",
                input_text=html_content,
            )
            return markdown.strip()
        except Exception as e:
            logger.warning(f"Failed to convert HTML to Markdown: {e}, using original content")
            # Fallback: return HTML as-is
            return html_content
    
    def _get_or_create_user_and_org(
        self,
        email: str,
        name: str,
    ) -> Tuple[User, Optional[Organisation]]:
        """
        Get or create user and assign to organization based on email domain.
        
        Args:
            email: User email address
            name: User display name
            
        Returns:
            Tuple of (User, Organisation or None)
        """
        # Check if user already exists
        try:
            user = User.objects.get(email=email)
            logger.debug(f"User {email} already exists")
            
            # Get primary organization
            primary_org = UserOrganisation.objects.filter(
                user=user,
                is_primary=True,
            ).first()
            
            return user, primary_org.organisation if primary_org else None
            
        except User.DoesNotExist:
            pass
        
        # Extract domain from email
        domain = email.split('@')[1] if '@' in email else None
        
        # Find organization by domain
        organisation = None
        if domain:
            organisation = self._find_organisation_by_domain(domain)
        
        # Generate username from email (sanitize for Django username requirements)
        # Django usernames allow letters, digits, and @/./+/-/_ characters
        import re
        username_base = email.split('@')[0] if '@' in email else email
        # Replace invalid characters with underscores
        username = re.sub(r'[^\w.@+-]', '_', username_base)
        
        # Ensure username is not empty
        if not username:
            username = "user_" + email.replace("@", "_at_").replace(".", "_")
        
        # Ensure username is unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Generate random password
        password = self._generate_random_password()
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            name=name or email,
            role=UserRole.USER,
            active=True,
        )
        
        logger.info(f"Created new user: {username} ({email})")
        
        # Assign to organization if found
        if organisation:
            UserOrganisation.objects.create(
                user=user,
                organisation=organisation,
                role=UserRole.USER,
                is_primary=True,
            )
            logger.info(f"Assigned user {username} to organization {organisation.name}")
        
        return user, organisation
    
    def _find_organisation_by_domain(self, domain: str) -> Optional[Organisation]:
        """
        Find organization by matching email domain.
        
        Args:
            domain: Email domain (e.g., "example.com")
            
        Returns:
            Organisation instance or None
        """
        # Check all organizations for matching domain
        for org in Organisation.objects.all():
            domains = org.get_mail_domains_list()
            if domain.lower() in [d.lower() for d in domains]:
                logger.debug(f"Found organization {org.name} for domain {domain}")
                return org
        
        logger.debug(f"No organization found for domain {domain}")
        return None
    
    def _classify_email(
        self,
        sender_email: str,
        subject: str,
        body: str,
    ) -> Tuple[Project, ItemType]:
        """
        Classify email to determine project and item type using AI.
        
        Args:
            sender_email: Sender email address
            subject: Email subject
            body: Email body content
            
        Returns:
            Tuple of (Project, ItemType)
        """
        # Get all project names
        projects = list(Project.objects.all())
        project_names = [p.name for p in projects]
        
        # Limit body to first 1000 chars to avoid overwhelming the AI
        body_preview = body[:1000]
        
        # Build context for AI agent
        context = f"""
Available Projects:
{', '.join(project_names)}

Email Information:
Sender: {sender_email}
Subject: {subject}

Email Body:
{body_preview}
"""
        
        try:
            # Call AI classification agent
            response = self.agent_service.execute_agent(
                filename="mail-issue-classification-agent.yml",
                input_text=context,
            )
            
            # Parse JSON response
            classification = json.loads(response.strip())
            
            project_name = classification.get("project")
            type_key = classification.get("type", "task")
            
            logger.info(f"AI classification: project={project_name}, type={type_key}")
            
        except Exception as e:
            logger.warning(f"AI classification failed: {e}, using fallback")
            project_name = None
            type_key = "task"
        
        # Find project
        project = self._get_project(project_name)
        
        # Find or create item type
        item_type = self._get_item_type(type_key)
        
        return project, item_type
    
    def _get_project(self, project_name: Optional[str]) -> Project:
        """
        Get project by name or return fallback project.
        
        Args:
            project_name: Project name from AI classification
            
        Returns:
            Project instance
        """
        if project_name:
            try:
                project = Project.objects.get(name=project_name)
                logger.debug(f"Using project: {project.name}")
                return project
            except Project.DoesNotExist:
                logger.warning(f"Project '{project_name}' not found, using fallback")
        
        # Try to get or create fallback project
        project, created = Project.objects.get_or_create(
            name=self.FALLBACK_PROJECT_NAME,
            defaults={
                "description": "Inbox for unclassified items",
            },
        )
        
        if created:
            logger.info(f"Created fallback project: {self.FALLBACK_PROJECT_NAME}")
        
        return project
    
    def _get_item_type(self, type_key: str) -> ItemType:
        """
        Get ItemType by key or return default task type.
        
        Args:
            type_key: Type key (bug, feature, idea, task)
            
        Returns:
            ItemType instance
        """
        # Normalize type key
        valid_types = ["bug", "feature", "idea", "task"]
        if type_key.lower() not in valid_types:
            type_key = "task"
        
        # Try to get existing type
        try:
            item_type = ItemType.objects.get(key=type_key.lower())
            return item_type
        except ItemType.DoesNotExist:
            pass
        
        # Create if not exists
        item_type, created = ItemType.objects.get_or_create(
            key=type_key.lower(),
            defaults={
                "name": type_key.capitalize(),
                "is_active": True,
            },
        )
        
        if created:
            logger.info(f"Created item type: {type_key}")
        
        return item_type
    
    def _generate_random_password(self, length: int = 32) -> str:
        """
        Generate a random password.
        
        Args:
            length: Password length
            
        Returns:
            Random password string
        """
        alphabet = string.ascii_letters + string.digits + string.punctuation
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    def _send_confirmation_email(self, item: Item) -> None:
        """
        Send auto-confirmation email after item creation.
        
        Args:
            item: Newly created Item instance
        """
        from core.services.mail.mail_trigger_service import (
            check_mail_trigger,
            prepare_mail_preview,
            get_notification_recipients_for_item,
        )
        from core.services.graph.mail_service import send_email
        
        # Check if there's a mail trigger for this item's status and type
        mapping = check_mail_trigger(item)
        
        if not mapping:
            logger.debug(f"No mail trigger found for item {item.id} (status={item.status}, type={item.type.key})")
            return
        
        # Get notification recipients
        recipients = get_notification_recipients_for_item(item)
        
        if not recipients['to']:
            logger.warning(f"No recipient email for item {item.id}, skipping confirmation email")
            return
        
        try:
            # Prepare mail preview
            preview = prepare_mail_preview(item, mapping)
            
            # Send email
            result = send_email(
                subject=preview['subject'],
                body=preview['message'],
                to=[recipients['to']],
                body_is_html=True,
                cc=recipients['cc'] if recipients['cc'] else None,
                sender=preview.get('from_address'),
                item=item,
                author=None,  # System-generated email
                visibility="Internal",
            )
            
            if result.success:
                logger.info(f"Sent confirmation email for item {item.id} to {recipients['to']}")
            else:
                logger.error(f"Failed to send confirmation email for item {item.id}: {result.error}")
                
        except Exception as e:
            logger.error(f"Error sending confirmation email for item {item.id}: {e}")
            # Don't raise - email sending failure shouldn't prevent item creation
    
    def _add_email_as_comment(
        self,
        item: Item,
        sender_email: str,
        sender_name: str,
        subject: str,
        body: str,
        message: Dict[str, Any],
    ) -> Item:
        """
        Add an email as a comment to an existing item.
        
        This is called when an email is a reply to a previously sent email
        (identified by issue ID in the subject).
        
        Args:
            item: Existing Item instance to add comment to
            sender_email: Email address of the sender
            sender_name: Display name of the sender
            subject: Email subject line
            body: Email body content (already converted to markdown)
            message: Graph API message dictionary
            
        Returns:
            The Item instance (unchanged)
        """
        message_id = message.get("id")
        
        try:
            with transaction.atomic():
                # Get or create user
                user, _ = self._get_or_create_user_and_org(
                    email=sender_email,
                    name=sender_name,
                )
                
                # Create comment with email content
                comment = ItemComment.objects.create(
                    item=item,
                    author=user,
                    visibility=CommentVisibility.PUBLIC,  # Email replies are public
                    kind=CommentKind.EMAIL_IN,
                    subject=subject,
                    body=body,
                    external_from=sender_email,
                    message_id=message_id,
                )
                
                logger.info(
                    f"Added email reply from {sender_email} as comment {comment.id} "
                    f"to item {item.id}"
                )
            
            # Mark message as processed (outside transaction)
            try:
                self.client.add_category_to_message(
                    user_upn=self.mailbox,
                    message_id=message_id,
                    category=self.PROCESSED_CATEGORY,
                )
                
                # Optionally mark as read (same logic as _process_message)
                if not message.get("isRead", False):
                    self.client.mark_message_as_read(
                        user_upn=self.mailbox,
                        message_id=message_id,
                    )
            except Exception as e:
                logger.error(f"Failed to mark message {message_id} as processed: {e}")
                # Don't raise - comment was created successfully
            
            return item
            
        except Exception as e:
            logger.error(f"Error adding email as comment to item {item.id}: {e}")
            raise


