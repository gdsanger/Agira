"""
Tests for Meeting Transcript Upload functionality.
"""
import json
import io
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus
)

User = get_user_model()


class MeetingTranscriptUploadTest(TestCase):
    """Test the meeting transcript upload functionality."""
    
    def setUp(self):
        """Set up test data."""
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User',
            role='Agent'
        )
        
        # Create organisation
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org)
        
        # Create meeting and task item types
        self.meeting_type = ItemType.objects.create(
            key='meeting',
            name='Meeting',
            description='Meeting item type'
        )
        self.task_type = ItemType.objects.create(
            key='task',
            name='Task',
            description='Task item type'
        )
        
        # Create meeting item
        self.meeting_item = Item.objects.create(
            project=self.project,
            type=self.meeting_type,
            title='Test Meeting',
            description='Old description',
            status=ItemStatus.INBOX,
            assigned_to=self.user
        )
        
        # Create non-meeting item for validation
        self.bug_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            description='Bug item type'
        )
        self.bug_item = Item.objects.create(
            project=self.project,
            type=self.bug_type,
            title='Test Bug',
            description='Bug description',
            status=ItemStatus.INBOX
        )
        
        # Login
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_upload_transcript_not_meeting_item(self):
        """Test that transcript upload is rejected for non-meeting items."""
        # Create a dummy docx file
        docx_content = b'PK\x03\x04'  # Minimal ZIP signature (DOCX is a ZIP)
        uploaded_file = SimpleUploadedFile(
            'transcript.docx',
            docx_content,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        url = reverse('item-upload-transcript', args=[self.bug_item.id])
        response = self.client.post(url, {'file': uploaded_file})
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('Meeting items', data['error'])
    
    def test_upload_transcript_no_file(self):
        """Test that upload is rejected when no file is provided."""
        url = reverse('item-upload-transcript', args=[self.meeting_item.id])
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('No file', data['error'])
    
    def test_upload_transcript_wrong_file_type(self):
        """Test that upload is rejected for non-docx files."""
        # Create a PDF file
        pdf_file = SimpleUploadedFile(
            'document.pdf',
            b'%PDF-1.4',
            content_type='application/pdf'
        )
        
        url = reverse('item-upload-transcript', args=[self.meeting_item.id])
        response = self.client.post(url, {'file': pdf_file})
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('.docx', data['error'])
    
    @patch('core.views.AgentService')
    @patch('core.views.AttachmentStorageService')
    @patch('docx.Document')
    def test_upload_transcript_success(self, mock_document, mock_storage_service, mock_agent_service):
        """Test successful transcript upload and processing."""
        # Mock DOCX extraction
        mock_doc_instance = MagicMock()
        mock_paragraph1 = MagicMock()
        mock_paragraph1.text = 'This is the meeting transcript.'
        mock_paragraph2 = MagicMock()
        mock_paragraph2.text = 'We discussed important topics.'
        mock_doc_instance.paragraphs = [mock_paragraph1, mock_paragraph2]
        mock_document.return_value = mock_doc_instance
        
        # Mock storage service
        mock_storage_instance = MagicMock()
        mock_attachment = MagicMock()
        mock_attachment.original_name = 'transcript.docx'
        mock_storage_instance.store_attachment.return_value = mock_attachment
        mock_storage_instance.read_attachment.return_value = b'dummy content'
        mock_storage_service.return_value = mock_storage_instance
        
        # Mock agent service
        mock_agent_instance = MagicMock()
        agent_response = json.dumps({
            'Summary': 'Meeting summary: Discussed project timeline and deliverables.',
            'Tasks': [
                {
                    'Title': 'Update project timeline',
                    'Description': 'Review and update the project timeline based on discussion'
                },
                {
                    'Title': 'Prepare presentation',
                    'Description': 'Create presentation for next stakeholder meeting'
                }
            ]
        })
        mock_agent_instance.execute_agent.return_value = agent_response
        mock_agent_service.return_value = mock_agent_instance
        
        # Create a valid DOCX file
        docx_file = SimpleUploadedFile(
            'transcript.docx',
            b'PK\x03\x04',  # Minimal ZIP signature
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        # Upload transcript
        url = reverse('item-upload-transcript', args=[self.meeting_item.id])
        response = self.client.post(url, {'file': docx_file})
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['tasks_created'], 2)
        
        # Verify meeting description was updated
        self.meeting_item.refresh_from_db()
        self.assertEqual(
            self.meeting_item.description,
            'Meeting summary: Discussed project timeline and deliverables.'
        )
        
        # Verify tasks were created
        child_tasks = Item.objects.filter(
            parent=self.meeting_item,
            type=self.task_type
        )
        self.assertEqual(child_tasks.count(), 2)
        
        # Verify first task
        task1 = child_tasks.filter(title='Update project timeline').first()
        self.assertIsNotNone(task1)
        self.assertEqual(task1.description, 'Review and update the project timeline based on discussion')
        self.assertEqual(task1.status, ItemStatus.INBOX)
        self.assertEqual(task1.assigned_to, self.user)
        self.assertIsNone(task1.requester)
        
        # Verify second task
        task2 = child_tasks.filter(title='Prepare presentation').first()
        self.assertIsNotNone(task2)
        self.assertEqual(task2.description, 'Create presentation for next stakeholder meeting')
    
    @patch('core.views.AgentService')
    @patch('core.views.AttachmentStorageService')
    @patch('docx.Document')
    def test_upload_transcript_empty_tasks(self, mock_document, mock_storage_service, mock_agent_service):
        """Test transcript upload with empty tasks array."""
        # Mock DOCX extraction
        mock_doc_instance = MagicMock()
        mock_paragraph = MagicMock()
        mock_paragraph.text = 'Brief status update meeting.'
        mock_doc_instance.paragraphs = [mock_paragraph]
        mock_document.return_value = mock_doc_instance
        
        # Mock storage service
        mock_storage_instance = MagicMock()
        mock_attachment = MagicMock()
        mock_attachment.original_name = 'transcript.docx'
        mock_storage_instance.store_attachment.return_value = mock_attachment
        mock_storage_instance.read_attachment.return_value = b'dummy content'
        mock_storage_service.return_value = mock_storage_instance
        
        # Mock agent service with empty tasks
        mock_agent_instance = MagicMock()
        agent_response = json.dumps({
            'Summary': 'Status update meeting with no action items.',
            'Tasks': []
        })
        mock_agent_instance.execute_agent.return_value = agent_response
        mock_agent_service.return_value = mock_agent_instance
        
        # Create a valid DOCX file
        docx_file = SimpleUploadedFile(
            'transcript.docx',
            b'PK\x03\x04',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        # Upload transcript
        url = reverse('item-upload-transcript', args=[self.meeting_item.id])
        response = self.client.post(url, {'file': docx_file})
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['tasks_created'], 0)
        
        # Verify meeting description was updated even with no tasks
        self.meeting_item.refresh_from_db()
        self.assertEqual(
            self.meeting_item.description,
            'Status update meeting with no action items.'
        )
        
        # Verify no tasks were created
        child_tasks = Item.objects.filter(parent=self.meeting_item)
        self.assertEqual(child_tasks.count(), 0)
    
    @patch('core.views.AgentService')
    @patch('core.views.AttachmentStorageService')
    @patch('docx.Document')
    def test_upload_transcript_invalid_agent_response(self, mock_document, mock_storage_service, mock_agent_service):
        """Test that invalid agent response is handled correctly."""
        # Mock DOCX extraction
        mock_doc_instance = MagicMock()
        mock_paragraph = MagicMock()
        mock_paragraph.text = 'Meeting content.'
        mock_doc_instance.paragraphs = [mock_paragraph]
        mock_document.return_value = mock_doc_instance
        
        # Mock storage service
        mock_storage_instance = MagicMock()
        mock_attachment = MagicMock()
        mock_attachment.original_name = 'transcript.docx'
        mock_storage_instance.store_attachment.return_value = mock_attachment
        mock_storage_instance.read_attachment.return_value = b'dummy content'
        mock_storage_service.return_value = mock_storage_instance
        
        # Mock agent service with invalid JSON
        mock_agent_instance = MagicMock()
        mock_agent_instance.execute_agent.return_value = 'This is not valid JSON'
        mock_agent_service.return_value = mock_agent_instance
        
        # Create a valid DOCX file
        docx_file = SimpleUploadedFile(
            'transcript.docx',
            b'PK\x03\x04',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        # Upload transcript
        url = reverse('item-upload-transcript', args=[self.meeting_item.id])
        response = self.client.post(url, {'file': docx_file})
        
        # Verify error response
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('invalid', data['error'].lower())
        
        # Verify meeting description was NOT updated
        self.meeting_item.refresh_from_db()
        self.assertEqual(self.meeting_item.description, 'Old description')
        
        # Verify no tasks were created
        child_tasks = Item.objects.filter(parent=self.meeting_item)
        self.assertEqual(child_tasks.count(), 0)
    
    def test_upload_transcript_file_too_large(self):
        """Test that upload is rejected when file exceeds 50 MB limit."""
        # Create a file larger than 50 MB (simulated with size metadata)
        # We'll create a small file but the storage service will validate the actual size
        large_file_content = b'PK\x03\x04' + b'x' * 100  # Small actual content
        uploaded_file = SimpleUploadedFile(
            'large_transcript.docx',
            large_file_content,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        # Mock the file size to be larger than 50 MB
        # We need to test the actual AttachmentStorageService validation
        from core.services.storage.errors import AttachmentTooLarge
        from unittest.mock import patch, MagicMock
        
        with patch('core.services.storage.service.AttachmentStorageService._get_file_size') as mock_get_size:
            # Mock file size to be 51 MB (exceeds 50 MB limit)
            mock_get_size.return_value = 51 * 1024 * 1024
            
            url = reverse('item-upload-transcript', args=[self.meeting_item.id])
            response = self.client.post(url, {'file': uploaded_file})
            
            # Verify error response with 413 Payload Too Large status
            self.assertEqual(response.status_code, 413)
            data = json.loads(response.content)
            self.assertFalse(data['success'])
            self.assertIn('50', data['error'])  # Error should mention the 50 MB limit
            self.assertIn('MB', data['error'])
    
    def test_upload_transcript_within_size_limit(self):
        """Test that files within the 50 MB limit are accepted."""
        # This test would pass through to the agent service mocking
        # We're primarily testing that the 50 MB limit is configured correctly
        from unittest.mock import patch, MagicMock
        
        with patch('core.views.AgentService') as mock_agent_service, \
             patch('core.views.AttachmentStorageService') as mock_storage_service, \
             patch('docx.Document') as mock_document:
            
            # Mock DOCX extraction
            mock_doc_instance = MagicMock()
            mock_paragraph = MagicMock()
            mock_paragraph.text = 'Test meeting content.'
            mock_doc_instance.paragraphs = [mock_paragraph]
            mock_document.return_value = mock_doc_instance
            
            # Mock storage service (simulating 40 MB file - within 50 MB limit)
            mock_storage_instance = MagicMock()
            mock_attachment = MagicMock()
            mock_attachment.original_name = 'transcript.docx'
            mock_storage_instance.store_attachment.return_value = mock_attachment
            mock_storage_instance.read_attachment.return_value = b'dummy content'
            mock_storage_service.return_value = mock_storage_instance
            
            # Mock agent service
            mock_agent_instance = MagicMock()
            agent_response = json.dumps({
                'Summary': 'Test meeting summary.',
                'Tasks': []
            })
            mock_agent_instance.execute_agent.return_value = agent_response
            mock_agent_service.return_value = mock_agent_instance
            
            # Create file
            docx_file = SimpleUploadedFile(
                'transcript.docx',
                b'PK\x03\x04' + b'x' * 1000,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            
            url = reverse('item-upload-transcript', args=[self.meeting_item.id])
            response = self.client.post(url, {'file': docx_file})
            
            # Should succeed
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertTrue(data['success'])
            
            # Verify that storage service was called with max_size_mb=50
            mock_storage_service.assert_called_once_with(max_size_mb=50)
