import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
import cloudflare

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    
    APP_NAME: str = "Multi-Domain Edge Manager"
    LISTEN_PORT: int = 8000
    DATA_DIR: str = Field(default="data")
    SQLITE_PATH: str | None = None  # if None, will be data/app.db
    LOCAL_IP: str = "localhost"

    WEB_USERNAME: str = "admin"
    WEB_PASSWORD: str = "admin"

    # Nginx (optional)
    NGINX_HTTP_CONF_PATH: str = "/etc/nginx/conf.d/edge_http.conf"
    NGINX_STREAM_CONF_PATH: str = "/etc/nginx/stream.d/edge_stream.conf"
    NGINX_RELOAD_CMD: str = "nginx -s reload"

    # DNS provider default (Cloudflare)
    DEFAULT_DNS_PROVIDER: str = "cloudflare"
    CLOUDFLARE_API_TOKEN: str = ""

    CF_ORIGIN_CA_KEY: str = ""
    CF_CERT_DAYS: int = 365 * 15        # 5-year Origin-CA cert
    CF_RENEW_SOON: int = 30             # renew if <30 days to expiry
    CF_SSL_DIR: str = "/etc/nginx/ssl"

    CF: cloudflare.Cloudflare | None = None


    ENABLE_NGINX: bool = False  # set True when ready
    ENABLE_CLOUDFLARE: bool = False  # set True when ready

    def model_post_init(self, __context):
        self.CF = cloudflare.Cloudflare(
            api_token=self.CLOUDFLARE_API_TOKEN,
            user_service_key=self.CF_ORIGIN_CA_KEY
        )

    def db_path(self) -> str:
        if self.SQLITE_PATH:
            return self.SQLITE_PATH
        d = Path(self.DATA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "app.db")

settings = Settings()
