"""
Tests for email reply and forward service.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model

from core.models import (
    Organisation,
    Project,
    ItemType,
    Item,
    ItemStatus,
    ItemComment,
    CommentKind,
    CommentVisibility,
    GraphAPIConfiguration,
)
from core.services.mail.email_reply_service import (
    prepare_reply,
    prepare_reply_all,
    prepare_forward,
    _parse_email_addresses,
    _ensure_subject_prefix,
    _filter_recipients,
)

User = get_user_model()


class EmailReplyServiceTest(TestCase):
    """Tests for email reply service."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create GraphAPI configuration
        self.config = GraphAPIConfiguration.objects.create(
            id=1,
            enabled=True,
            tenant_id="test-tenant",
            client_id="test-client",
            client_secret="test-secret",
            default_mail_sender="agira@system.com",
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="testpass123",
            name="Test User",
        )
        
        # Create another user
        self.sender_user = User.objects.create_user(
            username="sender",
            email="sender@external.com",
            password="testpass123",
            name="External Sender",
        )
        
        # Create test organization
        self.org = Organisation.objects.create(
            name="Test Org",
            mail_domains="example.com",
        )
        
        # Create test project
        self.project = Project.objects.create(
            name="TestProject",
            description="Test project",
        )
        
        # Create item type
        self.task_type = ItemType.objects.create(
            key="task",
            name="Task",
            is_active=True,
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title="Test Item",
            description="Test description",
            type=self.task_type,
            requester=self.user,
            status=ItemStatus.INBOX,
        )
    
    def test_parse_email_addresses_semicolon(self):
        """Test parsing semicolon-separated email addresses."""
        addresses = _parse_email_addresses("user1@test.com; user2@test.com; user3@test.com")
        self.assertEqual(addresses, ["user1@test.com", "user2@test.com", "user3@test.com"])
    
    def test_parse_email_addresses_comma(self):
        """Test parsing comma-separated email addresses."""
        addresses = _parse_email_addresses("user1@test.com, user2@test.com, user3@test.com")
        self.assertEqual(addresses, ["user1@test.com", "user2@test.com", "user3@test.com"])
    
    def test_parse_email_addresses_empty(self):
        """Test parsing empty string."""
        addresses = _parse_email_addresses("")
        self.assertEqual(addresses, [])
    
    def test_ensure_subject_prefix_re(self):
        """Test adding RE: prefix to subject."""
        subject = _ensure_subject_prefix("Test Subject", "RE:")
        self.assertEqual(subject, "RE: Test Subject")
    
    def test_ensure_subject_prefix_already_present(self):
        """Test that prefix is not added if already present."""
        subject = _ensure_subject_prefix("RE: Test Subject", "RE:")
        self.assertEqual(subject, "RE: Test Subject")
    
    def test_ensure_subject_prefix_fw(self):
        """Test adding FW: prefix to subject."""
        subject = _ensure_subject_prefix("Test Subject", "FW:")
        self.assertEqual(subject, "FW: Test Subject")
    
    def test_filter_recipients_system_address(self):
        """Test filtering out system address."""
        addresses = ["user@test.com", "agira@system.com", "another@test.com"]
        filtered = _filter_recipients(addresses)
        self.assertEqual(filtered, ["user@test.com", "another@test.com"])
    
    def test_filter_recipients_current_user(self):
        """Test filtering out current user's address."""
        addresses = ["user@test.com", "testuser@example.com", "another@test.com"]
        filtered = _filter_recipients(addresses, exclude_user=self.user)
        self.assertEqual(filtered, ["user@test.com", "another@test.com"])
    
    def test_prepare_reply_incoming_email(self):
        """Test preparing reply for incoming email."""
        # Create incoming email comment
        comment = ItemComment.objects.create(
            item=self.item,
            author=self.sender_user,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.EMAIL_IN,
            subject="Test Email",
            body="This is a test email",
            body_original_html="<p>This is a test email</p>",
            external_from="sender@external.com",
            external_to="agira@system.com",
            message_id="msg-123",
        )
        
        # Prepare reply
        reply_data = prepare_reply(comment, current_user=self.user)
        
        # Verify reply data
        self.assertEqual(reply_data['to'], ["sender@external.com"])
        self.assertEqual(reply_data['cc'], [])
        self.assertTrue(reply_data['subject'].startswith("RE:"))
        self.assertIn("Test Email", reply_data['subject'])
        self.assertIn("sender@external.com", reply_data['body'])
        self.assertEqual(reply_data['in_reply_to'], "msg-123")
    
    def test_prepare_reply_all_with_cc(self):
        """Test preparing reply-all with CC recipients."""
        # Create incoming email comment with CC
        comment = ItemComment.objects.create(
            item=self.item,
            author=self.sender_user,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.EMAIL_IN,
            subject="Test Email",
            body="This is a test email",
            body_original_html="<p>This is a test email</p>",
            external_from="sender@external.com",
            external_to="agira@system.com",
            external_cc="cc1@test.com; cc2@test.com",
            message_id="msg-123",
        )
        
        # Prepare reply-all
        reply_data = prepare_reply_all(comment, current_user=self.user)
        
        # Verify reply data
        self.assertEqual(reply_data['to'], ["sender@external.com"])
        # CC should include original To and CC, but not system address or current user
        self.assertIn("cc1@test.com", reply_data['cc'])
        self.assertIn("cc2@test.com", reply_data['cc'])
        self.assertNotIn("agira@system.com", reply_data['cc'])
        self.assertTrue(reply_data['subject'].startswith("RE:"))
    
    def test_prepare_forward(self):
        """Test preparing forward."""
        # Create email comment
        comment = ItemComment.objects.create(
            item=self.item,
            author=self.sender_user,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.EMAIL_IN,
            subject="Test Email",
            body="This is a test email",
            body_original_html="<p>This is a test email</p>",
            external_from="sender@external.com",
            external_to="agira@system.com",
            external_cc="cc1@test.com",
            message_id="msg-123",
        )
        
        # Prepare forward
        forward_data = prepare_forward(comment, current_user=self.user)
        
        # Verify forward data
        self.assertEqual(forward_data['to'], [])
        self.assertEqual(forward_data['cc'], [])
        self.assertTrue(forward_data['subject'].startswith("FW:"))
        self.assertIn("Test Email", forward_data['subject'])
        self.assertIn("Forwarded message", forward_data['body'])
        self.assertIn("sender@external.com", forward_data['body'])
        self.assertEqual(forward_data['in_reply_to'], '')
    
    def test_prepare_reply_outgoing_email(self):
        """Test preparing reply for outgoing email."""
        # Create outgoing email comment
        comment = ItemComment.objects.create(
            item=self.item,
            author=self.user,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.EMAIL_OUT,
            subject="[AGIRA-1] Status Update",
            body_html="<p>Status has changed</p>",
            body_original_html="<p>Status has changed</p>",
            external_from="agira@system.com",
            external_to="recipient@test.com",
            message_id="msg-456",
        )
        
        # Prepare reply
        reply_data = prepare_reply(comment, current_user=self.user)
        
        # Verify reply data
        self.assertEqual(reply_data['to'], ["recipient@test.com"])
        self.assertTrue(reply_data['subject'].startswith("RE:"))


