from django.db import models, transaction
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField
import secrets
import uuid


# Enums as TextChoices
class UserRole(models.TextChoices):
    USER = 'User', _('User')
    AGENT = 'Agent', _('Agent')
    APPROVER = 'Approver', _('Approver')
    ISB = 'ISB', _('ISB')
    MGMT = "Managemenet", _('Management')
    INFO = 'Info', _('Info')
    DEV = 'Development', _('Development')


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


class ReleaseType(models.TextChoices):
    MAJOR = 'Major', _('Major')
    MINOR = 'Minor', _('Minor')
    BUGFIX = 'Bugfix', _('Bugfix')
    HOTFIX = 'Hotfix', _('Hotfix')
    SECURITYFIX = 'Securityfix', _('Securityfix')


class ChangeStatus(models.TextChoices):
    DRAFT = 'Draft', _('Draft')
    PLANNED = 'Planned', _('Planned')
    IN_PROGRESS = 'InProgress', _('In Progress')
    DEPLOYED = 'Deployed', _('Deployed')
    ROLLED_BACK = 'RolledBack', _('Rolled Back')
    CANCELED = 'Canceled', _('Canceled')


class ApprovalStatus(models.TextChoices):
    PENDING = 'Pending', _('Pending')
    ACCEPT = 'Accept', _('Accept')
    REJECT = 'Reject', _('Reject')
    ABSTAINED = 'Abstained', _('Abstained')


class ItemStatus(models.TextChoices):
    INBOX = 'Inbox', _('📥 Inbox')
    BACKLOG = 'Backlog', _('📋 Backlog')
    WORKING = 'Working', _('🚧 Working')
    TESTING = 'Testing', _('🧪 Testing')
    READY_FOR_RELEASE = 'ReadyForRelease', _('✅ Ready for Release')
    CLOSED = 'Closed', _('✔ Closed')


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
    AI_GENERATED = 'AIGenerated', _('🤖 AI Generated')


class EmailDeliveryStatus(models.TextChoices):
    DRAFT = 'Draft', _('Draft')
    QUEUED = 'Queued', _('Queued')
    SENT = 'Sent', _('Sent')
    FAILED = 'Failed', _('Failed')


class AttachmentRole(models.TextChoices):
    PROJECT_FILE = 'ProjectFile', _('Project File')
    ITEM_FILE = 'ItemFile', _('Item File')
    COMMENT_ATTACHMENT = 'CommentAttachment', _('Comment Attachment')
    APPROVER_ATTACHMENT = 'ApproverAttachment', _('Approver Attachment')


class OpenQuestionStatus(models.TextChoices):
    OPEN = 'Open', _('Open')
    ANSWERED = 'Answered', _('Answered')
    DISMISSED = 'Dismissed', _('Dismissed')


class OpenQuestionAnswerType(models.TextChoices):
    FREE_TEXT = 'FreeText', _('Free Text')
    STANDARD_ANSWER = 'StandardAnswer', _('Standard Answer')
    NONE = 'None', _('None')


class OpenQuestionSource(models.TextChoices):
    AI_AGENT = 'AIAgent', _('AI Agent')
    HUMAN = 'Human', _('Human')


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
    short = models.CharField(max_length=10, blank=True, help_text="Short code/abbreviation for this organization (max 10 characters)")
    mail_domains = models.TextField(
        blank=True,
        help_text="Mail domains for this organization, one per line (e.g., example.com)"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
    
    def get_mail_domains_list(self):
        """
        Return list of mail domains, one per line.
        
        Returns:
            List of domain strings with whitespace stripped.
            Empty or whitespace-only domains are filtered out.
        """
        if not self.mail_domains:
            return []
        return [domain.strip() for domain in self.mail_domains.strip().split('\n') if domain.strip()]


class ItemType(models.Model):
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, help_text='Description shown to customers when creating issues in the embed portal')
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
    
    # Azure AD SSO fields
    azure_ad_object_id = models.CharField(max_length=255, unique=True, null=True, blank=True, 
                                          help_text=_('Azure AD Object ID for SSO'))
    
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
    
    def get_primary_org_short(self):
        """
        Get the short code of the user's primary organisation.
        
        Returns:
            str: The short code if exists, empty string if no primary org or no short code
        """
        try:
            primary_org = self.user_organisations.get(is_primary=True)
            return primary_org.organisation.short if primary_org.organisation.short else ''
        except UserOrganisation.DoesNotExist:
            return ''
    
    def get_primary_organisation(self):
        """
        Get the user's primary organisation.
        
        Returns:
            Organisation: The primary organisation if exists, None otherwise
        """
        try:
            primary_org = self.user_organisations.get(is_primary=True)
            return primary_org.organisation
        except UserOrganisation.DoesNotExist:
            return None


