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

# Folder where we temporarily save clips before sending them
CLIPS_DIR = "clips"
os.makedirs(CLIPS_DIR, exist_ok=True)

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="CutItNow API")

# CORS: allows your HTML page (running in a browser) to talk to this server.
# Without this the browser would block the request.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # In production: replace * with your domain
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve index.html and static files from a "static" folder
# so you can open your website at http://localhost:8000
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Data model ─────────────────────────────────────────────────────────────
# This describes exactly what the frontend must send us
class ClipRequest(BaseModel):
    url: str          # YouTube URL
    start: str        # e.g. "00:01:15"
    end: str          # e.g. "00:02:45"
    format: str       # "mp4" or "mp3"


# ── Routes ─────────────────────────────────────────────────────────────────

# Route 1: Health check — just to confirm the server is alive
@app.get("/")
def root():
    return {"status": "CutItNow API is running"}


# Route 2: Get video info (title, duration, thumbnail)
# The frontend calls this when the user pastes a URL
@app.get("/info")
def get_info(url: str):
    try:
        ydl_opts = {"quiet": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title":     info.get("title", "Unknown"),
            "duration":  info.get("duration", 0),   # seconds
            "thumbnail": info.get("thumbnail", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Route 3: Cut the clip — the main action
# Frontend sends a ClipRequest, we return the file
@app.post("/clip")
def cut_clip(req: ClipRequest):

    # Validate format
    if req.format not in ("mp4", "mp3"):
        raise HTTPException(status_code=400, detail="Format must be mp4 or mp3")

    # Give each clip a unique filename so two users don't overwrite each other
    clip_id = uuid.uuid4().hex
    output_path = os.path.join(CLIPS_DIR, f"{clip_id}.{req.format}")

    # ── Fetch stream URLs from YouTube ──
    try:
        if req.format == "mp3":
            ydl_opts = {"format": "bestaudio", "quiet": True}
        else:
            ydl_opts = {"format": "bestvideo[height<=1080]+bestaudio/best", "quiet": True}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video: {e}")

    # ── Build the ffmpeg command ──
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

    # ── Send the file back to the browser ──
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
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
