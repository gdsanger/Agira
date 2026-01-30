"""
Tests for OrganisationEmbedProject model
"""
from django.test import TestCase
from django.db import IntegrityError
from core.models import Organisation, Project, OrganisationEmbedProject


class OrganisationEmbedProjectTestCase(TestCase):
    """Test OrganisationEmbedProject model functionality"""

    def setUp(self):
        """Set up test data"""
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

    def test_embed_token_auto_generation(self):
        """Test that embed_token is automatically generated when not provided"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        # Token should be generated
        self.assertIsNotNone(embed.embed_token)
        self.assertTrue(len(embed.embed_token) > 0)
        # Token should be URL-safe (base64-urlsafe characters)
        # secrets.token_urlsafe produces ~64 chars for 48 bytes
        self.assertGreaterEqual(len(embed.embed_token), 60)

    def test_embed_token_is_unique(self):
        """Test that each embed access gets a unique token"""
        embed1 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        embed2 = OrganisationEmbedProject.objects.create(
            organisation=self.org2,
            project=self.project2
        )
        
        # Tokens should be different
        self.assertNotEqual(embed1.embed_token, embed2.embed_token)

    def test_embed_token_can_be_set_manually(self):
        """Test that embed_token can be set manually"""
        custom_token = 'my-custom-token-12345'
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1,
            embed_token=custom_token
        )
        
        # Should use the provided token
        self.assertEqual(embed.embed_token, custom_token)

    def test_is_enabled_defaults_to_true(self):
        """Test that is_enabled defaults to True"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        self.assertTrue(embed.is_enabled)

    def test_is_enabled_can_be_disabled(self):
        """Test that is_enabled can be set to False"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1,
            is_enabled=False
        )
        
        self.assertFalse(embed.is_enabled)

    def test_unique_constraint_organisation_project(self):
        """Test that (organisation, project) combination must be unique"""
        # Create first embed
        OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        # Try to create duplicate - should raise IntegrityError
        with self.assertRaises(IntegrityError):
            OrganisationEmbedProject.objects.create(
                organisation=self.org1,
                project=self.project1
            )

    def test_multiple_orgs_same_project(self):
        """Test that same project can be embedded by multiple organisations"""
        embed1 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        embed2 = OrganisationEmbedProject.objects.create(
            organisation=self.org2,
            project=self.project1
        )
        
        # Should both exist
        self.assertEqual(embed1.project, embed2.project)
        self.assertNotEqual(embed1.organisation, embed2.organisation)
        # And have different tokens
        self.assertNotEqual(embed1.embed_token, embed2.embed_token)

    def test_same_org_multiple_projects(self):
        """Test that same organisation can embed multiple projects"""
        embed1 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        embed2 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project2
        )
        
        # Should both exist
        self.assertEqual(embed1.organisation, embed2.organisation)
        self.assertNotEqual(embed1.project, embed2.project)
        # And have different tokens
        self.assertNotEqual(embed1.embed_token, embed2.embed_token)

    def test_str_representation(self):
        """Test string representation of model"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        expected = f"{self.org1.name} - {self.project1.name} (enabled)"
        self.assertEqual(str(embed), expected)
        
        # Test disabled state
        embed.is_enabled = False
        embed.save()
        expected_disabled = f"{self.org1.name} - {self.project1.name} (disabled)"
        self.assertEqual(str(embed), expected_disabled)

    def test_cascade_delete_organisation(self):
        """Test that deleting organisation deletes embed access"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        embed_id = embed.id
        
        # Delete organisation
        self.org1.delete()
        
        # Embed should be deleted too
        self.assertFalse(
            OrganisationEmbedProject.objects.filter(id=embed_id).exists()
        )

    def test_cascade_delete_project(self):
        """Test that deleting project deletes embed access"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        embed_id = embed.id
        
        # Delete project
        self.project1.delete()
        
        # Embed should be deleted too
        self.assertFalse(
            OrganisationEmbedProject.objects.filter(id=embed_id).exists()
        )

    def test_related_name_embed_projects(self):
        """Test reverse relation from Organisation to embed projects"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        # Should be accessible via reverse relation
        self.assertIn(embed, self.org1.embed_projects.all())

    def test_related_name_embed_accesses(self):
        """Test reverse relation from Project to embed accesses"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        
        # Should be accessible via reverse relation
        self.assertIn(embed, self.project1.embed_accesses.all())

    def test_token_regeneration(self):
        """Test that token can be regenerated by clearing and saving"""
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1
        )
        original_token = embed.embed_token
        
        # Clear token and save to regenerate
        embed.embed_token = None
        embed.save()
        
        # Should have a new token
        self.assertIsNotNone(embed.embed_token)
        self.assertNotEqual(embed.embed_token, original_token)
        self.assertTrue(len(embed.embed_token) > 0)