class EmailReplyViewsTest(TestCase):
    """Tests for email reply views."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create GraphAPI configuration
        self.config = GraphAPIConfiguration.objects.create(
            id=1,
            enabled=True,
            tenant_id="test-tenant",
            client_id="test-client",
            client_secret="test-secret",
            default_mail_sender="agira@system.com",
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="testpass123",
            name="Test User",
        )
        
        # Create test project
        self.project = Project.objects.create(
            name="TestProject",
            description="Test project",
        )
        
        # Create item type
        self.task_type = ItemType.objects.create(
            key="task",
            name="Task",
            is_active=True,
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title="Test Item",
            description="Test description",
            type=self.task_type,
            requester=self.user,
            status=ItemStatus.INBOX,
        )
        
        # Create email comment
        self.email_comment = ItemComment.objects.create(
            item=self.item,
            author=self.user,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.EMAIL_IN,
            subject="Test Email",
            body="This is a test email",
            body_original_html="<p>This is a test email</p>",
            external_from="sender@external.com",
            external_to="agira@system.com",
            message_id="msg-123",
        )
    
    def test_prepare_reply_endpoint(self):
        """Test prepare reply endpoint."""
        self.client.login(username="testuser", password="testpass123")
        
        response = self.client.get(f'/items/comments/{self.email_comment.id}/email/prepare-reply/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('to', data['data'])
        self.assertIn('cc', data['data'])
        self.assertIn('subject', data['data'])
        self.assertIn('body', data['data'])
    
    def test_prepare_reply_all_endpoint(self):
        """Test prepare reply-all endpoint."""
        self.client.login(username="testuser", password="testpass123")
        
        response = self.client.get(f'/items/comments/{self.email_comment.id}/email/prepare-reply-all/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('to', data['data'])
        self.assertIn('cc', data['data'])
    
    def test_prepare_forward_endpoint(self):
        """Test prepare forward endpoint."""
        self.client.login(username="testuser", password="testpass123")
        
        response = self.client.get(f'/items/comments/{self.email_comment.id}/email/prepare-forward/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['to'], [])
        self.assertEqual(data['data']['cc'], [])
    
    def test_prepare_reply_non_email_comment(self):
        """Test that prepare reply fails for non-email comment."""
        # Create regular comment
        regular_comment = ItemComment.objects.create(
            item=self.item,
            author=self.user,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.COMMENT,
            body="Regular comment",
        )
        
        self.client.login(username="testuser", password="testpass123")
        
        response = self.client.get(f'/items/comments/{regular_comment.id}/email/prepare-reply/')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error', data)
