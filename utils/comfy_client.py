import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

import requests


class ComfyClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/system_stats", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # -----------------------
    # Upload
    # -----------------------
    def upload_image(self, path: Path) -> str:
        """
        ComfyUI upload image endpoint returns {name: "..."} or similar.
        """
        files = {"image": (path.name, path.read_bytes())}
        r = requests.post(f"{self.base_url}/upload/image", files=files, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data.get("name") or data.get("filename") or path.name

    def upload_audio(self, path: Path) -> str:
        """
        Some Comfy builds accept /upload/audio, others use /upload/image only.
        If your ComfyUI has audio upload endpoint, this works.
        """
        files = {"audio": (path.name, path.read_bytes())}
        r = requests.post(f"{self.base_url}/upload/audio", files=files, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data.get("name") or data.get("filename") or path.name

    # -----------------------
    # Prompt queue + poll
    # -----------------------
    def queue_prompt(self, prompt: Dict[str, Any]) -> str:
        payload = {"prompt": prompt}
        r = requests.post(f"{self.base_url}/prompt", json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["prompt_id"]

    def wait_for_prompt(self, prompt_id: str, timeout_sec: int = 1800) -> Dict[str, Any]:
        """
        Poll /history/{prompt_id} until outputs exist.
        """
        start = time.time()
        while True:
            if time.time() - start > timeout_sec:
                raise TimeoutError("ComfyUI render timeout exceeded.")

            r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
            r.raise_for_status()
            hist = r.json()

            # When done, history contains prompt_id -> {outputs: ...}
            if prompt_id in hist and hist[prompt_id].get("outputs"):
                return hist[prompt_id]

            time.sleep(1.0)

    # -----------------------
    # Output download
    # -----------------------
    def extract_video_filenames(self, history_item: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Find video files in outputs from ComfyUI history.
        Returns list of dicts: {filename, subfolder, type}
        """
        outputs = history_item.get("outputs", {})
        results = []

        for _, node_out in outputs.items():
            # VHS_VideoCombine usually stores under "gifs" or "videos"
            for k in ["gifs", "videos", "images"]:
                if k in node_out and isinstance(node_out[k], list):
                    for item in node_out[k]:
                        # item: {"filename": "...", "subfolder": "", "type": "output"}
                        if isinstance(item, dict) and "filename" in item:
                            fn = item["filename"]
                            if fn.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
                                results.append(item)

        return results

    def download_output_file(self, file_info: Dict[str, str], dst_path: Path):
        """
        GET /view?filename=...&subfolder=...&type=...
        """
        params = {
            "filename": file_info.get("filename", ""),
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        }
        r = requests.get(f"{self.base_url}/view", params=params, timeout=300)
        r.raise_for_status()
        dst_path.write_bytes(r.content)
