from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import tempfile
import time
import re
import subprocess

app = FastAPI(title="Video Timestamp Finder")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    video_url: str
    topic: str


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_timestamp_to_hhmmss(ts: str) -> str:
    """Ensure timestamp is in HH:MM:SS format."""
    ts = ts.strip()
    # Already HH:MM:SS
    if re.match(r'^\d{2}:\d{2}:\d{2}$', ts):
        return ts
    # MM:SS format
    if re.match(r'^\d{1,2}:\d{2}$', ts):
        parts = ts.split(':')
        return f"00:{int(parts[0]):02d}:{int(parts[1]):02d}"
    # Plain seconds
    if re.match(r'^\d+$', ts):
        return seconds_to_hhmmss(int(ts))
    # Try to extract any HH:MM:SS pattern from string
    match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', ts)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}:{int(match.group(3)):02d}"
    match = re.search(r'(\d{1,2}):(\d{2})', ts)
    if match:
        return f"00:{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    return "00:00:00"


@app.post("/ask")
async def ask(body: AskRequest):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    tmp_audio = None
    uploaded_file = None

    try:
        # Step 1: Download audio using yt-dlp
        tmp_dir = tempfile.mkdtemp()
        tmp_audio = os.path.join(tmp_dir, "audio.mp3")

        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--no-playlist",
            "-o", tmp_audio,
            body.video_url
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"yt-dlp error: {result.stderr}")

        if not os.path.exists(tmp_audio):
            # yt-dlp may add extension
            for f in os.listdir(tmp_dir):
                if f.startswith("audio"):
                    tmp_audio = os.path.join(tmp_dir, f)
                    break

        if not os.path.exists(tmp_audio):
            raise HTTPException(status_code=500, detail="Audio file not created")

        # Step 2: Upload to Gemini Files API
        uploaded_file = client.files.upload(
            file=tmp_audio,
            config=types.UploadFileConfig(mime_type="audio/mpeg")
        )

        # Step 3: Poll until ACTIVE
        max_wait = 120
        waited = 0
        while uploaded_file.state.name != "ACTIVE" and waited < max_wait:
            time.sleep(3)
            waited += 3
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name != "ACTIVE":
            raise HTTPException(status_code=500, detail="File processing timed out")

        # Step 4: Ask Gemini to find timestamp using structured output
        prompt = f"""Listen to this audio carefully and find the exact moment when the following topic is spoken or discussed:

Topic: "{body.topic}"

Return ONLY the timestamp in HH:MM:SS format (e.g., "00:05:47") when this topic first appears.
If not found, return "00:00:00"."""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Content(parts=[
                    types.Part(file_data=types.FileData(
                        file_uri=uploaded_file.uri,
                        mime_type="audio/mpeg"
                    )),
                    types.Part(text=prompt)
                ])
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "timestamp": types.Schema(
                            type=types.Type.STRING,
                            description="Timestamp in HH:MM:SS format"
                        )
                    },
                    required=["timestamp"]
                ),
                temperature=0
            )
        )

        import json
        result_data = json.loads(response.text)
        timestamp = parse_timestamp_to_hhmmss(result_data.get("timestamp", "00:00:00"))

        return JSONResponse(content={
            "timestamp": timestamp,
            "video_url": body.video_url,
            "topic": body.topic
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Cleanup
        if tmp_audio and os.path.exists(tmp_audio):
            try:
                os.remove(tmp_audio)
            except:
                pass
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
            except:
                pass


@app.get("/health")
async def health():
    return {"status": "ok"}
