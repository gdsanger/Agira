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
import base64
from io import BytesIO
from typing import Optional, Dict, Any, List, Tuple
from django.db import transaction
from django.utils import timezone
from django.urls import reverse

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
    Attachment,
)
from core.services.config import get_graph_config
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled, ServiceError
from core.services.graph.client import get_client
from core.services.agents.agent_service import AgentService
from core.services.storage import AttachmentStorageService

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
        self.storage_service = AttachmentStorageService()
    
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
                
                # Process attachments (before creating comment so we can rewrite inline images)
                content_id_map = self._process_attachments(
                    message_id=message_id,
                    item=item,
                    user=user,
                )
                
                # Extract email metadata for comment
                to_recipients = message.get("toRecipients", [])
                to_addresses = [r.get("emailAddress", {}).get("address", "") for r in to_recipients]
                external_to = "; ".join([addr for addr in to_addresses if addr])
                
                cc_recipients = message.get("ccRecipients", [])
                cc_addresses = [r.get("emailAddress", {}).get("address", "") for r in cc_recipients]
                external_cc = "; ".join([addr for addr in cc_addresses if addr])
                
                body_data = message.get("body", {})
                body_original_html = body_data.get("content", "") if body_data.get("contentType", "").lower() == "html" else ""
                
                # Rewrite inline images in HTML body
                if body_original_html and content_id_map:
                    body_original_html = self._rewrite_inline_images(
                        body_original_html,
                        content_id_map
                    )
                
                # Rewrite inline images in markdown body
                if content_id_map:
                    body_markdown = self._rewrite_markdown_inline_images(
                        body_markdown,
                        content_id_map
                    )
                
                internet_message_id = message.get("internetMessageId", "")
                
                # Add incoming email as comment to the newly created item
                ItemComment.objects.create(
                    item=item,
                    author=user,
                    visibility=CommentVisibility.PUBLIC,
                    kind=CommentKind.EMAIL_IN,
                    subject=subject,
                    body=body_markdown,
                    external_from=sender_email,
                    external_to=external_to,
                    external_cc=external_cc,
                    body_original_html=body_original_html,
                    message_id=internet_message_id or message_id,
                )
                
                logger.info(
                    f"Added incoming email as comment to new item {item.id}"
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
    
    def _process_attachments(
        self,
        message_id: str,
        item: Item,
        user: User,
    ) -> Dict[str, Attachment]:
        """
        Process all attachments for an email message.
        
        Args:
            message_id: Graph API message ID
            item: Item to attach files to
            user: User who created the item (for attachment metadata)
            
        Returns:
            Dictionary mapping content_id to Attachment for inline attachments
        """
        content_id_map = {}
        
        try:
            # Fetch attachments from Graph API
            attachments = self.client.get_message_attachments(
                user_upn=self.mailbox,
                message_id=message_id,
            )
            
            logger.info(f"Processing {len(attachments)} attachments for message {message_id}")
            
            for att_data in attachments:
                try:
                    # Extract attachment metadata
                    att_type = att_data.get("@odata.type", "")
                    name = att_data.get("name", "unnamed")
                    content_type = att_data.get("contentType", "application/octet-stream")
                    size = att_data.get("size", 0)
                    is_inline = att_data.get("isInline", False)
                    content_id = att_data.get("contentId", "")
                    
                    # Only process FileAttachment types (skip ItemAttachment, Reference, etc.)
                    if att_type != "#microsoft.graph.fileAttachment":
                        logger.debug(f"Skipping attachment type {att_type}: {name}")
                        continue
                    
                    # Get attachment content (base64 encoded)
                    content_bytes_b64 = att_data.get("contentBytes", "")
                    if not content_bytes_b64:
                        logger.warning(f"Attachment {name} has no content, skipping")
                        continue
                    
                    # Decode base64 content
                    content_bytes = base64.b64decode(content_bytes_b64)
                    file_obj = BytesIO(content_bytes)
                    file_obj.name = name
                    
                    # Normalize content_id (remove angle brackets if present)
                    if content_id:
                        content_id = content_id.strip('<>')
                    
                    # Check for duplicate by content_id (for idempotency)
                    if content_id:
                        existing = Attachment.objects.filter(
                            content_id=content_id,
                            links__target_object_id=item.id,
                            links__target_content_type__model='item'
                        ).first()
                        
                        if existing:
                            logger.info(f"Attachment with content_id {content_id} already exists, skipping")
                            content_id_map[content_id] = existing
                            continue
                    
                    # Store attachment
                    attachment = self.storage_service.store_attachment(
                        file=file_obj,
                        target=item,
                        created_by=user,
                        original_name=name,
                        content_type=content_type,
                        content_id=content_id,
                        compute_hash=True,
                    )
                    
                    logger.info(
                        f"Stored attachment: {name} "
                        f"(size={size}, inline={is_inline}, content_id={content_id})"
                    )
                    
                    # Map content_id to attachment for inline image processing
                    # Note: We map ANY attachment with a content_id, not just those marked as inline,
                    # because Microsoft Graph may not always set isInline correctly
                    if content_id:
                        content_id_map[content_id] = attachment
                        
                except Exception as e:
                    logger.error(f"Error processing attachment {att_data.get('name', 'unknown')}: {e}")
                    # Continue processing other attachments
                    
        except Exception as e:
            logger.error(f"Error fetching attachments for message {message_id}: {e}")
        
        return content_id_map
    
    def _rewrite_inline_images(
        self,
        html_content: str,
        content_id_map: Dict[str, Attachment],
    ) -> str:
        """
        Rewrite HTML content to replace cid: references with attachment URLs.
        
        Args:
            html_content: Original HTML content with cid: references
            content_id_map: Mapping of content_id to Attachment objects
            
        Returns:
            HTML content with cid: references replaced by attachment URLs
        """
        if not content_id_map:
            return html_content
        
        # Pattern to match src="cid:..." or src='cid:...'
        # This captures both single and double quotes
        pattern = r'src=["\']cid:([^"\']+)["\']'
        
        def replace_cid(match):
            cid = match.group(1).strip()
            
            # Try to find attachment by content_id
            if cid in content_id_map:
                attachment = content_id_map[cid]
                # Generate URL to view/download the attachment
                url = reverse('item-view-attachment', args=[attachment.id])
                return f'src="{url}"'
            else:
                # Content ID not found, leave as-is
                logger.warning(f"Content ID {cid} referenced but not found in attachments")
                return match.group(0)
        
        # Replace all cid: references
        rewritten_html = re.sub(pattern, replace_cid, html_content, flags=re.IGNORECASE)
        
        return rewritten_html
    
    def _rewrite_markdown_inline_images(
        self,
        markdown_content: str,
        content_id_map: Dict[str, Attachment],
    ) -> str:
        """
        Rewrite Markdown content to replace cid: references with attachment URLs.
        
        Matches patterns like:
        - ![alt text](cid:CONTENT-ID)
        - ![](cid:CONTENT-ID)
        
        Args:
            markdown_content: Original Markdown content with cid: references
            content_id_map: Mapping of content_id to Attachment objects
            
        Returns:
            Markdown content with cid: references replaced by attachment URLs
        """
        if not content_id_map:
            return markdown_content
        
        # Pattern to match ![...](cid:...)
        # Captures the alt text and the content ID
        pattern = r'!\[([^\]]*)\]\(cid:([^)]+)\)'
        
        def replace_cid(match):
            alt_text = match.group(1)  # Don't strip - preserve whitespace in alt text
            cid = match.group(2).strip()  # Strip only the CID
            
            # Try to find attachment by content_id
            if cid in content_id_map:
                attachment = content_id_map[cid]
                # Generate URL to view/download the attachment
                url = reverse('item-view-attachment', args=[attachment.id])
                return f'![{alt_text}]({url})'
            else:
                # Content ID not found, leave as-is
                logger.warning(f"Content ID {cid} referenced in markdown but not found in attachments")
                return match.group(0)
        
        # Replace all cid: references
        # Note: Content IDs are case-sensitive, so we don't use re.IGNORECASE
        rewritten_markdown = re.sub(pattern, replace_cid, markdown_content)
        
        return rewritten_markdown
    
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
        from core.services.user_service import get_or_create_user_and_org
        return get_or_create_user_and_org(email=email, name=name)
    
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
        
        # Extract To recipients
        to_recipients = message.get("toRecipients", [])
        to_addresses = [r.get("emailAddress", {}).get("address", "") for r in to_recipients]
        external_to = "; ".join([addr for addr in to_addresses if addr])
        
        # Extract CC recipients
        cc_recipients = message.get("ccRecipients", [])
        cc_addresses = [r.get("emailAddress", {}).get("address", "") for r in cc_recipients]
        external_cc = "; ".join([addr for addr in cc_addresses if addr])
        
        # Get original HTML body
        body_data = message.get("body", {})
        body_original_html = body_data.get("content", "") if body_data.get("contentType", "").lower() == "html" else ""
        
        # Get In-Reply-To header for threading
        internet_message_id = message.get("internetMessageId", "")
        conversation_id = message.get("conversationId", "")
        
        try:
            # Get or create user first (outside the transaction to avoid conflicts)
            user, _ = self._get_or_create_user_and_org(
                email=sender_email,
                name=sender_name,
            )
            
            with transaction.atomic():
                # Process attachments (before creating comment so we can rewrite inline images)
                content_id_map = self._process_attachments(
                    message_id=message_id,
                    item=item,
                    user=user,
                )
                
                # Rewrite inline images in HTML body
                if body_original_html and content_id_map:
                    body_original_html = self._rewrite_inline_images(
                        body_original_html,
                        content_id_map
                    )
                
                # Rewrite inline images in markdown body
                if content_id_map:
                    body = self._rewrite_markdown_inline_images(
                        body,
                        content_id_map
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
                    external_to=external_to,
                    external_cc=external_cc,
                    body_original_html=body_original_html,
                    message_id=internet_message_id or message_id,
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


