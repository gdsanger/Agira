"""
Blueprint Import/Export Serializer

Handles serialization and deserialization of IssueBlueprint objects to/from JSON.
Supports versioned schema for forward/backward compatibility.
"""

import json
from typing import Dict, Any, Optional, Tuple
from django.core.exceptions import ValidationError
from core.models import IssueBlueprint, IssueBlueprintCategory, RiskLevel


# Current schema version
CURRENT_SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = ["1.0"]


class BlueprintSerializationError(Exception):
    """Raised when blueprint serialization fails"""
    pass


class BlueprintDeserializationError(Exception):
    """Raised when blueprint deserialization fails"""
    pass


def export_blueprint(blueprint: IssueBlueprint) -> Dict[str, Any]:
    """
    Export an IssueBlueprint to a versioned JSON-serializable dictionary.
    
    Args:
        blueprint: The IssueBlueprint instance to export
        
    Returns:
        Dictionary with versioned blueprint data
        
    Raises:
        BlueprintSerializationError: If serialization fails
    """
    try:
        data = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "blueprint": {
                "title": blueprint.title,
                "description_md": blueprint.description_md,
                "category": {
                    "name": blueprint.category.name,
                    "slug": blueprint.category.slug,
                },
                "is_active": blueprint.is_active,
                "version": blueprint.version,
                "tags": blueprint.tags,
                "default_labels": blueprint.default_labels,
                "default_risk_level": blueprint.default_risk_level,
                "default_security_relevant": blueprint.default_security_relevant,
                "notes": blueprint.notes,
            }
        }
        
        # Sort keys for deterministic output
        return _sort_dict_keys(data)
        
    except Exception as e:
        raise BlueprintSerializationError(f"Failed to export blueprint: {str(e)}")


def export_blueprint_json(blueprint: IssueBlueprint, indent: Optional[int] = 2) -> str:
    """
    Export an IssueBlueprint to a JSON string.
    
    Args:
        blueprint: The IssueBlueprint instance to export
        indent: JSON indentation level (None for compact)
        
    Returns:
        JSON string with blueprint data
        
    Raises:
        BlueprintSerializationError: If serialization fails
    """
    data = export_blueprint(blueprint)
    try:
        return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=True)
    except Exception as e:
        raise BlueprintSerializationError(f"Failed to convert to JSON: {str(e)}")


def import_blueprint(
    data: Dict[str, Any], 
    created_by=None,
    update_if_exists: bool = False
) -> Tuple[IssueBlueprint, bool]:
    """
    Import an IssueBlueprint from a dictionary.
    
    Args:
        data: Dictionary with blueprint data (must include schema_version)
        created_by: User who is importing (optional)
        update_if_exists: If True, update existing blueprint with same title+category
        
    Returns:
        Tuple of (IssueBlueprint instance, created: bool)
        
    Raises:
        BlueprintDeserializationError: If import fails
        ValidationError: If data validation fails
    """
    try:
        # Validate schema version
        schema_version = data.get("schema_version")
        if not schema_version:
            raise BlueprintDeserializationError(
                "Missing required field: schema_version"
            )
        
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise BlueprintDeserializationError(
                f"Unsupported schema version: {schema_version}. "
                f"Supported versions: {', '.join(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        
        # Extract blueprint data
        blueprint_data = data.get("blueprint")
        if not blueprint_data:
            raise BlueprintDeserializationError(
                "Missing required field: blueprint"
            )
        
        # Validate required fields
        required_fields = ["title", "description_md", "category"]
        for field in required_fields:
            if field not in blueprint_data:
                raise BlueprintDeserializationError(
                    f"Missing required field: blueprint.{field}"
                )
        
        # Handle category - create if doesn't exist
        category_data = blueprint_data["category"]
        if not isinstance(category_data, dict):
            raise BlueprintDeserializationError(
                "Field 'category' must be an object with 'name' and 'slug'"
            )
        
        category_name = category_data.get("name")
        category_slug = category_data.get("slug")
        
        if not category_name or not category_slug:
            raise BlueprintDeserializationError(
                "Category must have both 'name' and 'slug' fields"
            )
        
        # Get or create category
        category, _ = IssueBlueprintCategory.objects.get_or_create(
            slug=category_slug,
            defaults={"name": category_name, "is_active": True}
        )
        
        # If category exists but name is different, we keep the existing name
        # (slug is the canonical identifier)
        
        # Extract fields with defaults for optional fields
        title = blueprint_data["title"]
        description_md = blueprint_data["description_md"]
        is_active = blueprint_data.get("is_active", True)
        version = blueprint_data.get("version", 1)
        tags = blueprint_data.get("tags")
        default_labels = blueprint_data.get("default_labels")
        default_risk_level = blueprint_data.get("default_risk_level")
        default_security_relevant = blueprint_data.get("default_security_relevant")
        notes = blueprint_data.get("notes", "")
        
        # Validate risk level if provided
        if default_risk_level and default_risk_level not in [choice[0] for choice in RiskLevel.choices]:
            raise BlueprintDeserializationError(
                f"Invalid default_risk_level: {default_risk_level}. "
                f"Valid values: {', '.join([choice[0] for choice in RiskLevel.choices])}"
            )
        
        # Check if we should update existing blueprint
        created = True
        if update_if_exists:
            existing = IssueBlueprint.objects.filter(
                title=title,
                category=category
            ).first()
            
            if existing:
                # Update existing blueprint
                existing.description_md = description_md
                existing.is_active = is_active
                existing.version = version
                existing.tags = tags
                existing.default_labels = default_labels
                existing.default_risk_level = default_risk_level
                existing.default_security_relevant = default_security_relevant
                existing.notes = notes
                existing.save()
                return existing, False
        
        # Create new blueprint
        blueprint = IssueBlueprint.objects.create(
            title=title,
            category=category,
            description_md=description_md,
            is_active=is_active,
            version=version,
            tags=tags,
            default_labels=default_labels,
            default_risk_level=default_risk_level,
            default_security_relevant=default_security_relevant,
            notes=notes,
            created_by=created_by
        )
        
        return blueprint, created
        
    except BlueprintDeserializationError:
        raise
    except Exception as e:
        raise BlueprintDeserializationError(f"Failed to import blueprint: {str(e)}")


def import_blueprint_json(
    json_str: str,
    created_by=None,
    update_if_exists: bool = False
) -> Tuple[IssueBlueprint, bool]:
    """
    Import an IssueBlueprint from a JSON string.
    
    Args:
        json_str: JSON string with blueprint data
        created_by: User who is importing (optional)
        update_if_exists: If True, update existing blueprint with same title+category
        
    Returns:
        Tuple of (IssueBlueprint instance, created: bool)
        
    Raises:
        BlueprintDeserializationError: If import fails
        ValidationError: If data validation fails
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise BlueprintDeserializationError(
            f"Invalid JSON: {str(e)}"
        )
    
    return import_blueprint(data, created_by=created_by, update_if_exists=update_if_exists)


def _sort_dict_keys(d: Any) -> Any:
    """Recursively sort dictionary keys for deterministic output."""
    if isinstance(d, dict):
        return {k: _sort_dict_keys(v) for k, v in sorted(d.items())}
    elif isinstance(d, list):
        return [_sort_dict_keys(item) for item in d]
    else:
        return d
