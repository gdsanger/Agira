"""
Tests for attachment views
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.contenttypes.models import ContentType

from core.models import (
    Attachment, AttachmentLink, AttachmentRole,
    Item, ItemStatus, ItemType, Project, ProjectStatus,
    User, Organisation
)


class AttachmentViewTestCase(TestCase):
    """Test cases for generic attachment view"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="task",
            name="Task"
        )
        
        # Create item
        self.item = Item.objects.create(
            title="Test Item",
            status=ItemStatus.BACKLOG,
            type=self.item_type,
            project=self.project
        )
        
        # Create attachment linked to item
        self.item_attachment = Attachment.objects.create(
            original_name="test_item_file.txt",
            content_type="text/plain",
            size_bytes=100,
            storage_path="/fake/path/item_file.txt",
            created_by=self.user
        )
        
        # Create attachment link
        AttachmentLink.objects.create(
            attachment=self.item_attachment,
            target_content_type=ContentType.objects.get_for_model(Item),
            target_object_id=self.item.id,
            role=AttachmentRole.ITEM_FILE
        )
        
        # Create attachment linked to project
        self.project_attachment = Attachment.objects.create(
            original_name="test_project_file.txt",
            content_type="text/plain",
            size_bytes=200,
            storage_path="/fake/path/project_file.txt",
            created_by=self.user
        )
        
        # Create attachment link
        AttachmentLink.objects.create(
            attachment=self.project_attachment,
            target_content_type=ContentType.objects.get_for_model(Project),
            target_object_id=self.project.id,
            role=AttachmentRole.PROJECT_FILE
        )
        
        # Create orphan attachment (no parent)
        self.orphan_attachment = Attachment.objects.create(
            original_name="orphan_file.txt",
            content_type="text/plain",
            size_bytes=50,
            storage_path="/fake/path/orphan_file.txt",
            created_by=self.user
        )
    
    def test_attachment_view_requires_login(self):
        """Test that attachment view requires authentication"""
        url = reverse('attachment-view', kwargs={'attachment_id': self.item_attachment.id})
        response = self.client.get(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_attachment_view_with_item_parent_redirects_to_item_detail(self):
        """Test that attachment with item parent redirects to item detail"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('attachment-view', kwargs={'attachment_id': self.item_attachment.id})
        response = self.client.get(url)
        
        # Should redirect to item detail
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('item-detail', kwargs={'item_id': self.item.id})
        self.assertEqual(response.url, expected_url)
    
    def test_attachment_view_with_project_parent_redirects_to_project_detail(self):
        """Test that attachment with project parent redirects to project detail"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('attachment-view', kwargs={'attachment_id': self.project_attachment.id})
        response = self.client.get(url)
        
        # Should redirect to project detail
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('project-detail', kwargs={'id': self.project.id})
        self.assertEqual(response.url, expected_url)
    
    def test_attachment_view_nonexistent_returns_404(self):
        """Test that viewing non-existent attachment returns 404"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('attachment-view', kwargs={'attachment_id': 99999})
        response = self.client.get(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
    
    def test_attachment_view_deleted_returns_404(self):
        """Test that viewing deleted attachment returns 404"""
        self.client.login(username='testuser', password='testpass123')
        
        # Mark attachment as deleted
        self.item_attachment.is_deleted = True
        self.item_attachment.save()
        
        url = reverse('attachment-view', kwargs={'attachment_id': self.item_attachment.id})
        response = self.client.get(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
    
    def test_attachment_url_pattern_matches(self):
        """Test that the URL pattern is correctly configured"""
        url = reverse('attachment-view', kwargs={'attachment_id': 123})
        self.assertEqual(url, '/attachments/123/')