class UserOrganisation(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='user_organisations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_organisations')
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.USER)
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

    def get_breadcrumb(self):
        """
        Calculate the breadcrumb path from root to this node.
        Returns a string like "Root / Subnode / Leaf"
        
        Protects against circular references by limiting depth.
        """
        path = []
        current = self
        max_depth = 100  # Protect against circular references
        depth = 0
        
        # Traverse up the tree to build the path
        while current is not None and depth < max_depth:
            path.insert(0, current.name)
            current = current.parent_node
            depth += 1
        
        return " / ".join(path)
    
    def would_create_cycle(self, potential_parent):
        """
        Check if setting potential_parent as this node's parent would create a circular reference.
        Returns True if it would create a cycle, False otherwise.
        """
        if potential_parent is None:
            return False
        
        # A node cannot be its own parent
        if potential_parent.id == self.id:
            return True
        
        # Parent must be in the same project
        if potential_parent.project_id != self.project_id:
            return True
        
        # Check if potential_parent is a descendant of this node
        current = potential_parent
        max_depth = 100  # Protect against infinite loops
        depth = 0
        
        while current is not None and depth < max_depth:
            if current.id == self.id:
                return True
            current = current.parent_node
            depth += 1
        
        return False
    
    @classmethod
    def get_root_nodes_for_project(cls, project):
        """Get all root nodes (nodes without parents) for a project."""
        return cls.objects.filter(project=project, parent_node=None)
    
    def get_tree_structure(self, depth=0, max_depth=100):
        """
        Get the hierarchical tree structure starting from this node.
        Returns a dictionary with node info and children.
        Protects against circular references with max_depth limit.
        """
        if depth >= max_depth:
            return {
                'id': self.id,
                'name': f"{self.name} (max depth reached)",
                'type': self.type,
                'description': self.description,
                'children': []
            }
        
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'children': [child.get_tree_structure(depth + 1, max_depth) for child in self.child_nodes.all()]
        }

    def __str__(self):
        return f"{self.project.name} - {self.matchkey}"


class Release(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='releases')
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=ReleaseType.choices, null=True, blank=True)
    risk = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.NORMAL)
    risk_description = models.TextField(blank=True)
    risk_mitigation = models.TextField(blank=True)
    rescue_measure = models.TextField(blank=True)
    planned_date = models.DateField(null=True, blank=True, help_text=_('Planned release date'))
    update_date = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=ReleaseStatus.choices, default=ReleaseStatus.PLANNED)
    closed_at = models.DateTimeField(null=True, blank=True, help_text=_('Date and time when release was closed'))
    closed_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_releases', help_text=_('User who closed the release'))

    class Meta:
        ordering = ['-planned_date', '-updated_at', 'project', 'name']

    def __str__(self):
        return f"{self.project.name} - {self.version}"
    
    def get_primary_change(self):
        """Get the first change associated with this release."""
        return self.changes.first()


class Change(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='changes')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    planned_date = models.DateField(null=True, blank=True, help_text=_('Planned change date (date only)'))
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
    organisations = models.ManyToManyField(Organisation, blank=True, related_name='changes')
    is_safety_relevant = models.BooleanField(default=False)

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
    
    def get_associated_items(self):
        """
        Get all items associated with this change.
        Includes:
        - Items directly linked to the change via M2M relationship
        - Items from the associated release (via Item.solution_release)
        
        Returns deduplicated QuerySet ordered by ID.
        """
        item_ids = set()
        
        # Get items directly associated with the change
        direct_item_ids = set(self.items.values_list('id', flat=True))
        item_ids.update(direct_item_ids)
        
        # Get items from the associated release
        # Using release_id directly avoids an extra database query
        if self.release_id is not None:
            release_item_ids = set(
                Item.objects.filter(solution_release_id=self.release_id).values_list('id', flat=True)
            )
            item_ids.update(release_item_ids)
        
        # Return deduplicated queryset ordered by ID
        if item_ids:
            return Item.objects.filter(id__in=item_ids).select_related('project', 'type').order_by('id')
        return Item.objects.none()


