"""
config.py

Configuration management for engmemory.
Loads environment variables from .env file or system environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


class Config:
    """Configuration singleton for engmemory."""
    
    _instance = None
    _loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._loaded:
            self.load()
    
    def load(self, env_file: Optional[str] = None):
        """Load configuration from environment or .env file."""
        if HAS_DOTENV:
            # Try multiple .env locations
            if env_file:
                load_dotenv(env_file)
            else:
                # Try current directory
                load_dotenv()
                # Try home directory
                home_env = Path.home() / "engmemory.env"
                if home_env.exists():
                    load_dotenv(home_env)
        
        self._loaded = True
    
    # Azure
    @property
    def azure_subscription_id(self) -> Optional[str]:
        return os.getenv("AZURE_SUBSCRIPTION_ID")
    
    @property
    def azure_resource_group(self) -> str:
        return os.getenv("AZURE_RESOURCE_GROUP", "engmemory-rg")
    
    @property
    def azure_location(self) -> str:
        return os.getenv("AZURE_LOCATION", "eastus")
    
    # Azure AI Search
    @property
    def azure_search_endpoint(self) -> Optional[str]:
        return os.getenv("AZURE_SEARCH_ENDPOINT")
    
    @property
    def azure_search_index(self) -> str:
        return os.getenv("AZURE_SEARCH_INDEX", "commits")
    
    @property
    def azure_search_admin_key(self) -> Optional[str]:
        return os.getenv("AZURE_SEARCH_ADMIN_KEY")
    
    # Azure Blob Storage
    @property
    def azure_storage_account(self) -> Optional[str]:
        return os.getenv("AZURE_STORAGE_ACCOUNT")
    
    @property
    def azure_storage_endpoint(self) -> Optional[str]:
        return os.getenv("AZURE_STORAGE_ENDPOINT")
    
    @property
    def azure_storage_container(self) -> str:
        return os.getenv("AZURE_STORAGE_CONTAINER", "commits")
    
    @property
    def azure_storage_key(self) -> Optional[str]:
        return os.getenv("AZURE_STORAGE_KEY")
    
    # OpenRouter / LLM
    @property
    def openrouter_api_key(self) -> Optional[str]:
        return os.getenv("OPENROUTER_API_KEY")
    
    @property
    def openrouter_model(self) -> str:
        return os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    
    # Groq
    @property
    def groq_api_key(self) -> Optional[str]:
        return os.getenv("GROQ_API_KEY")
    
    @property
    def groq_model(self) -> str:
        return os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    
    @property
    def openai_api_key(self) -> Optional[str]:
        """Fallback to OpenAI if OpenRouter not configured."""
        return os.getenv("OPENAI_API_KEY")
    
    @property
    def openai_model(self) -> str:
        return os.getenv("OPENAI_MODEL", "gpt-4")
    
    # Microsoft Teams (Graph API)
    @property
    def teams_tenant_id(self) -> Optional[str]:
        return os.getenv("TEAMS_TENANT_ID")
    
    @property
    def teams_client_id(self) -> Optional[str]:
        return os.getenv("TEAMS_CLIENT_ID")
    
    @property
    def teams_client_secret(self) -> Optional[str]:
        return os.getenv("TEAMS_CLIENT_SECRET")
    
    @property
    def teams_team_id(self) -> Optional[str]:
        """The Team ID where channels will be created."""
        return os.getenv("TEAMS_TEAM_ID")
    
    @property
    def teams_webhook_url(self) -> Optional[str]:
        """Public HTTPS URL for Graph API subscription notifications."""
        return os.getenv("TEAMS_WEBHOOK_URL")
    
    # Slack
    @property
    def slack_bot_token(self) -> Optional[str]:
        """Slack Bot User OAuth Token (xoxb-...)."""
        return os.getenv("SLACK_BOT_TOKEN")
    
    @property
    def slack_signing_secret(self) -> Optional[str]:
        """Slack app signing secret for verifying webhooks."""
        return os.getenv("SLACK_SIGNING_SECRET")
    
    @property
    def slack_app_token(self) -> Optional[str]:
        """Slack app-level token for Socket Mode (optional)."""
        return os.getenv("SLACK_APP_TOKEN")
    
    # Repo
    @property
    def repo_path(self) -> Optional[str]:
        """Path to the git repository to manage."""
        return os.getenv("ENGMEMORY_REPO_PATH")

    @property
    def repo_url(self) -> Optional[str]:
        """Git URL of the project repo (for cloning workspaces)."""
        return os.getenv("ENGMEMORY_REPO_URL")

    @property
    def project_root(self) -> Optional[str]:
        """Root directory where ticket workspaces are created."""
        return os.getenv("ENGMEMORY_PROJECT_ROOT")
    
    # Jira
    @property
    def jira_domain(self) -> Optional[str]:
        return os.getenv("JIRA_DOMAIN")
    
    @property
    def jira_board_id(self) -> Optional[str]:
        return os.getenv("JIRA_BOARD_ID")
    
    @property
    def jira_email(self) -> Optional[str]:
        return os.getenv("JIRA_EMAIL")
    
    @property
    def jira_api_token(self) -> Optional[str]:
        return os.getenv("JIRA_API_TOKEN")
    
    # Helpers
    def is_azure_configured(self) -> bool:
        """Check if Azure services are configured."""
        return bool(
            self.azure_search_endpoint and
            self.azure_search_admin_key and
            self.azure_storage_endpoint
        )
    
    def is_teams_configured(self) -> bool:
        """Check if Teams integration is configured."""
        return bool(
            self.teams_tenant_id and
            self.teams_client_id and
            self.teams_client_secret and
            self.teams_team_id
        )
    
    def is_llm_configured(self) -> bool:
        """Check if any LLM service is configured."""
        return bool(self.groq_api_key or self.openrouter_api_key or self.openai_api_key)


# Global config instance
config = Config()
