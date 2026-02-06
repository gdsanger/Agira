from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import (
    Organisation, ItemType, User, UserOrganisation,
    Project, Node, Release, Change, ChangeApproval, ChangePolicy, ChangePolicyRole,
    Item, ItemRelation, ExternalIssueMapping, ItemComment,
    Attachment, AttachmentLink, Activity,
    GitHubConfiguration, WeaviateConfiguration, GooglePSEConfiguration,
    GraphAPIConfiguration, ZammadConfiguration,
    AIProvider, AIModel, AIJobsHistory,
    ExternalIssueKind, MailTemplate, OrganisationEmbedProject,
    IssueOpenQuestion, IssueStandardAnswer, GlobalSettings,
    IssueBlueprintCategory, IssueBlueprint
)
from core.services.github.service import GitHubService
from core.services.integrations.base import IntegrationError


# Inline Admin Classes
class UserOrganisationInline(admin.TabularInline):
    model = UserOrganisation
    extra = 1
    autocomplete_fields = ['organisation']


class OrganisationEmbedProjectInline(admin.TabularInline):
    model = OrganisationEmbedProject
    extra = 0
    autocomplete_fields = ['project']
    readonly_fields = ['embed_token_display', 'created_at', 'updated_at']
    fields = ['project', 'is_enabled', 'allowed_origins', 'embed_token_display', 'updated_at']
    
    def embed_token_display(self, obj):
        """Display masked token for security"""
        if obj and obj.embed_token:
            return self._mask_token(obj.embed_token)
        return '-'
    embed_token_display.short_description = 'Embed Token'
    
    @staticmethod
    def _mask_token(token):
        """Mask a token showing first 8 and last 8 characters"""
        if len(token) <= 16:
            # For short tokens, just show asterisks
            return '•' * min(len(token), 12)
        return f"{token[:8]}...{token[-8:]}"


class ChangeApprovalInline(admin.TabularInline):
    model = ChangeApproval
    extra = 1
    autocomplete_fields = ['approver']
    readonly_fields = ['decision_at', 'approved_at']
    fields = ['approver', 'is_required', 'status', 'informed_at', 'approved', 'approved_at', 'decision_at', 'comment', 'notes']


class ChangePolicyRoleInline(admin.TabularInline):
    model = ChangePolicyRole
    extra = 1
    fields = ['role']


class ExternalIssueMappingInline(admin.TabularInline):
    model = ExternalIssueMapping
    extra = 0
    readonly_fields = ['last_synced_at']
    fields = ['github_id', 'number', 'kind', 'state', 'html_url', 'last_synced_at']


class ItemCommentInline(admin.TabularInline):
    model = ItemComment
    extra = 0
    readonly_fields = ['created_at', 'sent_at']
    fields = ['author', 'kind', 'visibility', 'subject', 'body', 'created_at']
    can_delete = False


class IssueOpenQuestionInline(admin.TabularInline):
    model = IssueOpenQuestion
    extra = 0
    fields = ['question', 'status', 'answer_type', 'source', 'answered_by', 'answered_at']
    readonly_fields = ['answered_at', 'created_at', 'updated_at']
    autocomplete_fields = ['answered_by', 'standard_answer']
    can_delete = False


# Model Admin Classes
@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ['name', 'short']
    search_fields = ['name', 'short']
    inlines = [UserOrganisationInline, OrganisationEmbedProjectInline]


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'key', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'key']


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'name', 'email', 'role', 'active', 'is_staff']
    list_filter = ['role', 'active', 'is_staff', 'is_superuser']
    search_fields = ['username', 'name', 'email']
    ordering = ['username']
    inlines = [UserOrganisationInline]
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('name', 'email', 'role', 'active')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'name', 'email', 'password1', 'password2', 'role', 'active'),
        }),
    )
    
    readonly_fields = ['last_login', 'date_joined']


