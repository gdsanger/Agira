from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('projects/', views.projects, name='projects'),
    path('items/inbox/', views.items_inbox, name='items-inbox'),
    path('items/backlog/', views.items_backlog, name='items-backlog'),
    path('items/working/', views.items_working, name='items-working'),
    path('changes/', views.changes, name='changes'),
]
