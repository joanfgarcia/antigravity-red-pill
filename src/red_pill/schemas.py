import uuid
from typing import Any, ClassVar, Dict, List, Literal, Union

from pydantic import BaseModel, Field, field_validator

# Emotional Spectrum Definition (Inside Out 2 / v4.2.0)
ValidColor = Literal["orange", "yellow", "purple", "cyan", "blue", "gray"]
ValidEmotion = Literal["joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"]


class CreateEngramRequest(BaseModel):
	"""Input schema for memory ingestion."""

	content: str = Field(..., min_length=1, max_length=4096)
	importance: float = Field(default=1.0, ge=0.0, le=10.0)
	color: ValidColor = Field(default="gray")
	emotion: ValidEmotion = Field(default="neutral")
	intensity: float = Field(default=1.0, ge=0.0, le=10.0)
	metadata: Dict[str, Union[str, int, float, bool, List[str]]] = Field(default_factory=dict)

	@field_validator("content")
	@classmethod
	def no_null_bytes(cls, v: str) -> str:
		if "\x00" in v:
			raise ValueError("Content contains null bytes")
		return v

	RESERVED_KEYS: ClassVar[set] = {
		"content",
		"importance",
		"reinforcement_score",
		"created_at",
		"last_recalled_at",
		"immune",
		"color",
		"emotion",
		"intensity",
	}

	@field_validator("metadata")
	@classmethod
	def validate_metadata_structure(cls, v: Dict[str, Any]) -> Dict[str, Any]:
		for key, val in v.items():
			if key in cls.RESERVED_KEYS:
				raise ValueError(f"Reserved key '{key}' found")

			if isinstance(val, (dict, list)) and key != "associations":
				if isinstance(val, list):
					for item in val:
						if not isinstance(item, (str, int, float, bool)):
							raise ValueError(f"Complex type in metadata list {key}")
				elif isinstance(val, dict):
					raise ValueError(f"Nested dict in metadata field {key}")

			if key == "associations" and isinstance(val, list):
				if len(val) > 20:
					val = val[:20]
					v[key] = val
				for item in val:
					try:
						uuid.UUID(str(item))
					except ValueError:
						raise ValueError(f"Invalid association UUID: {item}")

			if isinstance(val, str) and len(val) > 1024:
				raise ValueError(f"Metadata field {key} exceeds limit")
		return v