@admin.register(UserOrganisation)
class UserOrganisationAdmin(admin.ModelAdmin):
    list_display = ['user', 'organisation', 'is_primary']
    list_filter = ['is_primary', 'organisation']
    search_fields = ['user__username', 'user__name', 'organisation__name']
    autocomplete_fields = ['user', 'organisation']


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'github_owner', 'github_repo', 'sentry_enable_auto_fetch']
    list_filter = ['status', 'sentry_enable_auto_fetch']
    search_fields = ['name', 'github_owner', 'github_repo']
    filter_horizontal = ['clients']
    
    fieldsets = (
        (None, {'fields': ('name', 'description', 'status', 'clients')}),
        ('GitHub', {'fields': ('github_owner', 'github_repo')}),
        ('Sentry', {
            'fields': ('sentry_dsn', 'sentry_project_slug', 'sentry_auth_token', 'sentry_enable_auto_fetch'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ['project', 'type', 'name', 'parent_node', 'get_matchkey']
    list_filter = ['project', 'type']
    search_fields = ['name', 'description']
    autocomplete_fields = ['project', 'parent_node']
    
    def get_matchkey(self, obj):
        return obj.matchkey
    get_matchkey.short_description = 'Matchkey'


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ['project', 'version', 'name', 'type', 'status', 'risk', 'update_date']
    list_filter = ['project', 'status', 'risk', 'type']
    search_fields = ['name', 'version']
    autocomplete_fields = ['project']
    readonly_fields = ['update_date']
    
    fieldsets = (
        (None, {'fields': ('project', 'name', 'version', 'type', 'status', 'update_date')}),
        ('Risk Management', {'fields': ('risk', 'risk_description', 'risk_mitigation', 'rescue_measure')}),
    )


@admin.register(Change)
class ChangeAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'status', 'risk', 'is_safety_relevant', 'executed_at', 'created_by']
    list_filter = ['project', 'status', 'risk', 'is_safety_relevant', 'organisations']
    search_fields = ['title', 'description']
    autocomplete_fields = ['project', 'release', 'created_by']
    filter_horizontal = ['organisations']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ChangeApprovalInline]
    
    fieldsets = (
        (None, {'fields': ('project', 'title', 'description', 'status', 'release', 'organisations', 'is_safety_relevant')}),
        ('Timeline', {'fields': ('planned_start', 'planned_end', 'executed_at', 'created_by')}),
        ('Risk Management', {'fields': ('risk', 'risk_description', 'mitigation', 'rollback_plan', 'communication_plan')}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(ChangeApproval)
class ChangeApprovalAdmin(admin.ModelAdmin):
    list_display = ['change', 'approver', 'is_required', 'status', 'informed_at', 'approved', 'approved_at', 'decision_at']
    list_filter = ['status', 'is_required', 'approved']
    search_fields = ['change__title', 'approver__username']
    autocomplete_fields = ['change', 'approver']
    readonly_fields = ['decision_at', 'approved_at']
    
    fieldsets = (
        (None, {'fields': ('change', 'approver', 'is_required')}),
        ('Status', {'fields': ('status', 'approved', 'decision_at', 'approved_at')}),
        ('Timeline', {'fields': ('informed_at',)}),
        ('Comments & Notes', {'fields': ('comment', 'notes')}),
    )


@admin.register(ChangePolicy)
class ChangePolicyAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'risk_level', 'security_relevant', 'release_type', 'roles_display', 'created_at', 'updated_at']
    list_filter = ['risk_level', 'security_relevant', 'release_type']
    search_fields = ['risk_level', 'release_type']
    inlines = [ChangePolicyRoleInline]
    
    fieldsets = (
        (None, {'fields': ('risk_level', 'security_relevant', 'release_type')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    readonly_fields = ['created_at', 'updated_at']
    
    def roles_display(self, obj):
        roles = obj.policy_roles.all()
        if roles:
            return ', '.join([role.get_role_display() for role in roles])
        return '-'
    roles_display.short_description = 'Roles'


@admin.register(ChangePolicyRole)
class ChangePolicyRoleAdmin(admin.ModelAdmin):
    list_display = ['policy', 'role']
    list_filter = ['role']
    search_fields = ['policy__risk_level', 'policy__release_type']
    autocomplete_fields = ['policy']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'status', 'type', 'assigned_to', 'requester', 'updated_at']
    list_filter = ['project', 'status', 'type']
    search_fields = ['title', 'description']
    autocomplete_fields = ['project', 'parent', 'type', 'organisation', 'requester', 'assigned_to', 'solution_release']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ExternalIssueMappingInline, ItemCommentInline, IssueOpenQuestionInline]
    actions = ['create_github_issue']
    
    fieldsets = (
        (None, {'fields': ('project', 'title', 'status', 'type')}),
        ('Description', {'fields': ('description', 'solution_description')}),
        ('Relationships', {'fields': ('parent', 'nodes', 'changes')}),
        ('Assignment', {'fields': ('organisation', 'requester', 'assigned_to', 'solution_release')}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    
    filter_horizontal = ['nodes', 'changes']
    
    def create_github_issue(self, request, queryset):
        """
        Admin action to create GitHub issues for selected items.
        
        Only creates issues for items with status: Backlog, Working, or Testing.
        """
        service = GitHubService()
        
        # Check if GitHub is enabled
        if not service.is_enabled():
            self.message_user(
                request,
                "GitHub integration is not enabled. Please enable it in GitHub Configuration.",
                level=messages.ERROR
            )
            return
        
        if not service.is_configured():
            self.message_user(
                request,
                "GitHub integration is not configured. Please add a GitHub token in GitHub Configuration.",
                level=messages.ERROR
            )
            return
        
        success_count = 0
        skipped_count = 0
        error_count = 0
        
        for item in queryset:
            # Check if item has valid status
            if not service.can_create_issue_for_item(item):
                skipped_count += 1
                self.message_user(
                    request,
                    f"Skipped '{item.title}': Item status must be Backlog, Working, or Testing (current: {item.status})",
                    level=messages.WARNING
                )
                continue
            
            # Check if item already has a GitHub issue
            if item.external_mappings.filter(kind=ExternalIssueKind.ISSUE).exists():
                skipped_count += 1
                self.message_user(
                    request,
                    f"Skipped '{item.title}': Item already has a GitHub issue mapped",
                    level=messages.WARNING
                )
                continue
            
            try:
                # Create GitHub issue
                mapping = service.create_issue_for_item(
                    item=item,
                    actor=request.user
                )
                
                success_count += 1
                self.message_user(
                    request,
                    f"Successfully created GitHub issue #{mapping.number} for '{item.title}'",
                    level=messages.SUCCESS
                )
            except ValueError as e:
                error_count += 1
                self.message_user(
                    request,
                    f"Error creating issue for '{item.title}': {str(e)}",
                    level=messages.ERROR
                )
            except IntegrationError as e:
                error_count += 1
                self.message_user(
                    request,
                    f"GitHub error for '{item.title}': {str(e)}",
                    level=messages.ERROR
                )
            except Exception as e:
                error_count += 1
                self.message_user(
                    request,
                    f"Unexpected error for '{item.title}': {str(e)}",
                    level=messages.ERROR
                )
        
        # Summary message
        summary_parts = []
        if success_count > 0:
            summary_parts.append(f"{success_count} issue(s) created")
        if skipped_count > 0:
            summary_parts.append(f"{skipped_count} item(s) skipped")
        if error_count > 0:
            summary_parts.append(f"{error_count} error(s)")
        
        if summary_parts:
            self.message_user(
                request,
                f"GitHub issue creation complete: {', '.join(summary_parts)}",
                level=messages.INFO
            )
    
    create_github_issue.short_description = "Create GitHub issue for selected items"


@admin.register(ItemRelation)
class ItemRelationAdmin(admin.ModelAdmin):
    list_display = ['from_item', 'relation_type', 'to_item']
    list_filter = ['relation_type']
    search_fields = ['from_item__title', 'to_item__title']
    autocomplete_fields = ['from_item', 'to_item']


@admin.register(ExternalIssueMapping)
class ExternalIssueMappingAdmin(admin.ModelAdmin):
    list_display = ['item', 'kind', 'number', 'state', 'last_synced_at', 'get_github_link']
    list_filter = ['kind', 'state']
    search_fields = ['item__title', 'number', 'html_url']
    autocomplete_fields = ['item']
    readonly_fields = ['github_id', 'html_url', 'last_synced_at']
    
    def get_github_link(self, obj):
        if obj.html_url:
            return format_html('<a href="{}" target="_blank">View on GitHub</a>', obj.html_url)
        return '-'
    get_github_link.short_description = 'GitHub Link'


@admin.register(ItemComment)
class ItemCommentAdmin(admin.ModelAdmin):
    list_display = ['item', 'author', 'kind', 'visibility', 'created_at', 'delivery_status']
    list_filter = ['kind', 'visibility', 'delivery_status']
    search_fields = ['item__title', 'subject', 'body']
    autocomplete_fields = ['item', 'author']
    readonly_fields = ['created_at', 'sent_at']
    
    fieldsets = (
        (None, {'fields': ('item', 'author', 'kind', 'visibility')}),
        ('Content', {'fields': ('subject', 'body', 'body_html')}),
        ('Email', {'fields': ('external_from', 'external_to', 'message_id', 'in_reply_to', 'delivery_status', 'sent_at')}),
        ('Metadata', {'fields': ('created_at',)}),
    )


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'original_name', 'get_file_size', 'created_by', 'is_deleted']
    list_filter = ['is_deleted', 'created_at']
    search_fields = ['original_name', 'sha256']
    autocomplete_fields = ['created_by']
    readonly_fields = ['created_at', 'sha256', 'get_file_size', 'storage_path']
    
    fieldsets = (
        (None, {'fields': ('original_name', 'content_type', 'is_deleted')}),
        ('Storage', {'fields': ('storage_path', 'get_file_size', 'sha256')}),
        ('Metadata', {'fields': ('created_at', 'created_by')}),
    )
    
    def get_file_size(self, obj):
        if obj.size_bytes:
            # Convert bytes to human-readable format
            size = obj.size_bytes
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024.0 or unit == 'TB':
                    return f"{size:.2f} {unit}"
                size /= 1024.0
        return "-"
    get_file_size.short_description = 'File Size'


@admin.register(AttachmentLink)
class AttachmentLinkAdmin(admin.ModelAdmin):
    list_display = ['attachment', 'role', 'target_content_type', 'target_object_id', 'created_at']
    list_filter = ['role', 'target_content_type', 'created_at']
    search_fields = ['attachment__original_name']
    autocomplete_fields = ['attachment']
    readonly_fields = ['created_at']


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'verb', 'actor', 'summary', 'target_content_type', 'target_object_id']
    list_filter = ['verb', 'actor', 'created_at']
    search_fields = ['summary', 'verb']
    autocomplete_fields = ['actor']
    readonly_fields = ['created_at', 'target_content_type', 'target_object_id']
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        # Activities are created by the system via ActivityService, not manually
        return False


# Configuration Admin Classes
class ConfigurationAdmin(admin.ModelAdmin):
    """Base admin class for singleton configuration models"""
    
    def has_add_permission(self, request):
        # Only allow adding if no instance exists
        return not self.model.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of configuration
        return False
    
    def get_form(self, request, obj=None, **kwargs):
        """Common method to mask encrypted fields in admin forms"""
        form = super().get_form(request, obj, **kwargs)
        if obj:
            # Mask encrypted fields with placeholder
            encrypted_fields = getattr(self, 'encrypted_fields', [])
            for field in encrypted_fields:
                if field in form.base_fields:
                    form.base_fields[field].widget.attrs['placeholder'] = '••••••••'
        return form


@admin.register(GitHubConfiguration)
class GitHubConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['github_token', 'private_key', 'webhook_secret']
    
    fieldsets = (
        (None, {'fields': ('enable_github',)}),
        ('GitHub API', {
            'fields': ('github_token', 'github_api_base_url', 'default_github_owner', 'github_copilot_username'),
            'description': 'Configure GitHub Personal Access Token or App token. Token needs repo access.'
        }),
        ('Legacy GitHub App', {
            'fields': ('enabled', 'app_id', 'installation_id', 'private_key', 'webhook_secret'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WeaviateConfiguration)
class WeaviateConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['api_key']
    
    fieldsets = (
        (None, {'fields': ('enabled','http_port', 'grpc_port')}),
        ('Weaviate Settings', {'fields': ('url', 'api_key')}),
    )


@admin.register(GooglePSEConfiguration)
class GooglePSEConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['api_key']
    
    fieldsets = (
        (None, {'fields': ('enabled',)}),
        ('Google PSE Settings', {'fields': ('api_key', 'search_engine_id')}),
    )


@admin.register(GraphAPIConfiguration)
class GraphAPIConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['client_secret']
    
    fieldsets = (
        (None, {'fields': ('enabled',)}),
        ('Graph API Settings', {
            'fields': ('tenant_id', 'client_id', 'client_secret', 'default_mail_sender'),
            'description': 'The default_mail_sender is the UPN (User Principal Name) that will be used as the sender for outbound emails. This user must exist in your Azure AD and the Graph API app must have Mail.Send permissions.'
        }),
    )


@admin.register(ZammadConfiguration)
class ZammadConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['api_token']
    
    fieldsets = (
        (None, {'fields': ('enabled',)}),
        ('Zammad Settings', {'fields': ('url', 'api_token')}),
    )


# AI Admin Classes
@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider_type', 'active', 'created_at']
    list_filter = ['provider_type', 'active']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        (None, {'fields': ('name', 'provider_type', 'active')}),
        ('API Configuration', {'fields': ('api_key', 'organization_id')}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    
    def get_form(self, request, obj=None, **kwargs):
        """Mask API key in admin forms"""
        form = super().get_form(request, obj, **kwargs)
        if obj and 'api_key' in form.base_fields:
            form.base_fields['api_key'].widget.attrs['placeholder'] = '••••••••'
        return form


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider', 'model_id', 'active', 'input_price_per_1m_tokens', 'output_price_per_1m_tokens', 'is_default']
    list_filter = ['provider', 'active', 'is_default']
    search_fields = ['name', 'model_id']
    autocomplete_fields = ['provider']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        (None, {'fields': ('provider', 'name', 'model_id', 'active', 'is_default')}),
        ('Pricing', {'fields': ('input_price_per_1m_tokens', 'output_price_per_1m_tokens')}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(AIJobsHistory)
class AIJobsHistoryAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'agent', 'user', 'provider', 'model', 'status', 'costs', 'duration_ms', 'input_tokens', 'output_tokens']
    list_filter = ['status', 'provider', 'model', 'agent']
    search_fields = ['agent', 'user__username', 'error_message']
    autocomplete_fields = ['user', 'provider', 'model']
    readonly_fields = ['timestamp']
    
    fieldsets = (
        (None, {'fields': ('agent', 'user', 'status', 'client_ip')}),
        ('AI Provider', {'fields': ('provider', 'model')}),
        ('Metrics', {'fields': ('input_tokens', 'output_tokens', 'costs', 'duration_ms')}),
        ('Metadata', {'fields': ('timestamp', 'error_message')}),
    )
    
    def has_add_permission(self, request):
        # Jobs are created by the system, not manually
        return False


@admin.register(MailTemplate)
class MailTemplateAdmin(admin.ModelAdmin):
    list_display = ['key', 'subject', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['key', 'subject', 'message']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        (None, {'fields': ('key', 'subject', 'is_active')}),
        ('Content', {'fields': ('message',)}),
        ('Sender Information', {
            'fields': ('from_name', 'from_address', 'cc_address'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(GlobalSettings)
class GlobalSettingsAdmin(ConfigurationAdmin):
    """Admin for GlobalSettings singleton"""
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of global settings
        return False
    
    fieldsets = (
        (None, {'fields': ('company_name', 'email', 'base_url')}),
        ('Address', {'fields': ('address',)}),
        ('Logo', {'fields': ('logo',)}),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OrganisationEmbedProject)
class OrganisationEmbedProjectAdmin(admin.ModelAdmin):
    list_display = ['organisation', 'project', 'is_enabled', 'embed_token_masked', 'updated_at']
    list_filter = ['is_enabled', 'organisation', 'updated_at']
    search_fields = ['organisation__name', 'project__name', 'embed_token']
    autocomplete_fields = ['organisation', 'project']
    readonly_fields = ['embed_token', 'created_at', 'updated_at']
    actions = ['rotate_token']
    
    fieldsets = (
        (None, {'fields': ('organisation', 'project', 'is_enabled')}),
        ('Token', {'fields': ('embed_token',)}),
        ('Allowed Origins', {'fields': ('allowed_origins',), 'description': 'Comma-separated list of allowed origins for iframe embedding'}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    
    def embed_token_masked(self, obj):
        """Display masked token for list view"""
        if obj.embed_token:
            return self._mask_token(obj.embed_token)
        return '-'
    embed_token_masked.short_description = 'Embed Token'
    
    @staticmethod
    def _mask_token(token):
        """Mask a token showing first 8 and last 8 characters"""
        if len(token) <= 16:
            # For short tokens, just show asterisks
            return '•' * min(len(token), 12)
        return f"{token[:8]}...{token[-8:]}"
    
    def rotate_token(self, request, queryset):
        """
        Admin action to rotate (regenerate) embed tokens.
        Generates a new token for each selected embed access.
        """
        count = 0
        for embed in queryset:
            # Clear the token to trigger auto-generation on save
            embed.embed_token = None
            embed.save()
            count += 1
        
        self.message_user(
            request,
            f"Successfully rotated {count} embed token(s). Old tokens are now invalid.",
            level=messages.SUCCESS
        )
    rotate_token.short_description = "Rotate embed token (invalidates old token)"


# Register Open Questions Models
@admin.register(IssueStandardAnswer)
class IssueStandardAnswerAdmin(admin.ModelAdmin):
    list_display = ['label', 'key', 'is_active', 'sort_order']
    list_filter = ['is_active']
    search_fields = ['label', 'key', 'text']
    list_editable = ['is_active', 'sort_order']
    ordering = ['sort_order', 'label']
    
    fieldsets = (
        (None, {'fields': ('key', 'label', 'text')}),
        ('Settings', {'fields': ('is_active', 'sort_order')}),
    )


@admin.register(IssueOpenQuestion)
class IssueOpenQuestionAdmin(admin.ModelAdmin):
    list_display = ['question_short', 'issue', 'status', 'source', 'answered_by', 'created_at']
    list_filter = ['status', 'source', 'created_at', 'answered_at']
    search_fields = ['question', 'answer_text', 'issue__title']
    autocomplete_fields = ['issue', 'answered_by', 'standard_answer']
    readonly_fields = ['created_at', 'updated_at', 'answered_at']
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {'fields': ('issue', 'question', 'source')}),
        ('Answer', {'fields': ('status', 'answer_type', 'answer_text', 'standard_answer', 'answered_by', 'answered_at')}),
        ('Metadata', {'fields': ('sort_order', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    
    def question_short(self, obj):
        """Display shortened question text"""
        return obj.question[:50] + '...' if len(obj.question) > 50 else obj.question
    question_short.short_description = 'Question'


@admin.register(IssueBlueprintCategory)
class IssueBlueprintCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'is_active')}),
        ('Metadata', {'fields': ('id', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(IssueBlueprint)
class IssueBlueprintAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'version', 'is_active', 'created_by', 'created_at', 'updated_at']
    list_filter = ['is_active', 'category', 'default_risk_level', 'default_security_relevant', 'created_at']
    search_fields = ['title', 'description_md', 'notes']
    autocomplete_fields = ['category', 'created_by']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        (None, {
            'fields': ('title', 'category', 'description_md', 'is_active', 'version')
        }),
        ('Optional Fields', {
            'fields': ('tags', 'default_labels', 'default_risk_level', 'default_security_relevant', 'notes'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
