"""Tests for the user-specific project/item visibility filter (#1248).

The feature is a UI filter, not authorization: lists and pickers shrink to the
projects assigned to the logged-in user, while every existing endpoint keeps
working. Both halves are covered here — what disappears, and what deliberately
does not.
"""
from django.test import Client, TestCase
from django.urls import reverse

from core.context_processors import open_github_issues_count
from core.models import (
    Change, ChangeStatus, ExternalIssueKind, ExternalIssueMapping, Item, ItemStatus,
    ItemType, Organisation, Project, ProjectStatus, User, UserRole,
)
from core.views import get_open_github_issues_count
from core.visibility import scope_items, scope_projects, visible_items_for, visible_projects_for


class ProjectVisibilityTestCase(TestCase):
    """Shared fixture: `mine` is assigned to the user, `theirs` is not."""

    def setUp(self):
        self.client = Client()
        self.org = Organisation.objects.create(name='Test Organisation')

        self.user = User.objects.create_user(
            username='member', email='member@example.com', password='testpass123',
            name='Member User', active=True,
        )
        self.other_user = User.objects.create_user(
            username='outsider', email='outsider@example.com', password='testpass123',
            name='Outsider', active=True,
        )

        self.mine = Project.objects.create(name='Alpha Mine', status=ProjectStatus.WORKING)
        self.theirs = Project.objects.create(name='Beta Theirs', status=ProjectStatus.WORKING)
        self.mine.members.add(self.user)
        self.theirs.members.add(self.other_user)

        self.item_type = ItemType.objects.create(key='bug', name='Bug')

        self.my_item = Item.objects.create(
            title='Visible item', description='in an assigned project',
            project=self.mine, type=self.item_type, status=ItemStatus.INBOX,
            organisation=self.org,
        )
        self.their_item = Item.objects.create(
            title='Hidden item', description='in a project I am not assigned to',
            project=self.theirs, type=self.item_type, status=ItemStatus.INBOX,
            organisation=self.org,
        )

        self.client.login(username='member', password='testpass123')


class VisibilityHelperTests(ProjectVisibilityTestCase):
    """The queryset helpers every view builds on."""

    def test_visible_projects_contains_only_assigned_projects(self):
        self.assertEqual(list(visible_projects_for(self.user)), [self.mine])
        self.assertEqual(list(visible_projects_for(self.other_user)), [self.theirs])

    def test_item_visibility_is_derived_from_the_project(self):
        self.assertEqual(list(visible_items_for(self.user)), [self.my_item])

    def test_a_user_without_assignment_sees_nothing(self):
        loner = User.objects.create_user(
            username='loner', email='loner@example.com', password='testpass123', active=True,
        )
        self.assertEqual(list(visible_projects_for(loner)), [])
        self.assertEqual(list(visible_items_for(loner)), [])

    def test_multiple_projects_per_user_are_supported(self):
        extra = Project.objects.create(name='Gamma', status=ProjectStatus.WORKING)
        extra.members.add(self.user)
        self.assertEqual(list(visible_projects_for(self.user)), [self.mine, extra])

    def test_assignment_is_many_to_many(self):
        self.theirs.members.add(self.user)
        self.assertCountEqual(list(visible_projects_for(self.user)), [self.mine, self.theirs])
        self.assertCountEqual(list(self.theirs.members.all()), [self.user, self.other_user])

    def test_scope_helpers_return_nothing_for_anonymous_users(self):
        self.assertEqual(list(scope_projects(Project.objects.all(), None)), [])
        self.assertEqual(list(scope_items(Item.objects.all(), None)), [])

    def test_scoping_does_not_duplicate_rows(self):
        """A join on a m2m must not multiply rows when several users are assigned."""
        self.mine.members.add(self.other_user)
        self.assertEqual(visible_projects_for(self.user).count(), 1)
        self.assertEqual(visible_items_for(self.user).count(), 1)


class ProjectListVisibilityTests(ProjectVisibilityTestCase):
    """Acceptance criterion 1: the project list shows assigned projects only."""

    def test_project_list_hides_unassigned_projects(self):
        response = self.client.get(reverse('projects'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['projects']), [self.mine])

    def test_project_list_search_runs_on_the_visible_set(self):
        """A project matching the search term but not assigned stays hidden."""
        response = self.client.get(reverse('projects'), {'q': 'Beta'})

        self.assertEqual(list(response.context['projects']), [])

    def test_project_list_search_still_finds_visible_projects(self):
        response = self.client.get(reverse('projects'), {'q': 'Alpha'})

        self.assertEqual(list(response.context['projects']), [self.mine])

    def test_project_list_status_filter_runs_on_the_visible_set(self):
        response = self.client.get(reverse('projects'), {'status': ProjectStatus.WORKING})

        self.assertEqual(list(response.context['projects']), [self.mine])

    def test_project_list_item_count_annotations_survive_the_filter(self):
        response = self.client.get(reverse('projects'))

        project = response.context['projects'][0]
        self.assertEqual(project.inbox_count, 1)

    def test_creator_is_assigned_to_a_new_project(self):
        response = self.client.post(reverse('project-create'), {
            'name': 'Fresh Project',
            'description': '',
            'status': ProjectStatus.NEW,
        })

        self.assertEqual(response.status_code, 200)
        created = Project.objects.get(name='Fresh Project')
        self.assertIn(self.user, created.members.all())
        self.assertIn(created, visible_projects_for(self.user))


