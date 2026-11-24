"""Tests del target Pi en `inject_anchor.py`.

Cubren lo específico de Pi: `AGENTS.override.md` (que en Pi >=0.87 sustituye a
`AGENTS.md`/`CLAUDE.md` del mismo directorio) y el override de semillas por IDE
(`seeds/pi/anchors/<anchor>.md` gana sobre `seeds/anchors/<anchor>.md`).
"""

from __future__ import annotations

import importlib.util
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ANCHOR_PATH = os.path.join(REPO_ROOT, "scripts", "inject_anchor.py")
SEEDS_DIR = os.path.join(REPO_ROOT, "seeds", "anchors")

VARS = {"AGENT_CORE_DIR": "/tmp/ac", "RED_PILL_CMD": "rp"}


def _load() -> object:
	spec = importlib.util.spec_from_file_location("inject_anchor_under_test", ANCHOR_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_anchor_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def test_pi_target_resuelve_a_agents_override():
	m = _load()
	target = m.REGISTRY_BY_IDE["pi"]
	assert target.requires_workspace
	assert m.resolve_target_path(target, "/tmp/ws") == "/tmp/ws/AGENTS.override.md"
	assert m.resolve_target_path(target, None) is None


def test_pi_seed_override_gana_y_fallback_generico():
	m = _load()
	override = m.ide_seed_path(SEEDS_DIR, "pi", "sovereign_handshake")
	assert override.endswith(os.path.join("seeds", "pi", "anchors", "sovereign_handshake.md"))
	# Un anchor sin override cae a la semilla genérica.
	assert m.ide_seed_path(SEEDS_DIR, "pi", "agent_core") == os.path.join(SEEDS_DIR, "agent_core.md")


def test_splice_ide_pi_escribe_override_y_es_idempotente(tmp_path):
	m = _load()
	ws = str(tmp_path)
	anchors = ["sovereign_handshake", "agent_core"]
	assert m.splice_ide("pi", anchors, SEEDS_DIR, ws, VARS, backup=False) == 2
	text = open(os.path.join(ws, "AGENTS.override.md"), encoding="utf-8").read()
	assert text.count("<!-- REDPILL:BEGIN") == 2
	assert "AUTOMÁTICO en Pi" in text  # semilla pi, no la genérica MCP
	assert m.splice_ide("pi", anchors, SEEDS_DIR, ws, VARS, backup=False) == 0  # converge


def test_backup_pristino_y_por_edicion(tmp_path):
	"""Primera edición crea .bak prístino; cada edición deja .bak.<ts>."""
	import glob

	m = _load()
	f = tmp_path / "CLAUDE.md"
	f.write_text("contenido original\n", encoding="utf-8")

	m._atomic_write(str(f), "version 1\n", backup=True)
	assert f.read_text(encoding="utf-8") == "version 1\n"
	assert (tmp_path / "CLAUDE.md.bak").read_text(encoding="utf-8") == "contenido original\n"

	m._atomic_write(str(f), "version 2\n", backup=True)
	# el .bak prístino NO se pisa
	assert (tmp_path / "CLAUDE.md.bak").read_text(encoding="utf-8") == "contenido original\n"
	# hay al menos una copia por edición
	assert glob.glob(str(tmp_path / "CLAUDE.md.bak.*"))


def test_anchor_handshake_exige_payload_completo() -> None:
	"""La identidad sólo viaja como retorno del handshake: el anchor debe pedir
	(a) `is_new_session: true` en Step 0 y (b) devolver el payload **completo**.
	Sin esto el agente resume (`len=… mission=…`) y se queda sin CORE_RULES —
	amnesia silenciosa por su propia mano (incidente 2026-10-27)."""
	seed = os.path.join(SEEDS_DIR, "sovereign_handshake.md")
	text = open(seed, encoding="utf-8").read()
	assert "is_new_session" in text, "falta la instrucción de is_new_session en Step 0"
	assert "Never truncate" in text, "falta la regla de no truncar el payload"
	assert "<BUNKER_CONTEXT>" in text and "CORE_RULES" in text, "la regla no explica qué se pierde"
	# La versión del bloque debe haberse bumpeado para re-splicar hosts existentes.
	m = _load()
	assert m.BLOCK_VERSION["sovereign_handshake"] >= 4


# ── variante del handshake: `hook` sólo donde alguien inyecta ────────────────


def _settings(home, events):
	cmd = "python3 ${HOME}/.claude/hooks/redpill_harness.py"
	hooks = {e: [{"hooks": [{"type": "command", "command": cmd}]}] for e in events}
	path = home / ".claude" / "settings.json"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(__import__("json").dumps({"hooks": hooks}), encoding="utf-8")


def _hook_script(home):
	script = home / ".claude" / "hooks" / "redpill_harness.py"
	script.parent.mkdir(parents=True, exist_ok=True)
	script.write_text("#", encoding="utf-8")


def test_claude_code_sin_hook_de_arnes_queda_en_prompt(tmp_path, monkeypatch):
	"""Sembrar `hook` sin quien inyecte deja la sesión sin identidad."""
	monkeypatch.setenv("HOME", str(tmp_path))
	m = _load()
	assert not m.hook_wired("claude-code")
	_settings(tmp_path, ["SessionStart", "UserPromptSubmit"])
	assert not m.hook_wired("claude-code")  # cableado pero sin script desplegado
	_hook_script(tmp_path)
	assert m.hook_wired("claude-code")
	assert m.hook_wired("claude-code-project", str(tmp_path / "ws"))


def test_claude_code_sin_session_start_no_es_hook(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))
	m = _load()
	_hook_script(tmp_path)
	_settings(tmp_path, ["UserPromptSubmit", "Stop"])
	assert not m.hook_wired("claude-code")


