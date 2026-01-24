from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField


# Enums as TextChoices
class UserRole(models.TextChoices):
    USER = 'User', _('User')
    AGENT = 'Agent', _('Agent')
    APPROVER = 'Approver', _('Approver')


class ProjectStatus(models.TextChoices):
    NEW = 'New', _('New')
    WORKING = 'Working', _('Working')
    CANCELED = 'Canceled', _('Canceled')
    FINISHED = 'Finished', _('Finished')


class NodeType(models.TextChoices):
    PROJECT = 'Project', _('Project')
    VIEW = 'View', _('View')
    ENTITY = 'Entity', _('Entity')
    CLASS = 'Class', _('Class')
    ACTION = 'Action', _('Action')
    REPORT = 'Report', _('Report')
    OTHER = 'Other', _('Other')


class RiskLevel(models.TextChoices):
    LOW = 'Low', _('Low')
    NORMAL = 'Normal', _('Normal')
    HIGH = 'High', _('High')
    VERY_HIGH = 'VeryHigh', _('Very High')


class ReleaseStatus(models.TextChoices):
    PLANNED = 'Planned', _('Planned')
    WORKING = 'Working', _('Working')
    CLOSED = 'Closed', _('Closed')


class ChangeStatus(models.TextChoices):
    DRAFT = 'Draft', _('Draft')
    PLANNED = 'Planned', _('Planned')
    IN_PROGRESS = 'InProgress', _('In Progress')
    DEPLOYED = 'Deployed', _('Deployed')
    ROLLED_BACK = 'RolledBack', _('Rolled Back')
    CANCELED = 'Canceled', _('Canceled')


class ApprovalStatus(models.TextChoices):
    PENDING = 'Pending', _('Pending')
    APPROVED = 'Approved', _('Approved')
    REJECTED = 'Rejected', _('Rejected')


class ItemStatus(models.TextChoices):
    INBOX = 'Inbox', _('Inbox')
    BACKLOG = 'Backlog', _('Backlog')
    WORKING = 'Working', _('Working')
    TESTING = 'Testing', _('Testing')
    READY_FOR_RELEASE = 'ReadyForRelease', _('Ready for Release')
    CLOSED = 'Closed', _('Closed')


class RelationType(models.TextChoices):
    DEPEND_ON = 'DependOn', _('Depends On')
    SIMILAR = 'Similar', _('Similar')
    RELATED = 'Related', _('Related')


class ExternalIssueKind(models.TextChoices):
    ISSUE = 'Issue', _('Issue')
    PR = 'PR', _('Pull Request')


class CommentVisibility(models.TextChoices):
    PUBLIC = 'Public', _('Public')
    INTERNAL = 'Internal', _('Internal')


class CommentKind(models.TextChoices):
    NOTE = 'Note', _('Note')
    COMMENT = 'Comment', _('Comment')
    EMAIL_IN = 'EmailIn', _('Email In')
    EMAIL_OUT = 'EmailOut', _('Email Out')


class EmailDeliveryStatus(models.TextChoices):
    DRAFT = 'Draft', _('Draft')
    QUEUED = 'Queued', _('Queued')
    SENT = 'Sent', _('Sent')
    FAILED = 'Failed', _('Failed')


class AttachmentRole(models.TextChoices):
    PROJECT_FILE = 'ProjectFile', _('Project File')
    ITEM_FILE = 'ItemFile', _('Item File')
    COMMENT_ATTACHMENT = 'CommentAttachment', _('Comment Attachment')


# Custom User Manager
class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError(_('The Username must be set'))
        if not email:
            raise ValueError(_('The Email must be set'))
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('active', True)
        extra_fields.setdefault('role', UserRole.AGENT)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(username, email, password, **extra_fields)


# Models
class Organisation(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ItemType(models.Model):
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.USER)
    active = models.BooleanField(default=True)
    
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'name']

    class Meta:
        ordering = ['username']

    def __str__(self):
        return f"{self.name} ({self.username})"


