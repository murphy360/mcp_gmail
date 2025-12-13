"""Tests for configuration module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_gmail.config import CategoriesConfig, Category, CategoryMatcher, Settings


class TestCategoryMatcher:
    """Tests for CategoryMatcher class."""

    def test_empty_matcher(self):
        """Test matcher with no patterns."""
        matcher = CategoryMatcher()
        assert matcher.senders == []
        assert matcher.subjects == []
        assert matcher.labels == []

    def test_matcher_lowercases_patterns(self):
        """Test that patterns are lowercased."""
        matcher = CategoryMatcher(
            senders=["Test@Example.com"],
            subjects=["URGENT Subject"],
        )
        assert matcher.senders == ["test@example.com"]
        assert matcher.subjects == ["urgent subject"]

    def test_matcher_preserves_labels(self):
        """Test that labels are preserved as-is."""
        matcher = CategoryMatcher(labels=["Work", "Important"])
        assert matcher.labels == ["Work", "Important"]


class TestCategory:
    """Tests for Category class."""

    def test_basic_category(self):
        """Test basic category creation."""
        cat = Category(
            key="test",
            name="Test Category",
            description="A test category",
            priority="high",
        )
        assert cat.key == "test"
        assert cat.name == "Test Category"
        assert cat.priority == "high"
        assert cat.matcher is not None

    def test_category_with_matchers(self):
        """Test category with matcher patterns."""
        cat = Category(
            key="work",
            name="Work",
            matchers={
                "senders": ["@company.com"],
                "subjects": ["project"],
            },
        )
        assert "@company.com" in cat.matcher.senders
        assert "project" in cat.matcher.subjects


class TestCategoriesConfig:
    """Tests for CategoriesConfig class."""

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from nonexistent file."""
        config = CategoriesConfig(tmp_path / "nonexistent.yaml")
        assert config.categories == {}
        assert config.default_category.name == "General"

    def test_load_valid_config(self, tmp_path):
        """Test loading valid YAML config."""
        config_file = tmp_path / "categories.yaml"
        config_file.write_text("""
categories:
  test:
    name: "Test Category"
    description: "A test"
    priority: high
    matchers:
      senders:
        - "@test.com"
      subjects:
        - "test"

default_category:
  name: "Default"
  priority: low

summary:
  daily_lookback_hours: 48
""")
        config = CategoriesConfig(config_file)
        
        assert "test" in config.categories
        assert config.categories["test"].name == "Test Category"
        assert config.categories["test"].priority == "high"
        assert config.default_category.name == "Default"
        assert config.summary_settings.get("daily_lookback_hours") == 48

    def test_get_all_categories_sorted(self, tmp_path):
        """Test categories are sorted by priority."""
        config_file = tmp_path / "categories.yaml"
        config_file.write_text("""
categories:
  low_priority:
    name: "Low"
    priority: low
  critical:
    name: "Critical"
    priority: critical
  normal:
    name: "Normal"
    priority: normal
""")
        config = CategoriesConfig(config_file)
        cats = config.get_all_categories()
        
        assert cats[0].priority == "critical"
        assert cats[-1].priority == "low"


class TestSettings:
    """Tests for Settings class."""

    def test_settings_from_env(self, monkeypatch):
        """Test loading settings from environment."""
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("MCP_SERVER_PORT", "9000")
        
        settings = Settings()
        
        assert settings.google_client_id == "test-client-id"
        assert settings.google_client_secret == "test-secret"
        assert settings.mcp_server_port == 9000

    def test_settings_defaults(self, monkeypatch):
        """Test default values."""
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
        
        settings = Settings()
        
        assert settings.mcp_server_host == "0.0.0.0"
        assert settings.mcp_server_port == 8000
        assert settings.log_level == "INFO"
