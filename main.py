import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import parse_qs, quote, urlparse

import yt_dlp
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery

load_dotenv()

app = FastAPI(
    title="Universal Social Media Video Downloader",
    description="High-performance downloader for Facebook, Twitter (X), Reddit, Instagram, TikTok, YouTube, Pinterest, LinkedIn, Snapchat, and Threads with native iOS and Android compatibility.",
)

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
ALLOWED_ORIGIN_ENV = os.getenv("ALLOWED_ORIGIN") or "*"
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGIN_ENV.split(",") if origin.strip()]
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2048"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER", "").strip().lower()
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "").strip()
PROXY_URL = os.getenv("PROXY_URL", "").strip() or os.getenv("HTTP_PROXY", "").strip()

CACHE_DIR = os.path.join(tempfile.gettempdir(), "social_downloader_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def _clean_old_cache():
    """Remove cache files older than 20 minutes so files remain available for mobile Safari Range requests and multi-part downloads."""
    try:
        now = time.time()
        for root, dirs, files in os.walk(CACHE_DIR):
            for f in files:
                p = os.path.join(root, f)
                if os.path.isfile(p) and (now - os.path.getmtime(p) > 1200):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            for d in dirs:
                dp = os.path.join(root, d)
                if os.path.isdir(dp) and (now - os.path.getmtime(dp) > 1200):
                    try:
                        shutil.rmtree(dp, ignore_errors=True)
                    except Exception:
                        pass
    except Exception:
        pass


def _verify_api_key(
    header_key: str | None = Security(api_key_header),
    query_key: str | None = Security(api_key_query),
):
    if not API_SECRET_KEY:
        return True
    key = header_key or query_key
    if not key or key != API_SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing API Key. Pass 'X-API-Key' header or '?api_key=' parameter.",
        )
    return True


def _get_cookie_file() -> str | None:
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        return COOKIES_FILE
    for candidate in ["cookies.txt", "youtube_cookies.txt", "facebook_cookies.txt"]:
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
    allow_origins=ALLOWED_ORIGINS if "*" not in ALLOWED_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Disposition", "Content-Type", "Accept-Ranges"],
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
    if host in {"reddit.com", "redd.it", "v.redd.it"} or host.endswith(".reddit.com"):
        return "reddit"
    if host in {"snapchat.com"} or host.endswith(".snapchat.com"):
        return "snapchat"
    if host in {"linkedin.com"} or host.endswith(".linkedin.com"):
        return "linkedin"
    if host in {"pinterest.com", "pin.it"} or host.endswith(".pinterest.com") or host.endswith(".pin.it"):
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


def _public_error(platform: str, exc: Exception) -> str:
    text = str(exc).lower()
    if "unavailable" in text or "private" in text or "does not exist" in text:
        return f"This video is unavailable, deleted, or private on {platform.capitalize()}."
    if "sign in" in text or "not a bot" in text or "429" in text:
        return f"{platform.capitalize()} rate-limited or blocked this request. Try again shortly."
    if "empty media" in text or "login" in text or "cookies" in text:
        if platform == "facebook":
            return "Facebook video unavailable. Ensure the post/reel is public."
        if platform == "instagram":
            return "Instagram video unavailable. Ensure the post is public."
        if platform == "snapchat":
            return "Snapchat video unavailable or expired. Ensure it is public."
        if platform == "linkedin":
            return "LinkedIn video unavailable. Ensure the post is public."
        if platform == "reddit":
            return "Reddit video unavailable or deleted."
        return "This video requires authentication or is private."
    if "ffmpeg" in text:
        return "ffmpeg is required to process this video."
    short = str(exc).split("\n")[0].strip()
    if len(short) > 220:
        short = short[:217] + "..."
    return short or "Download failed. The video may be private, geo-blocked, or unavailable."


