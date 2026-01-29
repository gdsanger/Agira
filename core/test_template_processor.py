"""
Tests for mail template processor.
"""

from datetime import datetime, timezone
from django.test import TestCase
from core.models import (
    Item,
    ItemType,
    ItemStatus,
    Project,
    User,
    MailTemplate,
    ProjectStatus,
    Organisation,
    UserOrganisation,
    Release,
    ReleaseStatus,
)
from core.services.mail.template_processor import process_template


class TemplateProcessorTestCase(TestCase):
    """Test cases for template processor"""
    
    def setUp(self):
        """Set up test data"""
        # Create a project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        # Create users
        self.requester = User.objects.create_user(
            username='requester',
            email='requester@example.com',
            password='pass123'
        )
        self.requester.name = 'John Requester'
        self.requester.save()
        
        self.assignee = User.objects.create_user(
            username='assignee',
            email='assignee@example.com',
            password='pass123'
        )
        self.assignee.name = 'Jane Assignee'
        self.assignee.save()
        
        # Create template with variables
        self.template = MailTemplate.objects.create(
            key='test-template',
            subject='Issue {{ issue.title }} - {{ issue.status }}',
            message='Project: {{ issue.project }}\nType: {{ issue.type }}\nRequester: {{ issue.requester }}\nAssigned: {{ issue.assigned_to }}'
        )
        
        # Create item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Bug',
            description='Bug description',
            type=self.item_type,
            status=ItemStatus.WORKING,
            requester=self.requester,
            assigned_to=self.assignee
        )
    
    def test_process_template_replaces_all_variables(self):
        """Test that all template variables are replaced correctly"""
        result = process_template(self.template, self.item)
        
        # Check subject
        self.assertIn('Test Bug', result['subject'])
        self.assertIn('Working', result['subject'])
        
        # Check message
        self.assertIn('Test Project', result['message'])
        self.assertIn('Bug', result['message'])
        self.assertIn('John Requester', result['message'])
        self.assertIn('Jane Assignee', result['message'])
    
    def test_process_template_with_missing_optional_fields(self):
        """Test processing when optional fields are None"""
        # Create item without requester and assigned_to
        item = Item.objects.create(
            project=self.project,
            title='Minimal Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        template = MailTemplate.objects.create(
            key='minimal-template',
            subject='{{ issue.title }}',
            message='Requester: {{ issue.requester }}, Assigned: {{ issue.assigned_to }}'
        )
        
        result = process_template(template, item)
        
        # Should replace with empty strings, not fail
        self.assertEqual(result['subject'], 'Minimal Item')
        self.assertIn('Requester: , Assigned:', result['message'])
    
    def test_process_template_preserves_non_variable_text(self):
        """Test that text without variables is preserved"""
        template = MailTemplate.objects.create(
            key='mixed-template',
            subject='Status Update',
            message='This is a plain text message without variables.'
        )
        
        result = process_template(template, self.item)
        
        self.assertEqual(result['subject'], 'Status Update')
        self.assertEqual(result['message'], 'This is a plain text message without variables.')
    
    def test_process_template_handles_html(self):
        """Test that HTML in message is preserved"""
        template = MailTemplate.objects.create(
            key='html-template',
            subject='{{ issue.title }}',
            message='<h1>{{ issue.title }}</h1><p>Status: {{ issue.status }}</p>'
        )
        
        result = process_template(template, self.item)
        
        self.assertIn('<h1>Test Bug</h1>', result['message'])
        self.assertIn('<p>Status: 🚧 Working</p>', result['message'])
    
    def test_process_template_status_display(self):
        """Test that status uses display name with emoji"""
        result = process_template(self.template, self.item)
        
        # Status display should include emoji
        self.assertIn('🚧 Working', result['subject'])
    
    def test_process_template_returns_dict_with_keys(self):
        """Test that result has expected keys"""
        result = process_template(self.template, self.item)
        
        self.assertIn('subject', result)
        self.assertIn('message', result)
        self.assertEqual(len(result), 2)
    
    def test_process_template_with_description(self):
        """Test that issue description is replaced correctly"""
        template = MailTemplate.objects.create(
            key='description-template',
            subject='{{ issue.title }}',
            message='Description: {{ issue.description }}'
        )
        
        result = process_template(template, self.item)
        
        self.assertIn('Bug description', result['message'])
    
    def test_process_template_with_organisation(self):
        """Test that requester's primary organisation is replaced correctly"""
        # Create organisation
        org = Organisation.objects.create(name='Test Organisation')
        
        # Link requester to organisation as primary
        UserOrganisation.objects.create(
            user=self.requester,
            organisation=org,
            is_primary=True
        )
        
        template = MailTemplate.objects.create(
            key='organisation-template',
            subject='{{ issue.title }}',
            message='Organisation: {{ issue.organisation }}'
        )
        
        result = process_template(template, self.item)
        
        self.assertIn('Test Organisation', result['message'])
    
    def test_process_template_with_organisation_no_primary(self):
        """Test that organisation variable is empty when requester has no primary org"""
        # Create organisation but don't set as primary
        org = Organisation.objects.create(name='Test Organisation')
        UserOrganisation.objects.create(
            user=self.requester,
            organisation=org,
            is_primary=False
        )
        
        template = MailTemplate.objects.create(
            key='organisation-template-2',
            subject='{{ issue.title }}',
            message='Organisation: {{ issue.organisation }}'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty organisation
        self.assertIn('Organisation: ', result['message'])
        self.assertNotIn('Test Organisation', result['message'])
    
    def test_process_template_with_solution_release_full_info(self):
        """Test that solution release includes name, version and date"""
        # Create release with all fields
        release = Release.objects.create(
            project=self.project,
            name='Sprint 42',
            version='1.5.0',
            update_date=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
            status=ReleaseStatus.PLANNED
        )
        
        self.item.solution_release = release
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='release-template',
            subject='{{ issue.title }}',
            message='Release: {{ issue.solution_release }}'
        )
        
        result = process_template(template, self.item)
        
        # Should include name, version and date
        self.assertIn('Sprint 42', result['message'])
        self.assertIn('Version 1.5.0', result['message'])
        self.assertIn('Planned: 2026-03-15', result['message'])
    
    def test_process_template_with_solution_release_only_name(self):
        """Test that solution release works with only name"""
        # Create release with only name
        release = Release.objects.create(
            project=self.project,
            name='Sprint 42',
            version='',
            update_date=None,
            status=ReleaseStatus.PLANNED
        )
        
        self.item.solution_release = release
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='release-template-2',
            subject='{{ issue.title }}',
            message='Release: {{ issue.solution_release }}'
        )
        
        result = process_template(template, self.item)
        
        # Should include only name
        self.assertIn('Release: Sprint 42', result['message'])
        self.assertNotIn('Version', result['message'])
        self.assertNotIn('Planned:', result['message'])
    
    def test_process_template_with_solution_release_name_and_version(self):
        """Test that solution release works with name and version only"""
        # Create release with name and version
        release = Release.objects.create(
            project=self.project,
            name='Sprint 42',
            version='1.5.0',
            update_date=None,
            status=ReleaseStatus.PLANNED
        )
        
        self.item.solution_release = release
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='release-template-3',
            subject='{{ issue.title }}',
            message='Release: {{ issue.solution_release }}'
        )
        
        result = process_template(template, self.item)
        
        # Should include name and version
        self.assertIn('Sprint 42 - Version 1.5.0', result['message'])
        self.assertNotIn('Planned:', result['message'])
