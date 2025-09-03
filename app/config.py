import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
import cloudflare

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    
    APP_NAME: str = "Multi-Domain Edge Manager"
    DATA_DIR: str = Field(default="data")
    SQLITE_PATH: str | None = None  # if None, will be data/app.db
    LOCAL_IP: str = "localhost"

    WEB_USERNAME: str = "admin"
    WEB_PASSWORD: str = "admin"

    # Nginx (optional)
    NGINX_HTTP_CONF_PATH: str = "/etc/nginx/conf.d/edge_http.conf"
    NGINX_STREAM_CONF_PATH: str = "/etc/nginx/stream.d/edge_stream.conf"
    NGINX_SSL_PATH: str = "/etc/nginx/ssl"
    NGINX_RELOAD_CMD: str = "nginx -s reload"
    ENABLE_NGINX: bool = False  # set True when ready

    # DNS provider default (Cloudflare)
    DEFAULT_DNS_PROVIDER: str = "cloudflare"
    CLOUDFLARE_API_TOKEN: str = ""

    CF_ORIGIN_CA_KEY: str = ""
    CF_REQUESTED_VALIDITY_DAYS: int = 5475  # ~15y
    CF_KEY_TYPE: str = "rsa"  # "rsa" or "ecdsa"
    CF_RSA_BITS: int = 2048  # 2048 or 4096

    CF: cloudflare.Cloudflare | None = None

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
