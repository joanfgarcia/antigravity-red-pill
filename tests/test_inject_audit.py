"""La siembra limpia sus restos y avisa de lo que convive con ella.

- Anclas retiradas del roster se podan; bloques REDPILL desconocidos sólo se avisan.
- Scripts de hook que la semilla ya no trae se retiran; uno editado a mano se respalda.
- La auditoría detecta duplicados entre ámbitos, bloques mixtos, hooks de otros
	arneses en los eventos de contexto, el MCP en dos ámbitos y el ancla `hook` sin
	arnés cableado.
- Foto antes/después: el diff y el informe dicen qué cambió.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import inject_anchor  # noqa: E402
import inject_settings  # noqa: E402
from inject import _audit as audit  # noqa: E402

HOOK_SEED = (REPO_ROOT / "seeds" / "anchors" / "sovereign_handshake.hook.md").read_text(encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
	monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
	return tmp_path


def _write(path: Path, text: str) -> Path:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")
	return path


def _block(name: str, body: str = "x", v: int = 1) -> str:
	return f"<!-- REDPILL:BEGIN {name} v={v} -->\n{body}\n<!-- REDPILL:END {name} -->"


def _cmd(script: str) -> dict:
	return {"type": "command", "command": f"python3 ${{HOME}}/.claude/hooks/{script}"}


def _codes(findings) -> list[str]:
	return [f.code for f in findings]


# ── Poda de anclas retiradas ──────────────────────────────────────────────────
def test_poda_el_ancla_retirada_y_respeta_lo_demas(tmp_path):
	path = _write(tmp_path / "AGENTS.md", f"# mío\n\n{_block('agent_core')}\n\n{_block('git_workflow')}\n\n{_block('desk')}\n")
	assert inject_anchor.prune_retired_blocks(str(path), backup=False) == ["git_workflow"]
	text = path.read_text(encoding="utf-8")
	assert "git_workflow" not in text
	assert "# mío" in text and "REDPILL:BEGIN agent_core" in text
	assert "REDPILL:BEGIN desk" in text, "un bloque desconocido puede ser de otro sembrador: no se borra"
	assert inject_anchor.prune_retired_blocks(str(path), backup=False) == []


def test_splice_ide_poda_al_sembrar(tmp_path):
	_write(tmp_path / "AGENTS.override.md", _block("git_workflow") + "\n")
	seeds = str(REPO_ROOT / "seeds" / "anchors")
	inject_anchor.splice_ide("pi", inject_anchor.BLOCK_ANCHORS, seeds, str(tmp_path), {}, backup=False)
	names = inject_anchor.block_names((tmp_path / "AGENTS.override.md").read_text(encoding="utf-8"))
	assert "git_workflow" not in names
	assert set(inject_anchor.BLOCK_ANCHORS) <= set(names)


# ── Scripts de hook convergentes ──────────────────────────────────────────────
def _seed_hooks(tmp_path: Path, scripts: dict[str, str]) -> str:
	seed = tmp_path / "seed"
	for name, text in scripts.items():
		_write(seed / "hooks" / name, text)
	return str(seed)


def test_retira_el_script_que_la_semilla_ya_no_trae(home):
	hooks = home / ".claude" / "hooks"
	_write(hooks / "redpill_viejo.py", "viejo")
	_write(hooks / "mio.py", "del operador")
	inject_settings.deploy_hook_scripts(_seed_hooks(home, {"redpill_harness.py": "nuevo"}))
	assert not (hooks / "redpill_viejo.py").exists()
	assert [p.name for p in hooks.glob("redpill_viejo.py.bak.*")], "lo retirado se conserva para volver atrás"
	assert (hooks / "mio.py").read_text(encoding="utf-8") == "del operador"
	manifest = json.loads((hooks / inject_settings.HOOK_MANIFEST).read_text(encoding="utf-8"))
	assert set(manifest) == {"redpill_harness.py"}


def test_respalda_el_script_editado_a_mano_y_no_el_sembrado(home):
	hooks = home / ".claude" / "hooks"
	inject_settings.deploy_hook_scripts(_seed_hooks(home / "v1", {"redpill_harness.py": "v1"}))
	inject_settings.deploy_hook_scripts(_seed_hooks(home / "v2", {"redpill_harness.py": "v2"}))
	assert not list(hooks.glob("redpill_harness.py.bak.*")), "actualizar lo que sembró red-pill no necesita respaldo"
	(hooks / "redpill_harness.py").write_text("v2 + parche local", encoding="utf-8")
	inject_settings.deploy_hook_scripts(_seed_hooks(home / "v3", {"redpill_harness.py": "v3"}))
	baks = list(hooks.glob("redpill_harness.py.bak.*"))
	assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == "v2 + parche local"
	assert (hooks / "redpill_harness.py").read_text(encoding="utf-8") == "v3"


# ── Auditoría ─────────────────────────────────────────────────────────────────
def test_hook_duplicado_entre_ambitos_y_bloque_mixto(home, monkeypatch):
	ws = home / "ws"
	_write(home / ".claude" / "hooks" / "redpill_harness.py", "x")
	user = {"hooks": {"UserPromptSubmit": [{"hooks": [_cmd("redpill_harness.py")]}]}}
	_write(home / ".claude" / "settings.json", json.dumps(user))
	project = {
		"hooks": {
			"UserPromptSubmit": [{"hooks": [_cmd("redpill_harness.py")]}],
			"Stop": [{"hooks": [_cmd("redpill_scribe.py"), {"type": "command", "command": "echo ajeno"}]}],
		}
	}
	_write(ws / ".claude" / "settings.json", json.dumps(project))
	codes = _codes(audit.audit(str(ws)))
	assert "hook_duplicate_scope" in codes
	assert "hook_mixed_block" in codes
	assert "hook_script_missing" in codes  # redpill_scribe.py no está desplegado


def test_hook_ajeno_en_evento_de_contexto_se_avisa(home):
	settings = {
		"hooks": {
			"SessionStart": [{"hooks": [{"type": "command", "command": "sh otro_arnes.sh"}]}],
			"Stop": [{"hooks": [{"type": "command", "command": "sh fin.sh"}]}],
		}
	}
	_write(home / ".claude" / "settings.json", json.dumps(settings))
	found = [f for f in audit.audit() if f.code == "foreign_context_hook"]
	assert len(found) == 1 and "otro_arnes.sh" in found[0].message


def test_anclas_retiradas_desconocidas_sin_marca_y_de_proyecto(home):
	ws = home / "ws"
	_write(home / ".claude" / "CLAUDE.md", _block("agent_core") + "\n" + _block("git_workflow") + "\n" + _block("desk") + "\n")
	_write(
		home / ".gemini" / "GEMINI.md",
		'<constraint critical="true" name="sovereign_handshake">viejo</constraint>\n' + _block("agent_core") + "\n" + _block("agent_core") + "\n",
	)
	_write(ws / "CLAUDE.md", _block("knowledge_access") + "\n")
	codes = _codes(audit.audit(str(ws)))
	for code in ("anchor_retired", "anchor_unknown", "anchor_unmarked", "anchor_duplicate", "anchor_project_duplicate"):
		assert code in codes, code


def test_ancla_hook_sin_arnes_cableado_es_error(home):
	_write(home / ".claude" / "CLAUDE.md", _block("sovereign_handshake", HOOK_SEED, 6) + "\n")
	errors = [f for f in audit.audit() if f.level == audit.ERROR]
	assert [f.code for f in errors] == ["anchor_hook_unwired"]


def test_ancla_hook_con_arnes_cableado_no_avisa(home):
	_write(home / ".claude" / "CLAUDE.md", _block("sovereign_handshake", HOOK_SEED, 6) + "\n")
	_write(home / ".claude" / "hooks" / "redpill_harness.py", "x")
	wired = {"hooks": {e: [{"hooks": [_cmd("redpill_harness.py")]}] for e in ("SessionStart", "UserPromptSubmit")}}
	_write(home / ".claude" / "settings.json", json.dumps(wired))
	assert "anchor_hook_unwired" not in _codes(audit.audit())


def test_mcp_en_dos_ambitos(home):
	ws = home / "ws"
	server = {"RedPill-Kernel": {"command": "uv"}}
	_write(home / ".claude.json", json.dumps({"mcpServers": server, "projects": {"/p": {"mcpServers": server}}}))
	_write(ws / ".mcp.json", json.dumps({"mcpServers": server}))
	found = [f for f in audit.audit(str(ws)) if f.code == "mcp_multi_scope"]
	assert len(found) == 2


def test_script_obsoleto_y_respaldos_en_hooks(home):
	hooks = home / ".claude" / "hooks"
	_write(hooks / "redpill_retirado.py", "x")
	_write(hooks / "redpill_scribe.py.bak", "x")
	codes = _codes(audit.audit())
	assert "hook_stale_script" in codes and "hook_backups" in codes


def test_maquina_limpia_sin_hallazgos(home):
	assert audit.audit() == []


def _all_anchors() -> str:
	return "\n".join(_block(a) for a in inject_anchor.BLOCK_ANCHORS) + "\n"


def test_override_de_pi_entra_en_la_foto_y_en_la_auditoria(home, monkeypatch):
	ws = home / "IA"
	monkeypatch.setenv("WORKSPACE_ROOT", str(ws))
	(home / ".pi" / "agent").mkdir(parents=True)
	override = _write(ws / "AGENTS.override.md", _all_anchors() + _block("git_workflow") + "\n")
	assert str(override) in audit.snapshot()
	assert "anchor_retired" in _codes(audit.audit())
	override.write_text(_all_anchors().replace("identity_pact", "otra"), encoding="utf-8")
	missing = [f for f in audit.audit() if f.code == "anchor_missing"]
	assert len(missing) == 1 and "identity_pact" in missing[0].message


def test_pi_instalado_sin_override_se_avisa(home, monkeypatch):
	monkeypatch.setenv("WORKSPACE_ROOT", str(home / "IA"))
	(home / "IA").mkdir()
	(home / ".pi" / "agent").mkdir(parents=True)
	missing = [f for f in audit.audit() if f.code == "anchor_missing"]
	assert len(missing) == 1 and "no existe" in missing[0].message


def test_ide_presente_con_anclas_incompletas(home):
	_write(home / ".claude" / "CLAUDE.md", _block("agent_core") + "\n")
	missing = [f for f in audit.audit() if f.code == "anchor_missing"]
	assert len(missing) == 1 and "sovereign_handshake" in missing[0].message


# ── Foto antes/después ────────────────────────────────────────────────────────
def test_foto_diff_e_informe(home):
	claude_md = _write(home / ".claude" / "CLAUDE.md", "antes\n")
	_write(home / ".claude.json", json.dumps({"mcpServers": {}, "numStartups": 1}))
	before = audit.snapshot()
	claude_md.write_text("después\n", encoding="utf-8")
	_write(home / ".claude.json", json.dumps({"mcpServers": {}, "numStartups": 2}))
	after = audit.snapshot()
	changes = audit.diff(before, after)
	assert list(changes) == [str(claude_md)], "el estado de la app en ~/.claude.json no es un cambio de la siembra"

	run = audit.new_run_dir()
	audit.save_snapshot(before, os.path.join(run, "before"))
	index = json.loads(Path(run, "before", "index.json").read_text(encoding="utf-8"))
	assert str(claude_md) in index.values()
	report = Path(audit.write_report(run, [], [], changes)).read_text(encoding="utf-8")
	assert "-antes" in report and "+después" in report
	assert "(+1 −1)" in audit.summarize_changes(changes)


def test_conserva_solo_las_ultimas_ejecuciones(home):
	base = Path(audit._state_dir())
	for i in range(13):
		(base / f"2026010{i:02d}").mkdir(parents=True)
	audit.prune_runs(keep=10)
	assert len(list(base.iterdir())) == 10
