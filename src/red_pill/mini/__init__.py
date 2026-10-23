"""Mini local harness (Forge/Loom) on top of the session substrate.

Forge (GPU 8B) executes with tools; Loom (NPU 35B MoE) reviews without tools.
The session mirror is the only memory: no Búnker handshake, no wake-up, no RAG.
"""

from red_pill.mini.providers import HTTPProvider, ProviderError, UnixHTTPProvider
from red_pill.mini.session import MiniConfig, MiniSession
from red_pill.mini.tools import TOOL_SCHEMAS, WorkspaceTools

__all__ = [
	"HTTPProvider",
	"MiniConfig",
	"MiniSession",
	"ProviderError",
	"TOOL_SCHEMAS",
	"UnixHTTPProvider",
	"WorkspaceTools",
]
