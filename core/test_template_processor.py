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
    
    def test_process_template_with_solution_description(self):
        """Test that solution description is replaced correctly"""
        # Set solution description on item
        self.item.solution_description = 'This is the solution to fix the bug'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-description-template',
            subject='{{ issue.title }}',
            message='Solution: {{ issue.solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        self.assertIn('This is the solution to fix the bug', result['message'])
    
    def test_process_template_with_empty_solution_description(self):
        """Test that empty solution description is replaced with empty string"""
        # Ensure solution description is empty
        self.item.solution_description = ''
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-description-empty-template',
            subject='{{ issue.title }}',
            message='Solution: {{ issue.solution_description }} - End'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty string, not null or placeholder
        self.assertIn('Solution:  - End', result['message'])
        self.assertNotIn('{{ issue.solution_description }}', result['message'])
    
    def test_process_template_with_html_in_solution_description(self):
        """Test that HTML in solution description is escaped"""
        # Set solution description with HTML
        self.item.solution_description = '<script>alert("XSS")</script>Fixed the bug'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-description-html-template',
            subject='{{ issue.title }}',
            message='Solution: {{ issue.solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # HTML should be escaped/stripped by sanitization
        self.assertNotIn('<script>', result['message'])
        self.assertIn('Fixed the bug', result['message'])
    
    def test_process_template_with_non_prefixed_solution_description(self):
        """Test that {{ solution_description }} (without issue. prefix) works"""
        # Set solution description on item
        self.item.solution_description = 'This is the solution without prefix'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-description-no-prefix-template',
            subject='{{ issue.title }}',
            message='Solution: {{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        self.assertIn('This is the solution without prefix', result['message'])
        self.assertNotIn('{{ solution_description }}', result['message'])
    
    def test_process_template_with_empty_non_prefixed_solution_description(self):
        """Test that empty {{ solution_description }} is replaced with empty string"""
        # Ensure solution description is empty
        self.item.solution_description = ''
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-description-no-prefix-empty-template',
            subject='{{ issue.title }}',
            message='Solution: {{ solution_description }} - End'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty string, not placeholder
        self.assertIn('Solution:  - End', result['message'])
        self.assertNotIn('{{ solution_description }}', result['message'])
    
    def test_process_template_with_both_prefixed_and_non_prefixed(self):
        """Test that both {{ issue.solution_description }} and {{ solution_description }} work in same template"""
        # Set solution description on item
        self.item.solution_description = 'Test solution'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-description-both-template',
            subject='{{ issue.title }}',
            message='Prefixed: {{ issue.solution_description }}, Non-prefixed: {{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Both should be replaced with the same HTML value (wrapped in <p>)
        self.assertIn('Prefixed: <p>Test solution</p>, Non-prefixed: <p>Test solution</p>', result['message'])
        self.assertNotIn('{{', result['message'])
    
    def test_solution_description_markdown_bold_conversion(self):
        """Test that Markdown bold syntax is converted to HTML"""
        # Set solution description with Markdown bold
        self.item.solution_description = '**Fix**'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-bold-template',
            subject='{{ issue.title }}',
            message='Solution: {{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Should convert **Fix** to <strong>Fix</strong>
        self.assertIn('<strong>Fix</strong>', result['message'])
        self.assertNotIn('**Fix**', result['message'])
    
    def test_solution_description_markdown_list_conversion(self):
        """Test that Markdown list syntax is converted to HTML"""
        # Set solution description with Markdown list (needs blank line before list)
        self.item.solution_description = '''**Fix**

- Schritt 1
- Schritt 2'''
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-list-template',
            subject='{{ issue.title }}',
            message='Solution: {{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Should convert to HTML list
        self.assertIn('<strong>Fix</strong>', result['message'])
        self.assertIn('<ul>', result['message'])
        self.assertIn('<li>Schritt 1</li>', result['message'])
        self.assertIn('<li>Schritt 2</li>', result['message'])
        self.assertIn('</ul>', result['message'])
        # Should not contain raw Markdown
        self.assertNotIn('- Schritt', result['message'])
    
    def test_solution_description_markdown_link_conversion(self):
        """Test that Markdown link syntax is converted to HTML"""
        # Set solution description with Markdown link
        self.item.solution_description = 'See [documentation](https://example.com)'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-link-template',
            subject='{{ issue.title }}',
            message='{{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Should convert to HTML link
        self.assertIn('<a href="https://example.com">documentation</a>', result['message'])
        self.assertNotIn('[documentation]', result['message'])
    
    def test_solution_description_markdown_heading_conversion(self):
        """Test that Markdown heading syntax is converted to HTML"""
        # Set solution description with Markdown heading
        self.item.solution_description = '## Solution Steps'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-heading-template',
            subject='{{ issue.title }}',
            message='{{ issue.solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Should convert ## to <h2>
        self.assertIn('<h2>Solution Steps</h2>', result['message'])
        self.assertNotIn('##', result['message'])
    
    def test_solution_description_markdown_code_conversion(self):
        """Test that Markdown code syntax is converted to HTML"""
        # Set solution description with Markdown code
        self.item.solution_description = 'Run `npm install` to fix'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-code-template',
            subject='{{ issue.title }}',
            message='{{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Should convert to HTML code
        self.assertIn('<code>npm install</code>', result['message'])
        # Backticks should be removed
        self.assertNotIn('`npm install`', result['message'])
    
    def test_solution_description_markdown_complex_example(self):
        """Test complex Markdown example from issue reproduction"""
        # Exact example from the issue (needs blank line before list)
        self.item.solution_description = '''**Fix**

- Schritt 1
- Schritt 2'''
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-complex-template',
            subject='{{ issue.title }}',
            message='<h1>Solution</h1>{{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Should have HTML, not Markdown
        self.assertIn('<h1>Solution</h1>', result['message'])
        self.assertIn('<strong>Fix</strong>', result['message'])
        self.assertIn('<ul>', result['message'])
        self.assertIn('<li>Schritt 1</li>', result['message'])
        self.assertIn('<li>Schritt 2</li>', result['message'])
        # Should NOT have Markdown syntax
        self.assertNotIn('**Fix**', result['message'])
        self.assertNotIn('- Schritt', result['message'])
    
    def test_solution_description_empty_markdown(self):
        """Test that empty solution description returns empty string"""
        # Empty solution description
        self.item.solution_description = ''
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-empty-template',
            subject='{{ issue.title }}',
            message='Start {{ solution_description }} End'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty string between Start and End
        self.assertIn('Start  End', result['message'])
    
    def test_solution_description_none_markdown(self):
        """Test that None solution description returns empty string"""
        # Set to empty string instead of None (field has NOT NULL constraint)
        self.item.solution_description = ''
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-none-template',
            subject='{{ issue.title }}',
            message='Start {{ issue.solution_description }} End'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty string between Start and End
        self.assertIn('Start  End', result['message'])
    
    def test_solution_description_xss_protection(self):
        """Test that XSS attempts in Markdown are sanitized"""
        # Attempt XSS via Markdown
        self.item.solution_description = '<script>alert("XSS")</script>**Bold text**'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-markdown-xss-template',
            subject='{{ issue.title }}',
            message='{{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Script tags should be removed (even if text content remains, the dangerous tags are gone)
        self.assertNotIn('<script>', result['message'])
        self.assertNotIn('</script>', result['message'])
        # Valid Markdown should be converted
        self.assertIn('<strong>Bold text</strong>', result['message'])
    
    def test_other_template_variables_still_escaped(self):
        """Test that other template variables are still HTML-escaped"""
        # Set title with HTML
        self.item.title = 'Test <script>alert("XSS")</script> Bug'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='other-variables-escaped-template',
            subject='{{ issue.title }}',
            message='Title: {{ issue.title }}'
        )
        
        result = process_template(template, self.item)
        
        # Title should be escaped
        self.assertIn('&lt;script&gt;', result['subject'])
        self.assertIn('&lt;script&gt;', result['message'])
        self.assertNotIn('<script>', result['message'])
    
    def test_solution_description_in_subject_plain_text(self):
        """Test that solution_description in subject is plain text (no HTML tags)"""
        # Set solution description with Markdown
        self.item.solution_description = '**Fix**: See [link](http://example.com)'
        self.item.save()
        
        template = MailTemplate.objects.create(
            key='solution-in-subject-template',
            subject='Fix: {{ solution_description }}',
            message='{{ solution_description }}'
        )
        
        result = process_template(template, self.item)
        
        # Subject should have plain text (no HTML tags)
        self.assertNotIn('<strong>', result['subject'])
        self.assertNotIn('<a href=', result['subject'])
        self.assertNotIn('<p>', result['subject'])
        # Should contain text content (without Markdown syntax or HTML tags)
        self.assertIn('Fix', result['subject'])
        self.assertIn('link', result['subject'])
        
        # Message should have HTML
        self.assertIn('<strong>Fix</strong>', result['message'])
        self.assertIn('<a href="http://example.com">link</a>', result['message'])

    
    def test_requester_first_name_extraction_normal_name(self):
        """Test that first name is extracted correctly from 'Max Mustermann'"""
        # Set requester with normal two-part name
        self.requester.name = 'Max Mustermann'
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='first-name-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should extract "Max" as first name
        self.assertEqual(result['subject'], 'Hallo Max')
        self.assertIn('<p>Hallo Max,</p>', result['message'])
    
    def test_requester_first_name_single_name(self):
        """Test that single name 'Madonna' remains unchanged"""
        # Set requester with single name (no whitespace)
        self.requester.name = 'Madonna'
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='single-name-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should use entire name since there's no whitespace
        self.assertEqual(result['subject'], 'Hallo Madonna')
        self.assertIn('<p>Hallo Madonna,</p>', result['message'])
    
    def test_requester_first_name_multiple_whitespace(self):
        """Test that first name is extracted correctly with multiple whitespaces"""
        # Set requester with leading/trailing whitespace and multiple spaces
        self.requester.name = '  Anna   Maria  Muster '
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='whitespace-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should trim and extract "Anna" as first name
        self.assertEqual(result['subject'], 'Hallo Anna')
        self.assertIn('<p>Hallo Anna,</p>', result['message'])
    
    def test_requester_first_name_empty_string(self):
        """Test that empty requester name results in empty first name"""
        # Set requester with empty name
        self.requester.name = ''
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='empty-name-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty string
        self.assertEqual(result['subject'], 'Hallo ')
        self.assertIn('<p>Hallo ,</p>', result['message'])
    
    def test_requester_first_name_no_requester(self):
        """Test that missing requester results in empty first name"""
        # Create item without requester
        item = Item.objects.create(
            project=self.project,
            title='No Requester Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        template = MailTemplate.objects.create(
            key='no-requester-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, item)
        
        # Should have empty string
        self.assertEqual(result['subject'], 'Hallo ')
        self.assertIn('<p>Hallo ,</p>', result['message'])
    
    def test_requester_first_name_with_tabs_and_newlines(self):
        """Test that first name extraction handles tabs and newlines as whitespace"""
        # Set requester with various whitespace characters
        self.requester.name = 'John\t\nDoe'
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='tab-newline-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should extract "John" (before tab/newline)
        self.assertEqual(result['subject'], 'Hallo John')
        self.assertIn('<p>Hallo John,</p>', result['message'])
    
    def test_requester_first_name_html_escaping(self):
        """Test that first name is HTML-escaped to prevent XSS"""
        # Set requester with HTML in name
        self.requester.name = '<script>alert("XSS")</script> Max'
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='xss-first-name-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should escape HTML in first name
        self.assertIn('&lt;script&gt;', result['subject'])
        self.assertNotIn('<script>', result['message'])
    
    def test_requester_full_name_still_works(self):
        """Test that {{ issue.requester }} still returns full name"""
        # Set requester with full name
        self.requester.name = 'Max Mustermann'
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='full-name-template',
            subject='{{ issue.requester }}',
            message='<p>Full: {{ issue.requester }}, First: {{ issue.requester_first_name }}</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should have full name in subject
        self.assertEqual(result['subject'], 'Max Mustermann')
        # Should have both full and first name in message
        self.assertIn('<p>Full: Max Mustermann, First: Max</p>', result['message'])
    
    def test_requester_first_name_only_whitespace(self):
        """Test that name with only whitespace results in empty first name"""
        # Set requester with only whitespace
        self.requester.name = '   \t\n  '
        self.requester.save()
        
        template = MailTemplate.objects.create(
            key='whitespace-only-template',
            subject='Hallo {{ issue.requester_first_name }}',
            message='<p>Hallo {{ issue.requester_first_name }},</p>'
        )
        
        result = process_template(template, self.item)
        
        # Should have empty string after trim
        self.assertEqual(result['subject'], 'Hallo ')
        self.assertIn('<p>Hallo ,</p>', result['message'])