def _render_error_page(message: str, status_code: int = 502) -> HTMLResponse:
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video Download Notice - FDownloader</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #090d16;
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    .card {{
      background: rgba(20, 26, 43, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 20px;
      padding: 36px 28px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.7);
    }}
    .icon {{
      width: 56px;
      height: 56px;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 20px;
      font-size: 24px;
      color: #ef4444;
    }}
    h1 {{
      font-size: 1.4rem;
      margin-bottom: 12px;
      color: #ffffff;
    }}
    p {{
      color: #94a3b8;
      font-size: 0.95rem;
      line-height: 1.5;
      margin-bottom: 24px;
    }}
    .btn {{
      display: inline-block;
      background: linear-gradient(135deg, #16a34a, #22c55e);
      color: #ffffff;
      text-decoration: none;
      font-weight: 600;
      font-size: 0.95rem;
      padding: 12px 24px;
      border-radius: 10px;
      box-shadow: 0 4px 12px rgba(22, 163, 74, 0.3);
      transition: opacity 0.2s;
    }}
    .btn:hover {{ opacity: 0.9; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <h1>Download Notice</h1>
    <p>{message}</p>
    <a href="https://fdownloader.online" class="btn">← Back to FDownloader</a>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=status_code)


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


def _ensure_ios_playable_video(file_path: str, audio_only: bool = False) -> str:
    """Fast remux for iOS faststart moov atom."""
    if audio_only or not file_path.endswith(".mp4"):
        return file_path

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    temp_target = file_path + ".ios_fixed.mp4"

    try:
        cmd_remux = [
            ffmpeg_bin, "-y", "-i", file_path,
            "-c", "copy",
            "-movflags", "+faststart",
            temp_target,
        ]
        res = subprocess.run(cmd_remux, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if res.returncode == 0 and os.path.isfile(temp_target) and os.path.getsize(temp_target) > 1000:
            os.replace(temp_target, file_path)
            return file_path
    except Exception:
        pass
    finally:
        if os.path.isfile(temp_target):
            try:
                os.remove(temp_target)
            except Exception:
                pass

    return file_path


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
            saved_path = _ensure_ios_playable_video(saved_path, audio_only=audio_only)
            return saved_path, title, ext
        except Exception as e:
            last_error = e
            continue

    raise last_error or RuntimeError("Could not download video via pytubefix fallback.")


def _execute_download(url: str, platform: str, ydl_format: str, output_template: str, download_dir: str, uid: str, format_str: str) -> tuple[str, str, str]:
    """Dual-engine pipeline: yt-dlp first, auto fallback to pytubefix if blocked."""
    _clean_old_cache()
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
                actual_file_path = _ensure_ios_playable_video(actual_file_path, audio_only=False)
                return actual_file_path, str(title), ext
    except Exception as ytdlp_err:
        if platform == "youtube":
            try:
                return _download_with_pytubefix(url, format_str, download_dir, uid)
            except Exception:
                raise ytdlp_err from None
        raise ytdlp_err

    raise RuntimeError("Downloaded file not found on disk.")


@app.get("/download")
async def download_video(
    request: Request,
    url: str = Query(...),
    format: str = Query("best"),
    api_key: str | None = Query(None),
):
    if API_SECRET_KEY and api_key != API_SECRET_KEY and request.headers.get("X-API-Key") != API_SECRET_KEY:
        return _render_error_page("Unauthorized request. Invalid API Key.", 401)

    if not _is_http_url(url):
        return _render_error_page("Invalid URL provided. Please provide a valid video link.", 400)

    platform = _platform(url)
    if not platform:
        return _render_error_page("Unsupported platform. Supported: Facebook, Twitter/X, Reddit, Instagram, TikTok, YouTube, Pinterest, LinkedIn, Snapchat, Threads.", 400)

    url = _normalize_url(url, platform)
    ydl_format, audio_only = _map_format(format)

    async with download_semaphore:
        uid = uuid.uuid4().hex[:10]
        item_dir = os.path.join(CACHE_DIR, uid)
        os.makedirs(item_dir, exist_ok=True)
        output_template = os.path.join(item_dir, f"{uid}.%(ext)s")
        
        try:
            actual_file_path, title, ext = await asyncio.to_thread(
                _execute_download,
                url,
                platform,
                ydl_format,
                output_template,
                item_dir,
                uid,
                format,
            )
        except Exception as exc:
            err_msg = _public_error(platform, exc)
            return _render_error_page(err_msg, 502)

        if not actual_file_path or not os.path.isfile(actual_file_path):
            return _render_error_page("Download finished but the file was not found on server.", 500)

        clean_ext = "mp3" if audio_only or ext == "mp3" else ext
        media_type = "audio/mpeg" if audio_only or clean_ext == "mp3" else "video/mp4"
        safe_name = _safe_filename(title, clean_ext)
        file_size = os.path.getsize(actual_file_path)

        return FileResponse(
            path=actual_file_path,
            media_type=media_type,
            filename=safe_name,
            headers={
                "Content-Length": str(file_size),
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "Accept-Ranges": "bytes",
                "Access-Control-Expose-Headers": "Content-Length, Content-Disposition, Content-Type, Accept-Ranges",
                "Cache-Control": "public, max-age=3600",
            },
        )


@app.get("/api/info", dependencies=[Depends(_verify_api_key)])
async def get_media_info(url: str = Query(...)):
    """API endpoint to extract media metadata (title, thumbnail, duration, platform)."""
    if not _is_http_url(url):
        raise HTTPException(status_code=400, detail="url must be a valid http or https link.")

    platform = _platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Platform not supported. Supported: Facebook, Twitter/X, Reddit, Instagram, TikTok, YouTube, Pinterest, LinkedIn, Snapchat, Threads.",
        )

    url = _normalize_url(url, platform)

    def _extract():
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            },
        }
        cookie_file = _get_cookie_file()
        if cookie_file:
            opts["cookiefile"] = cookie_file
        if PROXY_URL:
            opts["proxy"] = PROXY_URL

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]
            return info

    try:
        info = await asyncio.to_thread(_extract)
        return {
            "status": "success",
            "platform": platform,
            "title": info.get("title") or "Video",
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "formats": ["best", "1080p", "720p", "480p", "360p", "mp3"],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=_public_error(platform, e))


