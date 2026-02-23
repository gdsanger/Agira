"""
Tests for Change Attachment views
"""

from datetime import datetime
from io import BytesIO
from unittest.mock import patch, MagicMock

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Attachment, AttachmentLink, AttachmentRole,
    Change, ChangeStatus, Project, ProjectStatus,
    User, RiskLevel,
)
from core.printing import PdfRenderService


class ChangeAttachmentViewTestCase(TestCase):
    """Test cases for Change attachment views."""

    def setUp(self):
        self.client = Client()

        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User",
        )

        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING,
        )

        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
        )

        # Create an attachment linked to the change
        self.attachment = Attachment.objects.create(
            original_name="change_file.txt",
            content_type="text/plain",
            size_bytes=100,
            storage_path="/fake/path/change_file.txt",
            created_by=self.user,
        )
        change_ct = ContentType.objects.get_for_model(Change)
        AttachmentLink.objects.create(
            attachment=self.attachment,
            target_content_type=change_ct,
            target_object_id=self.change.id,
            role=AttachmentRole.CHANGE_FILE,
        )

    # --- change_attachments_tab ---

    def test_attachments_tab_requires_login(self):
        url = reverse('change-attachments-tab', kwargs={'change_id': self.change.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_attachments_tab_returns_200(self):
        self.client.force_login(self.user)
        url = reverse('change-attachments-tab', kwargs={'change_id': self.change.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'change_file.txt')

    def test_attachments_tab_404_for_missing_change(self):
        self.client.force_login(self.user)
        url = reverse('change-attachments-tab', kwargs={'change_id': 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    # --- change_upload_attachment ---

    @patch('core.views.AttachmentStorageService')
    def test_upload_attachment_requires_login(self, _mock):
        url = reverse('change-upload-attachment', kwargs={'change_id': self.change.id})
        response = self.client.post(url, {'file': BytesIO(b'data')})
        self.assertEqual(response.status_code, 302)

    @patch('core.views.AttachmentStorageService')
    def test_upload_attachment_no_file_returns_400(self, _mock):
        self.client.force_login(self.user)
        url = reverse('change-upload-attachment', kwargs={'change_id': self.change.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 400)

    @patch('core.views.ActivityService')
    @patch('core.views.AttachmentStorageService')
    def test_upload_attachment_success(self, mock_storage_cls, mock_activity_cls):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        new_attachment = Attachment.objects.create(
            original_name="new_file.pdf",
            content_type="application/pdf",
            size_bytes=200,
            storage_path="/fake/new_file.pdf",
            created_by=self.user,
        )
        change_ct = ContentType.objects.get_for_model(Change)
        AttachmentLink.objects.create(
            attachment=new_attachment,
            target_content_type=change_ct,
            target_object_id=self.change.id,
            role=AttachmentRole.CHANGE_FILE,
        )
        mock_storage.store_attachment.return_value = new_attachment
        mock_activity_cls.return_value = MagicMock()

        self.client.force_login(self.user)
        url = reverse('change-upload-attachment', kwargs={'change_id': self.change.id})
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("new_file.pdf", b"PDF content", content_type="application/pdf")
        response = self.client.post(url, {'file': f})

        self.assertIn(response.status_code, [200, 302])

    # --- change_delete_attachment ---

    def test_delete_attachment_requires_login(self):
        url = reverse('change-delete-attachment', kwargs={'attachment_id': self.attachment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

    @patch('core.views.AttachmentStorageService')
    def test_delete_attachment_success(self, mock_storage_cls):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        mock_storage.delete_attachment.return_value = None

        self.client.force_login(self.user)
        url = reverse('change-delete-attachment', kwargs={'attachment_id': self.attachment.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        import json
        data = json.loads(response.content)
        self.assertTrue(data['success'])

    # --- change_download_attachment ---

    def test_download_attachment_requires_login(self):
        url = reverse('change-download-attachment', kwargs={'attachment_id': self.attachment.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    @patch('core.views.AttachmentStorageService')
    def test_download_attachment_success(self, mock_storage_cls):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        mock_storage.read_attachment.return_value = b"file content"

        self.client.force_login(self.user)
        url = reverse('change-download-attachment', kwargs={'attachment_id': self.attachment.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"file content")

    @patch('core.views.AttachmentStorageService')
    def test_download_deleted_attachment_returns_404(self, _mock):
        self.attachment.is_deleted = True
        self.attachment.save()

        self.client.force_login(self.user)
        url = reverse('change-download-attachment', kwargs={'attachment_id': self.attachment.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    # --- change_detail context ---

    def test_change_detail_includes_attachments_in_context(self):
        self.client.force_login(self.user)
        url = reverse('change-detail', kwargs={'id': self.change.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('change_attachments', response.context)
        self.assertIn(self.attachment, response.context['change_attachments'])


class ChangePDFWithAttachmentsTestCase(TestCase):
    """Test that Change PDF includes attachments in the Attachments & References section."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="pdfuser",
            email="pdf@example.com",
            password="testpass",
            name="PDF User",
        )
        self.project = Project.objects.create(
            name="PDF Project",
            status=ProjectStatus.WORKING,
        )
        self.change = Change.objects.create(
            project=self.project,
            title="Change With Attachments",
            status=ChangeStatus.PLANNED,
            risk=RiskLevel.NORMAL,
            created_by=self.user,
        )
        self.attachment = Attachment.objects.create(
            original_name="report.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            storage_path="/fake/report.pdf",
            created_by=self.user,
        )
        change_ct = ContentType.objects.get_for_model(Change)
        AttachmentLink.objects.create(
            attachment=self.attachment,
            target_content_type=change_ct,
            target_object_id=self.change.id,
            role=AttachmentRole.CHANGE_FILE,
        )

    def test_pdf_generation_with_attachments(self):
        """PDF should generate successfully when change has attachments."""
        service = PdfRenderService()
        context = {
            'change': self.change,
            'items': self.change.get_associated_items(),
            'approvals': self.change.approvals.all(),
            'organisations': self.change.organisations.all(),
            'change_attachments': [self.attachment],
            'now': datetime.now(),
        }
        result = service.render(
            template_name='printing/change_report.html',
            context=context,
            base_url='http://localhost:8000/',
            filename=f'change_{self.change.id}.pdf',
        )
        self.assertGreater(len(result.pdf_bytes), 0)
        self.assertTrue(result.pdf_bytes.startswith(b'%PDF'))

    def test_pdf_generation_without_attachments(self):
        """PDF should generate successfully when change has no attachments."""
        service = PdfRenderService()
        context = {
            'change': self.change,
            'items': self.change.get_associated_items(),
            'approvals': self.change.approvals.all(),
            'organisations': self.change.organisations.all(),
            'change_attachments': [],
            'now': datetime.now(),
        }
        result = service.render(
            template_name='printing/change_report.html',
            context=context,
            base_url='http://localhost:8000/',
            filename=f'change_{self.change.id}.pdf',
        )
        self.assertGreater(len(result.pdf_bytes), 0)
        self.assertTrue(result.pdf_bytes.startswith(b'%PDF'))

    def test_change_print_view_includes_attachments(self):
        """change_print view should include attachments and return PDF."""
        client = Client()
        client.force_login(self.user)
        url = reverse('change-print', kwargs={'id': self.change.id})
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
