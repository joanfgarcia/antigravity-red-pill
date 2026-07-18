import uuid
from typing import Any, ClassVar, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

import red_pill.config as cfg

# Emotional Spectrum Definition (Inside Out 2 / v4.2.0)
ValidColor = Literal["orange", "yellow", "purple", "cyan", "blue", "gray", "red", "green", "emerald", "gold", "black", "white", "pink"]
# We map it directly to str to embrace Samantha's open-ended emotional taxonomy (e.g. 'frustration', 'existential dread').
ValidEmotion = str


class CreateEngramRequest(BaseModel):
	"""Input schema for memory ingestion."""

	content: str = Field(..., min_length=1, max_length=4096)
	importance: float = Field(default=1.0, ge=0.0, le=10.0)
	color: ValidColor = Field(default="gray")
	emotion: ValidEmotion = Field(default="neutral")
	intensity: float = Field(default=1.0, ge=0.0, le=10.0)
	metadata: Dict[str, Any] = Field(default_factory=dict)
	linguistic_markers: List[str] = Field(default_factory=list)

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
		"originator",
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
						if isinstance(item, dict) or not isinstance(item, (str, int, float, bool, dict)):
							raise ValueError(f"Complex type in metadata list {key}")
				elif isinstance(val, dict) and key not in ["last_3d", "last_7d", "last_30d", "global"]:
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


class EngramPayload(BaseModel):
	"""
	Strict read-schema for data loaded from Qdrant.
	Enforces the presence of core fields, mitigating 'Original Sin' schemaless debt.
	Automatically injects FSRS baseline values (difficulty/stability) for graceful migration.
	"""

	content: str
	importance: float
	reinforcement_score: float = 1.0
	color: ValidColor = "gray"
	emotion: ValidEmotion = "neutral"
	intensity: float = 1.0
	immune: bool = False
	created_at: float
	last_recalled_at: float
	schema_version: Union[str, int]
	originator: Optional[str] = None
	parent_id: Optional[str] = None

	# Bayesian Utility Model (v6.1 Phase B.1)
	# Alpha: Cumulative success weight (Prior/Reinforcement)
	# Beta: Cumulative uncertainty/decay weight (Purity/Erosion)
	utility_alpha: float = 1.0
	utility_beta: float = 1.0

	# Conversational DNA (v6.0 Claude-Pistis)
	# Captures shared aliases, nicknames, and unique linguistic triggers.
	linguistic_markers: List[str] = Field(default_factory=list)

	model_config = {"extra": "allow"}


class Axon(BaseModel):
	"""One associative link in a point's `associations` payload list (ADR-AXON-001).

	Wire formats accepted (see normalize_associations):
	- legacy plain id string — same-collection link forged by Oneiromancy
	- object with id / target_collection / weight / association_type
	target_collection=None means "same collection as the owning point".
	"""

	id: str
	target_collection: Optional[str] = None
	weight: float = 1.0
	association_type: str = "legacy"

	@field_validator("weight", mode="before")
	@classmethod
	def clamp_weight(cls, v: Any) -> float:
		try:
			return max(0.0, min(1.0, float(v)))
		except (TypeError, ValueError):
			return 1.0

	def is_cross(self, own_collection: str) -> bool:
		return self.target_collection is not None and self.target_collection != own_collection

	def to_payload(self) -> Union[str, Dict[str, Any]]:
		"""Serialize back: legacy links stay plain strings (lazy migration)."""
		if self.association_type == "legacy" and self.target_collection is None:
			return self.id
		payload: Dict[str, Any] = {"id": self.id, "weight": self.weight, "association_type": self.association_type}
		if self.target_collection is not None:
			payload["target_collection"] = self.target_collection
		return payload


def normalize_associations(raw: Any) -> List[Axon]:
	"""Parse a payload `associations` list tolerating every historical format.

	Readers MUST go through this: iterating raw entries with str(entry) turns a
	dict axon into its repr and silently corrupts propagation (P1 guard).
	"""
	if not isinstance(raw, list):
		return []
	axons: List[Axon] = []
	for entry in raw:
		if isinstance(entry, Axon):
			axons.append(entry)
		elif isinstance(entry, dict):
			entry_id = entry.get("id")
			if entry_id:
				axons.append(
					Axon(
						id=str(entry_id),
						target_collection=entry.get("target_collection"),
						weight=entry.get("weight", 1.0),
						association_type=str(entry.get("association_type", "legacy")),
					)
				)
		elif entry:
			axons.append(Axon(id=str(entry)))
	return axons
