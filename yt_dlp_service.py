import asyncio
import re

import yt_dlp
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="OpenFetch yt-dlp resolver")
ALLOWED_HOST = "dramafren.org"


class ResolveRequest(BaseModel):
    url: HttpUrl


def is_allowed_url(url: str) -> bool:
    host = url.split("/", 3)[2].split(":", 1)[0].lower()
    return host == ALLOWED_HOST or host.endswith(f".{ALLOWED_HOST}")


def resolve_with_yt_dlp(url: str) -> dict:
    options = {
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)

    media_url = info.get("url")
    if not media_url:
        raise RuntimeError("No direct media URL was returned")

    title = re.sub(r"[^\w .-]", "", info.get("title") or "video").strip() or "video"
    extension = info.get("ext") or "mp4"
    return {"status": "redirect", "url": media_url, "filename": f"{title}.{extension}"}


@app.post("/resolve")
async def resolve(request: ResolveRequest):
    url = str(request.url)
    if not is_allowed_url(url):
        raise HTTPException(status_code=403, detail="Only DramaFren URLs are allowed")

    try:
        return await asyncio.to_thread(resolve_with_yt_dlp, url)
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/health")
def health():
    return {"status": "ok"}