def test_hook_nativo_y_desktop_chat(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))
	m = _load()
	assert m.hook_wired("opencode") and m.hook_wired("pi")
	_hook_script(tmp_path)
	_settings(tmp_path, ["SessionStart", "UserPromptSubmit"])
	# El chat de Desktop (Project) no tiene hooks aunque Claude Code sí los tenga.
	assert not m.hook_wired("claude-desktop-project")
	assert not m.hook_wired("antigravity")


def test_desktop_chat_relay_lleva_el_turno_anterior():
	m = _load()
	relay = m.ide_call_vars("claude-desktop-project")["RELAY_INSTRUCTION"]
	assert "previous_prompt" in relay and "previous_response" in relay
	assert "previous_prompt" not in m.ide_call_vars("claude-code")["RELAY_INSTRUCTION"]


# ── variante `hook` compartida por todos los inyectores ──────────────────────


def test_seed_override_gana_a_hook_y_hook_a_generico(tmp_path):
	m = _load()
	seeds = tmp_path / "seeds" / "anchors"
	seeds.mkdir(parents=True)
	(seeds / "a.md").write_text("generico", encoding="utf-8")
	(seeds / "a.hook.md").write_text("hook", encoding="utf-8")
	assert m.anchor_seed_path(str(seeds), "opencode", "a", "prompt").endswith("a.md")
	assert m.anchor_seed_path(str(seeds), "opencode", "a", "hook").endswith("a.hook.md")
	own = tmp_path / "seeds" / "pi" / "anchors"
	own.mkdir(parents=True)
	(own / "a.md").write_text("pi", encoding="utf-8")
	assert m.anchor_seed_path(str(seeds), "pi", "a", "hook") == str(own / "a.md")


def test_pacto_en_hook_es_breve_y_en_prompt_completo(tmp_path, monkeypatch):
	"""Con arnés que inyecta, la identidad ya llega en CORE_RULES: el ancla sólo
	apunta al procedimiento. Sin arnés (antigravity, chat de Desktop) va completa."""
	monkeypatch.setenv("HOME", str(tmp_path))
	m = _load()
	hook = m.anchor_seed_path(SEEDS_DIR, "opencode", "identity_pact", m.anchor_variant("opencode"))
	prompt = m.anchor_seed_path(SEEDS_DIR, "antigravity", "identity_pact", m.anchor_variant("antigravity"))
	assert hook.endswith("identity_pact.hook.md")
	assert prompt.endswith("identity_pact.md")
	for path in (hook, prompt):
		text = open(path, encoding="utf-8").read()
		assert "IDENTITY_PACT.md" in text and "--accept" in text
	assert len(open(hook, encoding="utf-8").read()) < len(open(prompt, encoding="utf-8").read())


def test_splice_ide_pi_usa_la_variante_hook(tmp_path):
	"""Pi no tiene override de `identity_pact`: recibe la variante `hook`."""
	m = _load()
	m.splice_ide("pi", ["identity_pact"], SEEDS_DIR, str(tmp_path), VARS, backup=False)
	text = (tmp_path / "AGENTS.override.md").read_text(encoding="utf-8")
	assert "llegan en `CORE_RULES`" in text


def test_oom_shield_vive_solo_en_la_regla_de_jobs():
	"""El escudo OOM estaba en el handshake y chocaba con «nunca `systemd-run`
	suelto» de la regla de jobs. Ahora es la excepción in-process de esa regla."""
	pi_dir = os.path.join(REPO_ROOT, "seeds", "pi", "anchors")
	for path in (
		os.path.join(SEEDS_DIR, "sovereign_handshake.md"),
		os.path.join(SEEDS_DIR, "sovereign_handshake.hook.md"),
		os.path.join(pi_dir, "sovereign_handshake.md"),
	):
		assert "MemoryMax" not in open(path, encoding="utf-8").read(), path
	for path in (os.path.join(SEEDS_DIR, "job_dag_execution.md"), os.path.join(pi_dir, "job_dag_execution.md")):
		text = open(path, encoding="utf-8").read()
		assert "MemoryMax=<LIMIT>" in text and "in-process" in text and "systemd-run` suelto" in text


def test_prune_blocks_not_in_respeta_lo_ajeno(tmp_path):
	"""El filtro por rol poda las anclas conocidas que sobran, no los bloques de
	otro sembrador (el desk también escribe en el mismo fichero)."""
	m = _load()
	p = tmp_path / "AGENTS.override.md"
	p.write_text(
		"# propio\n"
		"<!-- REDPILL:BEGIN minimal v=1 -->\nminimal\n<!-- REDPILL:END minimal -->\n"
		"<!-- REDPILL:BEGIN agent_core v=2 -->\ncore\n<!-- REDPILL:END agent_core -->\n"
		"<!-- REDPILL:BEGIN desk v=1 -->\ndesk\n<!-- REDPILL:END desk -->\n",
		encoding="utf-8",
	)
	pruned = m.prune_blocks_not_in(str(p), ["agent_core"], backup=False)
	assert pruned == ["minimal"]
	text = p.read_text(encoding="utf-8")
	assert "REDPILL:BEGIN agent_core" in text
	assert "REDPILL:BEGIN desk" in text
	assert "REDPILL:BEGIN minimal" not in text


def test_perfil_sin_rules_blocks_es_roster_completo():
	"""`none` es la instalación estándar: `rules_blocks: []` significa roster
	completo, no «ninguna ancla». Si no, el contraste nacería desnudo."""
	m = _load()
	bundle = m.resolve_profile("none:local-9b:none")
	assert bundle is not None
	assert bundle.rules_blocks == []
