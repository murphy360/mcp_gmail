"""Google OAuth2 authentication for Gmail API."""

import json
import logging
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

TOKEN_FILE = "token.json"
CLIENT_SECRETS_FILE = "client_secrets.json"


class GmailAuth:
    """Handles Gmail OAuth2 authentication."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.credentials_path = Path(self.settings.credentials_path)
        self.credentials_path.mkdir(parents=True, exist_ok=True)
        self._credentials: Optional[Credentials] = None

    @property
    def token_path(self) -> Path:
        """Path to the stored OAuth token."""
        return self.credentials_path / TOKEN_FILE

    @property
    def client_secrets_path(self) -> Path:
        """Path to the client secrets file."""
        return self.credentials_path / CLIENT_SECRETS_FILE

    def create_client_secrets(self) -> None:
        """Create client_secrets.json from environment variables."""
        client_config = {
            "installed": {
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost:8080", "urn:ietf:wg:oauth:2.0:oob"],
            }
        }
        with open(self.client_secrets_path, "w", encoding="utf-8") as f:
            json.dump(client_config, f, indent=2)
        logger.info(f"Created client secrets file at {self.client_secrets_path}")

    def get_credentials(self) -> Credentials:
        """Get valid OAuth credentials, refreshing or re-authenticating as needed."""
        if self._credentials and self._credentials.valid:
            return self._credentials

        # Try to load existing token
        if self.token_path.exists():
            logger.info("Loading existing credentials from token file")
            self._credentials = Credentials.from_authorized_user_file(
                str(self.token_path), self.settings.gmail_scopes
            )

        # Refresh if expired
        if self._credentials and self._credentials.expired and self._credentials.refresh_token:
            logger.info("Refreshing expired credentials")
            try:
                self._credentials.refresh(Request())
                self._save_credentials()
                return self._credentials
            except Exception as e:
                logger.warning(f"Failed to refresh credentials: {e}")
                self._credentials = None

        # Need to re-authenticate
        if not self._credentials or not self._credentials.valid:
            raise AuthenticationRequiredError(
                "Authentication required. Run 'mcp-gmail-auth' to authenticate."
            )

        return self._credentials

    def authenticate_interactive(self, headless: bool = False) -> Credentials:
        """Run interactive OAuth flow to get new credentials.
        
        Args:
            headless: If True, print the auth URL for manual copy/paste (for Docker/SSH)
        """
        # Ensure client secrets exist
        if not self.client_secrets_path.exists():
            self.create_client_secrets()

        logger.info("Starting OAuth authentication flow")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_path),
            self.settings.gmail_scopes,
        )

        if headless:
            # For Docker/headless environments - manual flow
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
            
            print("\n" + "=" * 60)
            print("Open this URL in your browser to authenticate:")
            print("=" * 60)
            print(f"\n{auth_url}\n")
            print("=" * 60)
            
            code = input("Enter the authorization code: ").strip()
            flow.fetch_token(code=code)
            self._credentials = flow.credentials
        else:
            # Run local server for OAuth callback
            self._credentials = flow.run_local_server(
                port=8080,
                prompt="consent",
                access_type="offline",
            )

        self._save_credentials()
        logger.info("Authentication successful!")
        return self._credentials

    def _save_credentials(self) -> None:
        """Save credentials to token file."""
        if self._credentials:
            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(self._credentials.to_json())
            logger.info(f"Saved credentials to {self.token_path}")

    def is_authenticated(self) -> bool:
        """Check if valid credentials exist."""
        try:
            self.get_credentials()
            return True
        except AuthenticationRequiredError:
            return False

    def revoke(self) -> None:
        """Revoke and delete stored credentials."""
        if self.token_path.exists():
            self.token_path.unlink()
            logger.info("Deleted stored credentials")
        self._credentials = None


class AuthenticationRequiredError(Exception):
    """Raised when authentication is required but not available."""

    pass


def setup_oauth() -> None:
    """CLI entry point for OAuth setup."""
    import sys
    import os

    logging.basicConfig(level=logging.INFO)

    # Check if running in headless mode (Docker, SSH, no display)
    headless = os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")
    if not headless:
        # Auto-detect headless environment
        headless = not os.environ.get("DISPLAY") and sys.platform != "win32" and sys.platform != "darwin"

    print("=" * 60)
    print("Gmail MCP Server - OAuth Setup")
    print("=" * 60)
    print()
    
    if headless:
        print("Running in HEADLESS mode (manual URL copy/paste)")
    else:
        print("This will open a browser window for Google authentication.")
    
    print("Make sure you have configured GOOGLE_CLIENT_ID and")
    print("GOOGLE_CLIENT_SECRET in your .env file.")
    print()

    try:
        settings = get_settings()
    except Exception as e:
        print(f"Error loading settings: {e}")
        print("Make sure your .env file is configured correctly.")
        sys.exit(1)

    auth = GmailAuth(settings)

    try:
        creds = auth.authenticate_interactive(headless=headless)
        print()
        print("✓ Authentication successful!")
        print(f"✓ Token saved to: {auth.token_path}")
        print()
        print("You can now start the MCP server with: mcp-gmail")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_oauth()
