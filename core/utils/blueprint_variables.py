"""
Utility functions for blueprint variable parsing and replacement.
Supports variables in the format {{ variable_name }}.
"""
import re
from typing import List, Dict, Tuple


def extract_variables(text: str) -> List[str]:
    """
    Extract all variables from a text string.
    
    Variables are in the format {{ variable_name }}.
    Returns a list of unique variable names (without the braces).
    
    Args:
        text: The text to parse for variables
        
    Returns:
        List of unique variable names found in the text
        
    Examples:
        >>> extract_variables("Hello {{ name }}, welcome to {{ project }}!")
        ['name', 'project']
        >>> extract_variables("No variables here")
        []
    """
    if not text:
        return []
    
    # Pattern to match {{ variable_name }}
    # Allows alphanumeric, underscore, and hyphens in variable names
    pattern = r'\{\{\s*([a-zA-Z0-9_-]+)\s*\}\}'
    matches = re.findall(pattern, text)
    
    # Return unique variables in order of first appearance
    seen = set()
    unique_vars = []
    for var in matches:
        if var not in seen:
            seen.add(var)
            unique_vars.append(var)
    
    return unique_vars


def replace_variables(text: str, variables: Dict[str, str]) -> str:
    """
    Replace all variables in a text string with their values.
    
    Variables are in the format {{ variable_name }}.
    
    Args:
        text: The text containing variables to replace
        variables: Dictionary mapping variable names to their replacement values
        
    Returns:
        Text with all variables replaced by their values
        
    Examples:
        >>> replace_variables("Hello {{ name }}!", {"name": "John"})
        'Hello John!'
        >>> replace_variables("{{ greeting }} {{ name }}", {"greeting": "Hi", "name": "Alice"})
        'Hi Alice'
    """
    if not text or not variables:
        return text or ''
    
    result = text
    for var_name, var_value in variables.items():
        # Replace {{ var_name }} with value (with or without spaces)
        pattern = r'\{\{\s*' + re.escape(var_name) + r'\s*\}\}'
        result = re.sub(pattern, var_value, result)
    
    return result


def extract_variables_from_multiple(texts: List[str]) -> List[str]:
    """
    Extract all unique variables from multiple text strings.
    
    Variables are in the format {{ variable_name }}.
    Returns a de-duplicated list of unique variable names in order of first appearance.
    
    Args:
        texts: List of text strings to parse for variables
        
    Returns:
        List of unique variable names found across all texts
        
    Examples:
        >>> extract_variables_from_multiple(["{{ name }}", "{{ age }} and {{ name }}"])
        ['name', 'age']
        >>> extract_variables_from_multiple(["Title: {{ entity }}", "Desc: {{ entity }} in {{ env }}"])
        ['entity', 'env']
    """
    seen = set()
    unique_vars = []
    
    for text in texts:
        if text:
            vars_in_text = extract_variables(text)
            for var in vars_in_text:
                if var not in seen:
                    seen.add(var)
                    unique_vars.append(var)
    
    return unique_vars


def validate_variables(text: str, provided_variables: Dict[str, str]) -> Tuple[bool, List[str]]:
    """
    Validate that all required variables are provided.
    
    Args:
        text: The text containing variables
        provided_variables: Dictionary of provided variable values
        
    Returns:
        Tuple of (is_valid, missing_variables)
        where is_valid is True if all variables are provided,
        and missing_variables is a list of variable names that are missing
        
    Examples:
        >>> validate_variables("Hello {{ name }}!", {"name": "John"})
        (True, [])
        >>> validate_variables("{{ greeting }} {{ name }}", {"greeting": "Hi"})
        (False, ['name'])
    """
    required_vars = extract_variables(text)
    missing_vars = [var for var in required_vars if var not in provided_variables or not provided_variables[var]]
    
    is_valid = len(missing_vars) == 0
    return is_valid, missing_vars


def validate_variables_from_multiple(texts: List[str], provided_variables: Dict[str, str]) -> Tuple[bool, List[str]]:
    """
    Validate that all required variables from multiple texts are provided.
    
    Args:
        texts: List of text strings containing variables
        provided_variables: Dictionary of provided variable values
        
    Returns:
        Tuple of (is_valid, missing_variables)
        where is_valid is True if all variables are provided,
        and missing_variables is a list of variable names that are missing
        
    Examples:
        >>> validate_variables_from_multiple(["{{ name }}", "{{ age }}"], {"name": "John", "age": "30"})
        (True, [])
        >>> validate_variables_from_multiple(["{{ greeting }}", "{{ name }}"], {"greeting": "Hi"})
        (False, ['name'])
    """
    required_vars = extract_variables_from_multiple(texts)
    missing_vars = [var for var in required_vars if var not in provided_variables or not provided_variables[var]]
    
    is_valid = len(missing_vars) == 0
    return is_valid, missing_vars
