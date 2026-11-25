"""Tests for item copy (service, UI endpoint, API) and the Change API used by the MCP server."""
import json
import os

from django.contrib.auth import get_user_model
from django.test import TestCase, Client

from core.models import (
    Change, ChangeStatus, Item, ItemRelation, ItemStatus, ItemType, Organisation,
    Project, RelationType, Release,
)
from core.services.item_copy import copy_item_to_project

User = get_user_model()


class ItemCopyTests(TestCase):
    def setUp(self):
        os.environ['CUSTOMGPT_API_SECRET'] = 'secret'
        self.user = User.objects.create_user(username='u', email='u@example.com', password='x', name='U')
        self.p1 = Project.objects.create(name='P1')
        self.p2 = Project.objects.create(name='P2')
        self.p3 = Project.objects.create(name='P3')
        self.type = ItemType.objects.create(name='Bug')
        self.item = Item.objects.create(
            project=self.p1, title='Shared bug', description='desc', user_input='orig',
            type=self.type, status=ItemStatus.WORKING, solution_description='sol', intern=True,
        )

    def tearDown(self):
        os.environ.pop('CUSTOMGPT_API_SECRET', None)

    def test_service_copies_and_links(self):
        copy = copy_item_to_project(self.item, self.p2, actor=self.user)
        self.assertNotEqual(copy.id, self.item.id)
        self.assertEqual(copy.project, self.p2)
        self.assertEqual((copy.title, copy.description, copy.user_input), ('Shared bug', 'desc', 'orig'))
        self.assertTrue(copy.intern)
        self.assertEqual(copy.status, ItemStatus.INBOX)
        self.assertEqual(copy.solution_description, '')
        self.assertTrue(ItemRelation.objects.filter(
            from_item=copy, to_item=self.item, relation_type=RelationType.RELATED).exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.project, self.p1)
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_organisation_dropped_if_not_client(self):
        org = Organisation.objects.create(name='Org')
        self.item.organisation = org
        self.item.save()
        self.assertIsNone(copy_item_to_project(self.item, self.p2).organisation)
        self.p3.clients.add(org)
        self.assertEqual(copy_item_to_project(self.item, self.p3).organisation, org)

    def test_ui_endpoint_multi_copy(self):
        c = Client()
        c.force_login(self.user)
        r = c.post(f'/items/{self.item.id}/copy-to-project/',
                   json.dumps({'target_project_ids': [self.p2.id, self.p3.id]}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()['copies']), 2)
        self.assertEqual(Item.objects.count(), 3)

    def test_ui_endpoint_rejects_same_project(self):
        c = Client()
        c.force_login(self.user)
        r = c.post(f'/items/{self.item.id}/copy-to-project/',
                   json.dumps({'target_project_ids': [self.p1.id]}), content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Item.objects.count(), 1)

    def test_api_copy(self):
        c = Client(HTTP_X_API_SECRET='secret')
        r = c.post(f'/api/customgpt/items/{self.item.id}/copy',
                   json.dumps({'target_project_ids': [self.p2.id, self.p3.id]}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['original_id'], self.item.id)
        self.assertEqual({x['project_id'] for x in r.json()['copies']}, {self.p2.id, self.p3.id})

    def test_api_copy_errors(self):
        c = Client(HTTP_X_API_SECRET='secret')
        url = f'/api/customgpt/items/{self.item.id}/copy'
        self.assertEqual(c.post(url, '{}', content_type='application/json').status_code, 400)
        self.assertEqual(c.post(url, json.dumps({'target_project_ids': [9999]}),
                                content_type='application/json').status_code, 404)
        self.assertEqual(c.post(url, json.dumps({'target_project_ids': [self.p1.id]}),
                                content_type='application/json').status_code, 400)


class ChangeApiTests(TestCase):
    def setUp(self):
        os.environ['CUSTOMGPT_API_SECRET'] = 'secret'
        self.c = Client(HTTP_X_API_SECRET='secret')
        self.p1 = Project.objects.create(name='P1')
        self.p2 = Project.objects.create(name='P2')
        self.type = ItemType.objects.create(name='Bug')
        self.item = Item.objects.create(project=self.p1, title='I', type=self.type)

    def tearDown(self):
        os.environ.pop('CUSTOMGPT_API_SECRET', None)

    def _post(self, url, data):
        return self.c.post(url, json.dumps(data), content_type='application/json')

    def _patch(self, url, data):
        return self.c.patch(url, json.dumps(data), content_type='application/json')

    def test_create_read_update(self):
        r = self._post(f'/api/customgpt/projects/{self.p1.id}/changes', {
            'title': 'Rollout', 'risk': 'High', 'mitigation': 'm',
            'planned_start': '2026-12-01T09:00:00+01:00', 'planned_date': '2026-12-01',
            'item_ids': [self.item.id],
        })
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual((body['status'], body['risk'], body['mitigation']), ('Draft', 'High', 'm'))
        self.assertEqual(body['item_ids'], [self.item.id])
        cid = body['id']

        g = self.c.get(f'/api/customgpt/changes/{cid}').json()
        self.assertEqual(g['title'], 'Rollout')
        self.assertIn('approvals', g)

        u = self._patch(f'/api/customgpt/changes/{cid}', {'status': 'Planned', 'planned_date': None})
        self.assertEqual(u.status_code, 200, u.content)
        self.assertEqual(u.json()['status'], 'Planned')
        self.assertIsNone(u.json()['planned_date'])
        self.assertEqual(u.json()['title'], 'Rollout')

    def test_validation(self):
        base = f'/api/customgpt/projects/{self.p1.id}/changes'
        self.assertEqual(self._post(base, {}).status_code, 400)
        self.assertEqual(self._post(base, {'title': 'x', 'status': 'Nope'}).status_code, 400)
        self.assertEqual(self._post(base, {'title': 'x', 'planned_start': 'garbage'}).status_code, 400)
        foreign = Release.objects.create(project=self.p2, name='R', version='1.0')
        self.assertEqual(self._post(base, {'title': 'x', 'release_id': foreign.id}).status_code, 400)
        self.assertEqual(Change.objects.count(), 0)
        self.assertEqual(self._post('/api/customgpt/projects/999/changes', {'title': 'x'}).status_code, 404)

    def test_project_immutable_and_404(self):
        ch = Change.objects.create(project=self.p1, title='c')
        self.assertEqual(self._patch(f'/api/customgpt/changes/{ch.id}', {'project_id': self.p2.id}).status_code, 400)
        self.assertEqual(self.c.get('/api/customgpt/changes/9999').status_code, 404)

    def test_list_filters_and_items_link(self):
        a = Change.objects.create(project=self.p1, title='a', status=ChangeStatus.DEPLOYED)
        Change.objects.create(project=self.p2, title='b')
        self.assertEqual(len(self.c.get('/api/customgpt/changes').json()), 2)
        self.assertEqual(len(self.c.get(f'/api/customgpt/changes?project_id={self.p1.id}').json()), 1)
        self.assertEqual(len(self.c.get('/api/customgpt/changes?open_only=true').json()), 1)
        self.assertEqual(self.c.get('/api/customgpt/changes?status=bad').status_code, 400)

        r = self._post(f'/api/customgpt/changes/{a.id}/items', {'add_item_ids': [self.item.id]})
        self.assertEqual(r.json()['item_ids'], [self.item.id])
        r = self._post(f'/api/customgpt/changes/{a.id}/items', {'remove_item_ids': [self.item.id]})
        self.assertEqual(r.json()['item_ids'], [])
        self.assertEqual(self._post(f'/api/customgpt/changes/{a.id}/items', {'add_item_ids': [9999]}).status_code, 400)

    def test_lookups(self):
        Release.objects.create(project=self.p1, name='R', version='1.0')
        Organisation.objects.create(name='O')
        self.assertEqual(len(self.c.get(f'/api/customgpt/projects/{self.p1.id}/releases').json()), 1)
        self.assertEqual(len(self.c.get('/api/customgpt/organisations').json()), 1)


class ItemDetailCopyModalTest(TestCase):
    def test_detail_page_renders_copy_modal(self):
        user = User.objects.create_user(username='v', email='v@example.com', password='x', name='V')
        p1 = Project.objects.create(name='P1')
        p2 = Project.objects.create(name='P2')
        p1.members.add(user)
        p2.members.add(user)
        item = Item.objects.create(project=p1, title='I', type=ItemType.objects.create(name='Bug'))
        c = Client()
        c.force_login(user)
        r = c.get(f'/items/{item.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="copyItemModal"')
        self.assertContains(r, 'copyTarget%d' % p2.id)
        self.assertNotContains(r, 'copyTarget%d"' % p1.id)