class ItemListVisibilityTests(ProjectVisibilityTestCase):
    """Acceptance criterion 2: item lists show items of assigned projects only."""

    def test_status_list_hides_items_of_unassigned_projects(self):
        response = self.client.get(reverse('items-inbox'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item.id for item in response.context['items']], [self.my_item.id])

    def test_status_list_search_runs_on_the_visible_set(self):
        response = self.client.get(reverse('items-inbox'), {'q': 'Hidden'})

        self.assertEqual(list(response.context['items']), [])

    def test_status_list_search_still_finds_visible_items(self):
        response = self.client.get(reverse('items-inbox'), {'q': 'Visible'})

        self.assertEqual([item.id for item in response.context['items']], [self.my_item.id])

    def test_explicit_project_filter_cannot_reach_an_unassigned_project(self):
        """Hand-crafting ?project=<id> must not widen the result set."""
        response = self.client.get(reverse('items-inbox'), {'project': self.theirs.id})

        self.assertNotIn(self.their_item, response.context['items'])

    def test_pagination_counts_only_visible_items(self):
        for index in range(3):
            Item.objects.create(
                title=f'More hidden {index}', project=self.theirs, type=self.item_type,
                status=ItemStatus.INBOX,
            )
        response = self.client.get(reverse('items-inbox'))

        self.assertEqual(response.context['table'].paginator.count, 1)

    def test_sorting_runs_on_the_visible_set(self):
        response = self.client.get(reverse('items-inbox'), {'sort': 'title'})

        self.assertEqual([item.id for item in response.context['items']], [self.my_item.id])

    def test_distinct_header_values_only_offer_visible_projects(self):
        response = self.client.get(reverse('items-inbox'))

        self.assertEqual(response.context['distinct_values']['project'], [self.mine])

    def test_assigned_to_me_hides_items_of_unassigned_projects(self):
        """Item visibility is derived from the project, even for one's own items."""
        self.their_item.assigned_to = self.user
        self.their_item.save()
        self.my_item.assigned_to = self.user
        self.my_item.save()

        response = self.client.get(reverse('items-assigned'))

        self.assertEqual([item.id for item in response.context['items']], [self.my_item.id])

    def test_responsible_for_hides_items_of_unassigned_projects(self):
        # Only agents may be responsible for an item (existing model rule).
        self.user.role = UserRole.AGENT
        self.user.save()
        self.their_item.responsible = self.user
        self.their_item.save()

        response = self.client.get(reverse('items-responsible'))

        self.assertEqual(list(response.context['items']), [])

    def test_kanban_hides_items_of_unassigned_projects(self):
        response = self.client.get(reverse('items-kanban'))

        self.assertEqual(response.status_code, 200)
        inbox_items = response.context['items_by_status'][ItemStatus.INBOX]
        self.assertEqual([item.id for item in inbox_items], [self.my_item.id])

    def test_dashboard_kpis_count_only_visible_items(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['kpis']['inbox_count'], 1)

    def test_dashboard_in_progress_partial_is_scoped(self):
        self.their_item.status = ItemStatus.WORKING
        self.their_item.save()
        self.my_item.status = ItemStatus.WORKING
        self.my_item.save()

        response = self.client.get(reverse('dashboard-in-progress-items'))

        self.assertEqual([item.id for item in response.context['items']], [self.my_item.id])


class ProjectChoiceVisibilityTests(ProjectVisibilityTestCase):
    """Acceptance criterion 3: project pickers offer assigned projects only."""

    def assertOnlyVisibleProjects(self, projects):
        self.assertEqual(list(projects), [self.mine])

    def test_item_list_filter_dropdown(self):
        response = self.client.get(reverse('items-inbox'))

        self.assertOnlyVisibleProjects(response.context['filter'].filters['project'].queryset)

    def test_kanban_filter_dropdown(self):
        response = self.client.get(reverse('items-kanban'))

        self.assertOnlyVisibleProjects(response.context['filter'].filters['project'].queryset)

    def test_item_create_form(self):
        response = self.client.get(reverse('item-create'))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_item_create_ignores_preselection_of_an_unassigned_project(self):
        response = self.client.get(reverse('item-create'), {'project': self.theirs.id})

        self.assertIsNone(response.context['default_project'])

    def test_item_create_keeps_preselection_of_an_assigned_project(self):
        response = self.client.get(reverse('item-create'), {'project': self.mine.id})

        self.assertEqual(response.context['default_project'], self.mine)

    def test_item_edit_form(self):
        response = self.client.get(reverse('item-edit', args=[self.my_item.id]))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_item_detail_move_modal(self):
        response = self.client.get(reverse('item-detail', args=[self.my_item.id]))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_item_parent_picker_only_offers_visible_items(self):
        response = self.client.get(reverse('item-detail', args=[self.my_item.id]))

        self.assertEqual(list(response.context['parent_items']), [])

    def test_change_list_filter_dropdown(self):
        response = self.client.get(reverse('changes'))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_change_create_form(self):
        response = self.client.get(reverse('change-create'))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_change_edit_form(self):
        change = Change.objects.create(
            title='Some change', project=self.mine, status=ChangeStatus.PLANNED,
            created_by=self.user,
        )
        response = self.client.get(reverse('change-edit', args=[change.id]))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_claude_queue_filter_dropdown(self):
        response = self.client.get(reverse('claude-queue-jobs'))

        self.assertOnlyVisibleProjects(response.context['projects'])

    def test_firstaid_project_selector(self):
        response = self.client.get(reverse('firstaid:home'))

        self.assertOnlyVisibleProjects(response.context['projects'])


