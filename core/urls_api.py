"""
URL Configuration for CustomGPT Actions API.

This module provides URL routing for the CustomGPT Actions API endpoints.
All endpoints are under /api/customgpt/ and require authentication via x-api-secret header.
"""
from django.urls import path
from . import views_api, views_api_changes

urlpatterns = [
    # Projects
    path('projects', views_api.api_projects_list, name='api-projects-list'),
    path('projects/<int:project_id>', views_api.api_project_detail_handler, name='api-project-detail'),
    path('projects/<int:project_id>/open-items', views_api.api_project_open_items, name='api-project-open-items'),
    
    # Items
    path('items', views_api.api_items_list, name='api-items-list'),
    path('items/<int:item_id>', views_api.api_item_detail_handler, name='api-item-detail'),
    path('items/<int:item_id>/context', views_api.api_item_context, name='api-item-context'),
    path('items/<int:item_id>/github-pr', views_api.api_item_link_github_pr, name='api-item-link-github-pr'),
    path('projects/<int:project_id>/items', views_api.api_project_create_item, name='api-project-create-item'),
    path('items/<int:item_id>/copy', views_api.api_item_copy, name='api-item-copy'),

    # Changes
    path('changes', views_api_changes.api_changes_list, name='api-changes-list'),
    path('changes/<int:change_id>', views_api_changes.api_change_detail_handler, name='api-change-detail'),
    path('changes/<int:change_id>/items', views_api_changes.api_change_items, name='api-change-items'),
    path('projects/<int:project_id>/changes', views_api_changes.api_project_create_change, name='api-project-create-change'),
    path('projects/<int:project_id>/releases', views_api_changes.api_project_releases, name='api-project-releases'),
    path('organisations', views_api_changes.api_organisations_list, name='api-organisations-list'),
]
