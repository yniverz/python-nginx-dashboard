from pathlib import Path
import mimetypes
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import FileResponse, Response

# Ensure common types are known across OSes
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/json", ".map")

router = APIRouter()

# Point this to your real static directory (absolute path!)
STATIC_ROOT = (Path(__file__).resolve().parent / "web" / "static").resolve()

@router.get("/static/{path:path}", include_in_schema=False)
def static_files(request: Request, path: str):
    # Normalize & prevent path traversal
    full_path = (STATIC_ROOT / path).resolve()
    if not full_path.is_file() or not str(full_path).startswith(str(STATIC_ROOT)):
        print(f"Blocked access to: {full_path}")
        raise HTTPException(status_code=404)

    # Guess content type
    content_type, encoding = mimetypes.guess_type(full_path.name)
    media_type = content_type or "application/octet-stream"

    # Lightweight ETag from size+mtime (weak etag)
    st = full_path.stat()
    etag = f'W/"{st.st_size:x}-{int(st.st_mtime):x}"'
    if request.headers.get("if-none-match") == etag:
        # Short-circuit 304
        headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
        return Response(status_code=304, headers=headers)

    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
    if encoding:
        headers["Content-Encoding"] = encoding

    return FileResponse(path=full_path, media_type=media_type, headers=headers)
