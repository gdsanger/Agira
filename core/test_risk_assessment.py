"""
Tests for Change Risk Assessment functionality
"""

from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Change, ChangeStatus, Project, Organisation, User, RiskLevel
)


class ChangeRiskAssessmentTestCase(TestCase):
    """Test cases for AI-powered risk assessment"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass",
            name="Test User"
        )
        
        # Create project and organisation
        self.org = Organisation.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project")
        self.project.clients.add(self.org)
        
        # Create change
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            description="Test description",
            risk_description="This change will modify the email notification system.",
            mitigation="Set flags correctly before deployment.",
            rollback_plan="Disable the worker if issues occur.",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.LOW,
            created_by=self.user
        )
        
        # Login
        self.client.login(username="testuser", password="testpass")
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_json_response(self, mock_execute_agent):
        """Test risk assessment with JSON response from agent"""
        # Mock AI agent JSON response
        json_response = '''{
  "RiskClass": "normal",
  "RiskClassReason": "Der Change betrifft einen automatisierten E-Mail-Versand an eine große Empfängergruppe und kann bei inkonsistenten Flags zu massenhaften, unerwünschten Benachrichtigungen führen. Auch wenn keine hochschulrechtlichen oder sicherheitskritischen Auswirkungen erwartet werden und die Funktion bereits an anderen Hochschulen stabil läuft, besteht ein relevantes Reputations- und Betriebsrisiko (Irritation/Supportaufwand). Durch die klare Mitigation (Flags initial korrekt setzen) und den einfachen Rollback (Deaktivierung des Worker-Teils) ist das Risiko beherrschbar, weshalb die Einstufung als normal angemessen ist."
}'''
        mock_execute_agent.return_value = json_response
        
        # Call assess risk endpoint
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['risk_class'], RiskLevel.NORMAL)
        
        # Verify agent was called
        mock_execute_agent.assert_called_once()
        
        # Verify database was updated correctly
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk, RiskLevel.NORMAL)
        
        # Verify only RiskClassReason is in the description, not the full JSON
        self.assertIn("Der Change betrifft", self.change.risk_description)
        self.assertIn("AI Risk Assessment", self.change.risk_description)
        # The JSON structure should NOT be in the description
        self.assertNotIn('"RiskClass"', self.change.risk_description)
        self.assertNotIn('"RiskClassReason"', self.change.risk_description)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_json_high_risk(self, mock_execute_agent):
        """Test risk assessment with high risk class"""
        json_response = '''{
  "RiskClass": "high",
  "RiskClassReason": "This change affects critical infrastructure and requires immediate attention."
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['risk_class'], RiskLevel.HIGH)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk, RiskLevel.HIGH)
        self.assertIn("critical infrastructure", self.change.risk_description)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_json_very_high_risk(self, mock_execute_agent):
        """Test risk assessment with very high risk class"""
        json_response = '''{
  "RiskClass": "very high",
  "RiskClassReason": "This change could cause system-wide outage."
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['risk_class'], RiskLevel.VERY_HIGH)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk, RiskLevel.VERY_HIGH)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_json_low_risk(self, mock_execute_agent):
        """Test risk assessment with low risk class"""
        json_response = '''{
  "RiskClass": "low",
  "RiskClassReason": "Minor documentation update with no functional impact."
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['risk_class'], RiskLevel.LOW)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk, RiskLevel.LOW)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_non_json_fallback(self, mock_execute_agent):
        """Test risk assessment falls back to text parsing for non-JSON responses"""
        # Mock agent with non-JSON text response
        text_response = "This is a high risk change that requires careful consideration."
        mock_execute_agent.return_value = text_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        # Should still work with fallback text parsing
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # "high" should be detected in text
        self.assertEqual(data['risk_class'], RiskLevel.HIGH)
        
        # Verify the full text is used as the reason
        self.change.refresh_from_db()
        self.assertIn(text_response, self.change.risk_description)
        # Verify AI marker is present
        self.assertIn("## AI Risk Assessment", self.change.risk_description)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_german_risk_classes(self, mock_execute_agent):
        """Test that German risk class names are normalized correctly"""
        json_response = '''{
  "RiskClass": "sehr hoch",
  "RiskClassReason": "Sehr hohes Risiko für das System."
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # "sehr hoch" should map to VERY_HIGH
        self.assertEqual(data['risk_class'], RiskLevel.VERY_HIGH)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_updates_existing_ai_assessment(self, mock_execute_agent):
        """Test that running assessment again updates existing AI section"""
        # First assessment
        json_response_1 = '''{
  "RiskClass": "low",
  "RiskClassReason": "Initial assessment shows low risk."
}'''
        mock_execute_agent.return_value = json_response_1
        
        url = reverse('change-assess-risk', args=[self.change.id])
        self.client.post(url)
        
        # Verify first assessment
        self.change.refresh_from_db()
        self.assertIn("Initial assessment", self.change.risk_description)
        
        # Second assessment with different result
        json_response_2 = '''{
  "RiskClass": "high",
  "RiskClassReason": "Updated assessment shows high risk."
}'''
        mock_execute_agent.return_value = json_response_2
        
        self.client.post(url)
        
        # Verify second assessment replaces first
        self.change.refresh_from_db()
        self.assertIn("Updated assessment", self.change.risk_description)
        # Old assessment should not be there
        self.assertNotIn("Initial assessment", self.change.risk_description)
        # Should still have only one "AI Risk Assessment" marker
        self.assertEqual(self.change.risk_description.count("## AI Risk Assessment"), 1)
    
    def test_assess_risk_requires_content(self):
        """Test that assessment requires at least one field with content"""
        # Create change with all empty fields
        empty_change = Change.objects.create(
            project=self.project,
            title="Empty Change",
            risk_description="",
            mitigation="",
            rollback_plan="",
            created_by=self.user
        )
        
        url = reverse('change-assess-risk', args=[empty_change.id])
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('content', data['error'].lower())
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_unrecognized_risk_class(self, mock_execute_agent):
        """Test that unrecognized risk classes default to NORMAL"""
        json_response = '''{
  "RiskClass": "medium",
  "RiskClassReason": "This is a medium risk change."
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # Unrecognized value should default to NORMAL
        self.assertEqual(data['risk_class'], RiskLevel.NORMAL)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk, RiskLevel.NORMAL)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_only_risk_class(self, mock_execute_agent):
        """Test JSON with only RiskClass field"""
        json_response = '''{
  "RiskClass": "high"
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['risk_class'], RiskLevel.HIGH)
        
        # When only RiskClass is present, the full JSON should be used as reason
        self.change.refresh_from_db()
        self.assertIn(json_response.strip(), self.change.risk_description)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_only_risk_class_reason(self, mock_execute_agent):
        """Test JSON with only RiskClassReason field"""
        json_response = '''{
  "RiskClassReason": "This change needs attention but has no risk class specified."
}'''
        mock_execute_agent.return_value = json_response
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # Should default to NORMAL when RiskClass is missing
        self.assertEqual(data['risk_class'], RiskLevel.NORMAL)
        
        # Only RiskClassReason should be in description
        self.change.refresh_from_db()
        self.assertIn("This change needs attention", self.change.risk_description)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_assess_risk_with_malformed_json(self, mock_execute_agent):
        """Test that malformed JSON falls back to text parsing"""
        malformed_json = '{"RiskClass": "high"'  # Missing closing brace
        mock_execute_agent.return_value = malformed_json
        
        url = reverse('change-assess-risk', args=[self.change.id])
        response = self.client.post(url)
        
        # Should still work with fallback text parsing
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # "high" should be detected in text via fallback
        self.assertEqual(data['risk_class'], RiskLevel.HIGH)
        
        # Full malformed text should be used as reason
        self.change.refresh_from_db()
        self.assertIn(malformed_json, self.change.risk_description)
