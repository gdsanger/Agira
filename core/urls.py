from django.urls import path
from . import views
from . import views_azuread
from . import views_embed
from . import views_items

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Azure AD SSO authentication URLs
    path('auth/azuread/login/', views_azuread.azuread_login, name='azuread-login'),
    path('auth/azuread/callback/', views_azuread.azuread_callback, name='azuread-callback'),
    path('auth/azuread/logout/', views_azuread.azuread_logout, name='azuread-logout'),
    
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/partials/in_progress_items/', views.dashboard_in_progress_items, name='dashboard-in-progress-items'),
    path('dashboard/partials/activity_stream/', views.dashboard_activity_stream, name='dashboard-activity-stream'),
    path('projects/', views.projects, name='projects'),
    path('projects/new/', views.project_create, name='project-create'),
    path('projects/<int:id>/', views.project_detail, name='project-detail'),
    path('projects/<int:id>/edit/', views.project_edit, name='project-edit'),
    path('projects/<int:id>/update/', views.project_update, name='project-update'),
    path('projects/<int:id>/delete/', views.project_delete, name='project-delete'),
    path('projects/<int:id>/clients/add/', views.project_add_client, name='project-add-client'),
    path('projects/<int:id>/clients/remove/', views.project_remove_client, name='project-remove-client'),
    path('projects/<int:id>/items/add/', views.project_add_item, name='project-add-item'),
    path('projects/<int:id>/nodes/add/', views.project_add_node, name='project-add-node'),
    path('projects/<int:project_id>/nodes/<int:node_id>/', views.project_node_detail, name='project-node-detail'),
    path('projects/<int:project_id>/nodes/<int:node_id>/update/', views.project_node_update, name='project-node-update'),
    path('projects/<int:id>/nodes/tree/', views.project_nodes_tree, name='project-nodes-tree'),
    path('projects/<int:id>/releases/add/', views.project_add_release, name='project-add-release'),
    path('projects/<int:id>/releases/<int:release_id>/update/', views.project_update_release, name='project-update-release'),
    path('projects/<int:id>/releases/<int:release_id>/delete/', views.project_delete_release, name='project-delete-release'),
    path('projects/<int:id>/releases/<int:release_id>/close/', views.project_close_release, name='project-close-release'),
    path('releases/<int:release_id>/modal/', views.release_detail_modal, name='release-detail-modal'),
    path('releases/<int:release_id>/create-change/', views.release_create_change, name='release-create-change'),
    path('projects/<int:id>/items/tab/', views.project_items_tab, name='project-items-tab'),
    path('projects/<int:id>/attachments/tab/', views.project_attachments_tab, name='project-attachments-tab'),
    path('projects/<int:id>/upload-attachment/', views.project_upload_attachment, name='project-upload-attachment'),
    path('projects/attachments/<int:attachment_id>/delete/', views.project_delete_attachment, name='project-delete-attachment'),
    path('projects/attachments/<int:attachment_id>/view/', views.project_view_attachment, name='project-view-attachment'),
    path('projects/attachments/<int:attachment_id>/download/', views.project_download_attachment, name='project-download-attachment'),
    path('projects/<int:id>/import-github-issues/', views.project_import_github_issues, name='project-import-github-issues'),
    path('projects/<int:id>/github/sync-markdown/', views.project_sync_markdown, name='project-sync-markdown'),
    path('items/kanban/', views_items.ItemsKanbanView.as_view(), name='items-kanban'),
    path('items/inbox/', views_items.ItemsInboxView.as_view(), name='items-inbox'),
    path('items/backlog/', views_items.ItemsBacklogView.as_view(), name='items-backlog'),
    path('items/working/', views_items.ItemsWorkingView.as_view(), name='items-working'),
    path('items/testing/', views_items.ItemsTestingView.as_view(), name='items-testing'),
    path('items/ready/', views_items.ItemsReadyView.as_view(), name='items-ready'),
    path('items/github/open/', views.items_github_open, name='items-github-open'),
    path('items/new/', views.item_create, name='item-create'),
    path('items/lookup/<int:item_id>/', views.item_lookup, name='item-lookup'),
    path('items/<int:item_id>/', views.item_detail, name='item-detail'),
    path('items/<int:item_id>/edit/', views.item_edit, name='item-edit'),
    path('items/<int:item_id>/update/', views.item_update, name='item-update'),
    path('items/<int:item_id>/update-release/', views.item_update_release, name='item-update-release'),
    path('items/<int:item_id>/update-parent/', views.item_update_parent, name='item-update-parent'),
    path('items/<int:item_id>/update-intern/', views.item_update_intern, name='item-update-intern'),
    path('items/<int:item_id>/delete/', views.item_delete, name='item-delete'),
    path('items/<int:item_id>/send-status-mail/', views.item_send_status_mail, name='item-send-status-mail'),
    path('items/<int:item_id>/move-project/', views.item_move_project, name='item-move-project'),
    path('items/<int:item_id>/classify/', views.item_classify, name='item-classify'),
    path('items/<int:item_id>/change-status/', views.item_change_status, name='item-change-status'),
    path('items/<int:item_id>/add-comment/', views.item_add_comment, name='item-add-comment'),
    path('items/comments/<int:comment_id>/update/', views.item_update_comment, name='item-update-comment'),
    path('items/comments/<int:comment_id>/delete/', views.item_delete_comment, name='item-delete-comment'),
    path('items/comments/<int:comment_id>/email/prepare-reply/', views.email_prepare_reply, name='email-prepare-reply'),
    path('items/comments/<int:comment_id>/email/prepare-reply-all/', views.email_prepare_reply_all, name='email-prepare-reply-all'),
    path('items/comments/<int:comment_id>/email/prepare-forward/', views.email_prepare_forward, name='email-prepare-forward'),
    path('items/email/send/', views.email_send_reply, name='email-send-reply'),
    path('items/<int:item_id>/upload-attachment/', views.item_upload_attachment, name='item-upload-attachment'),
    path('items/<int:item_id>/upload-transcript/', views.item_upload_transcript, name='item-upload-transcript'),
    path('items/attachments/<int:attachment_id>/delete/', views.item_delete_attachment, name='item-delete-attachment'),
    path('items/attachments/<int:attachment_id>/view/', views.item_view_attachment, name='item-view-attachment'),
    path('items/attachments/<int:attachment_id>/download/', views.item_download_attachment, name='item-download-attachment'),
    path('attachments/<int:attachment_id>/ai-summary/', views.attachment_ai_summary, name='attachment-ai-summary'),
    path('items/<int:item_id>/tabs/comments/', views.item_comments_tab, name='item-comments-tab'),
    path('items/<int:item_id>/tabs/attachments/', views.item_attachments_tab, name='item-attachments-tab'),
    path('items/<int:item_id>/tabs/activity/', views.item_activity_tab, name='item-activity-tab'),
    path('items/<int:item_id>/tabs/github/', views.item_github_tab, name='item-github-tab'),
    path('items/<int:item_id>/tabs/related-items/', views.item_related_items_tab, name='item-related-items-tab'),
    path('items/<int:item_id>/relations/create/', views.item_relation_create, name='item-relation-create'),
    path('items/<int:item_id>/relations/<int:relation_id>/update/', views.item_relation_update, name='item-relation-update'),
    path('items/<int:item_id>/relations/<int:relation_id>/delete/', views.item_relation_delete, name='item-relation-delete'),
    path('items/<int:item_id>/link-github/', views.item_link_github, name='item-link-github'),
    path('items/<int:item_id>/create-github-issue/', views.item_create_github_issue, name='item-create-github-issue'),
    path('items/<int:item_id>/ai/optimize-description/', views.item_optimize_description_ai, name='item-optimize-description-ai'),
    path('items/<int:item_id>/ai/generate-solution/', views.item_generate_solution_ai, name='item-generate-solution-ai'),
    path('items/<int:item_id>/ai/pre-review/', views.item_pre_review, name='item-pre-review'),
    path('items/<int:item_id>/ai/save-pre-review/', views.item_save_pre_review, name='item-save-pre-review'),
    path('items/<int:item_id>/quick-create-user/', views.item_quick_create_user, name='item-quick-create-user'),
    
    # Open Questions endpoints
    path('items/<int:item_id>/open-questions/', views.item_open_questions_list, name='item-open-questions-list'),
    path('open-questions/<int:question_id>/answer/', views.item_open_question_answer, name='item-open-question-answer'),
    path('open-questions/<int:question_id>/answer-ai/', views.item_answer_question_ai, name='item-answer-question-ai'),
    
    # AI endpoints
    path('ai/generate-title/', views.ai_generate_title, name='ai-generate-title'),
    path('ai/optimize-text/', views.ai_optimize_text, name='ai-optimize-text'),
    
    # Change Management URLs
    path('changes/', views.changes, name='changes'),
    path('changes/new/', views.change_create, name='change-create'),
    path('changes/<int:id>/', views.change_detail, name='change-detail'),
    path('changes/<int:id>/edit/', views.change_edit, name='change-edit'),
    path('changes/<int:id>/update/', views.change_update, name='change-update'),
    path('changes/<int:id>/delete/', views.change_delete, name='change-delete'),
    path('changes/<int:id>/print/', views.change_print, name='change-print'),
    path('changes/<int:id>/approvers/add/', views.change_add_approver, name='change-add-approver'),
    path('changes/<int:id>/approvers/<int:approval_id>/update/', views.change_update_approver, name='change-update-approver'),
    path('changes/<int:id>/approvers/<int:approval_id>/remove/', views.change_remove_approver, name='change-remove-approver'),
    path('changes/<int:id>/approvers/<int:approval_id>/attachments/<int:attachment_id>/remove/', views.change_remove_approver_attachment, name='change-remove-approver-attachment'),
    path('changes/<int:id>/approvals/<int:approval_id>/approve/', views.change_approve, name='change-approve'),
    path('changes/<int:id>/approvals/<int:approval_id>/reject/', views.change_reject, name='change-reject'),
    path('changes/<int:id>/approvals/<int:approval_id>/abstain/', views.change_abstain, name='change-abstain'),
    # AI-assisted Change Management endpoints
    path('changes/<int:id>/ai/polish-risk-description/', views.change_polish_risk_description, name='change-polish-risk-description'),
    path('changes/<int:id>/ai/optimize-mitigation/', views.change_optimize_mitigation, name='change-optimize-mitigation'),
    path('changes/<int:id>/ai/optimize-rollback/', views.change_optimize_rollback, name='change-optimize-rollback'),
    path('changes/<int:id>/ai/assess-risk/', views.change_assess_risk, name='change-assess-risk'),
    
    # Organisation URLs
    path('organisations/', views.organisations, name='organisations'),
    path('organisations/new/', views.organisation_create, name='organisation-create'),
    path('organisations/<int:id>/', views.organisation_detail, name='organisation-detail'),
    path('organisations/<int:id>/edit/', views.organisation_edit, name='organisation-edit'),
    path('organisations/<int:id>/update/', views.organisation_update, name='organisation-update'),
    path('organisations/<int:id>/delete/', views.organisation_delete, name='organisation-delete'),
    path('organisations/<int:id>/users/add/', views.organisation_add_user, name='organisation-add-user'),
    path('organisations/<int:id>/users/update/', views.organisation_update_user, name='organisation-update-user'),
    path('organisations/<int:id>/users/remove/', views.organisation_remove_user, name='organisation-remove-user'),
    path('organisations/<int:id>/projects/link/', views.organisation_link_project, name='organisation-link-project'),
    path('organisations/<int:id>/projects/unlink/', views.organisation_unlink_project, name='organisation-unlink-project'),
    
    # AI Provider URLs
    path('ai-providers/', views.ai_providers, name='ai-providers'),
    path('ai-providers/new/', views.ai_provider_create, name='ai-provider-create'),
    path('ai-providers/<int:id>/', views.ai_provider_detail, name='ai-provider-detail'),
    path('ai-providers/<int:id>/update/', views.ai_provider_update, name='ai-provider-update'),
    path('ai-providers/<int:id>/delete/', views.ai_provider_delete, name='ai-provider-delete'),
    path('ai-providers/<int:id>/get-api-key/', views.ai_provider_get_api_key, name='ai-provider-get-api-key'),
    path('ai-providers/<int:id>/fetch-models/', views.ai_provider_fetch_models, name='ai-provider-fetch-models'),
    path('ai-providers/<int:provider_id>/models/add/', views.ai_model_create, name='ai-model-create'),
    path('ai-providers/<int:provider_id>/models/<int:model_id>/update/', views.ai_model_update, name='ai-model-update'),
    path('ai-providers/<int:provider_id>/models/<int:model_id>/update-field/', views.ai_model_update_field, name='ai-model-update-field'),
    path('ai-providers/<int:provider_id>/models/<int:model_id>/toggle-active/', views.ai_model_toggle_active, name='ai-model-toggle-active'),
    path('ai-providers/<int:provider_id>/models/<int:model_id>/delete/', views.ai_model_delete, name='ai-model-delete'),
    
    # Agent URLs
    path('agents/', views.agents, name='agents'),
    path('agents/new/', views.agent_create, name='agent-create'),
    path('agents/<str:filename>/', views.agent_detail, name='agent-detail'),
    path('agents/<str:filename>/save/', views.agent_save, name='agent-save'),
    path('agents/save/', views.agent_create_save, name='agent-create-save'),
    path('agents/<str:filename>/delete/', views.agent_delete, name='agent-delete'),
    path('agents/<str:filename>/test/', views.agent_test, name='agent-test'),
    # AI Jobs History URLs
    path('ai-jobs-history/', views.ai_jobs_history, name='ai-jobs-history'),
    
    # Mail Template URLs
    path('mail-templates/', views.mail_templates, name='mail-templates'),
    path('mail-templates/new/', views.mail_template_create, name='mail-template-create'),
    path('mail-templates/<int:id>/', views.mail_template_detail, name='mail-template-detail'),
    path('mail-templates/<int:id>/edit/', views.mail_template_edit, name='mail-template-edit'),
    path('mail-templates/<int:id>/update/', views.mail_template_update, name='mail-template-update'),
    path('mail-templates/<int:id>/delete/', views.mail_template_delete, name='mail-template-delete'),
    path('mail-templates/<int:id>/ai/generate/', views.mail_template_generate_ai, name='mail-template-generate-ai'),
    
    # Mail Action Mapping URLs
    path('mail-action-mappings/', views.mail_action_mappings, name='mail-action-mappings'),
    path('mail-action-mappings/new/', views.mail_action_mapping_create, name='mail-action-mapping-create'),
    path('mail-action-mappings/<int:id>/', views.mail_action_mapping_detail, name='mail-action-mapping-detail'),
    path('mail-action-mappings/<int:id>/edit/', views.mail_action_mapping_edit, name='mail-action-mapping-edit'),
    path('mail-action-mappings/<int:id>/update/', views.mail_action_mapping_update, name='mail-action-mapping-update'),
    path('mail-action-mappings/<int:id>/delete/', views.mail_action_mapping_delete, name='mail-action-mapping-delete'),
    
    # IssueBlueprint URLs
    path('configuration/blueprints/', views.blueprints, name='blueprints'),
    path('configuration/blueprints/new/', views.blueprint_create, name='blueprint-create'),
    path('configuration/blueprints/create/submit/', views.blueprint_create_submit, name='blueprint-create-submit'),
    path('configuration/blueprints/import/', views.blueprint_import_form, name='blueprint-import-form'),
    path('configuration/blueprints/import/submit/', views.blueprint_import, name='blueprint-import'),
    path('configuration/blueprints/<uuid:id>/', views.blueprint_detail, name='blueprint-detail'),
    path('configuration/blueprints/<uuid:id>/edit/', views.blueprint_edit, name='blueprint-edit'),
    path('configuration/blueprints/<uuid:id>/update/', views.blueprint_update, name='blueprint-update'),
    path('configuration/blueprints/<uuid:id>/delete/', views.blueprint_delete, name='blueprint-delete'),
    path('configuration/blueprints/<uuid:id>/export/', views.blueprint_export, name='blueprint-export'),
    path('configuration/blueprints/<uuid:id>/create-issue/', views.blueprint_create_issue, name='blueprint-create-issue'),
    
    # Item Blueprint Integration URLs
    path('items/<int:item_id>/create-blueprint/', views.item_create_blueprint, name='item-create-blueprint'),
    path('items/<int:item_id>/create-blueprint/submit/', views.item_create_blueprint_submit, name='item-create-blueprint-submit'),
    path('items/<int:item_id>/apply-blueprint/', views.item_apply_blueprint, name='item-apply-blueprint'),
    path('items/<int:item_id>/apply-blueprint/submit/', views.item_apply_blueprint_submit, name='item-apply-blueprint-submit'),
    path('blueprints/category/create-inline/', views.blueprint_category_create_inline, name='blueprint-category-create-inline'),
    
    # Global Settings URLs
    path('global-settings/', views.global_settings_detail, name='global-settings'),
    path('global-settings/update/', views.global_settings_update, name='global-settings-update'),
    
    # System Setting URLs
    path('system-setting/', views.system_setting_detail, name='system-setting'),
    path('system-setting/update/', views.system_setting_update, name='system-setting-update'),
    
    # Public URLs (no authentication required)
    path('public/logo.png', views.public_logo, name='public-logo'),
    # Change Policy URLs
    path('change-policies/', views.change_policies, name='change-policies'),
    path('change-policies/new/', views.change_policy_create, name='change-policy-create'),
    path('change-policies/<int:id>/edit/', views.change_policy_edit, name='change-policy-edit'),
    path('change-policies/<int:id>/update/', views.change_policy_update, name='change-policy-update'),
    path('change-policies/<int:id>/delete/', views.change_policy_delete, name='change-policy-delete'),
    
    # Weaviate Sync URLs
    path('weaviate/status/<str:object_type>/<str:object_id>/', views.weaviate_status, name='weaviate-status'),
    path('weaviate/object/<str:object_type>/<str:object_id>/', views.weaviate_object, name='weaviate-object'),
    path('weaviate/push/<str:object_type>/<str:object_id>/', views.weaviate_push, name='weaviate-push'),
    
    # Global Search
    path('search/', views.search, name='search'),
    
    # Generic Attachment URLs (for global search results and direct links)
    path('attachments/<int:attachment_id>/', views.attachment_view, name='attachment-view'),
    
    # Embed Portal URLs (token-based external access)
    path('embed/projects/<int:project_id>/issues/', views_embed.embed_project_issues, name='embed-project-issues'),
    path('embed/projects/<int:project_id>/releases/', views_embed.embed_project_releases, name='embed-project-releases'),
    path('embed/issues/<int:issue_id>/', views_embed.embed_issue_detail, name='embed-issue-detail'),
    path('embed/projects/<int:project_id>/issues/create/', views_embed.embed_issue_create_form, name='embed-issue-create-form'),
    path('embed/projects/<int:project_id>/issues/create/submit/', views_embed.embed_issue_create, name='embed-issue-create'),
    path('embed/projects/<int:project_id>/attachments/pre-upload/', views_embed.embed_attachment_pre_upload, name='embed-attachment-pre-upload'),
    path('embed/attachments/<int:attachment_id>/download/', views_embed.embed_attachment_download, name='embed-attachment-download'),
    path('embed/issues/<int:issue_id>/comments/', views_embed.embed_issue_add_comment, name='embed-issue-add-comment'),
    path('embed/issues/<int:issue_id>/upload-attachment/', views_embed.embed_issue_upload_attachment, name='embed-issue-upload-attachment'),
    path('embed/issues/<int:issue_id>/attachments/', views_embed.embed_issue_attachments, name='embed-issue-attachments'),
]
