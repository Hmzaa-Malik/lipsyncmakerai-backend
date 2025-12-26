import os
import time
import uuid
import shutil
import requests
from enum import Enum
from typing import Dict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# =========================
# CONFIG
# =========================
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORKFLOW_PATH = os.path.join(BASE_DIR, "Workflows", "infinite_talk_api.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================
# APP INIT
# =========================
app = FastAPI(title="LipsyncMakerAI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# JOB SYSTEM
# =========================
class JobStatus(str, Enum):
    queued = "queued"
    uploading = "uploading"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"

jobs: Dict[str, dict] = {}

# =========================
# HELPERS
# =========================
def save_upload(file: UploadFile) -> str:
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return path


def upload_to_comfyui(file_path: str, file_type: str) -> str:
    endpoint = f"{COMFYUI_URL}/upload/{file_type}"
    with open(file_path, "rb") as f:
        r = requests.post(endpoint, files={"file": f})
    r.raise_for_status()
    return r.json()["name"]


def load_workflow(image_name: str, audio_name: str, text: str) -> dict:
    import json

    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    for node in workflow["nodes"]:
        if node["type"] == "LoadImage":
            node["widgets_values"][0] = image_name
        if node["type"] == "LoadAudio":
            node["widgets_values"][0] = audio_name
        if node["type"] == "WanVideoTextEncode":
            node["widgets_values"][2] = text or ""

    return workflow


def submit_workflow(workflow: dict) -> str:
    r = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow})
    r.raise_for_status()
    return r.json()["prompt_id"]


def wait_for_output(prompt_id: str) -> str:
    while True:
        r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}")
        r.raise_for_status()
        history = r.json()

        if prompt_id in history:
            outputs = history[prompt_id]["outputs"]
            for node in outputs.values():
                if "videos" in node:
                    return node["videos"][0]["filename"]

        time.sleep(2)

# =========================
# ROUTES
# =========================
@app.get("/")
def root():
    return {"status": "ok", "service": "LipsyncMakerAI Backend"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/video")
def generate_video(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    text: str = Form("")
):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": JobStatus.queued,
        "output": None,
        "error": None,
    }

    try:
        jobs[job_id]["status"] = JobStatus.uploading

        image_path = save_upload(image)
        audio_path = save_upload(audio)

        image_name = upload_to_comfyui(image_path, "image")
        audio_name = upload_to_comfyui(audio_path, "audio")

        workflow = load_workflow(image_name, audio_name, text)

        jobs[job_id]["status"] = JobStatus.rendering

        prompt_id = submit_workflow(workflow)
        output_filename = wait_for_output(prompt_id)

        jobs[job_id]["status"] = JobStatus.completed
        jobs[job_id]["output"] = output_filename

        return {
            "job_id": job_id,
            "status": jobs[job_id]["status"]
        }

    except Exception as e:
        jobs[job_id]["status"] = JobStatus.failed
        jobs[job_id]["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/job/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": jobs[job_id]["status"],
        "output": jobs[job_id]["output"],
        "error": jobs[job_id]["error"],
    }


@app.get("/output/{filename}")
def get_output(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="video/mp4")
