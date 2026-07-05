"""
Tests for AI Model token-price parsing, persistence and display.

Regression coverage for issue #852: saved input/output token prices were
rendered as ``0,00`` in the ``/ai-providers/<id>/`` view because Django
localized the DecimalField values with a German comma, which an HTML
``<input type="number">`` cannot display.
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from core.models import AIProvider, AIModel, User
from core.services.ai.pricing import parse_price_input


class ParsePriceInputTestCase(TestCase):
    """Unit tests for the locale-robust price parser."""

    def test_parses_technical_format(self):
        self.assertEqual(parse_price_input('0.01'), Decimal('0.01'))

    def test_parses_german_format(self):
        self.assertEqual(parse_price_input('0,01'), Decimal('0.01'))

    def test_parses_larger_german_value(self):
        self.assertEqual(parse_price_input('15,50'), Decimal('15.50'))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_price_input(''))

    def test_whitespace_returns_none(self):
        self.assertIsNone(parse_price_input('   '))

    def test_none_returns_none(self):
        self.assertIsNone(parse_price_input(None))

    def test_invalid_value_raises(self):
        with self.assertRaises(ValueError):
            parse_price_input('abc')


class AIModelPriceDisplayTestCase(TestCase):
    """Integration tests for loading, displaying and saving model prices."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='pass',
            is_superuser=True,
        )
        self.client.force_login(self.user)

        self.provider = AIProvider.objects.create(
            name='Test Provider',
            provider_type='OpenAI',
            api_key='test-key',
            active=True,
        )
        self.model = AIModel.objects.create(
            provider=self.provider,
            name='Test Model',
            model_id='test-model',
            input_price_per_1m_tokens=Decimal('0.5000'),
            output_price_per_1m_tokens=Decimal('1.5000'),
        )

    def test_saved_prices_render_with_dot_separator(self):
        """Stored non-zero prices must appear in the number inputs (not as 0,00)."""
        url = reverse('ai-provider-detail', args=[self.provider.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Values must be rendered with a dot so <input type="number"> displays them.
        self.assertIn('value="0.5000"', content)
        self.assertIn('value="1.5000"', content)

        # They must NOT be localized with a comma inside the value attribute.
        self.assertNotIn('value="0,5000"', content)
        self.assertNotIn('value="1,5000"', content)

    def test_update_field_accepts_technical_format(self):
        url = reverse('ai-model-update-field', args=[self.provider.id, self.model.id])
        response = self.client.post(url, {
            'field': 'input_price_per_1m_tokens',
            'value': '2.25',
        })
        self.assertEqual(response.status_code, 204)
        self.model.refresh_from_db()
        self.assertEqual(self.model.input_price_per_1m_tokens, Decimal('2.25'))

    def test_update_field_accepts_german_format(self):
        url = reverse('ai-model-update-field', args=[self.provider.id, self.model.id])
        response = self.client.post(url, {
            'field': 'output_price_per_1m_tokens',
            'value': '3,75',
        })
        self.assertEqual(response.status_code, 204)
        self.model.refresh_from_db()
        self.assertEqual(self.model.output_price_per_1m_tokens, Decimal('3.75'))

    def test_saved_price_survives_reload(self):
        """Change a price and confirm it is displayed unchanged after reload."""
        update_url = reverse('ai-model-update-field', args=[self.provider.id, self.model.id])
        self.client.post(update_url, {
            'field': 'input_price_per_1m_tokens',
            'value': '0,01',
        })

        detail_url = reverse('ai-provider-detail', args=[self.provider.id])
        content = self.client.get(detail_url).content.decode()
        self.assertIn('value="0.0100"', content)

    def test_create_model_accepts_german_format(self):
        url = reverse('ai-model-create', args=[self.provider.id])
        response = self.client.post(url, {
            'name': 'New Model',
            'model_id': 'new-model',
            'input_price_per_1m_tokens': '0,02',
            'output_price_per_1m_tokens': '0,04',
        })
        self.assertEqual(response.status_code, 200)
        created = AIModel.objects.get(model_id='new-model')
        self.assertEqual(created.input_price_per_1m_tokens, Decimal('0.02'))
        self.assertEqual(created.output_price_per_1m_tokens, Decimal('0.04'))

    def test_update_field_rejects_negative(self):
        url = reverse('ai-model-update-field', args=[self.provider.id, self.model.id])
        response = self.client.post(url, {
            'field': 'input_price_per_1m_tokens',
            'value': '-1.0',
        })
        self.assertEqual(response.status_code, 400)
