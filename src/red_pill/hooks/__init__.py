"""`red_pill.hooks` — contrato del hook del arnés (RFC-HARNESS-001)."""

from __future__ import annotations

from red_pill.hooks.context_api import (
	HARNESS_ID,
	AckLedger,
	HookPayloadError,
	HookRequest,
	block,
	canon_harness,
	delivery_id,
	originator_for,
	telemetry_text,
)

__all__ = [
	"HARNESS_ID",
	"AckLedger",
	"HookPayloadError",
	"HookRequest",
	"block",
	"canon_harness",
	"delivery_id",
	"originator_for",
	"telemetry_text",
]
