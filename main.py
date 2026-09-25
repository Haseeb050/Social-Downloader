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
    description="Downloader for YouTube, Instagram, TikTok, X (Twitter), Facebook, Snapchat, LinkedIn, Reddit, Pinterest, and Threads (yt-dlp).",
)

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN") or "http://127.0.0.1:8000"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2048"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER", "").strip().lower()

PROXY_URL = os.getenv("PROXY_URL", "").strip() or os.getenv("HTTP_PROXY", "").strip()


def _get_cookie_file() -> str | None:
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        return COOKIES_FILE
    for candidate in ["cookies.txt", "youtube_cookies.txt"]:
        path = os.path.join(BASE_DIR, candidate)
        if os.path.isfile(path):
            return path
        if os.path.isfile(candidate):
            return candidate
    return None


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
    if host in {"tiktok.com", "vm.tiktok.com", "vt.tiktok.com"} or host.endswith(".tiktok.com"):
        return "tiktok"
    if host in {"twitter.com", "x.com", "t.co"} or host.endswith(".twitter.com") or host.endswith(".x.com"):
        return "twitter"
    if host in {"facebook.com", "fb.watch", "fb.com", "m.facebook.com", "web.facebook.com"} or host.endswith(".facebook.com"):
        return "facebook"
    if host in {"snapchat.com", "story.snapchat.com"} or host.endswith(".snapchat.com"):
        return "snapchat"
    if host in {"linkedin.com", "lnkd.in"} or host.endswith(".linkedin.com"):
        return "linkedin"
    if host in {"reddit.com", "redd.it", "v.redd.it"} or host.endswith(".reddit.com"):
        return "reddit"
    if host in {"pinterest.com", "pin.it"} or host.endswith(".pinterest.com"):
        return "pinterest"
    if host in {"threads.net"} or host.endswith(".threads.net"):
        return "threads"
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
    if platform == "twitter":
        clean_path = parsed.path.rstrip("/")
        return f"https://x.com{clean_path}"
    if platform == "reddit":
        clean_path = parsed.path.rstrip("/")
        return f"https://www.reddit.com{clean_path}"
    return url


def _map_format(fmt: str) -> tuple[str, bool]:
    raw = (fmt or "best").strip().lower()
    audio_only = raw in {"mp3", "audio", "bestaudio", "wav", "ogg"}
    if audio_only:
        return "bestaudio/best", True
    height = QUALITY_HEIGHT.get(raw)
    if height:
        return (
            f"best[height<={height}]/bestvideo[height<={height}]+bestaudio/best/18/b",
            False,
        )
    return "best/bestvideo+bestaudio/18/b", False


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
    if "unavailable" in text or "private" in text or "does not exist" in text:
        return f"This video is unavailable, deleted, or private on {platform.capitalize()}."
    if "sign in" in text or "not a bot" in text or "429" in text:
        return f"{platform.capitalize()} rate-limited or blocked this request. Try again shortly."
    if "empty media" in text or "login" in text or "cookies" in text:
        if platform == "instagram":
            return "Instagram video unavailable. Ensure the post is public."
        if platform == "facebook":
            return "Facebook video unavailable. Ensure the post/reel is public."
        if platform == "snapchat":
            return "Snapchat video unavailable or expired. Ensure it is public."
        if platform == "linkedin":
            return "LinkedIn video unavailable. Ensure the post is public."
        if platform == "reddit":
            return "Reddit video unavailable or deleted."
        return "This video requires authentication."
    if "ffmpeg" in text:
        return "ffmpeg is required to process this video."
    short = str(exc).split("\n")[0].strip()
    if len(short) > 220:
        short = short[:217] + "..."
    return short or "Download failed. The video may be private, geo-blocked, or unavailable."


def _ydl_opts(platform: str, ydl_format: str, output_template: str) -> dict:
    referers = {
        "youtube": "https://www.youtube.com/",
        "instagram": "https://www.instagram.com/",
        "tiktok": "https://www.tiktok.com/",
        "twitter": "https://x.com/",
        "facebook": "https://www.facebook.com/",
        "snapchat": "https://www.snapchat.com/",
        "linkedin": "https://www.linkedin.com/",
        "reddit": "https://www.reddit.com/",
        "pinterest": "https://www.pinterest.com/",
        "threads": "https://www.threads.net/",
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
        "js_runtimes": {
            "node": {"path": "node"},
        },
    }
    if platform == "youtube":
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["android", "ios", "web_creator"],
                "player_skip": ["webpage", "configs"],
            }
        }
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    elif COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    return opts


