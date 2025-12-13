"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google OAuth
    google_client_id: str = Field(..., description="Google OAuth Client ID")
    google_client_secret: str = Field(..., description="Google OAuth Client Secret")

    # Server Configuration
    mcp_server_host: str = Field(default="0.0.0.0", description="MCP server host")
    mcp_server_port: int = Field(default=8000, description="MCP server port")

    # Home Assistant
    ha_webhook_url: Optional[str] = Field(
        default=None, description="Home Assistant webhook URL"
    )
    ha_long_lived_token: Optional[str] = Field(
        default=None, description="Home Assistant long-lived access token"
    )

    # Paths
    credentials_path: Path = Field(
        default=Path("./credentials"), description="Path to store OAuth credentials"
    )
    categories_config: Path = Field(
        default=Path("./config/categories.yaml"), description="Path to categories config"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    # Gmail API Scopes
    gmail_scopes: list[str] = Field(
        default=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.modify",  # For marking as read/unread
        ],
        description="Gmail API scopes",
    )


class CategoryMatcher:
    """Matcher configuration for a category."""

    def __init__(
        self,
        senders: list[str] | None = None,
        subjects: list[str] | None = None,
        labels: list[str] | None = None,
    ):
        self.senders = [s.lower() for s in (senders or [])]
        self.subjects = [s.lower() for s in (subjects or [])]
        self.labels = labels or []


class Category:
    """Email category definition."""

    def __init__(
        self,
        key: str,
        name: str,
        description: str = "",
        priority: str = "normal",
        matchers: dict | None = None,
    ):
        self.key = key
        self.name = name
        self.description = description
        self.priority = priority
        self.matcher = CategoryMatcher(**(matchers or {}))


class CategoriesConfig:
    """Categories configuration loaded from YAML."""

    def __init__(self, config_path: Path):
        self.categories: dict[str, Category] = {}
        self.default_category: Category = Category(
            key="general", name="General", priority="normal"
        )
        self.summary_settings: dict = {}
        self._load_config(config_path)

    def _load_config(self, config_path: Path) -> None:
        """Load categories from YAML file."""
        if not config_path.exists():
            return

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return

        # Load categories
        for key, cat_data in data.get("categories", {}).items():
            self.categories[key] = Category(
                key=key,
                name=cat_data.get("name", key),
                description=cat_data.get("description", ""),
                priority=cat_data.get("priority", "normal"),
                matchers=cat_data.get("matchers", {}),
            )

        # Load default category
        if "default_category" in data:
            self.default_category = Category(
                key="default",
                name=data["default_category"].get("name", "General"),
                priority=data["default_category"].get("priority", "normal"),
            )

        # Load summary settings
        self.summary_settings = data.get("summary", {})

    def get_all_categories(self) -> list[Category]:
        """Get all categories sorted by priority."""
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        return sorted(
            self.categories.values(),
            key=lambda c: priority_order.get(c.priority, 2),
        )


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()


def get_categories_config(settings: Settings | None = None) -> CategoriesConfig:
    """Get categories configuration."""
    if settings is None:
        settings = get_settings()
    return CategoriesConfig(settings.categories_config)
