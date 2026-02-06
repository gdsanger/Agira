"""
URL Configuration for CustomGPT Actions API.

This module provides URL routing for the CustomGPT Actions API endpoints.
All endpoints are under /api/customgpt/ and require authentication via x-api-secret header.
"""
from django.urls import path
from . import views_api

urlpatterns = [
    # Projects
    path('projects', views_api.api_projects_list, name='api-projects-list'),
    path('projects/<int:project_id>', views_api.api_project_detail, name='api-project-detail'),
    path('projects/<int:project_id>', views_api.api_project_update_put, name='api-project-update-put'),
    path('projects/<int:project_id>', views_api.api_project_update_patch, name='api-project-update-patch'),
    path('projects/<int:project_id>/open-items', views_api.api_project_open_items, name='api-project-open-items'),
    
    # Items
    path('items', views_api.api_items_list, name='api-items-list'),
    path('items/<int:item_id>', views_api.api_item_detail, name='api-item-detail'),
    path('items/<int:item_id>', views_api.api_item_update_put, name='api-item-update-put'),
    path('items/<int:item_id>', views_api.api_item_update_patch, name='api-item-update-patch'),
    path('projects/<int:project_id>/items', views_api.api_project_create_item, name='api-project-create-item'),
    path('items/<int:item_id>/context', views_api.api_item_context, name='api-item-context'),
]
