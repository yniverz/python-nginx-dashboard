"""
Static file serving for the web application.
Handles CSS, JavaScript, images, and other static assets with caching and security.
"""
from pathlib import Path
import mimetypes
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import FileResponse, Response

# Register common MIME types for better content type detection
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/json", ".map")

router = APIRouter()

# Static files directory (absolute path for security)
STATIC_ROOT = (Path(__file__).resolve().parent / "static").resolve()

@router.get("/static/{path:path}", include_in_schema=False)
def static_files(request: Request, path: str):
    """
    Serve static files with security checks and HTTP caching.
    Prevents path traversal attacks and provides efficient caching headers.
    """
    # Normalize path and prevent directory traversal attacks
    full_path = (STATIC_ROOT / path).resolve()
    if not full_path.is_file() or not str(full_path).startswith(str(STATIC_ROOT)):
        print(f"Blocked access to: {full_path}")
        raise HTTPException(status_code=404)

    # Determine content type and encoding
    content_type, encoding = mimetypes.guess_type(full_path.name)
    media_type = content_type or "application/octet-stream"

    # Generate ETag for caching (based on file size and modification time)
    st = full_path.stat()
    etag = f'W/"{st.st_size:x}-{int(st.st_mtime):x}"'
    
    # Check if client has cached version
    if request.headers.get("if-none-match") == etag:
        # Return 304 Not Modified
        headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
        return Response(status_code=304, headers=headers)

    # Set caching headers for successful responses
    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
    if encoding:
        headers["Content-Encoding"] = encoding

    return FileResponse(path=full_path, media_type=media_type, headers=headers)
