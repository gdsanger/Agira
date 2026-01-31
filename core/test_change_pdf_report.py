"""
Tests for Change PDF Report functionality
"""

from io import BytesIO
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import Change, ChangeStatus, Project, User, RiskLevel
from reports.change_pdf import build_change_pdf


class ChangePDFReportTestCase(TestCase):
    """Test cases for Change PDF report generation"""
    
    def setUp(self):
        """Set up test data"""
        # Create a test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass",
            name="Test User"
        )
        
        # Create a test project
        self.project = Project.objects.create(
            name="Test Project",
            status="Working"
        )
        
        # Create a test change
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change for PDF",
            description="This is a test change for PDF generation",
            status=ChangeStatus.PLANNED,
            risk=RiskLevel.NORMAL,
            risk_description="Test risk description",
            mitigation="Test mitigation plan",
            rollback_plan="Test rollback plan",
            communication_plan="Test communication plan",
            created_by=self.user,
            is_safety_relevant=True
        )
    
    def test_pdf_generation_function(self):
        """Test that PDF generation function works"""
        buffer = BytesIO()
        build_change_pdf(self.change, buffer)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        # Verify PDF was generated
        self.assertGreater(len(pdf_bytes), 0, "PDF should not be empty")
        self.assertTrue(pdf_bytes.startswith(b'%PDF'), "Output should be a valid PDF")
    
    def test_change_print_url_exists(self):
        """Test that the print URL is configured"""
        url = reverse('change-print', kwargs={'id': self.change.id})
        self.assertEqual(url, f'/changes/{self.change.id}/print/')
    
    def test_change_print_view_requires_login(self):
        """Test that the print view requires authentication"""
        client = Client()
        url = reverse('change-print', kwargs={'id': self.change.id})
        response = client.get(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_change_print_view_returns_pdf(self):
        """Test that the print view returns a PDF"""
        client = Client()
        client.force_login(self.user)
        
        url = reverse('change-print', kwargs={'id': self.change.id})
        response = client.get(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('inline', response['Content-Disposition'])
        self.assertIn(f'change_{self.change.id}.pdf', response['Content-Disposition'])
        
        # Verify PDF content
        pdf_content = b''.join(response.streaming_content) if hasattr(response, 'streaming_content') else response.content
        self.assertTrue(pdf_content.startswith(b'%PDF'), "Response should be a valid PDF")
    
    def test_pdf_generation_with_empty_fields(self):
        """Test PDF generation with minimal/empty fields"""
        # Create change with minimal data
        minimal_change = Change.objects.create(
            project=self.project,
            title="Minimal Change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.LOW
        )
        
        buffer = BytesIO()
        build_change_pdf(minimal_change, buffer)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        # Should still generate valid PDF
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
    
    def test_pdf_generation_with_multiline_text(self):
        """Test PDF generation handles multiline text correctly"""
        # Create change with multiline descriptions
        multiline_change = Change.objects.create(
            project=self.project,
            title="Multiline Change",
            description="Line 1\nLine 2\nLine 3",
            risk_description="Risk line 1\nRisk line 2",
            mitigation="Mitigation line 1\nMitigation line 2",
            status=ChangeStatus.PLANNED,
            risk=RiskLevel.HIGH
        )
        
        buffer = BytesIO()
        build_change_pdf(multiline_change, buffer)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        # Should generate valid PDF
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
