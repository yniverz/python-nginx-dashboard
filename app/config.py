import os
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path

class Settings(BaseSettings):
    APP_NAME: str = "Multi-Domain Edge Manager"
    DATA_DIR: str = Field(default="data")
    SQLITE_PATH: str | None = None  # if None, will be data/app.db
    LOCAL_IP: str = os.getenv("LOCAL_IP", "localhost")

    WEB_USERNAME: str = os.getenv("WEB_USERNAME", "admin")
    WEB_PASSWORD: str = os.getenv("WEB_PASSWORD", "admin")

    # Nginx (optional)
    NGINX_HTTP_CONF_PATH: str = "/etc/nginx/conf.d/edge_http.conf"
    NGINX_STREAM_CONF_PATH: str = "/etc/nginx/stream.d/edge_stream.conf"
    NGINX_SSL_PATH: str = "/etc/nginx/ssl"
    NGINX_RELOAD_CMD: str = "nginx -s reload"
    ENABLE_NGINX: bool = False  # set True when ready

    # DNS provider default (Cloudflare)
    DEFAULT_DNS_PROVIDER: str = "cloudflare"
    CLOUDFLARE_API_TOKEN: str = os.getenv("CLOUDFLARE_API_TOKEN", "")

    CF_ORIGIN_CA_KEY: str = os.getenv("CF_ORIGIN_CA_KEY", "")
    CF_REQUESTED_VALIDITY_DAYS: int = int(os.getenv("CF_REQUESTED_VALIDITY_DAYS", "5475"))  # ~15y
    CF_KEY_TYPE: str = os.getenv("CF_KEY_TYPE", "rsa")  # "rsa" or "ecdsa"
    CF_RSA_BITS: int = int(os.getenv("CF_RSA_BITS", "2048"))  # 2048 or 4096

    def db_path(self) -> str:
        if self.SQLITE_PATH:
            return self.SQLITE_PATH
        d = Path(self.DATA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "app.db")

settings = Settings()
