"""
Application entry point for the Multi-Domain Edge Manager.
This module creates the FastAPI application and starts the development server.
"""
import os
from pathlib import Path
from app.main import create_app
from app.config import settings
import uvicorn
from app.services.ssl import ensure_selfsigned_cert

# Create the FastAPI application instance
app = create_app()

if __name__ == "__main__":
    # Configure SSL if enabled
    ssl_config = None
    if settings.USE_SSL:
        # Create SSL directory in data folder if it doesn't exist
        ssl_dir = Path(settings.DATA_DIR) / "ssl"
        ssl_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate self-signed certificate
        certfile, keyfile = ensure_selfsigned_cert(str(ssl_dir))
        
        # Configure SSL for uvicorn
        ssl_config = {
            "ssl_certfile": certfile,
            "ssl_keyfile": keyfile
        }
        print(f"SSL enabled with self-signed certificate: {certfile}")
    else:
        print("SSL disabled - running with HTTP only")
    
    # Start the development server with hot reloading in debug mode
    uvicorn.run(
        "run:app", 
        host="0.0.0.0", 
        port=settings.LISTEN_PORT, 
        reload=settings.DEBUG_MODE,
        **ssl_config if ssl_config else {}
    )
