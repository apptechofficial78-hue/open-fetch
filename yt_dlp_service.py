import asyncio
import html
import json
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import yt_dlp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="OpenFetch yt-dlp resolver")
ALLOWED_HOST = "dramafren.org"


class ResolveRequest(BaseModel):
    url: HttpUrl


def is_allowed_url(url: str) -> bool:
    host = url.split("/", 3)[2].split(":", 1)[0].lower()
    return host == ALLOWED_HOST or host.endswith(f".{ALLOWED_HOST}")


DRAMAFREN_AES_KEY = b"kiemtienmua911ca"
DRAMAFREN_AES_IV = b"1234567890oiytr\0"


def decrypt_dramafren_response(payload: bytes) -> dict:
    encrypted = bytes.fromhex(payload.decode("ascii", errors="strict").strip())
    decryptor = Cipher(algorithms.AES(DRAMAFREN_AES_KEY), modes.CBC(DRAMAFREN_AES_IV)).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()

    pad_length = padded[-1]
    if 1 <= pad_length <= 16 and padded.endswith(bytes([pad_length]) * pad_length):
        padded = padded[:-pad_length]

    text = padded.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("DramaFren returned an invalid encrypted player response")
    return json.loads(text[start:end + 1])


def fetch_dramafren_stream(embed_url: str, player_id: str) -> dict:
    video_url = urljoin(embed_url, f"/api/v1/video?id={player_id}")
    request = Request(video_url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": embed_url,
        "Origin": embed_url.rsplit("#", 1)[0],
    })
    with urlopen(request, timeout=20) as response:
        data = decrypt_dramafren_response(response.read())

    stream_url = data.get("source") or data.get("cfNative") or data.get("hlsVideoTiktok")
    if not stream_url:
        raise RuntimeError("DramaFren did not return a playable video stream")

    stream_url = urljoin(embed_url, stream_url)
    title = re.sub(r"[^\w .-]", "", data.get("title") or "video").strip() or "video"
    if title.lower().endswith(".mp4"):
        title = title[:-4]
    filename = f"{title}.mp4"

    return {
        "status": "redirect",
        "stream_type": "hls",
        "is_hls": True,
        "download_url": stream_url,
        "url": stream_url,
        "filename": filename,
        "title": title,
        "extension": "mp4",
    }


def resolve_dramafren_embed(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        page_html = response.read().decode("utf-8", errors="replace")

    iframe_match = re.search(r'<iframe\b[^>]*\bsrc=["\']([^"\']+)["\']', page_html, re.I)
    if not iframe_match:
        raise RuntimeError("No embedded video player was found on this page")

    embed_url = urljoin(url, html.unescape(iframe_match.group(1)))
    player_id_match = re.search(r"#([^#\s]+)$", embed_url)
    if player_id_match:
        try:
            return fetch_dramafren_stream(embed_url, player_id_match.group(1))
        except Exception as error:
            raise RuntimeError(f"DramaFren stream extraction failed: {error}") from error

    title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page_html, re.I)
    if not title_match:
        title_match = re.search(r'<title[^>]*>(.*?)</title>', page_html, re.I | re.S)
    title = html.unescape(title_match.group(1)).strip() if title_match else "video"
    title = re.sub(r"[^\w .-]", "", title).strip() or "video"

    return {"status": "redirect", "url": embed_url, "filename": f"{title}.mp4"}


def resolve_with_yt_dlp(url: str) -> dict:
    if is_allowed_url(url):
        return resolve_dramafren_embed(url)

    options = {
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError:
        return resolve_dramafren_embed(url)

    media_url = info.get("url") if isinstance(info, dict) else None
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
