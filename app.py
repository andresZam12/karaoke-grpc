"""Punto de entrada WSGI para despliegue en Vercel.

Sirve la interfaz web interactiva de Karaoke-gRPC y provee endpoints
JSON con las canciones para entornos serverless.
"""
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
SONGS_DIR = BASE_DIR / "songs"


def get_songs_data() -> list[dict[str, Any]]:
    """Carga las canciones JSON disponibles en songs/."""
    songs = []
    if SONGS_DIR.is_dir():
        for json_file in sorted(SONGS_DIR.glob("*.json")):
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    songs.append({
                        "id": data.get("id"),
                        "title": data.get("title"),
                        "artist": data.get("artist"),
                        "line_count": len(data.get("lines", [])),
                        "duration_s": round(data["lines"][-1]["t"] + 3.0, 1) if data.get("lines") else 0.0,
                    })
            except Exception:
                pass
    return songs


def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
    """Aplicación WSGI estándar compatible con el runtime de Vercel."""
    raw_path = environ.get("PATH_INFO", "/").strip("/")

    # Endpoint API opcional para consulta de catálogo
    if raw_path == "api/songs":
        body = json.dumps({"songs": get_songs_data()}, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-cache"),
        ])
        return [body]

    # Resolver archivo estático en web/
    file_rel = raw_path if raw_path else "index.html"
    target_file = (WEB_DIR / file_rel).resolve()

    # Prevenir Directory Traversal fuera de WEB_DIR
    try:
        target_file.relative_to(WEB_DIR)
    except ValueError:
        target_file = WEB_DIR / "index.html"

    # Si el archivo no existe, servir index.html como fallback SPA
    if not target_file.is_file():
        target_file = WEB_DIR / "index.html"

    mime_type, _ = mimetypes.guess_type(str(target_file))
    if target_file.suffix == ".css":
        mime_type = "text/css; charset=utf-8"
    elif target_file.suffix == ".js":
        mime_type = "application/javascript; charset=utf-8"
    elif target_file.suffix == ".html":
        mime_type = "text/html; charset=utf-8"
    else:
        mime_type = mime_type or "application/octet-stream"

    content = target_file.read_bytes()
    start_response("200 OK", [
        ("Content-Type", mime_type),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "public, max-age=3600" if target_file.suffix != ".html" else "no-cache"),
    ])
    return [content]


# Alias handler requerido por algunas versiones de Vercel
handler = app
