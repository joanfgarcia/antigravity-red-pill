import uuid

import pytest
from pydantic import ValidationError

from red_pill.schemas import CreateEngramRequest


def test_valid_engram_request():
	"""Validates a standard engram request."""
	data = {
		"content": "Test engram",
		"importance": 5.0,
		"metadata": {"source": "unit_test"}
	}
	request = CreateEngramRequest(**data)
	assert request.content == "Test engram"
	assert request.importance == 5.0

def test_null_byte_rejection():
	"""Ensures null bytes in content are rejected."""
	data = {"content": "Bad\x00data"}
	with pytest.raises(ValidationError) as exc:
		CreateEngramRequest(**data)
	assert "null bytes" in str(exc.value)

def test_reserved_key_rejection():
	"""Ensures engine reserved keys in metadata are rejected."""
	data = {
		"content": "Test",
		"metadata": {"reinforcement_score": 99.0}
	}
	with pytest.raises(ValidationError) as exc:
		CreateEngramRequest(**data)
	assert "Reserved key 'reinforcement_score' found" in str(exc.value)

def test_metadata_nesting_rejection():
	"""Ensures nested dictionaries in metadata are rejected (Flat structure enforcement)."""
	data = {
		"content": "Test",
		"metadata": {"nested": {"key": "value"}}
	}
	with pytest.raises(ValidationError) as exc:
		CreateEngramRequest(**data)
	# Pydantic Union validation fails first before reaching our custom validator
	assert "Input should be a valid string" in str(exc.value) or "Nested dict" in str(exc.value)

def test_association_uuid_validation():
	"""Ensures associations are valid UUID strings."""
	valid_uuid = str(uuid.uuid4())
	data = {
		"content": "Test",
		"metadata": {"associations": [valid_uuid]}
	}
	request = CreateEngramRequest(**data)
	assert request.metadata["associations"][0] == valid_uuid

	data_invalid = {
		"content": "Test",
		"metadata": {"associations": ["not-a-uuid"]}
	}
	with pytest.raises(ValidationError) as exc:
		CreateEngramRequest(**data_invalid)
	assert "Invalid association UUID" in str(exc.value)

def test_association_cap():
	"""Ensures associations are capped at 20 (DS-006 remediation)."""
	many_ids = [str(uuid.uuid4()) for _ in range(30)]
	data = {
		"content": "Test",
		"metadata": {"associations": many_ids}
	}
	request = CreateEngramRequest(**data)
	assert len(request.metadata["associations"]) == 20

def test_validate_metadata_structure_directly():
	"""Ensures custom validator directly catches nested dicts, complex lists, and long strings."""
	validator = CreateEngramRequest.validate_metadata_structure

	# Test complex type in list
	with pytest.raises(ValueError, match="Complex type in metadata list mixed"):
		validator({"mixed": ["string", {"nested": "dict"}]})

	# Test nested dict
	with pytest.raises(ValueError, match="Nested dict in metadata field my_dict"):
		validator({"my_dict": {"nested": "dict"}})

	# Test over-length string
	with pytest.raises(ValueError, match="Metadata field toolong exceeds limit"):
		validator({"toolong": "A" * 1025})