class GitHubIssueBadgeVisibilityTests(ProjectVisibilityTestCase):
    """The sidebar badge and the list behind it must agree."""

    def setUp(self):
        super().setUp()
        for item in (self.my_item, self.their_item):
            item.status = ItemStatus.WORKING
            item.save()
            ExternalIssueMapping.objects.create(
                item=item, github_id=100 + item.id, number=100 + item.id,
                kind=ExternalIssueKind.ISSUE, state='open',
                html_url=f'https://github.com/o/r/issues/{100 + item.id}',
            )

    def test_badge_counts_only_visible_items(self):
        self.assertEqual(get_open_github_issues_count(self.user), 1)

    def test_context_processor_uses_the_requesting_user(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['open_github_issues_count'], 1)

    def test_open_issues_list_is_scoped(self):
        response = self.client.get(reverse('items-github-open'))

        item_ids = [entry['item_id'] for entry in response.context['issues_data']]
        self.assertEqual(item_ids, [self.my_item.id])

    def test_context_processor_returns_zero_for_anonymous_requests(self):
        request = type('Req', (), {'user': type('U', (), {'is_authenticated': False})()})()

        self.assertEqual(open_github_issues_count(request), {'open_github_issues_count': 0})


class MembershipManagementTests(ProjectVisibilityTestCase):
    """Assigning users to projects from the project detail page."""

    def test_add_member_makes_the_project_visible(self):
        response = self.client.post(
            reverse('project-add-member', args=[self.theirs.id]),
            {'user_id': self.user.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertIn(self.theirs, visible_projects_for(self.user))

    def test_remove_member_hides_the_project_again(self):
        response = self.client.post(
            reverse('project-remove-member', args=[self.mine.id]),
            {'user_id': self.user.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.mine, visible_projects_for(self.user))

    def test_removing_a_member_keeps_the_items(self):
        self.client.post(
            reverse('project-remove-member', args=[self.mine.id]),
            {'user_id': self.user.id},
        )

        self.assertTrue(Item.objects.filter(id=self.my_item.id).exists())

    def test_add_member_requires_a_user_id(self):
        response = self.client.post(reverse('project-add-member', args=[self.mine.id]), {})

        self.assertEqual(response.status_code, 400)

    def test_membership_endpoints_reject_get(self):
        response = self.client.get(reverse('project-add-member', args=[self.mine.id]))

        self.assertEqual(response.status_code, 405)

    def test_membership_endpoints_require_login(self):
        self.client.logout()
        response = self.client.post(
            reverse('project-add-member', args=[self.mine.id]), {'user_id': self.user.id},
        )

        self.assertEqual(response.status_code, 302)

    def test_project_detail_lists_the_members(self):
        response = self.client.get(reverse('project-detail', args=[self.mine.id]))

        self.assertEqual(list(response.context['members']), [self.user])


class NoNewPermissionSystemTests(ProjectVisibilityTestCase):
    """Acceptance criterion 5: this filters the UI, it does not gate access.

    Direct URLs keep working exactly as before — the feature removes noise from
    lists, it does not introduce object permissions.
    """

    def test_detail_of_an_unassigned_project_stays_reachable(self):
        response = self.client.get(reverse('project-detail', args=[self.theirs.id]))

        self.assertEqual(response.status_code, 200)

    def test_detail_of_an_item_in_an_unassigned_project_stays_reachable(self):
        response = self.client.get(reverse('item-detail', args=[self.their_item.id]))

        self.assertEqual(response.status_code, 200)

    def test_items_tab_of_an_unassigned_project_still_lists_its_items(self):
        response = self.client.get(reverse('project-items-tab', args=[self.theirs.id]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.their_item, response.context['page_obj'])

    def test_lists_still_require_login(self):
        """The pre-existing login requirement is untouched."""
        self.client.logout()

        self.assertEqual(self.client.get(reverse('projects')).status_code, 302)
        self.assertEqual(self.client.get(reverse('items-inbox')).status_code, 302)
