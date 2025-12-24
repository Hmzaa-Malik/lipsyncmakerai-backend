import json
import time
import uuid
import shutil
import requests
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# ===================== CONFIG =====================

COMFY_URL = "http://192.168.56.1:8188"

# Your sanitized workflow (the one you already created)
WORKFLOW_PATH = Path("Workflows/infinite_talk_api.json")

# IMPORTANT: These must match your real ComfyUI folders
COMFY_INPUT_DIR = Path(r"D:\AI\ComfyUI\input")
COMFY_OUTPUT_DIR = Path(r"D:\AI\ComfyUI\output")

# Backend local folders (optional, but useful)
BASE_DIR = Path(__file__).parent
LOCAL_INPUT_DIR = BASE_DIR / "input"
LOCAL_INPUT_DIR.mkdir(exist_ok=True)

# ===================== APP =====================

app = FastAPI(title="LipsyncMakerAI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== HELPERS =====================

def safe_name(original: str) -> str:
    # Avoid spaces and weird chars to keep ComfyUI happy
    keep = []
    for ch in original:
        if ch.isalnum() or ch in ("_", "-", ".",):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep)

def load_workflow() -> dict:
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def patch_workflow(wf: dict, image_filename: str, audio_filename: str, text: str):
    """
    Your workflow JSON is "nodes/links" style.
    We patch widget values inside nodes:
      - LoadImage -> widgets_values[0] = image filename
      - LoadAudio -> widgets_values[0] = audio filename
      - WanVideoTextEncode -> widgets_values[0] = text (optional)
    """
    for node in wf.get("nodes", []):
        if node.get("type") == "LoadImage":
            # widgets_values = [filename, "image"]
            node["widgets_values"][0] = image_filename

        if node.get("type") == "LoadAudio":
            # widgets_values = [filename, null, null]
            node["widgets_values"][0] = audio_filename

        if node.get("type") == "WanVideoTextEncode":
            if text and isinstance(node.get("widgets_values"), list) and len(node["widgets_values"]) > 0:
                node["widgets_values"][0] = text

def submit_prompt(workflow_dict: dict) -> str:
    """
    ComfyUI expects: {"prompt": <something>}
    Many builds accept full workflow dict here because ComfyUI custom frontends translate it.
    If your ComfyUI rejects it later, we will switch to "API prompt format" mapping node IDs.
    """
    payload = {
        "prompt": workflow_dict,
        "client_id": str(uuid.uuid4())
    }
    r = requests.post(f"{COMFY_URL}/prompt", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["prompt_id"]

def find_any_mp4(obj):
    """
    Walk any nested dict/list and return first filename ending with .mp4
    Also supports ComfyUI history format where file dict has {"filename": "..."}
    """
    if isinstance(obj, dict):
        # common case: {"filename": "..."}
        fn = obj.get("filename")
        if isinstance(fn, str) and fn.lower().endswith(".mp4"):
            return fn

        for v in obj.values():
            got = find_any_mp4(v)
            if got:
                return got

    if isinstance(obj, list):
        for item in obj:
            got = find_any_mp4(item)
            if got:
                return got

    if isinstance(obj, str) and obj.lower().endswith(".mp4"):
        return obj

    return None

def wait_for_video(prompt_id: str, timeout_seconds=1200) -> str:
    start = time.time()
    while time.time() - start < timeout_seconds:
        r = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=30)
        if r.status_code == 200:
            data = r.json()
            mp4 = find_any_mp4(data)
            if mp4:
                return mp4
        time.sleep(2)
    raise TimeoutError("Timed out waiting for MP4 in ComfyUI history")

# ===================== ROUTES =====================

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy", "comfyui": COMFY_URL}

@app.post("/video")
async def generate_video(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    text: str = Form("")
):
    try:
        if not COMFY_INPUT_DIR.exists():
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"ComfyUI input folder not found: {COMFY_INPUT_DIR}"}
            )

        if not COMFY_OUTPUT_DIR.exists():
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"ComfyUI output folder not found: {COMFY_OUTPUT_DIR}"}
            )

        job_id = str(uuid.uuid4())[:8]

        img_name = safe_name(f"{job_id}_{image.filename}")
        aud_name = safe_name(f"{job_id}_{audio.filename}")

        local_img = LOCAL_INPUT_DIR / img_name
        local_aud = LOCAL_INPUT_DIR / aud_name

        with open(local_img, "wb") as f:
            shutil.copyfileobj(image.file, f)

        with open(local_aud, "wb") as f:
            shutil.copyfileobj(audio.file, f)

        # Copy into ComfyUI input so LoadImage/LoadAudio can see them
        comfy_img = COMFY_INPUT_DIR / img_name
        comfy_aud = COMFY_INPUT_DIR / aud_name

        shutil.copy2(local_img, comfy_img)
        shutil.copy2(local_aud, comfy_aud)

        # Load + patch workflow
        wf = load_workflow()
        patch_workflow(wf, img_name, aud_name, text.strip())

        # Submit to ComfyUI
        prompt_id = submit_prompt(wf)

        # Wait for mp4 name in history
        video_filename = wait_for_video(prompt_id)

        return {
            "status": "success",
            "prompt_id": prompt_id,
            "video": video_filename,
            "download": f"/output/{video_filename}"
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

@app.get("/output/{filename}")
def get_output(filename: str):
    fp = COMFY_OUTPUT_DIR / filename
    if not fp.exists():
        return JSONResponse(status_code=404, content={"status": "error", "message": "File not found in ComfyUI output"})
    return FileResponse(fp, media_type="video/mp4", filename=filename)
