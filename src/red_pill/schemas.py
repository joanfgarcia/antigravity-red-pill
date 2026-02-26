import uuid
from typing import Any, ClassVar, Dict, List, Literal, Union

from pydantic import BaseModel, Field, field_validator

import red_pill.config as cfg

# Emotional Spectrum Definition (Inside Out 2 / v4.2.0)
ValidColor = Literal["orange", "yellow", "purple", "cyan", "blue", "gray", "red", "green", "emerald"]
ValidEmotion = Literal[
	"joy",
	"sadness",
	"fear",
	"disgust",
	"anger",
	"surprise",
	"neutral",
	"love",
	"shame",
	"guilt",
	"desire",
	"confusion",
	"anxiety",
	"envy",
	"embarrassment",
	"ennui",
	"nostalgia",
	"sarcasm",
	"happiness",
]


class CreateEngramRequest(BaseModel):
	"""Input schema for memory ingestion."""

	content: str = Field(..., min_length=1, max_length=4096)
	importance: float = Field(default=1.0, ge=0.0, le=10.0)
	color: ValidColor = Field(default="gray")
	emotion: ValidEmotion = Field(default="neutral")
	intensity: float = Field(default=1.0, ge=0.0, le=10.0)
	metadata: Dict[str, Union[str, int, float, bool, List[Any]]] = Field(default_factory=dict)

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
		def _check_null_bytes(item: Any, location: str) -> None:
			if isinstance(item, str) and "\x00" in item:
				raise ValueError(f"{location} contains null bytes")
			if isinstance(item, list):
				for i, sub_item in enumerate(item):
					_check_null_bytes(sub_item, f"{location}[{i}]")
			if isinstance(item, dict):
				for k, val in item.items():
					_check_null_bytes(k, f"{location} key")
					_check_null_bytes(val, f"{location}/{k}")

		for key, val in v.items():
			_check_null_bytes(key, "Metadata key")
			_check_null_bytes(val, f"Metadata field {key}")

			if key in cls.RESERVED_KEYS:
				raise ValueError(f"Reserved key '{key}' found")

			if isinstance(val, (dict, list)) and key != "associations":
				if isinstance(val, list):
					for item in val:
						if key == "emotional_profile" and isinstance(item, dict):
							continue
						if not isinstance(item, (str, int, float, bool)):
							raise ValueError(f"Complex type in metadata list {key}")
				elif isinstance(val, dict):
					raise ValueError(f"Nested dict in metadata field {key}")

			if key == "associations" and isinstance(val, list):
				if len(val) > cfg.MAX_AXONS:
					val = val[: cfg.MAX_AXONS]
					v[key] = val
				for item in val:
					# ARCH-002 (Forward Compatibility): Support both flat UUIDs and {id, weight} dicts
					_id = item["id"] if isinstance(item, dict) else item
					try:
						uuid.UUID(str(_id))
					except (ValueError, KeyError, TypeError):
						raise ValueError(f"Invalid association ID in: {item}")

					if isinstance(item, dict):
						weight = item.get("weight", 1.0)
						if not isinstance(weight, (int, float)) or not (0 <= weight <= 2.0):
							raise ValueError(f"Invalid weight '{weight}' for association {item['id']}")

			if isinstance(val, str) and len(val) > 1024:
				raise ValueError(f"Metadata field {key} exceeds limit")
		return v
