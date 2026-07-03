"""Tests for the hybrid Item.suggested_model classifier (#834)."""

from unittest.mock import Mock

from django.test import TestCase

from core.models import ClaudeQueueJobModel, Item, ItemType, Project
from core.services.claude_queue.model_classifier import (
    ModelClassifierService,
    classify_by_heuristics,
)


class ClassifyByHeuristicsTestCase(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='task', name='Task')

    def _item(self, title='Some title', description=''):
        return Item.objects.create(
            title=title, description=description, project=self.project, type=self.item_type,
        )

    def test_migration_keyword_triggers_opus(self):
        item = self._item(description='This needs a database migration to add a column.')
        self.assertEqual(classify_by_heuristics(item), ClaudeQueueJobModel.OPUS)

    def test_security_keyword_triggers_opus(self):
        item = self._item(description='Fix an authentication bypass vulnerability in login.')
        self.assertEqual(classify_by_heuristics(item), ClaudeQueueJobModel.OPUS)

    def test_large_scope_keyword_triggers_opus(self):
        item = self._item(description='Refactor the billing architecture across the codebase.')
        self.assertEqual(classify_by_heuristics(item), ClaudeQueueJobModel.OPUS)

    def test_many_file_mentions_trigger_opus(self):
        item = self._item(
            description='Update views.py, models.py and templates/item_form.html consistently.'
        )
        self.assertEqual(classify_by_heuristics(item), ClaudeQueueJobModel.OPUS)

    def test_clear_scoped_description_returns_sonnet(self):
        item = self._item(
            description='Change the label on the export button from "Export" to "Download CSV".'
        )
        self.assertEqual(classify_by_heuristics(item), ClaudeQueueJobModel.SONNET)

    def test_short_vague_description_is_ambiguous(self):
        item = self._item(description='Fix the bug.')
        self.assertIsNone(classify_by_heuristics(item))

    def test_empty_description_is_ambiguous(self):
        item = self._item(description='')
        self.assertIsNone(classify_by_heuristics(item))


class ModelClassifierServiceTestCase(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='task', name='Task')

    def _item(self, title='Some title', description=''):
        return Item.objects.create(
            title=title, description=description, project=self.project, type=self.item_type,
        )

    def test_confident_heuristic_skips_haiku_call(self):
        agent_service = Mock()
        service = ModelClassifierService(agent_service=agent_service)
        item = self._item(description='This needs a database migration for the new field.')

        result = service.classify(item)

        self.assertEqual(result, ClaudeQueueJobModel.OPUS)
        agent_service.execute_agent.assert_not_called()

    def test_ambiguous_heuristic_falls_back_to_haiku_opus(self):
        agent_service = Mock()
        agent_service.execute_agent.return_value = 'opus'
        service = ModelClassifierService(agent_service=agent_service)
        item = self._item(description='Fix it.')

        result = service.classify(item)

        self.assertEqual(result, ClaudeQueueJobModel.OPUS)
        agent_service.execute_agent.assert_called_once()
        self.assertEqual(
            agent_service.execute_agent.call_args.kwargs['filename'],
            ModelClassifierService.HAIKU_AGENT_FILENAME,
        )

    def test_ambiguous_heuristic_falls_back_to_haiku_sonnet(self):
        agent_service = Mock()
        agent_service.execute_agent.return_value = 'sonnet'
        service = ModelClassifierService(agent_service=agent_service)
        item = self._item(description='Fix it.')

        self.assertEqual(service.classify(item), ClaudeQueueJobModel.SONNET)

    def test_haiku_failure_defaults_to_sonnet_not_opus(self):
        agent_service = Mock()
        agent_service.execute_agent.side_effect = RuntimeError('provider not configured')
        service = ModelClassifierService(agent_service=agent_service)
        item = self._item(description='Fix it.')

        # A misclassification must never silently burn opus.
        self.assertEqual(service.classify(item), ClaudeQueueJobModel.SONNET)

    def test_haiku_unexpected_response_defaults_to_sonnet(self):
        agent_service = Mock()
        agent_service.execute_agent.return_value = 'maybe opus?'
        service = ModelClassifierService(agent_service=agent_service)
        item = self._item(description='Fix it.')

        self.assertEqual(service.classify(item), ClaudeQueueJobModel.SONNET)
