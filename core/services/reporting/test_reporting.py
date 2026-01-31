"""
Tests for Core Report Service
"""

import json
from io import BytesIO
from datetime import datetime

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas

from core.models import ReportDocument, Project, Change, ChangeStatus, RiskLevel
from core.services.reporting import ReportService
from core.services.reporting.registry import (
    register_template, 
    get_template, 
    is_registered,
    list_templates,
    ReportRegistry
)
from reports.templates.change_v1 import ChangeReportV1


User = get_user_model()


class ReportRegistryTestCase(TestCase):
    """Test cases for Report Template Registry"""
    
    def setUp(self):
        """Set up test registry"""
        self.registry = ReportRegistry()
    
    def test_register_template(self):
        """Test registering a template"""
        self.registry.register('test.v1', ChangeReportV1)
        self.assertTrue(self.registry.is_registered('test.v1'))
    
    def test_register_duplicate_raises_error(self):
        """Test that registering duplicate key raises error"""
        self.registry.register('test.v1', ChangeReportV1)
        
        with self.assertRaises(ValueError) as cm:
            self.registry.register('test.v1', ChangeReportV1)
        
        self.assertIn("already registered", str(cm.exception))
    
    def test_get_template(self):
        """Test getting a registered template"""
        self.registry.register('test.v1', ChangeReportV1)
        template = self.registry.get_template('test.v1')
        self.assertIsInstance(template, ChangeReportV1)
    
    def test_get_unregistered_template_raises_error(self):
        """Test that getting unregistered template raises error"""
        with self.assertRaises(KeyError) as cm:
            self.registry.get_template('nonexistent.v1')
        
        self.assertIn("not found", str(cm.exception))
    
    def test_list_templates(self):
        """Test listing all registered templates"""
        self.registry.register('test1.v1', ChangeReportV1)
        self.registry.register('test2.v1', ChangeReportV1)
        
        templates = self.registry.list_templates()
        self.assertEqual(len(templates), 2)
        self.assertIn('test1.v1', templates)
        self.assertIn('test2.v1', templates)


