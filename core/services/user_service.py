"""
User management service for Agira.

This service provides user creation and organization assignment functionality
that can be reused across different entry points (email ingestion, customer portal, etc.).
"""

import logging
import re
import secrets
import string
from typing import Optional, Tuple

from django.contrib.auth import get_user_model

from core.models import Organisation, UserOrganisation, UserRole

User = get_user_model()

logger = logging.getLogger(__name__)


def get_or_create_user_and_org(
    email: str,
    name: Optional[str] = None,
) -> Tuple[User, Optional[Organisation]]:
    """
    Get existing user by email or create a new one.
    Assign to organization based on email domain if found.
    
    This function implements the same logic as email ingestion to ensure
    consistent user and organization handling across all entry points.
    
    Args:
        email: Email address (required, must be valid)
        name: Display name (optional, defaults to email if not provided)
        
    Returns:
        Tuple of (User, Organisation or None)
        
    Raises:
        ValueError: If email is empty or invalid
        
    Example:
        >>> user, org = get_or_create_user_and_org("john@example.com", "John Doe")
        >>> print(user.email)  # john@example.com
        >>> print(org.name if org else "No org")  # Example Inc or No org
    """
    if not email or not email.strip():
        raise ValueError("Email address is required")
    
    email = email.strip().lower()
    
    # Basic email validation
    if '@' not in email or len(email) < 3:
        raise ValueError(f"Invalid email format: {email}")
    
    # Try to find existing user by email
    try:
        user = User.objects.get(email=email)
        logger.debug(f"Found existing user: {user.username} ({email})")
        
        # Get primary organization for existing user
        primary_org = UserOrganisation.objects.filter(
            user=user,
            is_primary=True,
        ).first()
        
        return user, primary_org.organisation if primary_org else None
        
    except User.DoesNotExist:
        pass
    
    # Extract domain from email
    domain = email.split('@')[1] if '@' in email else None
    
    # Find organization by domain
    organisation = None
    if domain:
        organisation = _find_organisation_by_domain(domain)
    
    # Generate username from email (sanitize for Django username requirements)
    # Django usernames allow letters, digits, and @/./+/-/_ characters
    username_base = email.split('@')[0] if '@' in email else email
    # Replace invalid characters with underscores
    username = re.sub(r'[^\w.@+-]', '_', username_base)
    
    # Ensure username is not empty
    if not username:
        username = "user_" + email.replace("@", "_at_").replace(".", "_")
    
    # Ensure username is unique
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    
    # Generate random password
    password = _generate_random_password()
    
    # Create user
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        name=name or email,
        role=UserRole.USER,
        active=True,
    )
    
    logger.info(f"Created new user: {username} ({email})")
    
    # Assign to organization if found
    if organisation:
        UserOrganisation.objects.create(
            user=user,
            organisation=organisation,
            role=UserRole.USER,
            is_primary=True,
        )
        logger.info(f"Assigned user {username} to organization {organisation.name}")
    else:
        logger.info(f"No organization found for domain {domain}, user created without org assignment")
    
    return user, organisation


def _find_organisation_by_domain(domain: str) -> Optional[Organisation]:
    """
    Find organization by matching email domain.
    
    Args:
        domain: Email domain (e.g., "example.com")
        
    Returns:
        Organisation instance or None
    """
    # Check all organizations for matching domain
    for org in Organisation.objects.all():
        domains = org.get_mail_domains_list()
        if domain.lower() in [d.lower() for d in domains]:
            logger.debug(f"Found organization {org.name} for domain {domain}")
            return org
    
    logger.debug(f"No organization found for domain {domain}")
    return None


def _generate_random_password(length: int = 32) -> str:
    """
    Generate a random password.
    
    Args:
        length: Password length
        
    Returns:
        Random password string
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password
