
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Union, Any
import uuid
import time



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
