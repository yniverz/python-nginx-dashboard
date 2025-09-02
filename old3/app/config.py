import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
    APP_PORT: int = int(os.getenv("APP_PORT", "8080"))
    DB_PATH: str = os.getenv("DB_PATH", "var/data/app.sqlite")
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "changeme-admin")

    NGINX_HTTP_CONF: str = os.getenv("NGINX_HTTP_CONF", "var/nginx/reverse-proxy-http.conf")
    NGINX_STREAM_CONF: str = os.getenv("NGINX_STREAM_CONF", "var/nginx/reverse-proxy-stream.conf")
    NGINX_CMD: str = os.getenv("NGINX_CMD", "nginx")
    NGINX_RELOAD_CMD: str = os.getenv("NGINX_RELOAD_CMD", "nginx -s reload")

    CF_API_BASE: str = os.getenv("CF_API_BASE", "https://api.cloudflare.com/client/v4")
    CF_API_TOKEN: str = os.getenv("CF_API_TOKEN", "")
    CF_ORIGIN_CA_BASE: str = os.getenv("CF_ORIGIN_CA_BASE", "https://api.cloudflare.com/client/v4")
    CF_ORIGIN_CA_KEY: str = os.getenv("CF_ORIGIN_CA_KEY", "")
    DEFAULT_ACME_EMAIL: str = os.getenv("DEFAULT_ACME_EMAIL", "")

    VAR_DIR: str = "var"
    CERTS_DIR: str = os.path.join(VAR_DIR, "certs")

settings = Settings()

# ensure directories exist early
os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(settings.NGINX_HTTP_CONF), exist_ok=True)
os.makedirs(os.path.dirname(settings.NGINX_STREAM_CONF), exist_ok=True)
os.makedirs(settings.CERTS_DIR, exist_ok=True)
