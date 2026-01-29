"""
Context processors for Agira templates.

These functions add variables to the template context globally.
"""

from core.views import get_open_github_issues_count


def open_github_issues_count(request):
    """
    Add count of open GitHub issues to template context.
    
    Returns count of open GitHub issues (excluding PRs, excluding closed issues)
    linked to items with status Working or Testing.
    """
    if not request.user.is_authenticated:
        return {'open_github_issues_count': 0}
    
    count = get_open_github_issues_count()
    
    return {'open_github_issues_count': count}
