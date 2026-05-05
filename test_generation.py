import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("/home/joan/Documents/IA/sharing/src/red_pill/plugins/antigravity_ide/")))
from ide_client import AntigravityIDEClient

client = AntigravityIDEClient()
cid = "22b49090-1ff7-4e48-baa2-ba2eb33561d9"
data = client.get_cascade_trajectory(cid)
print(json.dumps(data, indent=2))
