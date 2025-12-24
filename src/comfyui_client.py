from __future__ import annotations
import time
import uuid
from typing import Any, Dict, Optional, Tuple, List

import requests


class ComfyUIClient:
    def __init__(self, base_url: str, timeout_s: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def submit_prompt(self, prompt_payload: Dict[str, Any]) -> str:
        """
        POST /prompt
        Returns prompt_id.
        """
        payload = dict(prompt_payload)
        payload["client_id"] = str(uuid.uuid4())

        r = requests.post(f"{self.base_url}/prompt", json=payload, timeout=self.timeout_s)
        # If 400 happens, we want the response text to debug
        if not r.ok:
            raise RuntimeError(f"ComfyUI /prompt failed ({r.status_code}): {r.text}")

        data = r.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
        return prompt_id

    def wait_for_completion(self, prompt_id: str, poll_interval_s: float = 1.0, max_wait_s: int = 600) -> Dict[str, Any]:
        """
        GET /history/{prompt_id} until completed.
        """
        deadline = time.time() + max_wait_s
        last_data: Optional[Dict[str, Any]] = None

        while time.time() < deadline:
            r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=self.timeout_s)
            if r.ok:
                data = r.json()
                last_data = data

                # When finished, history contains outputs for nodes.
                # Different ComfyUI versions vary, so we detect "outputs" existence.
                item = data.get(prompt_id)
                if item and isinstance(item, dict) and item.get("outputs"):
                    return item

            time.sleep(poll_interval_s)

        raise TimeoutError(f"Timed out waiting for ComfyUI job {prompt_id}. Last history: {last_data}")

    @staticmethod
    def extract_first_mp4(history_item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Try to find the first .mp4 output across node outputs.
        Returns dict like {"filename":..., "subfolder":..., "type":...} when possible.
        """
        outputs = history_item.get("outputs", {})
        if not isinstance(outputs, dict):
            return None

        # Scan all node outputs
        for _node_id, out in outputs.items():
            if not isinstance(out, dict):
                continue
            for key, val in out.items():
                # Many nodes return list of file objects under keys like "videos", "gifs", "images"
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            fn = item.get("filename", "")
                            if isinstance(fn, str) and fn.lower().endswith(".mp4"):
                                return item
                # Some nodes store a single file dict
                if isinstance(val, dict):
                    fn = val.get("filename", "")
                    if isinstance(fn, str) and fn.lower().endswith(".mp4"):
                        return val

        return None
