import json
from pathlib import Path
from .comfyui_client import run_infinite_talk

WORKFLOW_PATH = Path("workflows/infinite_talk.json")

def generate_video(image_path, audio_path, text):
    workflow = json.loads(WORKFLOW_PATH.read_text())

    # 🔴 THESE NODE IDS MUST MATCH YOUR WORKFLOW
    IMAGE_NODE_ID = "1"
    AUDIO_NODE_ID = "15"
    TEXT_NODE_ID = "5"

    workflow[IMAGE_NODE_ID]["inputs"]["image"] = image_path
    workflow[AUDIO_NODE_ID]["inputs"]["audio"] = audio_path
    workflow[TEXT_NODE_ID]["inputs"]["positive"] = text

    return run_infinite_talk(workflow)
