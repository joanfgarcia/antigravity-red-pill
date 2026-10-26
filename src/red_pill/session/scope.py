"""Alcance del compactor en background (B-02).

`autonomous` (default) compacta continuidades de misión/job, Telegram,
awakenings y locales; las sesiones interactivas de opencode quedan fuera.
`all` es el opt-in explícito (incluye interactivas); `off` desactiva el fondo.
"""

from __future__ import annotations

from typing import Optional

from red_pill.core.origins import (
	PROVIDER_ANTIGRAVITY,
	PROVIDER_CLAUDE,
	PROVIDER_OPENCODE,
	PROVIDER_PI,
	read_origins,
)

_DEFAULT_PREFIXES = (
	"job:",
	"telegram:",
	"local:",
	"mini:",
	"forge:",
	"loom:",
	"d23-review:",
	"awakening:",
)
_INTERACTIVE_PROVIDERS = {
	PROVIDER_OPENCODE,
	PROVIDER_CLAUDE,
	PROVIDER_PI,
	PROVIDER_ANTIGRAVITY,
	"claude",
}


def _scope_config() -> tuple[str, str]:
	try:
		import red_pill.config as cfg

		conf = cfg.get_config()
		scope = str(getattr(conf, "COMPACTOR_SCOPE", "autonomous") or "autonomous").strip().lower()
		prefixes = str(getattr(conf, "COMPACTOR_SCOPE_PREFIXES", "") or "")
		return scope, prefixes
	except Exception:
		return "autonomous", ""


def compactor_scope_allows(originator: Optional[str], origin: Optional[str] = None) -> bool:
	"""¿El compactor de fondo puede tocar esta continuidad/cuerpo?

	- `off` → nunca.
	- `all` → siempre (opt-in explícito).
	- `autonomous` → prefijos de job/telegram/local/mini/forge/loom/reviewer/
	awakening; para arneses interactivos (`opencode`, `pi`, `claude_code`,
	`claude`, `antigravity`) exige que el origen registrado sea `awakening` o
	`job` (no `user` interactivo).
	"""
	scope, raw_prefixes = _scope_config()
	if scope == "off":
		return False
	if scope == "all":
		return True
	if scope != "autonomous":
		return False
	value = str(originator or "").strip()
	if not value:
		return False
	provider, _, session_id = value.partition(":")
	if provider in _INTERACTIVE_PROVIDERS:
		tag = str(origin or "").strip().lower()
		if not tag:
			try:
				row = read_origins(provider).get(session_id) or {}
			except Exception:
				row = {}
			if isinstance(row, dict):
				tag = str(row.get("origin") or "").strip().lower()
		return tag in {"awakening", "job"}
	prefixes = [item.strip() for item in raw_prefixes.split(",") if item.strip()]
	if not prefixes:
		prefixes = list(_DEFAULT_PREFIXES)
	return any(value.startswith(prefix) for prefix in prefixes)
