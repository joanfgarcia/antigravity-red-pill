
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Dict, Union, Any
import uuid
import time

class EngramMetadata(BaseModel):
    """
    Strict validation for arbitrary metadata.
    Prevents deep nesting and huge payloads.
    """
    model_config = ConfigDict(extra='forbid') # No unknown fields allowed in top-level payload

    associations: List[str] = Field(default_factory=list)
    # We allow other simple types but could restrict them if needed
    # For now, let's allow a flat dictionary of simple types in a specific field?
    # Or strict typing on the top level?
    # The current implementation mixes metadata into the top level payload.
    # To be strict, we should probably define all allowed fields or use a catch-all with validation.
    
    # Let's define the KNOWN fields first
    content: str = Field(..., max_length=4096) # Limit content length
    importance: float = Field(default=1.0, ge=0.0, le=10.0)
    reinforcement_score: float = Field(default=1.0)
    created_at: float = Field(default_factory=time.time)
    last_recalled_at: float = Field(default_factory=time.time)
    immune: bool = Field(default=False)
    
    # Catch-all for extra metadata, but validated
    # Pydantic doesn't easily support "any other field must be X" without extra='allow'
    # But we want to forbid complex nested structures.
    
    @field_validator('associations')
    @classmethod
    def validate_associations(cls, v):
        valid_uuids = []
        for uid in v:
            try:
                uuid.UUID(str(uid))
                valid_uuids.append(str(uid))
            except ValueError:
                continue # or raise error?
        return valid_uuids

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        if len(v) == 0:
            raise ValueError("Content cannot be empty")
        # Check for null bytes
        if '\x00' in v:
            raise ValueError("Content contains null bytes (binary injection attempt)")
        return v

class CreateEngramRequest(BaseModel):
    """
    Schema for input to add_memory. 
    Separate from internal payload storage which has computed fields.
    """
    content: str = Field(..., min_length=1, max_length=4096)
    importance: float = Field(default=1.0, ge=0.0, le=10.0)
    metadata: Dict[str, Union[str, int, float, bool, List[str]]] = Field(default_factory=dict)
    
    @field_validator('content')
    @classmethod
    def no_null_bytes(cls, v):
        if '\x00' in v:
            raise ValueError("Content contains null bytes")
        return v
        
    @field_validator('metadata')
    @classmethod
    def validate_metadata_structure(cls, v):
        # Prevent recursion/deep nesting by enforcing simple types
        for key, val in v.items():
            if isinstance(val, (dict, list)) and key != 'associations':
                # associations is the only allowed list, and even then, usually handled separately
                # But let's allow lists of strings (tags)
                if isinstance(val, list):
                    for item in val:
                         if not isinstance(item, (str, int, float, bool)):
                             raise ValueError(f"Metadata list {key} contains complex type {type(item)}")
                elif isinstance(val, dict):
                     raise ValueError(f"Metadata field {key} is a nested dictionary. Flat structure required.")
            
            # Check for huge strings in values
            if isinstance(val, str) and len(val) > 1024:
                raise ValueError(f"Metadata field {key} exceeds 1024 characters")
        return v