HOME_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>Social Media Video Downloader</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(20, 26, 43, 0.82);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --input-bg: rgba(15, 23, 42, 0.9);
      --radius: 18px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 20px 16px;
      -webkit-font-smoothing: antialiased;
    }
    .container {
      width: 100%;
      max-width: 540px;
      background: var(--card-bg);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 32px 24px;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.6);
    }
    .header {
      text-align: center;
      margin-bottom: 24px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 9999px;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.35);
      color: #a5b4fc;
      font-size: 0.8rem;
      font-weight: 500;
      margin-bottom: 12px;
    }
    h1 {
      font-size: 1.8rem;
      font-weight: 700;
      background: linear-gradient(180deg, #ffffff 0%, #cbd5e1 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 6px;
    }
    .subtitle {
      color: var(--text-muted);
      font-size: 0.92rem;
    }
    .platforms {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px;
      margin-top: 12px;
    }
    .pill {
      font-size: 0.72rem;
      padding: 3px 8px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: #cbd5e1;
    }
    .form-group {
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 0.85rem;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 8px;
    }
    .input-wrapper {
      position: relative;
      display: flex;
      align-items: center;
    }
    input[type="url"], select {
      width: 100%;
      background: var(--input-bg);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: #fff;
      font-family: inherit;
      font-size: 0.95rem;
      padding: 13px 14px;
      border-radius: 12px;
      outline: none;
      transition: border-color 0.2s;
      -webkit-appearance: none;
    }
    input[type="url"]:focus, select:focus {
      border-color: #818cf8;
    }
    .paste-btn {
      position: absolute;
      right: 8px;
      top: 50%;
      transform: translateY(-50%);
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: #e2e8f0;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 6px 10px;
      border-radius: 8px;
      cursor: pointer;
    }
    select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2394a3b8'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 14px center;
      background-size: 16px;
      padding-right: 36px;
    }
    .submit-btn {
      width: 100%;
      background: var(--accent-gradient);
      color: #ffffff;
      font-family: inherit;
      font-size: 1rem;
      font-weight: 600;
      padding: 14px;
      border-radius: 12px;
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 15px rgba(99, 102, 241, 0.35);
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      margin-top: 6px;
    }
    .submit-btn:active {
      opacity: 0.85;
    }
    .spinner {
      display: none;
      width: 18px;
      height: 18px;
      border: 2px solid rgba(255, 255, 255, 0.3);
      border-top-color: #ffffff;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .status-hint {
      display: none;
      margin-top: 14px;
      font-size: 0.85rem;
      text-align: center;
      color: #93c5fd;
    }
    .footer {
      margin-top: 20px;
      text-align: center;
      font-size: 0.78rem;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">✨ iPhone, iPad & Android Supported</div>
      <h1>Social Downloader</h1>
      <p class="subtitle">Download social media videos & audio in full quality</p>
      <div class="platforms">
        <span class="pill">Facebook</span>
        <span class="pill">Twitter (X)</span>
        <span class="pill">Reddit</span>
        <span class="pill">Instagram</span>
        <span class="pill">TikTok</span>
        <span class="pill">YouTube</span>
        <span class="pill">Pinterest</span>
      </div>
    </div>

    <!-- Standard native form submit guarantees 100% reliable iOS Safari download dialog -->
    <form id="dlForm" action="/download" method="get" onsubmit="showLoading()">
      <div class="form-group">
        <label for="url">Video Link</label>
        <div class="input-wrapper">
          <input id="url" name="url" type="url" required placeholder="Paste Facebook, X, Reddit, TikTok link..." />
          <button type="button" class="paste-btn" onclick="pasteClipboard()">Paste</button>
        </div>
      </div>

      <div class="form-group">
        <label for="format">Format / Quality</label>
        <select id="format" name="format">
          <option value="best" selected>Best Video Quality (MP4)</option>
          <option value="1080p">1080p Full HD (MP4)</option>
          <option value="720p">720p HD (MP4)</option>
          <option value="480p">480p SD (MP4)</option>
          <option value="360p">360p (MP4)</option>
          <option value="mp3">Audio Only (MP3)</option>
        </select>
      </div>

      <button type="submit" id="btnSubmit" class="submit-btn">
        <div id="btnSpinner" class="spinner"></div>
        <span id="btnText">Download Video</span>
      </button>

      <div id="statusHint" class="status-hint">
        ⏳ Downloading & optimizing video. Please wait...
      </div>
    </form>
  </div>

  <div class="footer">
    Fast download with native iOS Photos & Files app playback
  </div>

  <script>
    async function pasteClipboard() {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          document.getElementById('url').value = text;
        }
      } catch (err) {
        console.log('Clipboard access restricted');
      }
    }

    function showLoading() {
      const btn = document.getElementById('btnSubmit');
      const spinner = document.getElementById('btnSpinner');
      const btnText = document.getElementById('btnText');
      const hint = document.getElementById('statusHint');

      spinner.style.display = 'block';
      btnText.innerText = 'Processing...';
      hint.style.display = 'block';

      setTimeout(() => {
        spinner.style.display = 'none';
        btnText.innerText = 'Download Video';
        hint.style.display = 'none';
      }, 12000);
    }
  </script>
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
            "facebook",
            "twitter",
            "reddit",
            "instagram",
            "tiktok",
            "youtube",
            "pinterest",
            "linkedin",
            "snapchat",
            "threads",
        ],
        "backend": "yt-dlp",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
