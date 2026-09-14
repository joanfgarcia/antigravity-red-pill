"""Model license policy: normalization, commercial-context gate and audit.

Sovereign compliance layer over `model_profiles.yaml` / `model_catalog.yaml`.
Every model profile/catalog entry may declare a `license:` block:

    license:
      id: "cc-by-nc-4.0"        # SPDX id when one exists, else friendly id
      commercial_ok: false      # CANNOT be used in a commercial context
      redistribution_ok: true
      attribution_required: true
      share_alike: true
      source: "https://huggingface.co/CohereLabs/tiny-aya-water"

For cloud/API models (no weights to redistribute) the relevant dimension is data
governance, not redistribution:

    license:
      id: "opencode-big-pickle-promo"
      commercial_ok: true              # API: no NC restriction, usable at work
      redistribution_ok: false         # N/A: no weights to distribute
      attribution_required: false
      share_alike: false
      prompts_used_for_training: true  # provider may train on your prompts
      confidential_ok: false           # do NOT send NDA/confidential data
      source: "https://opencode.ai/docs/zen/"

`prompts_used_for_training` / `confidential_ok` default to False (fail-closed on
confidentiality) but do NOT feed the commercial gate — they are surfaced by the
audit so an operator never feeds confidential data to a training-opt-in API.

The block is also accepted as a bare string shorthand (e.g. `license: apache-2.0`)
which is resolved through `_KNOWN_LICENSES`. Unknown licenses FAIL CLOSED
(commercial_ok=False) — the gate must never silently bless a model it cannot
verify. The YAML declaration is authoritative; `_KNOWN_LICENSES` is only a
fallback for the shorthand form and a defence-in-depth cross-check.

Context is selected via `REDPILL_LICENSE_CONTEXT` env var: `personal`
(default) or `commercial`. In a commercial context the gate raises
`ModelLicenseError` when a non-commercial model is selected, so a CC-BY-NC
model can never enter a work/commercial pipeline unnoticed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Canonical commercial-context policy for the LICENSE_ID shorthand form.
# Declaring a structured block in YAML overrides anything here.
_KNOWN_LICENSES: Dict[str, Dict[str, Any]] = {
	"apache-2.0": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": False, "share_alike": False},
	"mit": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": True, "share_alike": False},
	"llama-3.2-community": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": True, "share_alike": False},
	"llama-3.1-community": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": True, "share_alike": False},
	"gemma-terms-of-use": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": True, "share_alike": False},
	"deepseek-license": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": True, "share_alike": False},
	"falcon3-apache": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": False, "share_alike": False},
	"cc-by-nc-4.0": {"commercial_ok": False, "redistribution_ok": True, "attribution_required": True, "share_alike": True},
	"cc-by-nc-sa-4.0": {"commercial_ok": False, "redistribution_ok": True, "attribution_required": True, "share_alike": True},
	"cc-by-4.0": {"commercial_ok": True, "redistribution_ok": True, "attribution_required": True, "share_alike": False},
}

_EMPTY_POLICY: Dict[str, Any] = {
	"commercial_ok": False,
	"redistribution_ok": False,
	"attribution_required": True,
	"share_alike": False,
	"prompts_used_for_training": False,
	"confidential_ok": False,
}

_LICENSE_KEYS = ("commercial_ok", "redistribution_ok", "attribution_required", "share_alike", "source", "prompts_used_for_training", "confidential_ok")


class ModelLicenseError(Exception):
	"""Raised when a model would be used in a context its license forbids."""


def _env_commercial_context() -> bool:
	"""True when the current run is a commercial (work) context.

	`REDPILL_LICENSE_CONTEXT` accepts `commercial` (any casing) to mark the
	installation as work/commercial; anything else (or unset) is personal.
	"""
	return os.getenv("REDPILL_LICENSE_CONTEXT", "personal").strip().lower() == "commercial"


def normalize_license(raw: Any, model_name: str = "") -> Dict[str, Any]:
	"""Normalize a `license:` field (dict or shorthand string) to a policy dict.

	Unknown/absent licenses FAIL CLOSED: `commercial_ok=False`, `known=False`,
	so the gate blocks them in commercial contexts until declared.
	"""
	if isinstance(raw, dict):
		policy = {k: raw.get(k, _EMPTY_POLICY.get(k, False)) for k in _LICENSE_KEYS}
		policy["id"] = str(raw.get("id", "custom")).strip() or "custom"
		policy["known"] = True
		return policy

	if isinstance(raw, str):
		lic_id = raw.strip().lower()
		known = _KNOWN_LICENSES.get(lic_id)
		if known:
			policy = dict(_EMPTY_POLICY)
			policy.update(known)
			policy["id"] = lic_id
			policy["known"] = True
			policy["source"] = ""
			return policy
		logger.warning(f"[LICENSE] '{lic_id}' no está en _KNOWN_LICENSES → fail-closed (modelo={model_name or '?'}).")
		policy = dict(_EMPTY_POLICY)
		policy["id"] = lic_id or "unknown"
		policy["known"] = False
		policy["source"] = ""
		return policy

	policy = dict(_EMPTY_POLICY)
	policy["id"] = "undeclared"
	policy["known"] = False
	policy["source"] = ""
	if raw is not None:
		logger.warning(f"[LICENSE] Tipo de license no soportado {type(raw).__name__} → fail-closed (modelo={model_name or '?'}).")
	return policy


def commercial_ok(license_raw: Any, model_name: str = "") -> bool:
	"""True if the model's license allows use in a commercial context."""
	return bool(normalize_license(license_raw, model_name).get("commercial_ok"))


def assert_commercial_ok(
	license_raw: Any,
	model_name: str = "",
	context: Optional[str] = None,
) -> None:
	"""Gate: raise ModelLicenseError if a commercial context tries a non-commercial model.

	`context` overrides the env-derived context when provided (e.g. tests,
	or an explicit `--commercial` flag). In personal context the gate is a no-op.
	"""
	if context is not None:
		commercial = str(context).strip().lower() == "commercial"
	else:
		commercial = _env_commercial_context()

	if not commercial:
		return

	policy = normalize_license(license_raw, model_name)
	if policy.get("commercial_ok"):
		return

	raise ModelLicenseError(
		f"[LICENSE] Modelo '{model_name or policy.get('id', '?')}' (licencia "
		f"{policy.get('id')}) NO permite uso comercial. El contexto actual es "
		f"comercial (REDPILL_LICENSE_CONTEXT=commercial). Bloqueado por el "
		f"compliance gate — usa un modelo permisivo (Apache-2.0/MIT) o cambia "
		f"el contexto a personal."
	)


def describe(license_raw: Any, model_name: str = "") -> Dict[str, Any]:
	"""Human/CLI-friendly description of a model's license."""
	policy = normalize_license(license_raw, model_name)
	policy["commercial_allowed"] = policy.get("commercial_ok", False)
	policy["model"] = model_name
	return policy
