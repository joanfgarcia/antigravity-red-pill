"""Mini local harness (Forge/Loom) on top of the session substrate.

Forge (GPU 8B) executes with tools; Loom (NPU 35B MoE) reviews without tools.
The session mirror is the only memory: no Búnker handshake, no wake-up, no RAG.
"""

from red_pill.mini.contracts import AgentProfile, ChatProvider, Toolbox
from red_pill.mini.profiles import PROFILES
from red_pill.mini.providers import HTTPProvider, ProviderError, UnixHTTPProvider
from red_pill.mini.session import MiniConfig, MiniSession
from red_pill.mini.tools import TOOL_SCHEMAS, WorkspaceTools

__all__ = [
	"AgentProfile",
	"ChatProvider",
	"HTTPProvider",
	"MiniConfig",
	"MiniSession",
	"PROFILES",
	"ProviderError",
	"TOOL_SCHEMAS",
	"Toolbox",
	"UnixHTTPProvider",
	"WorkspaceTools",
]
