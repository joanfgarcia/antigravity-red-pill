"""Pydantic schemas for distiller parameters YAML validation."""

from pydantic import BaseModel, Field


class DistillEngramParams(BaseModel):
	temperature: float = Field(default=0.1, ge=0.0, le=2.0)
	max_retries: int = Field(default=2, ge=1, le=10)
	provider_alias: str = Field(default="sip")
	prompt_file: str = Field(default="distiller_v3.txt")


class SynthesizeHubV2Params(BaseModel):
	temperature: float = Field(default=0.1, ge=0.0, le=2.0)
	provider_alias: str = Field(default="sip")
	prompt_file: str = Field(default="hub_synthesis_v2.txt")


class ClassifyCategoryParams(BaseModel):
	temperature: float = Field(default=0.0, ge=0.0, le=2.0)
	provider_alias: str = Field(default="sip")
	prompt_file: str = Field(default="classify_category.txt")


class DistillSessionAnchorsParams(BaseModel):
	temperature: float = Field(default=0.1, ge=0.0, le=2.0)
	max_tokens: int = Field(default=1024, ge=64, le=8192)
	prompt_file: str = Field(default="session_anchors.txt")


class DistillerParamsConfig(BaseModel):
	distill_engram: DistillEngramParams = Field(default_factory=DistillEngramParams)
	synthesize_hub_v2: SynthesizeHubV2Params = Field(default_factory=SynthesizeHubV2Params)
	classify_category: ClassifyCategoryParams = Field(default_factory=ClassifyCategoryParams)
	distill_session_anchors: DistillSessionAnchorsParams = Field(default_factory=DistillSessionAnchorsParams)
