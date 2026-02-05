"""
Tests for custom template tags and filters.
"""
from django.test import TestCase
from core.templatetags.agira_filters import trim, render_markdown, safe_html, release_status_badge_class


class TrimFilterTestCase(TestCase):
    """Test the trim template filter"""

    def test_trim_with_none(self):
        """Test trim filter with None value"""
        result = trim(None)
        self.assertEqual(result, "")

    def test_trim_with_empty_string(self):
        """Test trim filter with empty string"""
        result = trim("")
        self.assertEqual(result, "")

    def test_trim_with_whitespace_only(self):
        """Test trim filter with whitespace-only string"""
        result = trim("   \n\t  ")
        self.assertEqual(result, "")

    def test_trim_with_leading_whitespace(self):
        """Test trim filter with leading whitespace"""
        result = trim("  hello")
        self.assertEqual(result, "hello")

    def test_trim_with_trailing_whitespace(self):
        """Test trim filter with trailing whitespace"""
        result = trim("hello  ")
        self.assertEqual(result, "hello")

    def test_trim_with_both_whitespace(self):
        """Test trim filter with leading and trailing whitespace"""
        result = trim("  hello world  ")
        self.assertEqual(result, "hello world")

    def test_trim_with_no_whitespace(self):
        """Test trim filter with no whitespace"""
        result = trim("hello")
        self.assertEqual(result, "hello")

    def test_trim_with_internal_whitespace(self):
        """Test trim filter preserves internal whitespace"""
        result = trim("  hello   world  ")
        self.assertEqual(result, "hello   world")


class RenderMarkdownFilterTestCase(TestCase):
    """Test the render_markdown template filter"""

    def test_render_markdown_with_none(self):
        """Test render_markdown filter with None value"""
        result = render_markdown(None)
        self.assertEqual(result, "")

    def test_render_markdown_with_empty_string(self):
        """Test render_markdown filter with empty string"""
        result = render_markdown("")
        self.assertEqual(result, "")

    def test_render_markdown_with_simple_text(self):
        """Test render_markdown filter with simple text"""
        result = render_markdown("Hello world")
        self.assertIn("Hello world", result)

    def test_render_markdown_with_heading(self):
        """Test render_markdown filter with heading"""
        result = render_markdown("## Test Heading")
        self.assertIn("<h2>Test Heading</h2>", result)

    def test_render_markdown_with_bold(self):
        """Test render_markdown filter with bold text"""
        result = render_markdown("This is **bold** text")
        self.assertIn("<strong>bold</strong>", result)

    def test_render_markdown_with_list(self):
        """Test render_markdown filter with list"""
        markdown = "* Item 1\n* Item 2"
        result = render_markdown(markdown)
        self.assertIn("<ul>", result)
        self.assertIn("<li>Item 1</li>", result)
        self.assertIn("<li>Item 2</li>", result)

    def test_render_markdown_sanitizes_script_tags(self):
        """Test render_markdown filter sanitizes script tags"""
        markdown = "Safe text\n\n<script>alert('XSS')</script>"
        result = render_markdown(markdown)
        self.assertNotIn("<script>", result)
        self.assertNotIn("alert", result)
        self.assertIn("Safe text", result)

    def test_render_markdown_sanitizes_javascript_urls(self):
        """Test render_markdown filter sanitizes javascript: URLs"""
        markdown = "[Click me](javascript:alert('XSS'))"
        result = render_markdown(markdown)
        self.assertNotIn("javascript:", result)

    def test_render_markdown_sanitizes_onerror_handlers(self):
        """Test render_markdown filter sanitizes event handlers"""
        markdown = '<img src="x" onerror="alert(\'XSS\')">'
        result = render_markdown(markdown)
        self.assertNotIn("onerror=", result)


class SafeHtmlFilterTestCase(TestCase):
    """Test the safe_html template filter"""

    def test_safe_html_with_none(self):
        """Test safe_html filter with None value"""
        result = safe_html(None)
        self.assertEqual(result, "")

    def test_safe_html_with_empty_string(self):
        """Test safe_html filter with empty string"""
        result = safe_html("")
        self.assertEqual(result, "")

    def test_safe_html_with_safe_tags(self):
        """Test safe_html filter preserves safe tags"""
        html = "<p>Hello <strong>world</strong></p>"
        result = safe_html(html)
        self.assertIn("<p>", result)
        self.assertIn("<strong>", result)

    def test_safe_html_removes_script_tags(self):
        """Test safe_html filter removes script tags"""
        html = "<p>Safe</p><script>alert('XSS')</script>"
        result = safe_html(html)
        self.assertNotIn("<script>", result)
        self.assertNotIn("alert", result)
        self.assertIn("<p>Safe</p>", result)

    def test_safe_html_removes_javascript_urls(self):
        """Test safe_html filter removes javascript: URLs"""
        html = '<a href="javascript:alert(\'XSS\')">Click</a>'
        result = safe_html(html)
        self.assertNotIn("javascript:", result)

    def test_safe_html_removes_event_handlers(self):
        """Test safe_html filter removes event handlers"""
        html = '<div onclick="alert(\'XSS\')">Click me</div>'
        result = safe_html(html)
        self.assertNotIn("onclick=", result)


class ReleaseStatusBadgeClassFilterTestCase(TestCase):
    """Test the release_status_badge_class template filter"""

    def test_planned_status(self):
        """Test badge class for Planned status"""
        result = release_status_badge_class('Planned')
        self.assertEqual(result, 'bg-info')

    def test_working_status(self):
        """Test badge class for Working status"""
        result = release_status_badge_class('Working')
        self.assertEqual(result, 'bg-warning')

    def test_closed_status(self):
        """Test badge class for Closed status"""
        result = release_status_badge_class('Closed')
        self.assertEqual(result, 'bg-success')

    def test_unknown_status(self):
        """Test badge class for unknown status defaults to secondary"""
        result = release_status_badge_class('UnknownStatus')
        self.assertEqual(result, 'bg-secondary')

    def test_none_status(self):
        """Test badge class for None value defaults to secondary"""
        result = release_status_badge_class(None)
        self.assertEqual(result, 'bg-secondary')

    def test_empty_status(self):
        """Test badge class for empty string defaults to secondary"""
        result = release_status_badge_class('')
        self.assertEqual(result, 'bg-secondary')