class ChangeApproval(models.Model):
    change = models.ForeignKey(Change, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approvals')
    is_required = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    decision_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    # Enhanced approver management fields
    approved_at = models.DateTimeField(null=True, blank=True, help_text="When the approval was granted")
    notes = models.TextField(blank=True, help_text="Internal notes about the approval process")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['change', 'approver'], name='unique_change_approver')
        ]
        ordering = ['change', 'approver']

    def __str__(self):
        return f"{self.change.title} - {self.approver.username} ({self.status})"


class ChangePolicy(models.Model):
    """
    Policy defining which roles should be assigned as approvers for a change
    based on risk level, security relevance, and optionally release type.
    """
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices)
    security_relevant = models.BooleanField(default=False)
    release_type = models.CharField(max_length=20, choices=ReleaseType.choices, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['risk_level', 'security_relevant', 'release_type'],
                name='unique_change_policy'
            )
        ]
        ordering = ['risk_level', 'security_relevant', 'release_type']

    def __str__(self):
        release_type_str = self.release_type if self.release_type else 'No Release'
        security_str = 'Security Relevant' if self.security_relevant else 'Not Security Relevant'
        return f"{self.get_risk_level_display()} - {security_str} - {release_type_str}"


class ChangePolicyRole(models.Model):
    """
    Role assigned to a change policy.
    Defines which roles should be notified/approved for changes matching the policy.
    """
    policy = models.ForeignKey(ChangePolicy, on_delete=models.CASCADE, related_name='policy_roles')
    role = models.CharField(max_length=20, choices=UserRole.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['policy', 'role'],
                name='unique_policy_role'
            )
        ]
        ordering = ['policy', 'role']

    def __str__(self):
        return f"{self.policy} - {self.get_role_display()}"