class UserOrganisation(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='user_organisations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_organisations')
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'organisation'], name='unique_user_organisation'),
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_primary=True),
                name='unique_primary_organisation_per_user'
            )
        ]
        ordering = ['organisation', 'user']

    def __str__(self):
        primary_str = " (Primary)" if self.is_primary else ""
        return f"{self.user.username} - {self.organisation.name}{primary_str}"


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    github_owner = models.CharField(max_length=255, blank=True)
    github_repo = models.CharField(max_length=255, blank=True)
    clients = models.ManyToManyField(Organisation, blank=True, related_name='projects')
    status = models.CharField(max_length=20, choices=ProjectStatus.choices, default=ProjectStatus.NEW)
    
    # Sentry fields
    sentry_dsn = models.CharField(max_length=500, blank=True)
    sentry_project_slug = models.CharField(max_length=255, blank=True)
    sentry_auth_token = EncryptedCharField(max_length=500, blank=True)
    sentry_enable_auto_fetch = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Node(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='nodes')
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=NodeType.choices)
    description = models.TextField(blank=True)
    parent_node = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_nodes')

    class Meta:
        ordering = ['project', 'type', 'name']

    @property
    def matchkey(self):
        return f"{self.type}:{self.name}"

    def __str__(self):
        return f"{self.project.name} - {self.matchkey}"


class Release(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='releases')
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=100)
    risk = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.NORMAL)
    risk_description = models.TextField(blank=True)
    risk_mitigation = models.TextField(blank=True)
    rescue_measure = models.TextField(blank=True)
    update_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ReleaseStatus.choices, default=ReleaseStatus.PLANNED)

    class Meta:
        ordering = ['-update_date', 'project', 'name']

    def __str__(self):
        return f"{self.project.name} - {self.version}"


class Change(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='changes')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ChangeStatus.choices, default=ChangeStatus.DRAFT)
    risk = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.NORMAL)
    risk_description = models.TextField(blank=True)
    mitigation = models.TextField(blank=True)
    rollback_plan = models.TextField(blank=True)
    communication_plan = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_changes')
    release = models.ForeignKey(Release, on_delete=models.SET_NULL, null=True, blank=True, related_name='changes')

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.release and self.release.project != self.project:
            raise ValidationError({
                'release': _('Release must belong to the same project as the change.')
            })

    def __str__(self):
        return f"{self.project.name} - {self.title}"


class ChangeApproval(models.Model):
    change = models.ForeignKey(Change, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approvals')
    is_required = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    decision_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['change', 'approver'], name='unique_change_approver')
        ]
        ordering = ['change', 'approver']

    def __str__(self):
        return f"{self.change.title} - {self.approver.username} ({self.status})"


class Item(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='items')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    solution_description = models.TextField(blank=True)
    type = models.ForeignKey(ItemType, on_delete=models.PROTECT, related_name='items')
    nodes = models.ManyToManyField(Node, blank=True, related_name='items')
    organisation = models.ForeignKey(Organisation, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    requester = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='requested_items')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_items')
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.INBOX)
    solution_release = models.ForeignKey(Release, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    changes = models.ManyToManyField(Change, blank=True, related_name='items')

    class Meta:
        ordering = ['-updated_at']

    def clean(self):
        super().clean()
        errors = {}

        # Parent must be in same project
        if self.parent and self.parent.project != self.project:
            errors['parent'] = _('Parent item must belong to the same project.')

        # Solution release must be in same project
        if self.solution_release and self.solution_release.project != self.project:
            errors['solution_release'] = _('Solution release must belong to the same project.')

        # If project has clients, organisation must be one of them
        if self.organisation:
            project_clients = list(self.project.clients.all())
            if project_clients and self.organisation not in project_clients:
                errors['organisation'] = _('Organisation must be one of the project clients.')

        # Requester must be member of organisation (if organisation is set)
        if self.requester and self.organisation:
            if not UserOrganisation.objects.filter(user=self.requester, organisation=self.organisation).exists():
                errors['requester'] = _('Requester must be a member of the selected organisation.')

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} - {self.title}"


class ItemRelation(models.Model):
    from_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='relations_from')
    to_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='relations_to')
    relation_type = models.CharField(max_length=20, choices=RelationType.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['from_item', 'to_item', 'relation_type'], name='unique_item_relation')
        ]
        indexes = [
            models.Index(fields=['from_item', 'to_item']),
        ]
        ordering = ['from_item', 'to_item']

    def __str__(self):
        return f"{self.from_item.title} {self.relation_type} {self.to_item.title}"


