"""
Antigravity IDE Plugin for Red-Pill.

Dual-backend bridge architecture:
	- AgyBridge (execution): agy CLI for Neon-Link commands + autonomous AWAKENINGs
	- GrpcBridge (extraction): gRPC-Web for Chronicle pipeline + archive_memories

Both bridges coexist. Config: IDE_BACKEND=agy|grpc|auto in .env
"""

from .bridge import BackendType, BridgeCapabilities, ConversationResult, IDEBridge, NotSupportedError
from .factory import create_bridge, create_extraction_bridge, preflight_check

__all__ = [
	"IDEBridge",
	"BackendType",
	"BridgeCapabilities",
	"ConversationResult",
	"NotSupportedError",
	"create_bridge",
	"create_extraction_bridge",
	"preflight_check",
]
