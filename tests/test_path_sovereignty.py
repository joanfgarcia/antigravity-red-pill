"""Path Sovereignty — no hardcoded home/XDG/absolute-user paths in src/red_pill + scripts.

Every filesystem path must resolve through `core/paths.py` (the sole owner of the
XDG/config/data/state/tmp/forge roots). Modules/scripts must not hardcode
`Path.home()`, `~/…`, `/home/<user>/…` literals, or read `XDG_*_HOME` themselves.

Allowed:
  - `core/paths.py` (canonical definitions)
  - `config.py` (config/env layer that paths.py reads)
  - third-party harness dirs discovered by convention (`.gemini`/`.claude`/`.pi`/`.opencode`)
  - a BOUNDED list of **pre-seed** scripts (run before the first seeding instantiates
    `.env` and before `red_pill` is importable). A NEW pre-seed script MUST be added
    to `SCRIPTS_PRE_SEED` (or the `scripts/inject/` package) so the test skips it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src" / "red_pill"
SCRIPTS_DIR = ROOT / "scripts"

ALLOWED_FILES = {
	SRC_DIR / "core" / "paths.py",
	SRC_DIR / "config.py",
}

# Third-party harness dirs (.gemini/.claude/.pi/.opencode), discovered by convention.
EXTERNAL_TOOL_FILES = {
	SRC_DIR / "plugins" / "antigravity_ide" / "agy_bridge.py",
	SRC_DIR / "plugins" / "antigravity_ide" / "telegram_extractor.py",
	SRC_DIR / "chronicle_sources" / "pi.py",
	SRC_DIR / "chronicle_sources" / "claude_code.py",
	SRC_DIR / "chronicle_sources" / "opencode.py",
	SRC_DIR / "swarm" / "bridges" / "pi.py",
	SRC_DIR / "swarm" / "bridges" / "opencode.py",
	SRC_DIR / "swarm" / "autonomous_cron.py",
}

# BOUNDED list of pre-seed scripts (install/inject run before `.env`/red_pill exist).
SCRIPTS_PRE_SEED = {
	SCRIPTS_DIR / "_config_common.py",
	SCRIPTS_DIR / "inject_cli.py",
	SCRIPTS_DIR / "inject_anchor.py",
	SCRIPTS_DIR / "inject_mcp.py",
	SCRIPTS_DIR / "inject_settings.py",
	SCRIPTS_DIR / "inject_opencode.py",
	SCRIPTS_DIR / "migrate_prompt_language.py",
	# Maquinaria del inyector de opencode (`inject_cli` → `inject/opencode/inject.py`
	# → estos dos). Son standalone (solo stdlib, `test_preseed_scripts_son_standalone`
	# lo blinda) y tocan las rutas del **OpenCode del host**, no las de red-pill:
	# `~/.config/opencode` y `/etc/opencode` son las ubicaciones oficiales de V2
	# (docs: config → Locations) y NO existen como helper en `core/paths.py`, que
	# sólo posee las raíces XDG de red-pill. Misma clase que EXTERNAL_TOOL_FILES
	# (`.claude`/`.pi`/`.opencode`), pero en scripts de la fase de inyección.
	SCRIPTS_DIR / "opencode_version.py",
	SCRIPTS_DIR / "migrate_opencode_v2.py",
}
# Instrumentos de laboratorio del HOST (banco de modelos, sondas de calidad y el
# bootstrapper del sandbox). Miden modelos locales por la ruta absoluta del
# Operador (`~/.local/share/red-pill/models`, `/home/joan/opt/k2-bench/...`) y no
# son código del kernel: corren desde el host o desde dentro del sandbox, a veces
# sin `.env`, sin red y antes de que exista estado de red-pill. No resuelven por
# `core/paths.py` porque son standalone a propósito (misma clase que el pre-seed).
# La excepción sólo es válida mientras sigan siéndolo:
# `test_host_instruments_son_standalone` lo blinda.
SCRIPTS_HOST_INSTRUMENTS = {
	SCRIPTS_DIR / "bench_admission.py",
	SCRIPTS_DIR / "dokime.py",
	SCRIPTS_DIR / "kv_perplexity_probe.py",
	SCRIPTS_DIR / "voice_probe.py",
}

# Scripts que miden los directorios de OTROS arneses (`.opencode`, `.claude`,
# `.pi`): mismas dirs de terceros que `EXTERNAL_TOOL_FILES` para `src/`, con la
# misma razón — son ubicaciones oficiales del arnés, no raíces XDG de red-pill,
# así que `core/paths.py` no las posee. Su propio `~/.local/share/red-pill` sí
# pasa por `get_models_dir()`; esto sólo cubre lo ajeno.
SCRIPTS_EXTERNAL_TOOL = {
	SCRIPTS_DIR / "harness_cost.py",
}
INJECT_PKG = SCRIPTS_DIR / "inject"

HARDCODED_PATTERNS = [
	re.compile(r'["\']~/[^"\']'),  # "~/…" (a path, not a bare "~/" token)
	re.compile(r'["\']/(?:home|Users|root)/'),  # "/home/<user>/…"
	re.compile(r"Path\.home\(\)\s*/"),  # Path.home() / "…"
	re.compile(r'expanduser\(\s*["\']~'),  # os.path.expanduser("~/…")
	re.compile(r'(?:os\.environ\.get|os\.getenv)\(\s*["\']XDG_(?:DATA|CONFIG|STATE|CACHE|RUNTIME)_HOME'),  # raw XDG read
]


def _is_allowed(py: Path) -> bool:
	if py in ALLOWED_FILES or py in EXTERNAL_TOOL_FILES or py in SCRIPTS_PRE_SEED or py in SCRIPTS_HOST_INSTRUMENTS or py in SCRIPTS_EXTERNAL_TOOL:
		return True
	return INJECT_PKG in py.parents  # the whole scripts/inject/** package (IDE injectors)


def _collect_violations():
	violations = []
	for base in (SRC_DIR, SCRIPTS_DIR):
		for py_file in base.rglob("*.py"):
			if _is_allowed(py_file) or "__pycache__" in str(py_file):
				continue
			try:
				content = py_file.read_text(encoding="utf-8")
			except Exception:
				continue
			for i, line in enumerate(content.splitlines(), 1):
				if line.lstrip().startswith("#"):
					continue
				for pattern in HARDCODED_PATTERNS:
					if pattern.search(line):
						if "legacy" in line.lower() or "fallback" in line.lower():
							continue
						rel = py_file.relative_to(ROOT)
						violations.append(f"{rel}:{i} - {line.strip()}")
	return violations


def test_no_hardcoded_paths():
	"""No hardcoded home/XDG/absolute-user paths outside core/paths.py (+ allowlists)."""
	violations = _collect_violations()
	if violations:
		msg = "Hardcoded paths found. Resolve them through core/paths.py:\n"
		msg += "  (see CONVENTIONS.md §7 — path resolution)\n\nViolations:\n"
		msg += "\n".join(f"  {v}" for v in violations)
		pytest.fail(msg)


_STDLIB_IMPORT = re.compile(r"^\s*(?:from|import)\s+red_pill\b", re.MULTILINE)


@pytest.mark.parametrize("script", sorted(SCRIPTS_PRE_SEED), ids=lambda p: p.name)
def test_preseed_scripts_son_standalone(script: Path):
	"""La excepción de rutas sólo vale si el script no puede usar `core/paths.py`.

	Si un pre-seed importa `red_pill`, ya puede resolver rutas por `paths.py` y su
	entrada en `SCRIPTS_PRE_SEED` deja de estar justificada: hay que refactorizarlo
	en vez de ampliar la lista.
	"""
	assert script.is_file(), f"{script} desapareció: retira su entrada del allowlist"
	content = script.read_text(encoding="utf-8")
	assert not _STDLIB_IMPORT.search(content), f"{script.name} importa red_pill: resuelve sus rutas por core/paths.py y sácalo de SCRIPTS_PRE_SEED"


@pytest.mark.parametrize("script", sorted(SCRIPTS_HOST_INSTRUMENTS), ids=lambda p: p.name)
def test_host_instruments_son_standalone(script: Path):
	"""La excepción de instrumentos de host sólo vale si siguen siendo standalone.

	Si uno importa `red_pill`, ya puede resolver sus rutas por `core/paths.py` y
	su entrada deja de estar justificada: hay que refactorizarlo, no ampliar la
	lista.
	"""
	assert script.is_file(), f"{script} desapareció: retira su entrada del allowlist"
	content = script.read_text(encoding="utf-8")
	assert not _STDLIB_IMPORT.search(content), (
		f"{script.name} importa red_pill: resuelve sus rutas por core/paths.py y sácalo de SCRIPTS_HOST_INSTRUMENTS"
	)
