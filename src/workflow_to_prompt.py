from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional


def _build_link_map(workflow_links: List[list]) -> Dict[int, Tuple[int, int]]:
    """
    ComfyUI workflow "links" entries are like:
    [link_id, from_node_id, from_slot_index, to_node_id, to_slot_index, type]
    We need: link_id -> (from_node_id, from_slot_index)
    """
    link_map: Dict[int, Tuple[int, int]] = {}
    for item in workflow_links:
        try:
            link_id = int(item[0])
            from_node = int(item[1])
            from_slot = int(item[2])
            link_map[link_id] = (from_node, from_slot)
        except Exception:
            continue
    return link_map


def workflow_to_prompt(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert full ComfyUI workflow export (nodes/links/...) into ComfyUI API /prompt format:
    {
      "prompt": {
        "133": {"class_type": "LoadImage", "inputs": {...}},
        ...
      }
    }

    Handles:
    - linked inputs -> [from_node_id, from_slot_index]
    - widget inputs -> widget values (best-effort)
    """
    nodes: List[Dict[str, Any]] = workflow.get("nodes", [])
    links: List[list] = workflow.get("links", [])
    link_map = _build_link_map(links)

    prompt: Dict[str, Any] = {}

    for node in nodes:
        node_id = str(node.get("id"))
        class_type = node.get("type")

        # Some UI nodes like "Label (rgthree)" are not executable; skip them.
        if not class_type or "Label" in str(class_type):
            continue

        entry: Dict[str, Any] = {"class_type": class_type, "inputs": {}}
        inputs = node.get("inputs", [])
        widgets_values = node.get("widgets_values", None)

        # Case A: widgets_values is a dict (common in VHS_VideoCombine)
        widgets_dict: Optional[Dict[str, Any]] = widgets_values if isinstance(widgets_values, dict) else None

        # Case B: widgets_values is a list aligned with widget inputs order
        widgets_list: List[Any] = widgets_values if isinstance(widgets_values, list) else []
        widget_cursor = 0

        for inp in inputs:
            name = inp.get("name")
            link = inp.get("link", None)

            if not name:
                continue

            # Linked input -> [from_node_id, from_slot_index]
            if link is not None:
                if link in link_map:
                    from_node, from_slot = link_map[link]
                    entry["inputs"][name] = [str(from_node), int(from_slot)]
                else:
                    # Unknown link; leave out to avoid validation failure
                    pass
                continue

            # Non-linked: try widget value
            if widgets_dict is not None and name in widgets_dict:
                entry["inputs"][name] = widgets_dict[name]
                continue

            # If input has widget and widgets_values is list, take next value
            if inp.get("widget") is not None and widget_cursor < len(widgets_list):
                entry["inputs"][name] = widgets_list[widget_cursor]
                widget_cursor += 1
                continue

            # Otherwise: do nothing (some inputs are optional)
            # Leaving it out is safer than sending null and failing validation.

        prompt[node_id] = entry

    return {"prompt": prompt}
