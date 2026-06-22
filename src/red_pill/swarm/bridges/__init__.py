"""Agent-backend bridges — generic abstraction for running a prompt through an
agent backend (agy / claude / local / grpc), independent of which executes it."""

from .base import (
	AgentBridge,
	BackendType,
	BridgeCapabilities,
	ConversationResult,
	NotSupportedError,
)
from .cascade import AllModelsExhausted, CascadeBridge, CascadeError, NoModelsConfigured
from .factory import create_bridge, create_cascade_bridge, create_extraction_bridge, preflight_check

__all__ = [
	"AgentBridge",
	"BackendType",
	"BridgeCapabilities",
	"ConversationResult",
	"NotSupportedError",
	"CascadeBridge",
	"CascadeError",
	"NoModelsConfigured",
	"AllModelsExhausted",
	"create_bridge",
	"create_cascade_bridge",
	"create_extraction_bridge",
	"preflight_check",
]
