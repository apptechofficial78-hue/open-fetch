import asyncio
import logging
import os
from typing import Annotated, Literal
from urllib.parse import urlsplit

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("media_resolver")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

app = FastAPI(title="Media Link Resolver", version="1.0.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: HttpUrl


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class DirectMediaResponse(BaseModel):
    stream_type: Literal["direct"] = "direct"
    is_hls: Literal[False] = False
    title: str
    thumbnail: HttpUrl | None
    extension: str
    download_url: HttpUrl


class HLSMediaResponse(BaseModel):
    stream_type: Literal["hls"] = "hls"
    is_hls: Literal[True] = True
    title: str
    thumbnail: HttpUrl | None
    extension: str
    download_url: HttpUrl


MediaResponse = Annotated[
    DirectMediaResponse | HLSMediaResponse,
    Field(discriminator="stream_type"),
]


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        error = detail
    else:
        error = {"code": "http_error", "message": str(detail)}

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "Provide a valid HTTP or HTTPS URL in the 'url' field.",
            }
        },
    )


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_hls(media_url: str, protocol: object) -> bool:
    path = urlsplit(media_url).path.lower()
    protocol_name = str(protocol or "").lower()
    return path.endswith(".m3u8") or "m3u8" in protocol_name or "hls" in protocol_name


def _extract_media(url: str) -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "user_agent": USER_AGENT,
        "socket_timeout": 20,
        "retries": 2,
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise ValueError("The extractor returned no media information.")

    entries = info.get("entries")
    if not info.get("url") and entries:
        info = next((entry for entry in entries if isinstance(entry, dict)), {})

    selected_info = info
    media_url = info.get("url")
    if not isinstance(media_url, str) or not media_url:
        formats = [
            item
            for item in info.get("formats", [])
            if isinstance(item, dict)
            and isinstance(item.get("url"), str)
            and item["url"]
        ]
        if formats:
            selected_info = max(
                formats,
                key=lambda item: (
                    item.get("vcodec") not in (None, "none")
                    and item.get("acodec") not in (None, "none"),
                    _number(item.get("preference")),
                    _number(item.get("height")),
                    _number(item.get("tbr")),
                ),
            )
            media_url = selected_info["url"]

    if not isinstance(media_url, str) or not media_url:
        raise ValueError("The extractor did not return a usable media URL.")

    protocol = selected_info.get("protocol") or info.get("protocol")
    is_hls = _is_hls(media_url, protocol)
    extension = selected_info.get("ext") or info.get("ext")

    if is_hls:
        extension = "m3u8"
    elif not isinstance(extension, str) or not extension:
        filename = urlsplit(media_url).path.rsplit("/", 1)[-1]
        extension = filename.rsplit(".", 1)[-1] if "." in filename else "unknown"

    title = info.get("title")
    thumbnail = info.get("thumbnail")

    return {
        "stream_type": "hls" if is_hls else "direct",
        "is_hls": is_hls,
        "title": title if isinstance(title, str) and title.strip() else "Untitled video",
        "thumbnail": thumbnail if isinstance(thumbnail, str) else None,
        "extension": extension.lower().lstrip("."),
        "download_url": media_url,
    }


@app.post(
    "/resolve",
    response_model=MediaResponse,
    responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
async def resolve_media(request: ResolveRequest) -> MediaResponse:
    try:
        result = await asyncio.to_thread(_extract_media, str(request.url))
    except yt_dlp.utils.DownloadError as exc:
        hostname = urlsplit(str(request.url)).hostname or "unknown host"
        logger.warning(
            "Media extraction failed for host %s (%s)",
            hostname,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "extraction_failed",
                "message": (
                    "Could not extract media from this URL. It may be unsupported, "
                    "unavailable, or access-restricted."
                ),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "media_not_found", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected media extraction failure")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "resolver_error",
                "message": "The media resolver encountered an unexpected error.",
            },
        ) from exc

    return result


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
