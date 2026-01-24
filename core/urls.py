from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:id>/', views.project_detail, name='project-detail'),
    path('projects/<int:id>/update/', views.project_update, name='project-update'),
    path('projects/<int:id>/delete/', views.project_delete, name='project-delete'),
    path('projects/<int:id>/clients/add/', views.project_add_client, name='project-add-client'),
    path('projects/<int:id>/clients/remove/', views.project_remove_client, name='project-remove-client'),
    path('projects/<int:id>/items/add/', views.project_add_item, name='project-add-item'),
    path('projects/<int:id>/nodes/add/', views.project_add_node, name='project-add-node'),
    path('projects/<int:id>/releases/add/', views.project_add_release, name='project-add-release'),
    path('items/inbox/', views.items_inbox, name='items-inbox'),
    path('items/backlog/', views.items_backlog, name='items-backlog'),
    path('items/working/', views.items_working, name='items-working'),
    path('items/testing/', views.items_testing, name='items-testing'),
    path('items/ready/', views.items_ready, name='items-ready'),
    path('items/<int:item_id>/classify/', views.item_classify, name='item-classify'),
    path('changes/', views.changes, name='changes'),
]
