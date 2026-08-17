import asyncio
import os
import re
import shutil
import tempfile
import uuid
from urllib.parse import parse_qs, quote, urlparse

import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

load_dotenv()

app = FastAPI(
    title="Social Media Video Downloader",
    description="Local downloader for YouTube, Instagram, and TikTok (yt-dlp, no Apify).",
)

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN") or "http://127.0.0.1:8000"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2048"))
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER", "").strip().lower()

QUALITY_HEIGHT = {
    "1080": 1080,
    "1080p": 1080,
    "720": 720,
    "720p": 720,
    "480": 480,
    "480p": 480,
    "360": 360,
    "360p": 360,
}

download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _platform(url: str) -> str | None:
    host = _host(url)
    if host in {"youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"} or host.endswith(".youtube.com"):
        return "youtube"
    if host in {"instagram.com", "instagr.am"} or host.endswith(".instagram.com"):
        return "instagram"
    if host in {"tiktok.com"} or host.endswith(".tiktok.com"):
        return "tiktok"
    return None


def _normalize_url(url: str, platform: str) -> str:
    parsed = urlparse(url)
    if platform == "instagram":
        return f"https://www.instagram.com{parsed.path.rstrip('/')}/"
    if platform == "youtube":
        host = parsed.netloc.lower()
        path = parsed.path.strip("/")
        if "youtu.be" in host:
            return f"https://www.youtube.com/watch?v={path.split('/')[0]}"
        if "/shorts/" in parsed.path:
            video_id = parsed.path.split("/shorts/")[-1].strip("/").split("/")[0]
            return f"https://www.youtube.com/watch?v={video_id}"
        video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    return url


def _map_format(fmt: str) -> tuple[str, bool]:
    raw = (fmt or "best").strip().lower()
    audio_only = raw in {"mp3", "audio", "bestaudio", "wav", "ogg"}
    if audio_only:
        return "bestaudio/best", True
    height = QUALITY_HEIGHT.get(raw)
    if height:
        return (
            f"b[height<={height}][ext=mp4]/bv*[height<={height}]+ba/b[height<={height}]/b",
            False,
        )
    return "b[ext=mp4]/bv*+ba/b", False


def _safe_filename(title: str, ext: str) -> str:
    cleaned = re.sub(r'[\r\n"]+', "", title or "video")
    cleaned = cleaned.replace("/", "-").replace("\\", "-").strip()
    ascii_name = cleaned.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("._-")
    ext = (ext or "mp4").lstrip(".")
    return f"{ascii_name or 'video'}.{ext}"


def _content_disposition(title: str, ext: str) -> str:
    fallback = _safe_filename(title, ext)
    utf8_name = re.sub(r'[\r\n"]+', "", title or "video").replace("/", "-").replace("\\", "-").strip() or "video"
    utf8_name = f"{utf8_name[:80]}.{(ext or 'mp4').lstrip('.')}"
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(utf8_name)}'


def _cleanup(path: str | None) -> None:
    if not path:
        return
    shutil.rmtree(path, ignore_errors=True)


def _public_error(platform: str, exc: Exception) -> str:
    text = str(exc).lower()
    if "sign in" in text or "not a bot" in text:
        return "YouTube blocked this request. Set COOKIES_FROM_BROWSER=chrome in .env (Chrome mein YouTube login hona chahiye)."
    if "empty media" in text or "login" in text or "cookies" in text:
        if platform == "instagram":
            return "Instagram ne video nahi di. Public reel ho, ya COOKIES_FROM_BROWSER=chrome set karein (Chrome mein Instagram login)."
        return "This video needs login cookies. Set COOKIES_FROM_BROWSER=chrome in .env."
    if "private" in text:
        return "This video is private or unavailable."
    if "ffmpeg" in text:
        return "ffmpeg is required to merge this video. Install ffmpeg and retry."
    if "impersonate" in text:
        return "Download client setup failed. Retry after server reload."
    short = str(exc).split("\n")[0].strip()
    if len(short) > 220:
        short = short[:217] + "..."
    return short or "Download failed. The video may be private, geo-blocked, or the site blocked this request."


