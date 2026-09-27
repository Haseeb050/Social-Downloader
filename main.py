import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from urllib.parse import parse_qs, quote, urlparse

import yt_dlp
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from starlette.background import BackgroundTask

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

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def _verify_api_key(
    header_key: str | None = Security(api_key_header),
    query_key: str | None = Security(api_key_query),
):
    """If API_SECRET_KEY is configured in .env, require it in headers or query params."""
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
    allow_origins=ALLOWED_ORIGINS if "*" not in ALLOWED_ORIGINS else ["*"],
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
    if host in {"twitter.com", "x.com", "t.co"} or host.endswith(".twitter.com") or host.endswith(".x.com"):
        return "twitter"
    if host in {"facebook.com", "fb.watch", "fb.com", "m.facebook.com", "web.facebook.com"} or host.endswith(".facebook.com"):
        return "facebook"
    if host in {"reddit.com", "redd.it", "v.redd.it"} or host.endswith(".reddit.com"):
        return "reddit"
    if host in {"instagram.com", "instagr.am"} or host.endswith(".instagram.com"):
        return "instagram"
    if host in {"tiktok.com", "vt.tiktok.com", "vm.tiktok.com"} or host.endswith(".tiktok.com"):
        return "tiktok"
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "youtube"
    if host in {"snapchat.com"} or host.endswith(".snapchat.com"):
        return "snapchat"
    if host in {"linkedin.com"} or host.endswith(".linkedin.com"):
        return "linkedin"
    if host in {"pinterest.com", "pin.it"} or host.endswith(".pinterest.com") or host.endswith(".pin.it"):
        return "pinterest"
    if host in {"threads.net"} or host.endswith(".threads.net"):
        return "threads"
    return None


