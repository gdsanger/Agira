"""
Tests for OrganisationEmbedProject admin functionality
"""
from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from core.models import Organisation, Project, OrganisationEmbedProject, User
from core.admin import OrganisationEmbedProjectAdmin, OrganisationEmbedProjectInline, OrganisationAdmin


class MockRequest:
    """Mock request object for testing admin actions"""
    def __init__(self, user):
        self.user = user
        # Add session and messages support
        self.session = {}
        self._messages = FallbackStorage(self)
        

class OrganisationEmbedProjectInlineTestCase(TestCase):
    """Test OrganisationEmbedProjectInline functionality"""

    def setUp(self):
        """Set up test data"""
        self.site = AdminSite()
        self.inline = OrganisationEmbedProjectInline(OrganisationEmbedProject, self.site)
        
        # Create test data
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project'
        )

    def test_inline_model(self):
        """Test that inline uses correct model"""
        self.assertEqual(self.inline.model, OrganisationEmbedProject)

    def test_inline_extra(self):
        """Test that inline doesn't add extra blank forms"""
        self.assertEqual(self.inline.extra, 0)

    def test_inline_autocomplete_fields(self):
        """Test that inline uses autocomplete for project"""
        self.assertEqual(self.inline.autocomplete_fields, ['project'])

    def test_inline_readonly_fields(self):
        """Test that inline has correct readonly fields"""
        expected_readonly = ['embed_token_display', 'created_at', 'updated_at']
        self.assertEqual(self.inline.readonly_fields, expected_readonly)

    def test_inline_fields(self):
        """Test that inline displays correct fields"""
        expected_fields = ['project', 'is_enabled', 'embed_token_display', 'updated_at']
        self.assertEqual(self.inline.fields, expected_fields)

    def test_inline_embed_token_display(self):
        """Test that embed_token_display masks the token"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org,
            project=self.project
        )
        
        # Get the masked display
        masked = self.inline.embed_token_display(embed)
        
        # Should contain first 8 and last 8 characters with ... in between
        self.assertIn('...', str(masked))
        self.assertIn(embed.embed_token[:8], str(masked))
        self.assertIn(embed.embed_token[-8:], str(masked))

    def test_inline_embed_token_display_none(self):
        """Test embed_token_display when object is None"""
        masked = self.inline.embed_token_display(None)
        self.assertEqual(masked, '-')


class OrganisationAdminTestCase(TestCase):
    """Test that OrganisationAdmin includes the inline"""

    def setUp(self):
        """Set up test data"""
        self.site = AdminSite()
        self.admin = OrganisationAdmin(Organisation, self.site)

    def test_has_embed_project_inline(self):
        """Test that OrganisationAdmin includes OrganisationEmbedProjectInline"""
        inline_classes = [inline.__class__ for inline in self.admin.get_inline_instances(None)]
        self.assertIn(OrganisationEmbedProjectInline, inline_classes)


class OrganisationEmbedProjectAdminTestCase(TestCase):
    """Test OrganisationEmbedProject admin functionality"""

    def setUp(self):
        """Set up test data"""
        self.site = AdminSite()
        self.admin = OrganisationEmbedProjectAdmin(OrganisationEmbedProject, self.site)
        
        # Create test user (admin)
        self.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password'
        )
        
        # Create test data
        self.org1 = Organisation.objects.create(name='Test Org 1')
        self.org2 = Organisation.objects.create(name='Test Org 2')
        self.project1 = Project.objects.create(
            name='Test Project 1',
            description='Test project description'
        )
        self.project2 = Project.objects.create(
            name='Test Project 2',
            description='Another test project'
        )

    def test_list_display_fields(self):
        """Test that list_display contains the correct fields"""
        expected_fields = ['organisation', 'project', 'is_enabled', 'embed_token_masked', 'updated_at']
        self.assertEqual(self.admin.list_display, expected_fields)

    def test_list_filter_fields(self):
        """Test that list_filter contains the correct fields"""
        expected_filters = ['is_enabled', 'organisation', 'updated_at']
        self.assertEqual(self.admin.list_filter, expected_filters)

    def test_search_fields(self):
        """Test that search_fields contains the correct fields"""
        expected_search = ['organisation__name', 'project__name', 'embed_token']
        self.assertEqual(self.admin.search_fields, expected_search)

    def test_autocomplete_fields(self):
        """Test that autocomplete_fields contains the correct fields"""
        expected_autocomplete = ['organisation', 'project']
        self.assertEqual(self.admin.autocomplete_fields, expected_autocomplete)

    def test_readonly_fields(self):
        """Test that readonly_fields contains the correct fields"""
        expected_readonly = ['embed_token', 'created_at', 'updated_at']
        self.assertEqual(self.admin.readonly_fields, expected_readonly)

    def test_has_rotate_token_action(self):
        """Test that rotate_token action is registered"""
        self.assertIn('rotate_token', self.admin.actions)

    def test_embed_token_masked_display(self):
        """Test that embed_token is properly masked in list view"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        # Get the masked display
        masked = self.admin.embed_token_masked(embed)
        
        # Should contain first 8 and last 8 characters with ... in between
        self.assertIn('...', str(masked))
        self.assertIn(embed.embed_token[:8], str(masked))
        self.assertIn(embed.embed_token[-8:], str(masked))

    def test_embed_token_masked_display_none(self):
        """Test embed_token_masked when token is None"""
        # Create a minimal mock object
        class MockEmbed:
            embed_token = None
        
        masked = self.admin.embed_token_masked(MockEmbed())
        self.assertEqual(masked, '-')

    def test_rotate_token_action(self):
        """Test that rotate_token action regenerates tokens"""
        # Create test embeds
        embed1 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        embed2 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project2
        )
        
        # Store original tokens
        original_token1 = embed1.embed_token
        original_token2 = embed2.embed_token
        
        # Create queryset
        queryset = OrganisationEmbedProject.objects.filter(
            id__in=[embed1.id, embed2.id]
        )
        
        # Create mock request
        request = MockRequest(self.user)
        
        # Execute rotate_token action
        self.admin.rotate_token(request, queryset)
        
        # Reload from database
        embed1.refresh_from_db()
        embed2.refresh_from_db()
        
        # Tokens should be different
        self.assertIsNotNone(embed1.embed_token)
        self.assertIsNotNone(embed2.embed_token)
        self.assertNotEqual(embed1.embed_token, original_token1)
        self.assertNotEqual(embed2.embed_token, original_token2)
        
        # New tokens should be different from each other
        self.assertNotEqual(embed1.embed_token, embed2.embed_token)

    def test_rotate_token_action_single(self):
        """Test that rotate_token action works with single item"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        original_token = embed.embed_token
        
        # Create queryset with single item
        queryset = OrganisationEmbedProject.objects.filter(id=embed.id)
        
        # Create mock request
        request = MockRequest(self.user)
        
        # Execute rotate_token action
        self.admin.rotate_token(request, queryset)
        
        # Reload from database
        embed.refresh_from_db()
        
        # Token should be different
        self.assertNotEqual(embed.embed_token, original_token)

    def test_fieldsets_structure(self):
        """Test that fieldsets are properly structured"""
        fieldsets = self.admin.fieldsets
        
        # Should have 3 sections
        self.assertEqual(len(fieldsets), 3)
        
        # Check section names and fields
        self.assertEqual(fieldsets[0][0], None)  # Main section
        self.assertIn('organisation', fieldsets[0][1]['fields'])
        self.assertIn('project', fieldsets[0][1]['fields'])
        self.assertIn('is_enabled', fieldsets[0][1]['fields'])
        
        self.assertEqual(fieldsets[1][0], 'Token')  # Token section
        self.assertIn('embed_token', fieldsets[1][1]['fields'])
        
        self.assertEqual(fieldsets[2][0], 'Metadata')  # Metadata section
        self.assertIn('created_at', fieldsets[2][1]['fields'])
        self.assertIn('updated_at', fieldsets[2][1]['fields'])
