"""
Tests for blueprint variable utility functions.
"""
from django.test import TestCase
from core.utils.blueprint_variables import (
    extract_variables, 
    replace_variables, 
    validate_variables,
    extract_variables_from_multiple,
    validate_variables_from_multiple
)


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
    
    def test_extract_variables_from_multiple(self):
        """Test extracting variables from multiple text strings"""
        texts = ["{{ name }}", "{{ age }} and {{ name }}"]
        variables = extract_variables_from_multiple(texts)
        self.assertEqual(variables, ['name', 'age'])
    
    def test_extract_variables_from_multiple_with_title_and_description(self):
        """Test extracting variables from title and description"""
        title = "Error in {{ entity }}"
        description = "Please check {{ entity }} in {{ environment }}. {{ entity }} occurs multiple times."
        variables = extract_variables_from_multiple([title, description])
        # Should get entity first from title, then environment from description
        self.assertEqual(variables, ['entity', 'environment'])
    
    def test_extract_variables_from_multiple_empty_texts(self):
        """Test extracting variables from empty texts"""
        variables = extract_variables_from_multiple([])
        self.assertEqual(variables, [])
        
        variables = extract_variables_from_multiple(["", None, ""])
        self.assertEqual(variables, [])
    
    def test_extract_variables_from_multiple_only_in_title(self):
        """Test extracting variables that only appear in title"""
        title = "{{ feature_name }}"
        description = "This is a plain description without variables."
        variables = extract_variables_from_multiple([title, description])
        self.assertEqual(variables, ['feature_name'])
    
    def test_extract_variables_from_multiple_only_in_description(self):
        """Test extracting variables that only appear in description"""
        title = "Simple Title"
        description = "Description with {{ variable1 }} and {{ variable2 }}"
        variables = extract_variables_from_multiple([title, description])
        self.assertEqual(variables, ['variable1', 'variable2'])
    
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
    
    def test_validate_variables_from_multiple_all_provided(self):
        """Test validation from multiple texts when all variables provided"""
        texts = ["{{ name }}", "{{ age }}"]
        is_valid, missing = validate_variables_from_multiple(texts, {
            "name": "John",
            "age": "30"
        })
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])
    
    def test_validate_variables_from_multiple_missing(self):
        """Test validation from multiple texts with missing variables"""
        texts = ["{{ greeting }}", "{{ name }}"]
        is_valid, missing = validate_variables_from_multiple(texts, {
            "greeting": "Hi"
        })
        self.assertFalse(is_valid)
        self.assertEqual(missing, ["name"])
    
    def test_validate_variables_from_multiple_title_and_description(self):
        """Test validation from title and description"""
        title = "Error in {{ entity }}"
        description = "Check {{ entity }} in {{ environment }}"
        
        # All provided
        is_valid, missing = validate_variables_from_multiple(
            [title, description],
            {"entity": "Database", "environment": "Production"}
        )
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])
        
        # Missing environment
        is_valid, missing = validate_variables_from_multiple(
            [title, description],
            {"entity": "Database"}
        )
        self.assertFalse(is_valid)
        self.assertEqual(missing, ["environment"])
    
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
    
    def test_extract_variables_with_unicode_german_umlauts(self):
        """Test extracting variables with German umlauts (ä, ö, ü, Ä, Ö, Ü)"""
        text = "Fehler bei {{ Entität }} in {{ Umgebung }}"
        variables = extract_variables(text)
        self.assertEqual(variables, ['Entität', 'Umgebung'])
    
    def test_extract_variables_mixed_unicode_and_ascii(self):
        """Test extracting both Unicode and ASCII variables together"""
        text = "{{ Entität }} und {{ Namespace }} in {{ environment }}"
        variables = extract_variables(text)
        self.assertEqual(variables, ['Entität', 'Namespace', 'environment'])
    
    def test_extract_variables_from_multiple_with_unicode(self):
        """Test extracting Unicode variables from title and description"""
        title = "Fehler bei {{ Entität }}"
        description = "Bitte prüfe {{ Entität }} in {{ Namespace }}. {{ Entität }} tritt mehrfach auf."
        variables = extract_variables_from_multiple([title, description])
        # Should extract 'Entität' first from title, then 'Namespace' from description
        # 'Entität' should only appear once despite multiple occurrences
        self.assertEqual(variables, ['Entität', 'Namespace'])
    
    def test_replace_variables_with_unicode(self):
        """Test replacing Unicode variables"""
        text = "Fehler bei {{ Entität }} in {{ Namespace }}"
        result = replace_variables(text, {
            "Entität": "Datenbank",
            "Namespace": "Production"
        })
        self.assertEqual(result, "Fehler bei Datenbank in Production")
    
    def test_replace_variables_unicode_multiple_occurrences(self):
        """Test replacing Unicode variables that appear multiple times"""
        text = "{{ Entität }} hat ein Problem. Bitte {{ Entität }} prüfen."
        result = replace_variables(text, {"Entität": "Server"})
        self.assertEqual(result, "Server hat ein Problem. Bitte Server prüfen.")
    
    def test_validate_variables_with_unicode(self):
        """Test validation with Unicode variables"""
        text = "{{ Entität }} in {{ Namespace }}"
        
        # All provided
        is_valid, missing = validate_variables(text, {
            "Entität": "Database",
            "Namespace": "Production"
        })
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])
        
        # Missing Namespace
        is_valid, missing = validate_variables(text, {
            "Entität": "Database"
        })
        self.assertFalse(is_valid)
        self.assertEqual(missing, ["Namespace"])
    
    def test_issue_330_scenario(self):
        """Test the exact scenario from issue #330"""
        # This is the bug scenario: Two different variables where only one was shown
        title = "Fehler bei {{ Entität }}"
        description = "Bitte prüfe {{ Entität }} in {{ Namespace }}. {{ Entität }} tritt mehrfach auf."
        
        # Extract all variables from both title and description
        variables = extract_variables_from_multiple([title, description])
        
        # Should find both Entität and Namespace
        self.assertEqual(len(variables), 2)
        self.assertIn('Entität', variables)
        self.assertIn('Namespace', variables)
        
        # Variables should be in order of first appearance
        self.assertEqual(variables[0], 'Entität')  # First in title
        self.assertEqual(variables[1], 'Namespace')  # First in description
        
        # Replace variables
        values = {
            'Entität': 'Service',
            'Namespace': 'test-env'
        }
        
        replaced_title = replace_variables(title, values)
        replaced_description = replace_variables(description, values)
        
        self.assertEqual(replaced_title, "Fehler bei Service")
        self.assertEqual(replaced_description, "Bitte prüfe Service in test-env. Service tritt mehrfach auf.")
        
        # Ensure all occurrences of Entität are replaced
        self.assertNotIn('{{ Entität }}', replaced_description)
        self.assertEqual(replaced_description.count('Service'), 2)
