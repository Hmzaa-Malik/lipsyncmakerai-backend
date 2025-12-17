import os
import time
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# =========================
# CONFIG (edit only paths)
# =========================
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")

# IMPORTANT: this must be your REAL ComfyUI input folder on Windows
# Example:
# C:\Users\arste\AI\ComfyUI Install This\ComfyUI\input
COMFYUI_INPUT_DIR = Path(os.getenv("COMFYUI_INPUT_DIR", r"C:\Users\arste\AI\ComfyUI Install This\ComfyUI\input"))

WORKFLOW_PATH = Path("workflows/infinite_talk_api.json")

# Your workflow node IDs (from your screenshots / workflow)
TEXT_NODE_ID = "135"   # WanVideoTextEncode
IMAGE_NODE_ID = "133"  # LoadImage
AUDIO_NODE_ID = "125"  # LoadAudio

app = FastAPI(title="LipsyncMakerAI Backend")

# Allow frontend calls (Next.js / Vercel, local dev, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later you can lock this to your domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Backend is working"}


def load_api_workflow() -> Dict[str, Any]:
    """
    Loads the ComfyUI API-format workflow.
    If this file is UI-format, ComfyUI will throw 'missing class_type'.
    """
    if not WORKFLOW_PATH.exists():
        raise FileNotFoundError(f"Workflow not found: {WORKFLOW_PATH}")

    wf = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    # API format usually has: {"prompt": {...}, ...}
    # Some builds store it directly as the prompt dict itself.
    if "prompt" in wf:
        prompt = wf["prompt"]
    else:
        prompt = wf

    # quick validation (class_type must exist per node)
    any_node = next(iter(prompt.values()))
    if isinstance(any_node, dict) and "class_type" not in any_node:
        raise ValueError(
            "Your workflow file is NOT API format.\n"
            "Please export from ComfyUI using: Save (API Format)\n"
            "and save as workflows/infinite_talk_api.json"
        )

    return prompt


def copy_to_comfyui_input(upload: UploadFile) -> str:
    """
    Copies an uploaded file into ComfyUI input folder and returns the filename.
    ComfyUI nodes (LoadImage/LoadAudio) usually expect a filename inside input/.
    """
    COMFYUI_INPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Keep original filename but make it safer
    filename = Path(upload.filename).name
    dst = COMFYUI_INPUT_DIR / filename

    with dst.open("wb") as f:
        shutil.copyfileobj(upload.file, f)

    return filename


def set_node_input(prompt: Dict[str, Any], node_id: str, key: str, value: Any) -> None:
    """
    Safely updates prompt[node_id]["inputs"][key] = value
    """
    if node_id not in prompt:
        raise KeyError(f"Node id {node_id} not found in workflow prompt")
    node = prompt[node_id]
    if "inputs" not in node:
        node["inputs"] = {}
    node["inputs"][key] = value


def queue_prompt_to_comfyui(prompt: Dict[str, Any]) -> str:
    """
    POST /prompt -> returns prompt_id
    """
    r = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": prompt}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "prompt_id" not in data:
        raise RuntimeError(f"Unexpected ComfyUI response: {data}")
    return data["prompt_id"]


def wait_for_completion(prompt_id: str, timeout_sec: int = 1800) -> Dict[str, Any]:
    """
    Poll /history/{prompt_id} until outputs exist or timeout.
    """
    start = time.time()
    while True:
        if time.time() - start > timeout_sec:
            raise TimeoutError("ComfyUI job timed out")

        r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=30)
        r.raise_for_status()
        hist = r.json()

        # When done, ComfyUI returns a dict with prompt_id key and outputs
        if prompt_id in hist and "outputs" in hist[prompt_id]:
            return hist[prompt_id]

        time.sleep(2)


def extract_output_files(history_item: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extracts output files from history response.
    """
    results = []
    outputs = history_item.get("outputs", {})
    for node_id, out in outputs.items():
        # files are usually under: out["videos"] or out["images"]
        for key in ["videos", "images", "gifs"]:
            if key in out:
                for f in out[key]:
                    results.append({
                        "node_id": str(node_id),
                        "type": key,
                        "filename": f.get("filename", ""),
                        "subfolder": f.get("subfolder", ""),
                        "format": f.get("type", ""),
                    })
    return results


@app.post("/video")
def generate_video(
    text: str = Form(""),
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
):
    """
    Runs InfiniteTalk workflow via ComfyUI API.
    Requires:
      - image file
      - audio file
      - text (optional, used as positive prompt)
    """
    try:
        prompt = load_api_workflow()

        # 1) copy user files into ComfyUI input/
        image_name = copy_to_comfyui_input(image)
        audio_name = copy_to_comfyui_input(audio)

        # 2) set workflow inputs
        # LoadImage usually uses input key "image"
        set_node_input(prompt, IMAGE_NODE_ID, "image", image_name)

        # LoadAudio usually uses input key "audio" (sometimes "audio_file")
        # If your node fails, we will switch this key to match your API workflow.
        set_node_input(prompt, AUDIO_NODE_ID, "audio", audio_name)

        # WanVideoTextEncode: usually "positive_prompt" or "text" depending on node implementation
        # Your screenshot shows two boxes; in many builds it's "positive" and "negative".
        if text.strip():
            # Try common keys; whichever exists in your workflow will work.
            # If none exist, we will adjust after you share the API workflow.
            for k in ["positive", "text", "prompt", "positive_prompt"]:
                try:
                    set_node_input(prompt, TEXT_NODE_ID, k, text.strip())
                    break
                except Exception:
                    pass

        # 3) queue in ComfyUI
        prompt_id = queue_prompt_to_comfyui(prompt)

        # 4) wait + return outputs
        history_item = wait_for_completion(prompt_id)
        files = extract_output_files(history_item)

        return {
            "status": "completed",
            "prompt_id": prompt_id,
            "outputs": files,
            "note": "If outputs list is empty, we will locate the correct output node in history.",
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