def _download_with_pytubefix(url: str, format_str: str, download_dir: str, uid: str) -> tuple[str, str, str]:
    """Secondary fallback engine using pytubefix for YouTube when yt-dlp encounters issues."""
    try:
        from pytubefix import YouTube
    except ImportError as err:
        raise RuntimeError("pytubefix is not installed.") from err

    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
    raw = (format_str or "best").strip().lower()
    audio_only = raw in {"mp3", "audio", "bestaudio", "wav", "ogg"}

    last_error = None
    for client in ["VISION_OS", "ANDROID", "WEB", "MWEB", "IOS"]:
        try:
            yt = YouTube(url, client=client, proxies=proxies)
            stream = None
            if audio_only:
                stream = yt.streams.get_audio_only()
            else:
                height = QUALITY_HEIGHT.get(raw)
                if height:
                    stream = yt.streams.filter(res=f"{height}p", file_extension="mp4").first()
                if not stream:
                    stream = yt.streams.get_highest_resolution() or yt.streams.first()

            if not stream:
                continue

            title = yt.title or "video"
            ext = "mp3" if audio_only else (stream.subtype or "mp4")
            out_file = f"{uid}.{ext}"
            saved_path = stream.download(output_path=download_dir, filename=out_file)
            return saved_path, title, ext
        except Exception as e:
            last_error = e
            continue

    raise last_error or RuntimeError("Could not download video via pytubefix fallback.")


def _execute_download(url: str, platform: str, ydl_format: str, output_template: str, download_dir: str, uid: str, format_str: str) -> tuple[str, str, str]:
    """Dual-engine pipeline: yt-dlp first, auto fallback to pytubefix if blocked."""
    try:
        opts = _ydl_opts(platform, ydl_format, output_template)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("No video info returned.")
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0] or {}

            actual_file_path = None
            for name in os.listdir(download_dir):
                if name.startswith(uid):
                    actual_file_path = os.path.join(download_dir, name)
                    break

            if actual_file_path and os.path.isfile(actual_file_path):
                title = info.get("title") or info.get("id") or "video"
                ext = os.path.splitext(actual_file_path)[1].lstrip(".") or "mp4"
                return actual_file_path, str(title), ext
    except Exception as ytdlp_err:
        # If it's YouTube and yt-dlp failed, try pytubefix fallback
        if platform == "youtube":
            try:
                return _download_with_pytubefix(url, format_str, download_dir, uid)
            except Exception:
                raise ytdlp_err from None
        raise ytdlp_err

    raise RuntimeError("Downloaded file not found on disk.")


@app.get("/download")
async def download_video(url: str = Query(...), format: str = Query("best")):
    if not _is_http_url(url):
        raise HTTPException(status_code=400, detail="url must be a valid http or https link.")

    platform = _platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Only YouTube, Instagram, TikTok, X (Twitter), Facebook, Snapchat, LinkedIn, Reddit, Pinterest, and Threads URLs are supported.",
        )

    url = _normalize_url(url, platform)
    ydl_format, audio_only = _map_format(format)
    download_dir = None

    async with download_semaphore:
        download_dir = tempfile.mkdtemp(prefix="ydl_")
        uid = uuid.uuid4().hex[:8]
        output_template = os.path.join(download_dir, f"{uid}.%(ext)s")
        try:
            actual_file_path, title, ext = await asyncio.to_thread(
                _execute_download,
                url,
                platform,
                ydl_format,
                output_template,
                download_dir,
                uid,
                format,
            )
        except HTTPException:
            _cleanup(download_dir)
            raise
        except Exception as exc:
            _cleanup(download_dir)
            raise HTTPException(status_code=502, detail=_public_error(platform, exc)) from exc

        if not actual_file_path or not os.path.isfile(actual_file_path):
            _cleanup(download_dir)
            raise HTTPException(status_code=500, detail="Download finished but the file was not found.")

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
            headers={"Content-Disposition": _content_disposition(title, ext)},
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
  <p class="hint">Supported: YouTube, Instagram, TikTok, X (Twitter), Facebook, Snapchat, LinkedIn, Reddit, Pinterest, Threads.</p>
  <form action="/download" method="get">
    <label for="url">Video URL</label>
    <input id="url" name="url" type="url" required placeholder="https://x.com/... or https://snapchat.com/... or https://reddit.com/..." />
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
        "platforms": [
            "youtube",
            "instagram",
            "tiktok",
            "twitter",
            "facebook",
            "snapchat",
            "linkedin",
            "reddit",
            "pinterest",
            "threads",
        ],
        "backend": "yt-dlp",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
