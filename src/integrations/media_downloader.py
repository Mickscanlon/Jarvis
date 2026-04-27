"""
media_downloader.py - yt-dlp for YouTube/video, instaloader for Instagram
"""
import os
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DOWNLOAD_BASE = Path("C:/Users/micha/Downloads/JARVIS")
VIDEO_DIR = DOWNLOAD_BASE / "Video"
MUSIC_DIR = DOWNLOAD_BASE / "Music"
INSTAGRAM_DIR = DOWNLOAD_BASE / "Instagram"


def _ensure_dirs():
    for d in [VIDEO_DIR, MUSIC_DIR, INSTAGRAM_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _notify(title: str, message: str):
    try:
        from tools import send_notification
        send_notification(title, message)
    except Exception:
        pass


def download_video(url: str, audio_only: bool = False, notify: bool = True):
    """Download video or audio from YouTube/any supported site via yt-dlp."""
    _ensure_dirs()

    def _run():
        try:
            import yt_dlp
            dest = MUSIC_DIR if audio_only else VIDEO_DIR

            ydl_opts = {
                "outtmpl": str(dest / "%(title)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }

            if audio_only:
                ydl_opts.update({
                    "format": "bestaudio/best",
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                })
            else:
                ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", url)

            if notify:
                _notify("JARVIS Download Complete", f"{'Audio' if audio_only else 'Video'}: {title}")
            logger.info(f"[Download] Complete: {title}")
        except Exception as e:
            logger.error(f"[Download] Video error: {e}")
            if notify:
                _notify("JARVIS Download Failed", str(e)[:100])

    threading.Thread(target=_run, daemon=True).start()
    return "Download started, sir. I'll notify you when it's done."


def search_and_download_audio(query: str) -> str:
    """Search YouTube and download the top result as MP3."""
    url = f"ytsearch1:{query}"
    return download_video(url, audio_only=True)


def download_instagram(url: str, notify: bool = True) -> str:
    """Download Instagram post, reel, or story."""
    _ensure_dirs()

    def _run():
        try:
            import instaloader
            L = instaloader.Instaloader(
                dirname_pattern=str(INSTAGRAM_DIR / "{target}"),
                filename_pattern="{date_utc}_UTC_{shortcode}",
                save_metadata=False, download_geotags=False, download_comments=False,
                post_metadata_txt_pattern="", storyitem_metadata_txt_pattern=""
            )
            shortcode = url.split("/")[-2] if "/" in url else url
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            L.download_post(post, target=INSTAGRAM_DIR)
            if notify:
                _notify("JARVIS", f"Instagram download complete: {shortcode}")
        except Exception as e:
            logger.error(f"[Download] Instagram error: {e}")
            if notify:
                _notify("JARVIS Download Failed", str(e)[:100])

    threading.Thread(target=_run, daemon=True).start()
    return "Instagram download started, sir."


def download_file(url: str, destination: str = None) -> str:
    """Download a direct file URL."""
    import httpx
    from urllib.parse import urlparse

    filename = os.path.basename(urlparse(url).path) or "download"
    if not destination:
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".mp4", ".mkv", ".avi", ".mov"):
            destination = str(VIDEO_DIR)
        elif ext in (".mp3", ".wav", ".flac", ".m4a"):
            destination = str(MUSIC_DIR)
        else:
            destination = str(DOWNLOAD_BASE)

    _ensure_dirs()
    dest_path = os.path.join(destination, filename)

    def _run():
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            _notify("JARVIS", f"Download complete: {filename}")
        except Exception as e:
            _notify("JARVIS Download Failed", str(e)[:100])

    threading.Thread(target=_run, daemon=True).start()
    return f"Downloading {filename}, sir. I'll notify you when done."
