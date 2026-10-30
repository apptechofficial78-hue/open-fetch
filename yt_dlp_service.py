import asyncio
import html
import json
import re
import subprocess
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import yt_dlp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="OpenFetch media resolver", version="2.0.0")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
DRAMAFREN_AES_KEY = b"kiemtienmua911ca"
DRAMAFREN_AES_IV = b"1234567890oiytr\0"


class ResolveRequest(BaseModel):
    url: HttpUrl
    downloadMode: str = Field(default="video", pattern="^(video|audio)$")
    audioFormat: str = Field(default="mp3", pattern="^(mp3|m4a|opus|wav)$")


def decrypt_dramafren_response(payload: bytes) -> dict:
    encrypted = bytes.fromhex(payload.decode("ascii").strip())
    decryptor = Cipher(algorithms.AES(DRAMAFREN_AES_KEY), modes.CBC(DRAMAFREN_AES_IV)).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    pad_length = padded[-1] if padded else 0
    if 1 <= pad_length <= 16 and padded.endswith(bytes([pad_length]) * pad_length):
        padded = padded[:-pad_length]
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", padded.decode("utf-8", errors="replace"))
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("DramaFren returned an invalid encrypted player response")
    return json.loads(text[start:end + 1])


def fetch_dramafren_stream(embed_url: str, player_id: str) -> dict:
    video_url = urljoin(embed_url, f"/api/v1/video?id={player_id}")
    request = Request(video_url, headers={
        "User-Agent": USER_AGENT,
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
    title = re.sub(r"\.mp4$", "", title, flags=re.I)
    return {
        "status": "redirect", "stream_type": "hls", "is_hls": True,
        "download_url": stream_url, "url": stream_url,
        "filename": f"{title}.mp4", "title": title, "extension": "m3u8"
    }


def resolve_dramafren_embed(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        page_html = response.read().decode("utf-8", errors="replace")
    iframe_match = re.search(r'<iframe\b[^>]*\bsrc=["\']([^"\']+)["\']', page_html, re.I)
    if not iframe_match:
        raise RuntimeError("No embedded video player was found on this page")
    embed_url = urljoin(url, html.unescape(iframe_match.group(1)))
    player_id_match = re.search(r"#([^#\s]+)$", embed_url)
    if player_id_match:
        return fetch_dramafren_stream(embed_url, player_id_match.group(1))

    title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page_html, re.I)
    if not title_match:
        title_match = re.search(r'<title[^>]*>(.*?)</title>', page_html, re.I | re.S)
    title = html.unescape(title_match.group(1)).strip() if title_match else "video"
    title = re.sub(r"[^\w .-]", "", title).strip() or "video"
    return {"status": "redirect", "url": embed_url, "filename": f"{title}.mp4"}


def normalize_yt_info(info: dict, download_mode: str, audio_format: str) -> dict:
    entries = info.get("entries")
    if entries and not info.get("url"):
        info = next((entry for entry in entries if isinstance(entry, dict)), info)
    formats = [item for item in info.get("formats", []) if isinstance(item, dict) and item.get("url")]
    if download_mode == "audio":
        candidates = [item for item in formats if item.get("vcodec") in (None, "none") and item.get("acodec") not in (None, "none")]
        candidates = candidates or [item for item in formats if item.get("acodec") not in (None, "none")]
        selected = max(candidates, key=lambda item: item.get("abr") or item.get("tbr") or 0) if candidates else info
        extension = audio_format
    else:
        video_formats = [item for item in formats if item.get("vcodec") not in (None, "none")]
        combined = [item for item in video_formats if item.get("acodec") not in (None, "none")]
        candidates = combined or video_formats
        selected = max(candidates, key=lambda item: (item.get("height") or 0, item.get("tbr") or 0)) if candidates else info
        extension = selected.get("ext") if isinstance(selected, dict) else info.get("ext")
        extension = extension or "mp4"

    media_url = selected.get("url") if isinstance(selected, dict) else None
    media_url = media_url or info.get("url")
    if not media_url:
        raise RuntimeError("No direct media URL was returned")
    protocol = selected.get("protocol") or info.get("protocol") if isinstance(selected, dict) else info.get("protocol")
    is_hls = ".m3u8" in media_url.lower() or "m3u8" in str(protocol).lower() or "hls" in str(protocol).lower()
    title = re.sub(r"[^\w .-]", "", info.get("title") or "video").strip() or "video"
    return {
        "status": "redirect", "stream_type": "hls" if is_hls else "direct", "is_hls": is_hls,
        "download_url": media_url, "url": media_url,
        "title": title, "filename": f"{title}.{extension}", "extension": "m3u8" if is_hls else extension.lower().lstrip("."),
        "thumbnail": info.get("thumbnail")
    }


def resolve_with_yt_dlp(url: str, download_mode: str = "video", audio_format: str = "mp3") -> dict:
    host = url.split("/", 3)[2].lower() if "/" in url else ""
    if host == "dramafren.org" or host.endswith(".dramafren.org"):
        return resolve_dramafren_embed(url)

    options = {
        "format": "bestaudio[ext=m4a]/bestaudio/best" if download_mode == "audio" else "bv*+ba/best/bestvideo*+bestaudio/best",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "skip_download": True, "user_agent": USER_AGENT, "socket_timeout": 20, "retries": 2
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as error:
        if download_mode == "video":
            raise RuntimeError(f"Media extraction failed: {error}") from error
        raise RuntimeError(f"Audio extraction failed: {error}") from error
    if not isinstance(info, dict):
        raise RuntimeError("The extractor returned no media information")
    return normalize_yt_info(info, download_mode, audio_format)


@app.post("/resolve")
async def resolve(request: ResolveRequest):
    try:
        return await asyncio.to_thread(resolve_with_yt_dlp, str(request.url), request.downloadMode, request.audioFormat)
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/download")
def download_audio(
    url: HttpUrl,
    format: str = Query(default="mp3", pattern="^(mp3|m4a|opus|wav)$"),
):
    codec_options = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3"],
        "m4a": ["-c:a", "aac", "-b:a", "192k", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov"],
        "opus": ["-c:a", "libopus", "-b:a", "128k", "-f", "opus"],
        "wav": ["-c:a", "pcm_s16le", "-f", "wav"],
    }
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-reconnect", "1",
        "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", str(url),
        "-vn", *codec_options[format], "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def stream_output():
        try:
            assert process.stdout is not None
            while chunk := process.stdout.read(65536):
                yield chunk
        finally:
            process.stdout.close()
            process.wait()

    media_type = {
        "mp3": "audio/mpeg", "m4a": "audio/mp4", "opus": "audio/ogg", "wav": "audio/wav",
    }[format]
    headers = {"Content-Disposition": f'attachment; filename="openfetch.{format}"'}
    return StreamingResponse(stream_output(), media_type=media_type, headers=headers)


@app.get("/health")
def health():
    return {"status": "ok"}
