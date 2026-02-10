"""
Application configuration using Pydantic settings.
Loads configuration from environment variables and .env file.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
import cloudflare

class Settings(BaseSettings):
    """Application settings with environment variable support."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Application settings
    APP_NAME: str = "Multi-Domain Edge Manager"
    ROOT_PATH: str = ""  # For reverse proxy deployments
    LISTEN_PORT: int = 8000
    DATA_DIR: str = Field(default="data")
    SQLITE_PATH: str | None = None  # Override default database path
    SESSION_SECRET: str | None = None  # Random string for secure session cookies

    # Web interface authentication
    WEB_USERNAME: str = "admin"
    WEB_PASSWORD: str = "admin"

    # Nginx configuration paths and commands
    NGINX_HTTP_CONF_PATH: str = "/etc/nginx/conf.d/edge_http.conf"
    NGINX_STREAM_CONF_PATH: str = "/etc/nginx/stream.d/edge_stream.conf"
    NGINX_RELOAD_CMD: str = "nginx -s reload"

    # Cloudflare DNS and SSL settings
    DEFAULT_DNS_PROVIDER: str = "cloudflare"
    CLOUDFLARE_API_TOKEN: str = ""
    CF_ORIGIN_CA_KEY: str = ""  # For Origin CA certificates
    CF_CERT_DAYS: int = 365 * 15  # 15-year Origin-CA certificate validity
    CF_RENEW_SOON: int = 30  # Renew certificates when <30 days to expiry
    CF_SSL_DIR: str = "/etc/nginx/ssl"

    # Cloudflare client instance (initialized in post_init)
    CF: cloudflare.Cloudflare | None = None

    # Let's Encrypt SSL settings
    LE_EMAIL: str = ""  # Email for Let's Encrypt account registration
    LE_SSL_DIR: str = "/etc/letsencrypt"  # Certbot configuration directory
    LE_ACME_DIR: str = "/var/www/challenges"  # Directory for ACME challenge files
    LE_RENEW_SOON: int = 30  # Renew certificates when <30 days to expiry
    LE_PRODUCTION: bool = False  # Use Let's Encrypt production server (vs staging)

    # Network settings
    LOCAL_IP: str = "localhost"

    # Feature flags
    DEBUG_MODE: bool = True
    ENABLE_NGINX: bool = False  # Enable nginx configuration generation
    ENABLE_CLOUDFLARE: bool = False  # Enable Cloudflare DNS/SSL management
    ENABLE_LETSENCRYPT: bool = False  # Enable Let's Encrypt SSL management
    USE_SSL: bool = False  # Enable HTTPS using self-signed certificates

    def model_post_init(self, __context):
        """Initialize Cloudflare client after settings are loaded."""
        self.CF = cloudflare.Cloudflare(
            api_token=self.CLOUDFLARE_API_TOKEN,
            user_service_key=self.CF_ORIGIN_CA_KEY
        )

    def db_path(self) -> str:
        """Get the database file path, creating the directory if needed."""
        if self.SQLITE_PATH:
            return self.SQLITE_PATH
        d = Path(self.DATA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "app.db")

# Global settings instance
settings = Settings()