def _ydl_opts(platform: str, ydl_format: str, output_template: str) -> dict:
    referers = {
        "youtube": "https://www.youtube.com/",
        "instagram": "https://www.instagram.com/",
        "tiktok": "https://www.tiktok.com/",
    }
    opts = {
        "format": ydl_format,
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "socket_timeout": 30,
        "retries": 3,
        "max_filesize": MAX_FILE_SIZE_MB * 1024 * 1024,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": referers.get(platform, "https://www.google.com/"),
        },
        "extractor_args": {
            "youtube": {"player_client": ["android", "web", "tv"]},
        },
    }
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    elif COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    return opts


def _extract_and_download(url: str, platform: str, ydl_format: str, output_template: str) -> dict:
    opts = _ydl_opts(platform, ydl_format, output_template)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("No video info returned.")
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0] or {}
        return info


@app.get("/download")
async def download_video(url: str = Query(...), format: str = Query("best")):
    if not _is_http_url(url):
        raise HTTPException(status_code=400, detail="url must be a valid http or https link.")

    platform = _platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Only YouTube, Instagram, and TikTok URLs are supported.",
        )

    url = _normalize_url(url, platform)
    ydl_format, audio_only = _map_format(format)
    download_dir = None

    async with download_semaphore:
        download_dir = tempfile.mkdtemp(prefix="ydl_")
        uid = uuid.uuid4().hex[:8]
        output_template = os.path.join(download_dir, f"{uid}.%(ext)s")
        try:
            info = await asyncio.to_thread(
                _extract_and_download,
                url,
                platform,
                ydl_format,
                output_template,
            )
        except HTTPException:
            _cleanup(download_dir)
            raise
        except Exception as exc:
            _cleanup(download_dir)
            raise HTTPException(status_code=502, detail=_public_error(platform, exc)) from exc

        actual_file_path = None
        for name in os.listdir(download_dir):
            if name.startswith(uid):
                actual_file_path = os.path.join(download_dir, name)
                break

        if not actual_file_path or not os.path.isfile(actual_file_path):
            _cleanup(download_dir)
            raise HTTPException(status_code=500, detail="Download finished but the file was not found.")

        title = info.get("title") or info.get("id") or "video"
        ext = os.path.splitext(actual_file_path)[1].lstrip(".") or ("mp3" if audio_only else "mp4")
        media_type = "audio/mpeg" if audio_only or ext == "mp3" else "video/mp4"
        file_to_stream = actual_file_path
        dir_to_clean = download_dir

        def iterfile():
            try:
                with open(file_to_stream, "rb") as handle:
                    while True:
                        chunk = handle.read(64 * 1024)
                        if not chunk:
                            break
                        yield chunk
            finally:
                _cleanup(dir_to_clean)

        return StreamingResponse(
            iterfile(),
            media_type=media_type,
            headers={"Content-Disposition": _content_disposition(str(title), ext)},
        )


HOME_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Social Downloader</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: Segoe UI, sans-serif; max-width: 640px; margin: 48px auto; padding: 0 16px; }
    h1 { font-size: 1.4rem; }
    p { color: #666; }
    label { display: block; margin: 16px 0 6px; font-weight: 600; }
    input, select, button { width: 100%; box-sizing: border-box; padding: 10px 12px; font-size: 1rem; }
    button { margin-top: 20px; cursor: pointer; }
    .hint { font-size: 0.9rem; }
  </style>
</head>
<body>
  <h1>Social Video Downloader</h1>
  <p class="hint">YouTube, Instagram, and TikTok. Download can take 30–90 seconds.</p>
  <form action="/download" method="get">
    <label for="url">Video URL</label>
    <input id="url" name="url" type="url" required placeholder="https://www.youtube.com/watch?v=..." />
    <label for="format">Quality</label>
    <select id="format" name="format">
      <option value="best" selected>Best</option>
      <option value="1080p">1080p</option>
      <option value="720p">720p</option>
      <option value="480p">480p</option>
      <option value="360p">360p</option>
      <option value="mp3">Audio (mp3)</option>
    </select>
    <button type="submit">Download</button>
  </form>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return HOME_PAGE


@app.get("/health")
async def health():
    return {
        "ok": True,
        "platforms": ["youtube", "instagram", "tiktok"],
        "backend": "yt-dlp",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