class ExternalIssueMapping(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='external_mappings')
    github_id = models.BigIntegerField(unique=True)
    number = models.IntegerField()
    kind = models.CharField(max_length=20, choices=ExternalIssueKind.choices)
    state = models.CharField(max_length=50)
    html_url = models.URLField()
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item', 'kind', 'number']

    def __str__(self):
        return f"{self.item.project.name} #{self.number} ({self.kind})"


class ItemComment(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='comments')
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='comments')
    visibility = models.CharField(max_length=20, choices=CommentVisibility.choices, default=CommentVisibility.PUBLIC)
    kind = models.CharField(max_length=20, choices=CommentKind.choices, default=CommentKind.COMMENT)
    subject = models.CharField(max_length=500, blank=True)
    body = models.TextField()
    body_html = models.TextField(blank=True)
    external_from = models.EmailField(blank=True)
    external_to = models.EmailField(blank=True)
    message_id = models.CharField(max_length=255, blank=True)
    in_reply_to = models.CharField(max_length=255, blank=True)
    delivery_status = models.CharField(max_length=20, choices=EmailDeliveryStatus.choices, default=EmailDeliveryStatus.DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.item.title} - Comment by {self.author.username if self.author else 'Unknown'}"


class Attachment(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_attachments')
    original_name = models.CharField(max_length=500)
    content_type = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    storage_path = models.CharField(max_length=1000)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['sha256']),
        ]

    def __str__(self):
        return f"{self.original_name} (ID: {self.id})"


class AttachmentLink(models.Model):
    attachment = models.ForeignKey(Attachment, on_delete=models.CASCADE, related_name='links')
    target_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_object_id = models.PositiveIntegerField()
    target = GenericForeignKey('target_content_type', 'target_object_id')
    role = models.CharField(max_length=30, choices=AttachmentRole.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['attachment', 'target_content_type', 'target_object_id', 'role'], name='unique_attachment_target_role')
        ]
        ordering = ['attachment']

    def __str__(self):
        return f"{self.attachment.original_name} -> {self.target} ({self.role})"


class Activity(models.Model):
    target_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_object_id = models.PositiveIntegerField()
    target = GenericForeignKey('target_content_type', 'target_object_id')
    verb = models.CharField(max_length=255)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    summary = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Activities'

    def __str__(self):
        actor_name = self.actor.username if self.actor else 'System'
        return f"{actor_name} {self.verb} at {self.created_at}"


# Configuration Singleton Models
class SingletonModel(models.Model):
    """Abstract base class for singleton models"""
    
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion of singleton configuration
        # Override to do nothing rather than actually deleting
        pass

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class GitHubConfiguration(SingletonModel):
    # Enable/disable flag
    enable_github = models.BooleanField(default=False, help_text="Enable GitHub integration")
    
    # API Configuration
    github_token = EncryptedCharField(max_length=500, blank=True, help_text="GitHub Personal Access Token or App token")
    github_api_base_url = models.URLField(default='https://api.github.com', help_text="GitHub API base URL")
    default_github_owner = models.CharField(max_length=255, blank=True, help_text="Default GitHub owner/organization")
    github_copilot_username = models.CharField(max_length=255, blank=True, help_text="GitHub username for Copilot attribution")
    
    # Legacy fields (for GitHub App integration)
    app_id = models.CharField(max_length=255, blank=True)
    installation_id = models.CharField(max_length=255, blank=True)
    private_key = EncryptedCharField(max_length=5000, blank=True)
    webhook_secret = EncryptedCharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'GitHub Configuration'
        verbose_name_plural = 'GitHub Configuration'

    def __str__(self):
        return "GitHub Configuration"


class WeaviateConfiguration(SingletonModel):
    url = models.URLField(blank=True)
    api_key = EncryptedCharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Weaviate Configuration'
        verbose_name_plural = 'Weaviate Configuration'

    def __str__(self):
        return "Weaviate Configuration"


