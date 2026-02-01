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


class ChangeAssociatedItemsTestCase(TestCase):
    """Test cases for Change associated items functionality"""
    
    def setUp(self):
        """Set up test data"""
        from core.models import Item, ItemType, Release, ReleaseStatus
        
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
        
        # Create an item type
        self.item_type = ItemType.objects.create(
            key="feature",
            name="Feature"
        )
        
        # Create a release
        self.release = Release.objects.create(
            project=self.project,
            name="v1.0",
            version="1.0.0",
            status=ReleaseStatus.PLANNED
        )
        
        # Create items for the release
        self.release_item1 = Item.objects.create(
            project=self.project,
            title="Release Item 1",
            type=self.item_type,
            solution_release=self.release
        )
        
        self.release_item2 = Item.objects.create(
            project=self.project,
            title="Release Item 2",
            type=self.item_type,
            solution_release=self.release
        )
        
        # Create an item not in the release
        self.standalone_item = Item.objects.create(
            project=self.project,
            title="Standalone Item",
            type=self.item_type
        )
        
        # Create a change with the release
        self.change_with_release = Change.objects.create(
            project=self.project,
            title="Test Change with Release",
            status=ChangeStatus.PLANNED,
            risk=RiskLevel.NORMAL,
            release=self.release
        )
        
        # Create a change without release
        self.change_without_release = Change.objects.create(
            project=self.project,
            title="Test Change without Release",
            status=ChangeStatus.PLANNED,
            risk=RiskLevel.NORMAL
        )
    
    def test_get_associated_items_with_release(self):
        """Test that get_associated_items returns release items"""
        items = self.change_with_release.get_associated_items()
        
        # Should include both release items
        self.assertEqual(items.count(), 2)
        self.assertIn(self.release_item1, items)
        self.assertIn(self.release_item2, items)
        self.assertNotIn(self.standalone_item, items)
    
    def test_get_associated_items_without_release(self):
        """Test that get_associated_items returns empty when no release"""
        items = self.change_without_release.get_associated_items()
        
        # Should be empty
        self.assertEqual(items.count(), 0)
    
    def test_get_associated_items_with_direct_items(self):
        """Test that get_associated_items includes direct M2M items"""
        # Add standalone item directly to change
        self.change_with_release.items.add(self.standalone_item)
        
        items = self.change_with_release.get_associated_items()
        
        # Should include both release items and the direct item
        self.assertEqual(items.count(), 3)
        self.assertIn(self.release_item1, items)
        self.assertIn(self.release_item2, items)
        self.assertIn(self.standalone_item, items)
    
    def test_get_associated_items_deduplication(self):
        """Test that get_associated_items deduplicates items"""
        # Add a release item directly to the change (should be deduplicated)
        self.change_with_release.items.add(self.release_item1)
        
        items = self.change_with_release.get_associated_items()
        
        # Should still only have 2 items (deduplicated)
        self.assertEqual(items.count(), 2)
        self.assertIn(self.release_item1, items)
        self.assertIn(self.release_item2, items)
    
    def test_get_associated_items_ordering(self):
        """Test that get_associated_items returns items ordered by ID"""
        items = list(self.change_with_release.get_associated_items())
        
        # Should be ordered by ID
        for i in range(len(items) - 1):
            self.assertLess(items[i].id, items[i + 1].id)
    
    def test_change_detail_view_with_release_items(self):
        """Test that change detail view shows release items"""
        client = Client()
        client.force_login(self.user)
        
        url = reverse('change-detail', kwargs={'id': self.change_with_release.id})
        response = client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that items are in context
        items = response.context['items']
        self.assertEqual(items.count(), 2)
        self.assertIn(self.release_item1, items)
        self.assertIn(self.release_item2, items)
    
    def test_pdf_includes_release_items(self):
        """Test that PDF report includes release items"""
        buffer = BytesIO()
        build_change_pdf(self.change_with_release, buffer)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        # Verify PDF was generated
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        
        # Note: Full PDF content verification would require PDF parsing library
        # For now, we verify that the PDF is generated without errors
    
    def test_pdf_without_items(self):
        """Test that PDF generation works for change without items"""
        buffer = BytesIO()
        build_change_pdf(self.change_without_release, buffer)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        # Should still generate valid PDF
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
