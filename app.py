from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# Endpoint to check if backend is working
@app.get("/")
def root():
    return {"message": "Backend is working"}

# Endpoint for Text-to-Speech (TTS)
class TTSRequest(BaseModel):
    text: str
    language: str

@app.post("/tts")
def generate_tts(req: TTSRequest):
    return {
        "status": "ok",
        "text": req.text,
        "language": req.language
    }

# Endpoint for video generation
class VideoRequest(BaseModel):
    text: str
    video_path: str

@app.post("/video")
def generate_video(req: VideoRequest):
    return {
        "status": "ok",
        "text": req.text,
        "video_path": req.video_path
    }