class Item(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='items')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    user_input = models.TextField(blank=True, help_text=_('Original email text, not modified by AI'))
    solution_description = models.TextField(blank=True)
    type = models.ForeignKey(ItemType, on_delete=models.PROTECT, related_name='items')
    nodes = models.ManyToManyField(Node, blank=True, related_name='items')
    organisation = models.ForeignKey(Organisation, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    requester = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='requested_items')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_items')
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.INBOX)
    solution_release = models.ForeignKey(Release, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    changes = models.ManyToManyField(Change, blank=True, related_name='items')
    intern = models.BooleanField(default=False)

    class Meta:
        ordering = ['-updated_at']

    def clean(self):
        super().clean()
        errors = {}

        # Parent status must not be closed
        if self.parent and self.parent.status == ItemStatus.CLOSED:
            errors['parent'] = _('Cannot set a closed item as parent.')

        # Solution release must be in same project
        if self.solution_release and self.solution_release.project != self.project:
            errors['solution_release'] = _('Solution release must belong to the same project.')

        # Requester must be member of organisation (if organisation is set)
        if self.requester and self.organisation:
            if not UserOrganisation.objects.filter(user=self.requester, organisation=self.organisation).exists():
                errors['requester'] = _('Requester must be a member of the selected organisation.')

        if errors:
            raise ValidationError(errors)
    
    def validate_nodes(self):
        """
        Validate that all assigned nodes belong to the item's project.
        This must be called after the item is saved (for M2M validation).
        """
        project_node_ids = set(self.project.nodes.values_list('id', flat=True))
        item_node_ids = set(self.nodes.values_list('id', flat=True))
        invalid_nodes = item_node_ids - project_node_ids
        if invalid_nodes:
            raise ValidationError({
                'nodes': _('All nodes must belong to the item\'s project.')
            })
    
    def get_primary_node(self):
        """
        Get the primary node for this item.
        Returns the first node if any are assigned, None otherwise.
        """
        return self.nodes.first()
    
    def update_description_with_breadcrumb(self, node=None):
        """
        Update the description to include or update the node breadcrumb.
        If node is None, uses the primary node from self.nodes.
        If no node is assigned, removes any existing breadcrumb.
        
        Format:
        Betrifft: {breadcrumb}
        
        ---
        {existing description}
        """
        if node is None:
            node = self.get_primary_node()
        
        # Remove any existing breadcrumb block
        desc = self.description or ""
        lines = desc.split('\n')
        
        # Find and remove existing "Betrifft:" block
        new_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('Betrifft: '):
                # Skip this line and look for separator
                i += 1
                # Skip empty lines and find separator
                while i < len(lines):
                    if lines[i].strip() == '---':
                        # Skip separator
                        i += 1
                        # Skip one following empty line if present
                        if i < len(lines) and lines[i].strip() == '':
                            i += 1
                        break
                    elif lines[i].strip() == '':
                        # Skip empty lines between Betrifft and separator
                        i += 1
                    else:
                        # Content before separator - shouldn't happen, but handle it
                        break
                continue
            new_lines.append(line)
            i += 1
        
        # Remove leading empty lines
        while new_lines and new_lines[0].strip() == '':
            new_lines.pop(0)
        
        # Build new description
        if node:
            breadcrumb = node.get_breadcrumb()
            new_description = f"Betrifft: {breadcrumb}\n\n---\n"
            if new_lines:
                new_description += '\n'.join(new_lines)
            self.description = new_description
        else:
            # No node, just use the cleaned description without breadcrumb
            self.description = '\n'.join(new_lines)

    def save(self, *args, **kwargs):
        # Check if this is an update (not a new item)
        if self.pk:
            try:
                # Get the old item from database
                old_item = Item.objects.get(pk=self.pk)
                old_requester_id = old_item.requester_id if old_item.requester else None
                new_requester_id = self.requester_id if self.requester else None
                
                # Check if requester has changed
                if old_requester_id != new_requester_id and self.requester:
                    # Get the new requester's primary organisation
                    primary_org = self.requester.get_primary_organisation()
                    if primary_org:
                        # Update the item's organisation to the requester's primary organisation
                        self.organisation = primary_org
                    # If requester has no primary organisation, leave organisation unchanged
                    # (as per requirement: leave unchanged, but display warning to user)
            except Item.DoesNotExist:
                # This shouldn't happen, but handle gracefully
                pass
        
        self.full_clean()
        super().save(*args, **kwargs)
    
    def get_followers(self):
        """
        Get all users following this item.
        Returns a QuerySet of User objects.
        """
        return User.objects.filter(followed_items__item=self)

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


class ItemFollower(models.Model):
    """
    Many-to-Many relationship table between Items and Users for followers.
    Allows users to follow items and receive notifications (e.g., in CC of emails).
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='item_followers')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followed_items')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['item', 'user'], name='unique_item_follower')
        ]
        indexes = [
            models.Index(fields=['item']),
            models.Index(fields=['user']),
        ]
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username} follows {self.item.title}"


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
    external_to = models.TextField(blank=True)  # Changed to TextField to support multiple recipients
    external_cc = models.TextField(blank=True)  # New field for CC recipients
    body_original_html = models.TextField(blank=True)  # Store original HTML for reply/forward
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
    file_type = models.CharField(max_length=20, blank=True, db_index=True, help_text="File type determined from extension (e.g., PDF, DOCX, MD)")
    
    # Email attachment metadata
    content_id = models.CharField(max_length=500, blank=True, help_text="Content-ID for inline email attachments (e.g., 'image001.png@01D9...')")
    
    # GitHub metadata fields for synced markdown files
    github_repo_path = models.CharField(max_length=1000, blank=True, help_text="Path in GitHub repository (e.g., docs/README.md)")
    github_sha = models.CharField(max_length=40, blank=True, help_text="GitHub blob SHA for version tracking")
    github_last_synced = models.DateTimeField(null=True, blank=True, help_text="Last sync time from GitHub")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['sha256']),
            models.Index(fields=['github_repo_path']),
            models.Index(fields=['content_id']),
        ]

    def __str__(self):
        return f"{self.original_name} (ID: {self.id})"
    
    def determine_file_type(self) -> str:
        """
        Determine file type from filename extension or content_type.
        
        Returns:
            String representing the file type (e.g., 'PDF', 'DOCX', 'MD')
        """
        import os
        
        # Extract extension from original_name
        if self.original_name:
            _, ext = os.path.splitext(self.original_name.lower())
            ext = ext.lstrip('.')
            
            # Map common extensions to display names
            extension_map = {
                'pdf': 'PDF',
                'doc': 'DOC',
                'docx': 'DOCX',
                'xls': 'XLS',
                'xlsx': 'XLSX',
                'ppt': 'PPT',
                'pptx': 'PPTX',
                'txt': 'TXT',
                'md': 'MD',
                'markdown': 'MD',
                'html': 'HTML',
                'htm': 'HTML',
                'xml': 'XML',
                'json': 'JSON',
                'csv': 'CSV',
                'zip': 'ZIP',
                'rar': 'RAR',
                '7z': '7Z',
                'tar': 'TAR',
                'gz': 'GZ',
                'jpg': 'JPG',
                'jpeg': 'JPG',
                'png': 'PNG',
                'gif': 'GIF',
                'bmp': 'BMP',
                'svg': 'SVG',
                'mp3': 'MP3',
                'mp4': 'MP4',
                'avi': 'AVI',
                'mov': 'MOV',
                'wav': 'WAV',
                'py': 'PY',
                'js': 'JS',
                'java': 'JAVA',
                'c': 'C',
                'cpp': 'CPP',
                'cs': 'CS',
                'go': 'GO',
                'rb': 'RB',
                'php': 'PHP',
                'sql': 'SQL',
                'sh': 'SH',
                'bat': 'BAT',
                'ps1': 'PS1',
            }
            
            if ext in extension_map:
                return extension_map[ext]
            elif ext:
                # Return uppercase version of unknown extensions
                return ext.upper()[:10]  # Limit to 10 chars
        
        # Fallback to content_type if no extension
        if self.content_type:
            # Extract main type from MIME type
            mime_map = {
                'application/pdf': 'PDF',
                'application/msword': 'DOC',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
                'application/vnd.ms-excel': 'XLS',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XLSX',
                'application/vnd.ms-powerpoint': 'PPT',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPTX',
                'text/plain': 'TXT',
                'text/markdown': 'MD',
                'text/html': 'HTML',
                'text/xml': 'XML',
                'application/json': 'JSON',
                'text/csv': 'CSV',
                'application/zip': 'ZIP',
                'image/jpeg': 'JPG',
                'image/png': 'PNG',
                'image/gif': 'GIF',
                'image/svg+xml': 'SVG',
            }
            
            if self.content_type in mime_map:
                return mime_map[self.content_type]
            
            # Try to extract from content_type
            if '/' in self.content_type:
                main_type = self.content_type.split('/')[0]
                if main_type in ('image', 'audio', 'video'):
                    return main_type.upper()[:10]
        
        return 'FILE'  # Default fallback
    
    def save(self, *args, **kwargs):
        """Override save to auto-populate file_type if not set."""
        if not self.file_type:
            self.file_type = self.determine_file_type()
        super().save(*args, **kwargs)


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
    target_object_id = models.CharField(max_length=255)
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
    url = models.URLField(blank=True, help_text="Weaviate instance URL (e.g., http://localhost or http://192.168.1.100)")
    http_port = models.IntegerField(
        default=8081,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="HTTP port for Weaviate (default: 8080, local install often uses 8081)"
    )
    grpc_port = models.IntegerField(
        default=50051,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="gRPC port for Weaviate (default: 50051)"
    )
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


class MailTemplate(models.Model):
    """
    Model for managing email templates.
    Templates can be used for various email notifications without versioning or mapping logic.
    """
    key = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Technical identifier for the template (e.g., issue-created-confirmation)"
    )
    subject = models.CharField(
        max_length=500,
        help_text="Email subject line. Use {{ issue.variable }} placeholders (e.g., {{ issue.title }}, {{ issue.requester }}, {{ issue.requester_first_name }}, {{ issue.description }}, {{ issue.solution_description }}). Note: {{ solution_description }} without prefix also works for backward compatibility."
    )
    message = models.TextField(
        help_text="Email content (Markdown or HTML). Use {{ issue.variable }} placeholders (e.g., {{ issue.requester }}, {{ issue.requester_first_name }}, {{ issue.organisation }}, {{ issue.solution_release }}, {{ issue.solution_description }}). Note: {{ solution_description }} without prefix also works for backward compatibility."
    )
    from_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional sender name"
    )
    from_address = models.EmailField(
        blank=True,
        help_text="Optional sender email address"
    )
    cc_address = models.EmailField(
        blank=True,
        help_text="Optional CC email address"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this template is active and can be used"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']
        verbose_name = 'Mail Template'
        verbose_name_plural = 'Mail Templates'
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.key} ({'active' if self.is_active else 'inactive'})"


class MailActionMapping(models.Model):
    """
    Model for mapping issue states (status + type) to mail templates.
    This mapping defines which mail template should be used for specific
    combinations of item status and item type.
    
    This is a purely declarative model - it does not trigger emails or
    evaluate state changes. It serves as configuration data for notification logic.
    """
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this mapping is active and can be used"
    )
    item_status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        help_text="Issue status for which this mapping applies"
    )
    item_type = models.ForeignKey(
        ItemType,
        on_delete=models.CASCADE,
        related_name='mail_action_mappings',
        help_text="Issue type for which this mapping applies"
    )
    mail_template = models.ForeignKey(
        MailTemplate,
        on_delete=models.PROTECT,
        related_name='mail_action_mappings',
        help_text="Mail template to use for this status/type combination"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item_status', 'item_type']
        verbose_name = 'Mail Action Mapping'
        verbose_name_plural = 'Mail Action Mappings'
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['item_status', 'item_type']),
        ]

    def __str__(self):
        status_display = self.get_item_status_display()
        type_name = self.item_type.name if self.item_type else 'Unknown'
        template_key = self.mail_template.key if self.mail_template else 'Unknown'
        active_str = 'active' if self.is_active else 'inactive'
        return f"{status_display} + {type_name} → {template_key} ({active_str})"


class OrganisationEmbedProject(models.Model):
    """
    Defines embed access for a specific organisation-project combination.
    Allows external iFrame embedding based on a generated token.
    """
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name='embed_projects',
        help_text=_('Organisation that has embed access')
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='embed_accesses',
        help_text=_('Project that can be embedded')
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text=_('Whether this embed access is currently enabled')
    )
    embed_token = models.CharField(
        max_length=128,
        unique=True,
        help_text=_('Cryptographically secure token for embed access')
    )
    allowed_origins = models.TextField(
        blank=True,
        default='',
        help_text=_('Comma-separated list of allowed origins for iframe embedding (e.g., https://app.example.com, https://portal.example.org)')
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['organisation_id', 'project_id']
        verbose_name = _('Organisation Embed Project')
        verbose_name_plural = _('Organisation Embed Projects')
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'project'],
                name='unique_organisation_project_embed'
            )
        ]
        indexes = [
            models.Index(fields=['embed_token']),
            models.Index(fields=['is_enabled']),
        ]

    def __str__(self):
        return f"{self.organisation.name} - {self.project.name} ({'enabled' if self.is_enabled else 'disabled'})"
    
    def get_allowed_origins(self):
        """
        Parse and return the list of allowed origins.
        
        Returns:
            list: List of allowed origin strings (whitespace trimmed, empty entries removed)
        """
        if not self.allowed_origins:
            return []
        
        # Split by comma, trim whitespace, and remove empty entries
        origins = [
            origin.strip() 
            for origin in self.allowed_origins.split(',') 
            if origin.strip()
        ]
        return origins

    def save(self, *args, **kwargs):
        """
        Auto-generate embed_token if not set.
        Uses secrets.token_urlsafe for cryptographically secure, URL-safe tokens.
        Includes retry mechanism in case of token collision (extremely unlikely).
        """
        if not self.embed_token:
            # Generate 48 bytes = 64 characters base64-encoded (URL-safe)
            # Retry up to 3 times in the extremely unlikely event of a collision
            from django.db import IntegrityError
            max_retries = 3
            for attempt in range(max_retries):
                self.embed_token = secrets.token_urlsafe(48)
                try:
                    super().save(*args, **kwargs)
                    return
                except IntegrityError as e:
                    if attempt == max_retries - 1 or 'embed_token' not in str(e):
                        raise
                    # Token collision, retry with new token
                    continue
        super().save(*args, **kwargs)


class ReportDocument(models.Model):
    """
    Stores generated PDF reports with their context snapshot for audit purposes.
    
    This model provides:
    - Persistence of generated PDF reports
    - Context snapshot for reproducibility
    - SHA256 hash for integrity verification
    - Link to the object the report is about
    """
    report_key = models.CharField(max_length=100, help_text="Report type identifier (e.g., 'change.v1')")
    object_type = models.CharField(max_length=100, help_text="Type of object this report is for (e.g., 'change')")
    object_id = models.CharField(max_length=100, help_text="ID of the object")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='created_reports'
    )
    context_json = models.TextField(help_text="Snapshot of the data used to generate this report")
    pdf_file = models.FileField(upload_to='reports/%Y/%m/%d/')
    sha256 = models.CharField(max_length=64, help_text="SHA256 hash of the PDF for integrity verification")
    metadata_json = models.TextField(
        blank=True,
        null=True,
        help_text="Additional metadata (template version, etc.)"
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['report_key', 'object_type', 'object_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.report_key} for {self.object_type} #{self.object_id}"


class IssueStandardAnswer(models.Model):
    """
    Configurable standard answers for quick question responses.
    
    Provides pre-defined answers for common questions to speed up
    the process of answering open questions on issues.
    """
    key = models.SlugField(max_length=100, unique=True, help_text="Unique key for this standard answer")
    label = models.CharField(max_length=200, help_text="Short label shown in UI")
    text = models.TextField(help_text="Full answer text")
    is_active = models.BooleanField(default=True, help_text="Whether this answer is available for selection")
    sort_order = models.IntegerField(default=0, help_text="Display order (lower numbers first)")
    
    class Meta:
        ordering = ['sort_order', 'label']
    
    def __str__(self):
        return self.label


class IssueOpenQuestion(models.Model):
    """
    Open questions identified by AI agents or humans for an issue.
    
    Questions are never deleted, only marked as answered or dismissed.
    This maintains a historical record of all questions and decisions.
    """
    issue = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='open_questions')
    question = models.TextField(help_text="The question text")
    status = models.CharField(
        max_length=20,
        choices=OpenQuestionStatus.choices,
        default=OpenQuestionStatus.OPEN,
        help_text="Current status of the question"
    )
    answer_text = models.TextField(
        blank=True,
        null=True,
        help_text="Free text answer if provided"
    )
    answer_type = models.CharField(
        max_length=20,
        choices=OpenQuestionAnswerType.choices,
        default=OpenQuestionAnswerType.NONE,
        help_text="Type of answer provided"
    )
    standard_answer_key = models.SlugField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Key of standard answer if used"
    )
    standard_answer = models.ForeignKey(
        IssueStandardAnswer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='question_uses',
        help_text="Standard answer if selected"
    )
    source = models.CharField(
        max_length=20,
        choices=OpenQuestionSource.choices,
        default=OpenQuestionSource.AI_AGENT,
        help_text="Source of this question"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    answered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the question was answered or dismissed"
    )
    answered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='answered_questions',
        help_text="User who answered or dismissed the question"
    )
    sort_order = models.IntegerField(
        default=0,
        help_text="Display order within the issue (lower numbers first)"
    )
    
    class Meta:
        ordering = ['sort_order', 'created_at']
        indexes = [
            models.Index(fields=['issue', 'status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Question for {self.issue.title}: {self.question[:50]}..."
    
    def get_answer_display_text(self):
        """
        Get the display text for the answer.
        
        Returns the standard answer text if a standard answer is used,
        otherwise returns the free text answer.
        """
        if self.answer_type == OpenQuestionAnswerType.STANDARD_ANSWER and self.standard_answer:
            return self.standard_answer.text
        elif self.answer_type == OpenQuestionAnswerType.FREE_TEXT and self.answer_text:
            return self.answer_text
        return ""


class GlobalSettings(models.Model):
    """
    Global application settings (Singleton).
    Only one instance should exist in the database.
    """
    company_name = models.CharField(
        max_length=255,
        default="Your Company Name",
        help_text="Company name"
    )
    email = models.EmailField(
        default="company@example.com",
        help_text="Company contact email address"
    )
    address = models.TextField(
        default="Street Address\nZIP City\nCountry",
        help_text="Company address (Street, ZIP, City, Country)"
    )
    base_url = models.URLField(
        max_length=500,
        default="https://example.com",
        help_text="Base URL of the application"
    )
    logo = models.ImageField(
        upload_to='global_settings/',
        blank=True,
        null=True,
        help_text="Company logo (PNG, JPG, WEBP, GIF - max 5 MB)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Global Settings'
        verbose_name_plural = 'Global Settings'

    def __str__(self):
        return f"Global Settings - {self.company_name}"

    def save(self, *args, **kwargs):
        """
        Enforce singleton pattern - ensure only one instance exists.
        """
        if not self.pk and GlobalSettings.objects.exists():
            # If trying to create a new instance when one already exists
            raise ValidationError("Only one GlobalSettings instance can exist.")
        return super().save(*args, **kwargs)

    @classmethod
    def get_instance(cls):
        """
        Get the singleton instance, creating it with defaults if it doesn't exist.
        """
        instance, created = cls.objects.get_or_create(pk=1)
        return instance


class SystemSetting(models.Model):
    """
    System settings (Singleton).
    Only one instance should exist in the database.
    Stores system-wide configuration like system name, company info, and logo.
    """
    # ID is auto-increment by default, no need to explicitly define it
    system_name = models.CharField(
        max_length=255,
        default="Agira Issue Tracking v1.0",
        help_text="System name"
    )
    company = models.CharField(
        max_length=255,
        default="Agira Software Enterprises",
        help_text="Company name"
    )
    company_logo = models.ImageField(
        upload_to='system_settings/',
        blank=True,
        null=True,
        help_text="Company logo (PNG, JPG, WEBP, GIF - max 5 MB). Stored as relative path."
    )
    email = models.EmailField(
        default="agira@angermeier.net",
        help_text="Company contact email address"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return f"System Settings - {self.system_name}"

    def save(self, *args, **kwargs):
        """
        Enforce singleton pattern - ensure only one instance exists.
        """
        if not self.pk and SystemSetting.objects.exists():
            # If trying to create a new instance when one already exists
            raise ValidationError("Only one SystemSetting instance can exist.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Prevent deletion of system settings.
        """
        # Do nothing - prevent deletion
        pass

    @classmethod
    def get_instance(cls):
        """
        Get the singleton instance, creating it with defaults if it doesn't exist.
        """
        instance, created = cls.objects.get_or_create(pk=1)
        return instance


class IssueBlueprintCategory(models.Model):
    """
    Global categories for issue blueprints.
    Provides project-independent categorization of blueprint templates.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Issue Blueprint Category'
        verbose_name_plural = 'Issue Blueprint Categories'

    def __str__(self):
        return self.name


class IssueBlueprint(models.Model):
    """
    Reusable issue/feature templates (blueprints).
    Project-independent templates that can be used to create new issues.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    category = models.ForeignKey(
        IssueBlueprintCategory,
        on_delete=models.PROTECT,
        related_name='blueprints'
    )
    description_md = models.TextField(
        help_text='Description in Markdown format. Acceptance criteria should be included here.'
    )
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Optional fields
    tags = models.JSONField(
        blank=True,
        null=True,
        help_text='List of tags as strings'
    )
    default_labels = models.JSONField(
        blank=True,
        null=True,
        help_text='List of default labels as strings'
    )
    default_risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        null=True,
        blank=True,
        help_text='Default risk level for issues created from this blueprint'
    )
    default_security_relevant = models.BooleanField(
        null=True,
        blank=True,
        help_text='Default security relevance for issues created from this blueprint'
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text='Internal notes about this blueprint'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_blueprints',
        help_text='User who created this blueprint'
    )

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Issue Blueprint'
        verbose_name_plural = 'Issue Blueprints'
        indexes = [
            models.Index(fields=['title', 'category', 'version']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.title} (v{self.version})"

