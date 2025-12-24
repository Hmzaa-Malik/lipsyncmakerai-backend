import json
from pathlib import Path

SRC = Path("Workflows/infinitetalk_clean.json")
DST = Path("Workflows/infinite_talk_api.json")

with open(SRC, "r", encoding="utf-8") as f:
    wf = json.load(f)

clean = {
    "nodes": wf["nodes"],
    "links": wf["links"],
    "version": wf.get("version", 0.4)
}

with open(DST, "w", encoding="utf-8") as f:
    json.dump(clean, f, indent=2)

print("✅ Clean API-safe workflow written to:", DST)
