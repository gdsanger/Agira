"""
URL configuration for First AID (First AI Documentation) app.
"""
from django.urls import path
from . import views

app_name = 'firstaid'

urlpatterns = [
    # Main First AID interface
    path('', views.firstaid_home, name='home'),
    
    # Chat endpoints
    path('chat/', views.firstaid_chat, name='chat'),
    path('chat/clear-history/', views.clear_chat_history, name='clear-chat-history'),
    
    # Source endpoints
    path('sources/', views.firstaid_sources, name='sources'),
    
    # Tool/Action endpoints
    path('tools/generate-kb-article/', views.generate_kb_article, name='generate-kb-article'),
    path('tools/generate-documentation/', views.generate_documentation, name='generate-documentation'),
    path('tools/generate-flashcards/', views.generate_flashcards, name='generate-flashcards'),
    path('tools/create-issue/', views.create_issue, name='create-issue'),
]
