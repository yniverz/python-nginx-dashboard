from app.main import create_app
from app.config import settings
import uvicorn

app = create_app()

if __name__ == "__main__":
    uvicorn.run("run:app", host="0.0.0.0", port=settings.LISTEN_PORT, reload=True)