class GooglePSEConfiguration(SingletonModel):
    api_key = EncryptedCharField(max_length=500, blank=True)
    search_engine_id = models.CharField(max_length=255, blank=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Google PSE Configuration'
        verbose_name_plural = 'Google PSE Configuration'

    def __str__(self):
        return "Google PSE Configuration"


class GraphAPIConfiguration(SingletonModel):
    tenant_id = models.CharField(max_length=255, blank=True)
    client_id = models.CharField(max_length=255, blank=True)
    client_secret = EncryptedCharField(max_length=500, blank=True)
    default_mail_sender = models.EmailField(blank=True, help_text="Default sender email (UPN) for outbound emails, e.g., support@domain.tld")
    enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Graph API Configuration'
        verbose_name_plural = 'Graph API Configuration'

    def __str__(self):
        return "Graph API Configuration"


class ZammadConfiguration(SingletonModel):
    url = models.URLField(blank=True)
    api_token = EncryptedCharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Zammad Configuration'
        verbose_name_plural = 'Zammad Configuration'

    def __str__(self):
        return "Zammad Configuration"


# AI Models
class AIProviderType(models.TextChoices):
    OPENAI = 'OpenAI', _('OpenAI')
    GEMINI = 'Gemini', _('Gemini')
    CLAUDE = 'Claude', _('Claude')


class AIJobStatus(models.TextChoices):
    PENDING = 'Pending', _('Pending')
    COMPLETED = 'Completed', _('Completed')
    ERROR = 'Error', _('Error')


class AIProvider(models.Model):
    """AI Provider configuration (OpenAI, Gemini, Claude, etc.)"""
    name = models.CharField(max_length=255)
    provider_type = models.CharField(max_length=20, choices=AIProviderType.choices)
    api_key = EncryptedCharField(max_length=500)
    organization_id = models.CharField(max_length=255, blank=True, help_text="Optional: For OpenAI organization")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['provider_type', 'name']
        verbose_name = 'AI Provider'
        verbose_name_plural = 'AI Providers'

    def __str__(self):
        return f"{self.name} ({self.provider_type})"


class AIModel(models.Model):
    """AI Model configuration with pricing"""
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name='models')
    name = models.CharField(max_length=255)
    model_id = models.CharField(max_length=255, help_text="Provider model string (e.g., gpt-4, gemini-pro)")
    input_price_per_1m_tokens = models.DecimalField(
        max_digits=10, 
        decimal_places=4, 
        null=True, 
        blank=True,
        help_text="Price per 1M input tokens"
    )
    output_price_per_1m_tokens = models.DecimalField(
        max_digits=10, 
        decimal_places=4, 
        null=True, 
        blank=True,
        help_text="Price per 1M output tokens"
    )
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False, help_text="Use as default model for this provider")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['provider', 'name']
        verbose_name = 'AI Model'
        verbose_name_plural = 'AI Models'
        constraints = [
            models.UniqueConstraint(fields=['provider', 'model_id'], name='unique_provider_model')
        ]

    def __str__(self):
        return f"{self.provider.provider_type} - {self.name}"


class AIJobsHistory(models.Model):
    """History of AI API calls for logging and cost tracking"""
    agent = models.CharField(max_length=255, default='core.ai', help_text="Agent name or 'core.ai' for direct calls")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ai_jobs')
    provider = models.ForeignKey(AIProvider, on_delete=models.SET_NULL, null=True, related_name='jobs')
    model = models.ForeignKey(AIModel, on_delete=models.SET_NULL, null=True, related_name='jobs')
    status = models.CharField(max_length=20, choices=AIJobStatus.choices, default=AIJobStatus.PENDING)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    costs = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, help_text="Total cost in USD")
    
    timestamp = models.DateTimeField(auto_now_add=True)
    duration_ms = models.IntegerField(null=True, blank=True, help_text="Duration in milliseconds")
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'AI Job History'
        verbose_name_plural = 'AI Jobs History'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['provider', 'model']),
            models.Index(fields=['user']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        model_name = self.model.name if self.model else 'Unknown'
        return f"{self.agent} - {model_name} ({self.status}) @ {self.timestamp}"
