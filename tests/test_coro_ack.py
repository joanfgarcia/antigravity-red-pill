"""AD-099 — el arnés receptor acusa el nudge: `handed_off` → `delivered` por hook.

Contrato: todo nudge lleva `msg=<event_id>`. El hook de inicio de turno del arnés
lo ve en el prompt y promueve la fila, pero SOLO si el cuerpo que recibe es del
alma destinataria. Un acuse no retrocede. Los hooks copian la regex y la
sentencia del kernel tal cual (paridad).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from red_pill.session import delivery
from red_pill.session.store import SessionRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "seeds" / "settings" / "hooks" / "redpill_turn_start.py"
PLUGIN = REPO_ROOT / "seeds" / "opencode" / "plugins" / "redpill-scribe.js"


def _registry(path: Path) -> SessionRegistry:
	reg = SessionRegistry(str(path))
	reg.upsert_session(originator="claude_code:uuid-a", continuity_id="alma-1", mission_id="repo:next")
	reg.upsert_session(originator="opencode:ses_b", continuity_id="alma-2", mission_id="repo:next")
	return reg


def _handed_off(reg: SessionRegistry, *, to: str = "alma-1", verb: str = "ask") -> dict:
	ev = reg.add_event(
		event_type="message",
		mission_id="repo:next",
		summary="¿llega?",
		continuity_id="alma-2",
		originator="opencode:ses_b",
		global_turn=1,
		to_continuity=to,
		verb=verb,
	)
	assert delivery.set_delivery_state(event_id=ev["event_id"], continuity_id=to, state=delivery.STATE_HANDED_OFF, db_path=reg.db_path)
	return ev


def _state(reg: SessionRegistry, ev: dict, soul: str = "alma-1") -> str:
	return delivery.get_delivery(ev["event_id"], soul, db_path=reg.db_path)["state"]


@pytest.fixture
def reg(tmp_path):
	return _registry(tmp_path / "session.db")


class TestMarcador:
	def test_el_mensaje_lleva_el_marcador(self, reg):
		ev = _handed_off(reg)
		nudge = delivery.build_event_nudge(reg.get_event(ev["event_id"]))
		assert delivery.ACK_MARKER_RE.findall(nudge) == [ev["event_id"]]
		assert f"reply_to={ev['event_id']}" in nudge, "la dirección de respuesta va completa"

	def test_la_nota_del_tablon_tambien(self, reg):
		ev = reg.add_event(event_type="phase_done", mission_id="repo:next", summary="hecho", continuity_id="alma-1", originator="dag:j", global_turn=1)
		nudge = delivery.build_event_nudge(reg.get_event(ev["event_id"]))
		assert delivery.ACK_MARKER_RE.findall(nudge) == [ev["event_id"]]


class TestAcuse:
	def test_el_cuerpo_destinatario_acusa(self, reg):
		ev = _handed_off(reg)
		nudge = delivery.build_event_nudge(reg.get_event(ev["event_id"]))
		assert delivery.acknowledge_seen("claude_code:uuid-a", nudge, db_path=reg.db_path) == 1
		row = delivery.get_delivery(ev["event_id"], "alma-1", db_path=reg.db_path)
		assert row["state"] == delivery.STATE_DELIVERED
		assert row["reason"] == "ack_hook:claude_code:uuid-a"

	def test_sin_marcador_no_hace_nada(self, reg):
		ev = _handed_off(reg)
		assert delivery.acknowledge_seen("claude_code:uuid-a", "hola, ¿qué tal?", db_path=reg.db_path) == 0
		assert _state(reg, ev) == delivery.STATE_HANDED_OFF

	def test_la_sesion_huerfana_no_acusa(self, reg):
		"""`opencode run --session <id desconocido>` abre una sesión sin registro."""
		ev = _handed_off(reg)
		assert delivery.acknowledge_seen("opencode:ses_huerfana", f"msg={ev['event_id']}", db_path=reg.db_path) == 0
		assert _state(reg, ev) == delivery.STATE_HANDED_OFF

	def test_el_cuerpo_de_otra_alma_no_acusa(self, reg):
		ev = _handed_off(reg)
		assert delivery.acknowledge_seen("opencode:ses_b", f"msg={ev['event_id']}", db_path=reg.db_path) == 0
		assert _state(reg, ev) == delivery.STATE_HANDED_OFF

	def test_lo_visto_en_el_digest_no_se_toca(self, reg):
		ev = _handed_off(reg)
		delivery.set_delivery_state(event_id=ev["event_id"], continuity_id="alma-1", state=delivery.STATE_PULLED, db_path=reg.db_path)
		assert delivery.acknowledge_seen("claude_code:uuid-a", f"msg={ev['event_id']}", db_path=reg.db_path) == 0
		assert _state(reg, ev) == delivery.STATE_PULLED

	def test_el_acuse_no_retrocede(self, reg):
		"""Con el socket, el hook puede confirmar ANTES de que se escriba `handed_off`."""
		ev = _handed_off(reg)
		delivery.acknowledge_seen("claude_code:uuid-a", f"msg={ev['event_id']}", db_path=reg.db_path)
		delivery.set_delivery_state(event_id=ev["event_id"], continuity_id="alma-1", state=delivery.STATE_HANDED_OFF, db_path=reg.db_path)
		assert _state(reg, ev) == delivery.STATE_DELIVERED
		delivery.set_delivery_state(event_id=ev["event_id"], continuity_id="alma-1", state=delivery.STATE_READ, db_path=reg.db_path)
		assert _state(reg, ev) == delivery.STATE_READ, "leer sí avanza"


class TestParidad:
	def test_el_hook_de_claude_copia_regex_y_sentencia(self):
		spec = importlib.util.spec_from_file_location("redpill_turn_start_parity", HOOK)
		mod = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(mod)
		assert mod.ACK_SQL == delivery.ACK_SQL
		assert mod.ACK_MARKER_RE.pattern == delivery.ACK_MARKER_RE.pattern

	def test_el_plugin_de_opencode_copia_regex_y_sentencia(self):
		src = PLUGIN.read_text(encoding="utf-8")
		assert f'const ACK_SQL = "{delivery.ACK_SQL}";' in src
		assert f"const ACK_MARKER_RE = /{delivery.ACK_MARKER_RE.pattern}/g;" in src


class TestHookDeClaude:
	def _run(self, data_home: Path, prompt: str) -> subprocess.CompletedProcess:
		payload = {"session_id": "uuid-a", "hook_event_name": "UserPromptSubmit", "cwd": "/ws", "prompt": prompt}
		env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_MESSAGING")}
		env["XDG_DATA_HOME"] = str(data_home)
		return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)

	def test_prompt_con_marcador_acusa(self, tmp_path):
		queue = tmp_path / "red-pill" / "queue"
		queue.mkdir(parents=True)
		reg = _registry(queue / "session.db")
		ev = _handed_off(reg)
		nudge = delivery.build_event_nudge(reg.get_event(ev["event_id"]))
		res = self._run(tmp_path, nudge)
		assert res.returncode == 0, res.stderr
		assert _state(reg, ev) == delivery.STATE_DELIVERED

	def test_prompt_sin_marcador_no_toca_nada(self, tmp_path):
		queue = tmp_path / "red-pill" / "queue"
		queue.mkdir(parents=True)
		reg = _registry(queue / "session.db")
		ev = _handed_off(reg)
		assert self._run(tmp_path, "un turno normal").returncode == 0
		assert _state(reg, ev) == delivery.STATE_HANDED_OFF

	def test_sin_session_db_no_la_crea(self, tmp_path):
		res = self._run(tmp_path, "msg=" + "a" * 32)
		assert res.returncode == 0, res.stderr
		assert not (tmp_path / "red-pill" / "queue" / "session.db").exists()
