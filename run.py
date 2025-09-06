"""
Application entry point for the Multi-Domain Edge Manager.
This module creates the FastAPI application and starts the development server.
"""
from app.main import create_app
from app.config import settings
import uvicorn

# Create the FastAPI application instance
app = create_app()

if __name__ == "__main__":
    # Start the development server with hot reloading in debug mode
    uvicorn.run("run:app", host="0.0.0.0", port=settings.LISTEN_PORT, reload=settings.DEBUG_MODE)
