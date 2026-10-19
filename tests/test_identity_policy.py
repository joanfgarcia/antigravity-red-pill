"""Guard de la política de identidad de instancia (docs/CORE/IDENTITY_AND_INSTANCE.md).

El repo es motor genérico + novela: la identidad del agente/Operador es config del
puesto. Este test **falla** si un nombre de instancia se cuela en la superficie que
se inyecta o ejecuta. Las excepciones (tests, scripts de bakeoff, heurísticas de
calidad, autoría y novela) están documentadas en la política y NO se escanean.

Revalidar: `pytest -q tests/test_identity_policy.py tests/test_instance_identity.py`
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INSTANCE = ("Aleth", "Aletheia", "Joan")
_POLICY = _REPO / "docs" / "CORE" / "IDENTITY_AND_INSTANCE.md"

# Ficheros concretos que DEBEN estar sin nombres (código de inyección/motor).
_FILES = [
	"scripts/inject_anchor.py",
	"scripts/inject_opencode.py",
	"scripts/inject/opencode/inject.py",
	"scripts/inject/claude-code/inject.py",
	"scripts/inject/pi/inject.py",
	"scripts/wake_up_v6.py",
	"src/red_pill/config.py",
	"src/red_pill/seed.py",
	"src/red_pill/mcp_server.py",
	"src/red_pill/core/pact.py",
]

# Globs que DEBEN estar sin nombres.
_GLOBS = [
	"seeds/anchors/**/*.md",
	"seeds/*.md",
	"src/red_pill/**/prompts/**/*.txt",
	"src/red_pill/**/prompts/**/*.yaml",
]


def _offenders() -> list[str]:
	bad: list[str] = []
	candidates = [_REPO / f for f in _FILES]
	for g in _GLOBS:
		candidates += list(_REPO.glob(g))
	for p in candidates:
		if not p.is_file():
			continue
		try:
			text = p.read_text(encoding="utf-8", errors="ignore")
		except OSError:
			continue
		hits = [n for n in _INSTANCE if n in text]
		if hits:
			bad.append(f"{p.relative_to(_REPO)} → {hits}")
	return bad


def test_superficie_inyectada_sin_identidad_de_instancia():
	"""Ningún nombre de instancia en anclas, prompts, código de inyección/motor."""
	bad = _offenders()
	assert not bad, "identidad de instancia en superficie inyectada:\n" + "\n".join(bad)


def test_politica_documentada():
	"""La política (con la allowlist) debe existir y describir las excepciones."""
	assert _POLICY.is_file(), f"falta la política: {_POLICY.relative_to(_REPO)}"
	text = _POLICY.read_text(encoding="utf-8")
	assert "allowlist" in text.lower()
	assert "ABSOLUTE_KEYWORDS" in text and "agent_name" in text
