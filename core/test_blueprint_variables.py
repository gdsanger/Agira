"""
Tests for blueprint variable utility functions.
"""
from django.test import TestCase
from core.utils.blueprint_variables import extract_variables, replace_variables, validate_variables


class BlueprintVariableUtilsTestCase(TestCase):
    """Test cases for blueprint variable utility functions"""
    
    def test_extract_variables_simple(self):
        """Test extracting variables from simple text"""
        text = "Hello {{ name }}, welcome to {{ project }}!"
        variables = extract_variables(text)
        self.assertEqual(variables, ['name', 'project'])
    
    def test_extract_variables_no_variables(self):
        """Test extracting variables from text without variables"""
        text = "This is plain text without any variables"
        variables = extract_variables(text)
        self.assertEqual(variables, [])
    
    def test_extract_variables_empty_text(self):
        """Test extracting variables from empty text"""
        variables = extract_variables("")
        self.assertEqual(variables, [])
        
        variables = extract_variables(None)
        self.assertEqual(variables, [])
    
    def test_extract_variables_duplicate(self):
        """Test that duplicate variables are only returned once"""
        text = "{{ name }} and {{ name }} again, plus {{ project }}"
        variables = extract_variables(text)
        self.assertEqual(variables, ['name', 'project'])
    
    def test_extract_variables_with_spaces(self):
        """Test extracting variables with spaces around the name"""
        text = "{{name}} and {{ name }} and {{  name  }}"
        variables = extract_variables(text)
        self.assertEqual(variables, ['name'])
    
    def test_extract_variables_with_underscores_and_hyphens(self):
        """Test extracting variables with underscores and hyphens"""
        text = "{{ project_name }} and {{ risk-level }}"
        variables = extract_variables(text)
        self.assertEqual(variables, ['project_name', 'risk-level'])
    
    def test_replace_variables_simple(self):
        """Test replacing variables in simple text"""
        text = "Hello {{ name }}!"
        result = replace_variables(text, {"name": "John"})
        self.assertEqual(result, "Hello John!")
    
    def test_replace_variables_multiple(self):
        """Test replacing multiple variables"""
        text = "{{ greeting }} {{ name }}, welcome to {{ project }}!"
        result = replace_variables(text, {
            "greeting": "Hi",
            "name": "Alice",
            "project": "Agira"
        })
        self.assertEqual(result, "Hi Alice, welcome to Agira!")
    
    def test_replace_variables_with_spaces(self):
        """Test replacing variables with different spacing"""
        text = "{{name}} and {{ name }} and {{  name  }}"
        result = replace_variables(text, {"name": "Bob"})
        self.assertEqual(result, "Bob and Bob and Bob")
    
    def test_replace_variables_partial(self):
        """Test replacing only some variables"""
        text = "{{ greeting }} {{ name }}"
        result = replace_variables(text, {"greeting": "Hello"})
        # Unreplaced variables should remain as-is
        self.assertEqual(result, "Hello {{ name }}")
    
    def test_replace_variables_empty_text(self):
        """Test replacing variables in empty text"""
        result = replace_variables("", {"name": "John"})
        self.assertEqual(result, "")
        
        result = replace_variables(None, {"name": "John"})
        self.assertEqual(result, "")
    
    def test_replace_variables_no_variables(self):
        """Test replacing when no variables dict provided"""
        text = "Hello {{ name }}!"
        result = replace_variables(text, {})
        self.assertEqual(result, "Hello {{ name }}!")
        
        result = replace_variables(text, None)
        self.assertEqual(result, "Hello {{ name }}!")
    
    def test_validate_variables_all_provided(self):
        """Test validation when all variables are provided"""
        text = "{{ greeting }} {{ name }}"
        is_valid, missing = validate_variables(text, {
            "greeting": "Hello",
            "name": "Alice"
        })
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])
    
    def test_validate_variables_missing(self):
        """Test validation when some variables are missing"""
        text = "{{ greeting }} {{ name }} {{ project }}"
        is_valid, missing = validate_variables(text, {
            "greeting": "Hello"
        })
        self.assertFalse(is_valid)
        self.assertEqual(set(missing), {"name", "project"})
    
    def test_validate_variables_empty_value(self):
        """Test validation when variable value is empty"""
        text = "{{ name }}"
        is_valid, missing = validate_variables(text, {
            "name": ""
        })
        self.assertFalse(is_valid)
        self.assertEqual(missing, ["name"])
    
    def test_validate_variables_no_variables(self):
        """Test validation when text has no variables"""
        text = "Plain text"
        is_valid, missing = validate_variables(text, {})
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])
    
    def test_complex_markdown_scenario(self):
        """Test with realistic markdown blueprint content"""
        text = """# {{ feature_name }}

## Description
This feature will add {{ feature_description }} to the {{ project_name }} project.

## Acceptance Criteria
- [ ] {{ criterion_1 }}
- [ ] {{ criterion_2 }}

## Technical Notes
Risk Level: {{ risk_level }}
"""
        
        # Extract variables
        variables = extract_variables(text)
        self.assertEqual(set(variables), {
            'feature_name', 'feature_description', 'project_name',
            'criterion_1', 'criterion_2', 'risk_level'
        })
        
        # Replace variables
        values = {
            'feature_name': 'User Authentication',
            'feature_description': 'OAuth2 support',
            'project_name': 'Agira',
            'criterion_1': 'Users can login with Google',
            'criterion_2': 'Users can login with GitHub',
            'risk_level': 'High'
        }
        result = replace_variables(text, values)
        
        self.assertIn('User Authentication', result)
        self.assertIn('OAuth2 support', result)
        self.assertIn('Agira', result)
        self.assertNotIn('{{', result)  # No variables left
        self.assertNotIn('}}', result)
        
        # Validate
        is_valid, missing = validate_variables(text, values)
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])
