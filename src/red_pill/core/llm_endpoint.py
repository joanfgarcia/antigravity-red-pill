"""Single source of truth for the LOCAL LLM endpoint (dual-bind proxy / MLX server).

CONVENTIONS §10.8.1: the endpoint is configuration, never a literal in the callers
(§10.8.3 — one resolver, many consumers). Derives from `cfg.MLX_LM_URL` (falling
back to `cfg.DUAL_BIND_PROXY_URL`), then the `127.0.0.1:8760` dual-bind convention.
"""

from __future__ import annotations

from urllib.parse import urlparse

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8760


def _configured_url() -> str:
	try:
		import red_pill.config as cfg

		return (getattr(cfg, "MLX_LM_URL", "") or getattr(cfg, "DUAL_BIND_PROXY_URL", "") or "").strip()
	except Exception:
		return ""


def llm_base_url() -> str:
	"""`scheme://host:port` of the local LLM (config-derived; default 127.0.0.1:8760)."""
	raw = _configured_url()
	if raw:
		p = urlparse(raw)
		if p.scheme and p.hostname:
			return f"{p.scheme}://{p.netloc}"
	return f"http://{_DEFAULT_HOST}:{_DEFAULT_PORT}"


def llm_port() -> int:
	"""Port of the local LLM (the single replacement for the scattered `return 8760`)."""
	try:
		p = urlparse(_configured_url())
		if p.port:
			return int(p.port)
	except ValueError:
		pass
	return _DEFAULT_PORT


def llm_chat_url() -> str:
	"""OpenAI-compatible chat-completions endpoint."""
	return f"{llm_base_url()}/v1/chat/completions"


def llm_health_url() -> str:
	"""Models/health endpoint used to probe the local LLM."""
	return f"{llm_base_url()}/v1/models"
