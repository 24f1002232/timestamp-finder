# Video Timestamp Finder API

FastAPI endpoint that finds exact timestamps in YouTube videos using yt-dlp + Gemini Audio API.

## Setup & Run

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-gemini-api-key"
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Test

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"video_url": "https://youtu.be/dQw4w9WgXcQ", "topic": "never gonna give you up"}'
```

## Deploy to Railway

1. Push to GitHub
2. railway.app → New Project → from GitHub
3. Add env var: GEMINI_API_KEY
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Note: Make sure yt-dlp is available in the deployment environment.
Add to nixpacks.toml if needed:
```toml
[phases.setup]
nixPkgs = ["yt-dlp", "ffmpeg"]
```
