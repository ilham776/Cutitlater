import subprocess

# Install Node.js for yt-dlp signature solving
try:
    subprocess.run(["node", "--version"], check=True, capture_output=True)
except FileNotFoundError:
    subprocess.run(["nodeenv", "--prebuilt", "/tmp/node"], capture_output=True)
    os.environ["PATH"] = "/tmp/node/bin:" + os.environ.get("PATH", "")
import os
import subprocess
import uuid
import imageio_ffmpeg
import yt_dlp

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Setup ──────────────────────────────────────────────────────────────────
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

CLIPS_DIR = "clips"
os.makedirs(CLIPS_DIR, exist_ok=True)

# ── Cookies setup ──────────────────────────────────────────────────────────
# Railway stores the cookies content as an environment variable.
# We write it to a temp file so yt-dlp can read it.
COOKIES_FILE = "cookies.txt"

def setup_cookies():
    cookies_content = os.environ.get("YOUTUBE_COOKIES")
    if cookies_content:
        with open(COOKIES_FILE, "w") as f:
            f.write(cookies_content)
        return True
    return False

COOKIES_AVAILABLE = setup_cookies()

def get_ydl_opts(format_str):
    opts = {
        "format": format_str,
        "quiet": True,
    }
    if COOKIES_AVAILABLE:
        opts["cookiefile"] = COOKIES_FILE
    return opts

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="CutItNow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Data model ─────────────────────────────────────────────────────────────
class ClipRequest(BaseModel):
    url: str
    start: str
    end: str
    format: str

# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status": "CutItNow API is running",
        "cookies": "loaded" if COOKIES_AVAILABLE else "not found"
    }

@app.get("/info")
def get_info(url: str):
    try:
        ydl_opts = get_ydl_opts("best")
        ydl_opts["skip_download"] = True
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title":     info.get("title", "Unknown"),
            "duration":  info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/clip")
def cut_clip(req: ClipRequest):
    if req.format not in ("mp4", "mp3"):
        raise HTTPException(status_code=400, detail="Format must be mp4 or mp3")

    clip_id = uuid.uuid4().hex
    output_path = os.path.join(CLIPS_DIR, f"{clip_id}.{req.format}")

    # Fetch stream URLs
    try:
        if req.format == "mp3":
            ydl_opts = get_ydl_opts("bestaudio")
        else:
            ydl_opts = get_ydl_opts("bestvideo+bestaudio/best/best")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video: {e}")

    # Build ffmpeg command
    try:
        if req.format == "mp3":
            audio_url = info["url"]
            cmd = [
                ffmpeg_path, "-y",
                "-ss", req.start, "-to", req.end,
                "-i", audio_url,
                "-vn",
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                output_path,
            ]
        else:
            if "requested_formats" in info:
                video_url = info["requested_formats"][0]["url"]
                audio_url = info["requested_formats"][1]["url"]
                cmd = [
                    ffmpeg_path, "-y",
                    "-ss", req.start, "-to", req.end, "-i", video_url,
                    "-ss", req.start, "-to", req.end, "-i", audio_url,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path,
                ]
            else:
                video_url = info["url"]
                cmd = [
                    ffmpeg_path, "-y",
                    "-ss", req.start, "-to", req.end,
                    "-i", video_url,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path,
                ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if result.returncode != 0:
            raise Exception(result.stderr.decode())

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ffmpeg error: {e}")

    mime = "audio/mpeg" if req.format == "mp3" else "video/mp4"
    filename = f"cutitnow_clip.{req.format}"

    return FileResponse(
        path=output_path,
        media_type=mime,
        filename=filename,
    )

# ── Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
