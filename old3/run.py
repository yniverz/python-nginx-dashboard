from app.main import create_app
import uvicorn
from app.config import settings

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=False,
        workers=1
    )
