import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class FlowEngine:
    """
    Engine to load and merge Autonomous Flow registries.
    Supports Global (Red-Pill Core), Community (Swarm HUB), and Local (.agent/ flows.yaml).
    """

    def __init__(self, global_registry_path: str, community_registry_path: Optional[str] = None):
        self.global_path = Path(global_registry_path)
        self.community_path = Path(community_registry_path) if community_registry_path else None
        self.local_filename = ".agent/flows.yaml"

    def load_flows(self, cwd: Optional[str] = None) -> Dict[str, Any]:
        """Merge global, community and local flows with priority and locking."""
        flows = {}

        # 1. Load Global (Baseline)
        flows.update(self._read_yaml(self.global_path))

        # 2. Load Community (Shared Standards)
        if self.community_path:
            comm_flows = self._read_yaml(self.community_path)
            for fid, f in comm_flows.items():
                # Community can override global unless global is locked (future proof)
                flows[fid] = f

        # 3. Load Local (Project specific)
        if cwd:
            local_path = Path(cwd) / self.local_filename
            local_flows = self._read_yaml(local_path)
            for fid, f in local_flows.items():
                if flows.get(fid, {}).get("locked", False):
                    # SEC-P01: Locked flows cannot be overridden locally for compliance
                    continue
                flows[fid] = f

        return flows

    def _read_yaml(self, path: Path) -> Dict[str, Any]:
        if path and path.exists():
            try:
                data = yaml.safe_load(path.read_text())
                return data.get("flows", {})
            except Exception as e:
                print(f"Error reading flow registry at {path}: {e}")
        return {}

    def get_flow(self, flow_id: str, cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve a specific flow by ID."""
        flows = self.load_flows(cwd)
        return flows.get(flow_id)