class ReportServiceTestCase(TestCase):
    """Test cases for ReportService"""
    
    def setUp(self):
        """Set up test data"""
        self.service = ReportService()
        
        # Create test user
        self.user = User.objects.create(
            username='testuser',
            email='test@example.com',
            name='Test User'
        )
        
        # Create test project
        self.project = Project.objects.create(
            name='Test Project'
        )
        
        # Create test change
        self.change = Change.objects.create(
            project=self.project,
            title='Test Change',
            description='Test description',
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            created_by=self.user
        )
    
    def test_render_generates_pdf(self):
        """Test that render() generates PDF bytes"""
        context = {
            'title': 'Test Change Report',
            'project_name': 'Test Project',
            'description': 'Test description',
            'status': 'Draft',
            'risk': 'Normal',
            'created_by': 'Test User',
            'created_at': '2024-01-01 12:00:00',
        }
        
        pdf_bytes = self.service.render('change.v1', context)
        
        # Verify PDF bytes
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)
        
        # Verify PDF header
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
    
    def test_render_with_invalid_report_key_raises_error(self):
        """Test that render() raises error for invalid report key"""
        context = {'title': 'Test'}
        
        with self.assertRaises(KeyError):
            self.service.render('invalid.v1', context)
    
    def test_generate_and_store_creates_report(self):
        """Test that generate_and_store() creates ReportDocument"""
        context = {
            'title': self.change.title,
            'project_name': self.project.name,
            'description': self.change.description,
            'status': self.change.status,
            'risk': self.change.risk,
            'created_by': self.user.name,
            'created_at': self.change.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        report = self.service.generate_and_store(
            report_key='change.v1',
            object_type='change',
            object_id=self.change.id,
            context=context,
            created_by=self.user
        )
        
        # Verify report was created
        self.assertIsInstance(report, ReportDocument)
        self.assertEqual(report.report_key, 'change.v1')
        self.assertEqual(report.object_type, 'change')
        self.assertEqual(report.object_id, str(self.change.id))
        self.assertEqual(report.created_by, self.user)
        
        # Verify context was stored
        stored_context = json.loads(report.context_json)
        self.assertEqual(stored_context['title'], context['title'])
        
        # Verify PDF file was saved
        self.assertTrue(report.pdf_file)
        self.assertTrue(report.pdf_file.name.endswith('.pdf'))
        
        # Verify SHA256 hash was calculated
        self.assertEqual(len(report.sha256), 64)
    
    def test_generate_and_store_with_metadata(self):
        """Test generate_and_store() with additional metadata"""
        context = {
            'title': 'Test Report',
            'project_name': self.project.name,
        }
        
        metadata = {
            'template_version': '1.0',
            'custom_field': 'value'
        }
        
        report = self.service.generate_and_store(
            report_key='change.v1',
            object_type='change',
            object_id=self.change.id,
            context=context,
            metadata=metadata
        )
        
        # Verify metadata was stored
        self.assertIsNotNone(report.metadata_json)
        stored_metadata = json.loads(report.metadata_json)
        self.assertEqual(stored_metadata['template_version'], '1.0')
        self.assertEqual(stored_metadata['custom_field'], 'value')
    
    def test_context_snapshot_persistence(self):
        """Test that context is properly saved as snapshot"""
        original_context = {
            'title': 'Original Title',
            'project_name': self.project.name,
            'description': 'Original Description',
            'items': [
                {'title': 'Item 1', 'status': 'Open'},
                {'title': 'Item 2', 'status': 'Closed'}
            ]
        }
        
        report = self.service.generate_and_store(
            report_key='change.v1',
            object_type='change',
            object_id=self.change.id,
            context=original_context,
            created_by=self.user
        )
        
        # Modify the change
        self.change.title = 'Modified Title'
        self.change.description = 'Modified Description'
        self.change.save()
        
        # Retrieve and verify context snapshot
        stored_context = json.loads(report.context_json)
        self.assertEqual(stored_context['title'], 'Original Title')
        self.assertEqual(stored_context['description'], 'Original Description')
        self.assertEqual(len(stored_context['items']), 2)
        
        # Verify the context is independent of the model
        self.assertNotEqual(stored_context['title'], self.change.title)


class ChangeReportV1TestCase(TestCase):
    """Test cases for Change Report Template V1"""
    
    def setUp(self):
        """Set up test data"""
        self.template = ChangeReportV1()
        self.user = User.objects.create(
            username='testuser',
            email='test@example.com',
            name='Test User'
        )
    
    def test_build_story_basic(self):
        """Test building story with basic context"""
        context = {
            'title': 'Test Change',
            'project_name': 'Test Project',
            'description': 'Test description',
            'status': 'Draft',
            'risk': 'Normal',
            'created_by': 'Test User',
            'created_at': '2024-01-01',
        }
        
        story = self.template.build_story(context)
        
        # Verify story is a list
        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)
    
    def test_build_story_with_items(self):
        """Test building story with items table"""
        context = {
            'title': 'Test Change',
            'project_name': 'Test Project',
            'items': [
                {'title': 'Item 1', 'status': 'Open'},
                {'title': 'Item 2', 'status': 'Closed'},
                {'title': 'Item 3', 'status': 'In Progress'},
            ]
        }
        
        story = self.template.build_story(context)
        self.assertIsInstance(story, list)
        
        # Verify that story contains table elements
        from reportlab.platypus import Table
        tables = [item for item in story if isinstance(item, Table)]
        self.assertGreater(len(tables), 0)
    
    def test_build_story_with_approvals(self):
        """Test building story with approvals table"""
        context = {
            'title': 'Test Change',
            'project_name': 'Test Project',
            'approvals': [
                {'approver': 'User 1', 'status': 'Pending', 'decision_at': 'N/A'},
                {'approver': 'User 2', 'status': 'Approved', 'decision_at': '2024-01-01'},
            ]
        }
        
        story = self.template.build_story(context)
        self.assertIsInstance(story, list)
        
        # Verify that story contains table elements
        from reportlab.platypus import Table
        tables = [item for item in story if isinstance(item, Table)]
        self.assertGreater(len(tables), 0)
    
    def test_multi_page_report(self):
        """Test that report works with many items (multi-page)"""
        context = {
            'title': 'Large Change Report',
            'project_name': 'Test Project',
            'description': 'A change with many items',
            'status': 'In Progress',
            'risk': 'High',
            'created_by': 'Test User',
            'created_at': '2024-01-01',
            'items': [
                {'title': f'Item {i}', 'status': 'Open'} 
                for i in range(100)
            ]
        }
        
        service = ReportService()
        pdf_bytes = service.render('change.v1', context)
        
        # Verify PDF was generated
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
    
    def test_draw_header_footer(self):
        """Test that header/footer function works"""
        context = {
            'title': 'Test Change',
            'project_name': 'Test Project',
        }
        
        # Create a mock canvas and doc
        buffer = BytesIO()
        c = pdf_canvas.Canvas(buffer, pagesize=A4)
        
        # Create mock doc object with pagesize attribute
        class MockDoc:
            pagesize = A4
        
        doc = MockDoc()
        
        # This should not raise an error
        self.template.draw_header_footer(c, doc, context)
        
        # Save the canvas to verify it works
        c.save()
        pdf_bytes = buffer.getvalue()
        self.assertGreater(len(pdf_bytes), 0)


class ReportDocumentModelTestCase(TestCase):
    """Test cases for ReportDocument model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create(
            username='testuser',
            email='test@example.com',
            name='Test User'
        )
        
        self.project = Project.objects.create(name='Test Project')
        
        self.change = Change.objects.create(
            project=self.project,
            title='Test Change',
            created_by=self.user
        )
    
    def test_report_document_creation(self):
        """Test creating a ReportDocument"""
        report = ReportDocument.objects.create(
            report_key='change.v1',
            object_type='change',
            object_id=str(self.change.id),
            created_by=self.user,
            context_json='{"test": "data"}',
            sha256='a' * 64
        )
        
        self.assertEqual(report.report_key, 'change.v1')
        self.assertEqual(report.object_type, 'change')
        self.assertEqual(report.created_by, self.user)
    
    def test_report_document_str(self):
        """Test string representation"""
        report = ReportDocument.objects.create(
            report_key='change.v1',
            object_type='change',
            object_id='123',
            context_json='{}',
            sha256='a' * 64
        )
        
        expected = 'change.v1 for change #123'
        self.assertEqual(str(report), expected)
    
    def test_report_document_ordering(self):
        """Test that reports are ordered by created_at descending"""
        report1 = ReportDocument.objects.create(
            report_key='change.v1',
            object_type='change',
            object_id='1',
            context_json='{}',
            sha256='a' * 64
        )
        
        report2 = ReportDocument.objects.create(
            report_key='change.v1',
            object_type='change',
            object_id='2',
            context_json='{}',
            sha256='b' * 64
        )
        
        reports = list(ReportDocument.objects.all())
        self.assertEqual(reports[0], report2)
        self.assertEqual(reports[1], report1)
