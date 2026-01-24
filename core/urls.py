from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:id>/', views.project_detail, name='project-detail'),
    path('items/inbox/', views.items_inbox, name='items-inbox'),
    path('items/backlog/', views.items_backlog, name='items-backlog'),
    path('items/working/', views.items_working, name='items-working'),
    path('items/testing/', views.items_testing, name='items-testing'),
    path('items/ready/', views.items_ready, name='items-ready'),
    path('items/<int:item_id>/', views.item_detail, name='item-detail'),
    path('items/<int:item_id>/classify/', views.item_classify, name='item-classify'),
    path('items/<int:item_id>/change-status/', views.item_change_status, name='item-change-status'),
    path('items/<int:item_id>/add-comment/', views.item_add_comment, name='item-add-comment'),
    path('items/<int:item_id>/upload-attachment/', views.item_upload_attachment, name='item-upload-attachment'),
    path('items/<int:item_id>/tabs/comments/', views.item_comments_tab, name='item-comments-tab'),
    path('items/<int:item_id>/tabs/attachments/', views.item_attachments_tab, name='item-attachments-tab'),
    path('items/<int:item_id>/tabs/activity/', views.item_activity_tab, name='item-activity-tab'),
    path('items/<int:item_id>/tabs/github/', views.item_github_tab, name='item-github-tab'),
    path('changes/', views.changes, name='changes'),
]
