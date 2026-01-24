from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import (
    Organisation, ItemType, User, UserOrganisation,
    Project, Node, Release, Change, ChangeApproval,
    Item, ItemRelation, ExternalIssueMapping, ItemComment,
    Attachment, AttachmentLink, Activity,
    GitHubConfiguration, WeaviateConfiguration, GooglePSEConfiguration,
    GraphAPIConfiguration, ZammadConfiguration
)


# Inline Admin Classes
class UserOrganisationInline(admin.TabularInline):
    model = UserOrganisation
    extra = 1
    autocomplete_fields = ['organisation']


class ChangeApprovalInline(admin.TabularInline):
    model = ChangeApproval
    extra = 1
    autocomplete_fields = ['approver']
    readonly_fields = ['decision_at']
    fields = ['approver', 'is_required', 'status', 'decision_at', 'comment']


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


# Model Admin Classes
@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']
    inlines = [UserOrganisationInline]


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
    list_display = ['project', 'version', 'name', 'status', 'risk', 'update_date']
    list_filter = ['project', 'status', 'risk']
    search_fields = ['name', 'version']
    autocomplete_fields = ['project']
    readonly_fields = ['update_date']
    
    fieldsets = (
        (None, {'fields': ('project', 'name', 'version', 'status', 'update_date')}),
        ('Risk Management', {'fields': ('risk', 'risk_description', 'risk_mitigation', 'rescue_measure')}),
    )


@admin.register(Change)
class ChangeAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'status', 'risk', 'executed_at', 'created_by']
    list_filter = ['project', 'status', 'risk']
    search_fields = ['title', 'description']
    autocomplete_fields = ['project', 'release', 'created_by']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ChangeApprovalInline]
    
    fieldsets = (
        (None, {'fields': ('project', 'title', 'description', 'status', 'release')}),
        ('Timeline', {'fields': ('planned_start', 'planned_end', 'executed_at', 'created_by')}),
        ('Risk Management', {'fields': ('risk', 'risk_description', 'mitigation', 'rollback_plan', 'communication_plan')}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(ChangeApproval)
class ChangeApprovalAdmin(admin.ModelAdmin):
    list_display = ['change', 'approver', 'is_required', 'status', 'decision_at']
    list_filter = ['status', 'is_required']
    search_fields = ['change__title', 'approver__username']
    autocomplete_fields = ['change', 'approver']
    readonly_fields = ['decision_at']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'status', 'type', 'assigned_to', 'requester', 'updated_at']
    list_filter = ['project', 'status', 'type']
    search_fields = ['title', 'description']
    autocomplete_fields = ['project', 'parent', 'type', 'organisation', 'requester', 'assigned_to', 'solution_release']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ExternalIssueMappingInline, ItemCommentInline]
    
    fieldsets = (
        (None, {'fields': ('project', 'title', 'status', 'type')}),
        ('Description', {'fields': ('description', 'solution_description')}),
        ('Relationships', {'fields': ('parent', 'nodes', 'changes')}),
        ('Assignment', {'fields': ('organisation', 'requester', 'assigned_to', 'solution_release')}),
        ('Metadata', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    
    filter_horizontal = ['nodes', 'changes']


@admin.register(ItemRelation)
class ItemRelationAdmin(admin.ModelAdmin):
    list_display = ['from_item', 'relation_type', 'to_item']
    list_filter = ['relation_type']
    search_fields = ['from_item__title', 'to_item__title']
    autocomplete_fields = ['from_item', 'to_item']


@admin.register(ExternalIssueMapping)
class ExternalIssueMappingAdmin(admin.ModelAdmin):
    list_display = ['item', 'kind', 'number', 'state', 'github_id', 'last_synced_at']
    list_filter = ['kind', 'state']
    search_fields = ['item__title', 'number', 'github_id']
    autocomplete_fields = ['item']
    readonly_fields = ['last_synced_at']


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
    list_display = ['original_name', 'project', 'content_type', 'get_file_size', 'uploaded_at', 'uploaded_by']
    list_filter = ['project', 'content_type']
    search_fields = ['original_name', 'description']
    autocomplete_fields = ['project', 'uploaded_by']
    readonly_fields = ['uploaded_at', 'sha256', 'get_file_size']
    
    fieldsets = (
        (None, {'fields': ('project', 'file', 'original_name', 'description')}),
        ('Metadata', {'fields': ('content_type', 'get_file_size', 'sha256', 'uploaded_at', 'uploaded_by')}),
    )
    
    def get_file_size(self, obj):
        if obj.size:
            # Convert bytes to human-readable format
            size = obj.size
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024.0 or unit == 'TB':
                    return f"{size:.2f} {unit}"
                size /= 1024.0
        return "-"
    get_file_size.short_description = 'File Size'


@admin.register(AttachmentLink)
class AttachmentLinkAdmin(admin.ModelAdmin):
    list_display = ['attachment', 'role', 'target_content_type', 'target_object_id']
    list_filter = ['role', 'target_content_type']
    search_fields = ['attachment__original_name']
    autocomplete_fields = ['attachment']


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ['verb', 'actor', 'created_at', 'target_content_type', 'target_object_id']
    list_filter = ['verb', 'actor', 'created_at']
    search_fields = ['verb', 'summary']
    autocomplete_fields = ['actor']
    readonly_fields = ['created_at']


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
    encrypted_fields = ['private_key', 'webhook_secret']
    
    fieldsets = (
        (None, {'fields': ('enabled',)}),
        ('GitHub App', {'fields': ('app_id', 'installation_id', 'private_key', 'webhook_secret')}),
    )


@admin.register(WeaviateConfiguration)
class WeaviateConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['api_key']
    
    fieldsets = (
        (None, {'fields': ('enabled',)}),
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
        ('Graph API Settings', {'fields': ('tenant_id', 'client_id', 'client_secret')}),
    )


@admin.register(ZammadConfiguration)
class ZammadConfigurationAdmin(ConfigurationAdmin):
    encrypted_fields = ['api_token']
    
    fieldsets = (
        (None, {'fields': ('enabled',)}),
        ('Zammad Settings', {'fields': ('url', 'api_token')}),
    )