def _resolve_url(url: str) -> str:
    """Follow HTTP redirects for short URLs (e.g. Reddit /s/, Snapchat /t/, TikTok vt/vm, LinkedIn lnkd.in, etc.)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    needs_resolve = (
        "/s/" in parsed.path
        or "/share/" in parsed.path
        or "/t/" in parsed.path
        or host in {"lnkd.in", "pin.it", "t.co", "vt.tiktok.com", "vm.tiktok.com", "fb.watch", "youtu.be", "redd.it"}
    )
    if not needs_resolve:
        return url

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return e.headers.get("Location")
        return url
    except Exception:
        return url


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
    if platform == "threads":
        clean_path = parsed.path.rstrip("/")
        return f"https://www.threads.net{clean_path}"
    return url


def _map_format(fmt: str) -> tuple[str, bool]:
    raw = (fmt or "best").strip().lower()
    audio_only = raw in {"mp3", "audio", "bestaudio", "wav", "ogg"}
    if audio_only:
        return "bestaudio[ext=m4a]/bestaudio/best", True
    height = QUALITY_HEIGHT.get(raw)
    if height:
        return (
            f"bestvideo[height<={height}][vcodec^=avc][ext=mp4]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height<={height}][vcodec^=avc]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best",
            False,
        )
    return (
        "bestvideo[vcodec^=avc][ext=mp4]+bestaudio[acodec^=mp4a]/"
        "bestvideo[vcodec^=avc]+bestaudio[ext=m4a]/"
        "bestvideo[ext=mp4]+bestaudio[acodec^=mp4a]/"
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo+bestaudio/best",
        False,
    )


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


def _ydl_opts(platform: str, ydl_format: str, output_template: str, audio_only: bool = False) -> dict:
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

    if audio_only:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        opts["postprocessors"] = [
            {
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4",
            }
        ]
        # Ensure universal iOS Safari & Android audio/video codec + moov atom faststart
        opts["postprocessor_args"] = {
            "merger": [
                "-c:v", "copy",
                "-c:a", "aac",
                "-movflags", "+faststart",
            ],
            "videoremuxer": [
                "-movflags", "+faststart",
            ],
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


def _post_process_for_ios(file_path: str, audio_only: bool = False) -> str:
    """Ensure MP4 has faststart moov atom header for immediate iOS Safari streaming and Photos app playback."""
    if audio_only or not file_path.endswith(".mp4"):
        return file_path
    
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    temp_faststart = file_path + ".faststart.mp4"
    try:
        cmd = [
            ffmpeg_bin, "-y", "-i", file_path,
            "-c", "copy",
            "-movflags", "+faststart",
            temp_faststart,
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        if res.returncode == 0 and os.path.isfile(temp_faststart) and os.path.getsize(temp_faststart) > 0:
            os.replace(temp_faststart, file_path)
    except Exception:
        if os.path.isfile(temp_faststart):
            try:
                os.remove(temp_faststart)
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
                    stream = yt.streams.filter(progressive=True, res=f"{height}p", file_extension="mp4").first()
                    if not stream:
                        stream = yt.streams.filter(res=f"{height}p", file_extension="mp4").first()
                if not stream:
                    stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
                if not stream:
                    stream = yt.streams.get_highest_resolution() or yt.streams.first()

            if not stream:
                continue

            title = yt.title or "video"
            ext = "mp3" if audio_only else (stream.subtype or "mp4")
            out_file = f"{uid}.{ext}"
            saved_path = stream.download(output_path=download_dir, filename=out_file)
            saved_path = _post_process_for_ios(saved_path, audio_only=audio_only)
            return saved_path, title, ext
        except Exception as e:
            last_error = e
            continue

    raise last_error or RuntimeError("Could not download video via pytubefix fallback.")


def _execute_download(url: str, platform: str, ydl_format: str, output_template: str, download_dir: str, uid: str, format_str: str, audio_only: bool = False) -> tuple[str, str, str]:
    """Dual-engine pipeline: yt-dlp first, auto fallback to pytubefix if blocked."""
    try:
        opts = _ydl_opts(platform, ydl_format, output_template, audio_only=audio_only)
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
                actual_file_path = _post_process_for_ios(actual_file_path, audio_only=audio_only)
                return actual_file_path, str(title), ext
    except Exception as ytdlp_err:
        if platform == "youtube":
            try:
                return _download_with_pytubefix(url, format_str, download_dir, uid)
            except Exception:
                raise ytdlp_err from None
        raise ytdlp_err

    raise RuntimeError("Downloaded file not found on disk.")


@app.get("/download", dependencies=[Depends(_verify_api_key)])
async def download_video(url: str = Query(...), format: str = Query("best")):
    if not _is_http_url(url):
        raise HTTPException(status_code=400, detail="url must be a valid http or https link.")

    url = await asyncio.to_thread(_resolve_url, url)
    platform = _platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Platform not supported. Supported: Facebook, Twitter/X, Reddit, Instagram, TikTok, YouTube, Pinterest, LinkedIn, Snapchat, Threads.",
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
                audio_only,
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

        clean_ext = "mp3" if audio_only or ext == "mp3" else ext
        media_type = "audio/mpeg" if audio_only or clean_ext == "mp3" else "video/mp4"

        return FileResponse(
            path=actual_file_path,
            media_type=media_type,
            headers={
                "Content-Disposition": _content_disposition(title, clean_ext),
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            background=BackgroundTask(_cleanup, download_dir),
        )


@app.get("/api/info", dependencies=[Depends(_verify_api_key)])
async def get_media_info(url: str = Query(...)):
    """API endpoint to extract media metadata (title, thumbnail, duration, platform)."""
    if not _is_http_url(url):
        raise HTTPException(status_code=400, detail="url must be a valid http or https link.")

    url = await asyncio.to_thread(_resolve_url, url)
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
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
      --card-bg: rgba(20, 26, 43, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --input-bg: rgba(15, 23, 42, 0.85);
      --radius: 16px;
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
      padding: 24px 16px;
      position: relative;
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
    }
    body::before, body::after {
      content: '';
      position: absolute;
      width: 320px;
      height: 320px;
      border-radius: 50%;
      filter: blur(120px);
      z-index: 0;
      pointer-events: none;
    }
    body::before {
      background: rgba(99, 102, 241, 0.25);
      top: 10%;
      left: 15%;
    }
    body::after {
      background: rgba(236, 72, 153, 0.2);
      bottom: 15%;
      right: 15%;
    }
    .container {
      width: 100%;
      max-width: 580px;
      background: var(--card-bg);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 36px 28px;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.5);
      position: relative;
      z-index: 1;
    }
    .header {
      text-align: center;
      margin-bottom: 28px;
    }
    .logo-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 9999px;
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: #818cf8;
      font-size: 0.85rem;
      font-weight: 500;
      margin-bottom: 12px;
    }
    h1 {
      font-size: 1.85rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: linear-gradient(180deg, #ffffff 0%, #cbd5e1 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 8px;
    }
    .subtitle {
      color: var(--text-muted);
      font-size: 0.95rem;
    }
    .platforms {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px;
      margin-top: 14px;
    }
    .pill {
      font-size: 0.75rem;
      padding: 4px 10px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.07);
      color: #cbd5e1;
    }
    .form-group {
      margin-bottom: 20px;
    }
    label {
      display: block;
      font-size: 0.88rem;
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
      padding: 14px 16px;
      border-radius: 12px;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
      -webkit-appearance: none;
    }
    input[type="url"]:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
    }
    .paste-btn {
      position: absolute;
      right: 8px;
      top: 50%;
      transform: translateY(-50%);
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: #e2e8f0;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 6px 12px;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.2s;
    }
    .paste-btn:hover {
      background: rgba(255, 255, 255, 0.16);
    }
    select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2394a3b8'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 14px center;
      background-size: 18px;
      padding-right: 40px;
    }
    .submit-btn {
      width: 100%;
      background: var(--accent-gradient);
      color: #ffffff;
      font-family: inherit;
      font-size: 1.05rem;
      font-weight: 600;
      padding: 15px;
      border-radius: 12px;
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 15px rgba(99, 102, 241, 0.35);
      transition: transform 0.15s, opacity 0.2s;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
    }
    .submit-btn:hover {
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45);
    }
    .submit-btn:active {
      transform: translateY(1px);
    }
    .submit-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
      transform: none;
    }
    .spinner {
      display: none;
      width: 20px;
      height: 20px;
      border: 3px solid rgba(255, 255, 255, 0.3);
      border-top-color: #ffffff;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .status-msg {
      margin-top: 18px;
      font-size: 0.88rem;
      text-align: center;
      display: none;
      padding: 10px 14px;
      border-radius: 10px;
    }
    .status-msg.loading {
      display: block;
      background: rgba(99, 102, 241, 0.12);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.25);
    }
    .status-msg.error {
      display: block;
      background: rgba(239, 68, 68, 0.12);
      color: #fca5a5;
      border: 1px solid rgba(239, 68, 68, 0.25);
    }
    .status-msg.success {
      display: block;
      background: rgba(34, 197, 94, 0.12);
      color: #86efac;
      border: 1px solid rgba(34, 197, 94, 0.25);
    }
    .footer {
      margin-top: 24px;
      text-align: center;
      font-size: 0.8rem;
      color: var(--text-muted);
      z-index: 1;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="logo-badge">⚡ iOS & Android Compatible</div>
      <h1>Social Video Downloader</h1>
      <p class="subtitle">Download videos and audio in highest quality</p>
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

    <form id="dlForm" onsubmit="handleDownload(event)">
      <div class="form-group">
        <label for="url">Video URL</label>
        <div class="input-wrapper">
          <input id="url" name="url" type="url" required placeholder="Paste link from Facebook, X, Reddit, TikTok..." />
          <button type="button" class="paste-btn" onclick="pasteClipboard()">Paste</button>
        </div>
      </div>

      <div class="form-group">
        <label for="format">Download Format & Quality</label>
        <select id="format" name="format">
          <option value="best" selected>Best Quality (MP4)</option>
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

      <div id="statusBox" class="status-msg"></div>
    </form>
  </div>

  <div class="footer">
    Fast, private & compatible with iPhone, iPad, Android and PC
  </div>

  <script>
    async function pasteClipboard() {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          document.getElementById('url').value = text;
        }
      } catch (err) {
        console.log('Clipboard paste not allowed:', err);
      }
    }

    async function handleDownload(e) {
      e.preventDefault();
      const urlInput = document.getElementById('url').value.trim();
      const format = document.getElementById('format').value;
      const btn = document.getElementById('btnSubmit');
      const spinner = document.getElementById('btnSpinner');
      const btnText = document.getElementById('btnText');
      const status = document.getElementById('statusBox');

      if (!urlInput) return;

      btn.disabled = true;
      spinner.style.display = 'block';
      btnText.innerText = 'Processing Video...';
      status.className = 'status-msg loading';
      status.innerText = 'Fetching and optimizing video for iOS & Android playback...';

      try {
        const downloadUrl = `/download?url=${encodeURIComponent(urlInput)}&format=${encodeURIComponent(format)}`;
        
        // Trigger download directly so iOS Safari and Android Chrome handle the stream seamlessly
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.setAttribute('download', '');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        status.className = 'status-msg success';
        status.innerText = 'Download started! Check your downloads or files.';
      } catch (err) {
        status.className = 'status-msg error';
        status.innerText = 'Error initiating download. Please try again.';
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          spinner.style.display = 'none';
          btnText.innerText = 'Download Video';
        }, 3000);
      }
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
