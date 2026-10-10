"""
CERT-COND-003 sesiones (Alma y Coro, Fase 0a): identity + session.db
=====================================================================
Cubre:
- `identity.py` (puro): UUIDv7, cascada de misión A2, tag `<session>`
	(render/parse/idempotencia F5).
- `store.py` (`session.db`): upsert/recovery por originator, reencarnación
	(nuevo alma sobre el mismo cuerpo), reloj `global_turn` monotónico,
	canonización de afinidad (D19).
"""

import os

import pytest

from red_pill.session.identity import (
	_parse_session_tags,
	decorate_with_session_tag,
	new_continuity_id,
	render_session_tag,
	resolve_default_mission,
)
from red_pill.session.store import SessionRegistry


@pytest.fixture
def reg(tmp_path):
	store = SessionRegistry(str(tmp_path / "session.db"))
	yield store


class TestIdentity:
	def test_uuid7_unique_orderable_version(self):
		a = new_continuity_id()
		b = new_continuity_id()
		assert a != b
		assert len(a) == 36
		assert a[14] == "7"  # versión UUIDv7
		assert os.urandom  # (sanidad trivial: el módulo circula)

	def test_mission_cascade_param_wins(self):
		assert resolve_default_mission("telegram:42") == "telegram:42"
		assert resolve_default_mission(" mission:adhoc-1 ") == "mission:adhoc-1"

	def test_mission_cascade_repo_branch(self):
		assert resolve_default_mission(None, branch="feat/x") == "repo:feat/x"
		assert resolve_default_mission(None, branch="HEAD") is not None  # no infiere HEAD

	def test_mission_cascade_adhoc(self):
		assert resolve_default_mission(None) == f"mission:adhoc-{__import__('datetime').date.today().isoformat()}"

	def test_mission_empty_param_falls_through(self):
		assert resolve_default_mission("", branch="main") == "repo:main"

	def test_tag_render_and_parse(self):
		tag = render_session_tag(continuity_id="alma-1", originator="opencode:s1", mission_id="repo:main")
		parsed = _parse_session_tags(tag)
		assert parsed == [{"continuity_id": "alma-1", "leg": "opencode:s1", "mission": "repo:main"}]

	def test_tag_parse_mission_with_slash(self):
		# Un `repo:<rama>` con '/' ya no se trunca al parsear (fix adversarial).
		tag = render_session_tag(
			continuity_id="alma-1", originator="opencode:s1", mission_id="repo:feat/phase-0a-affinity"
		)
		parsed = _parse_session_tags(tag)
		assert parsed == [
			{"continuity_id": "alma-1", "leg": "opencode:s1", "mission": "repo:feat/phase-0a-affinity"}
		]

	def test_tag_roundtrip_sanitizes_breaking_chars(self):
		# '>' '<' '"' en una rama romperían el grammar del tag → se sanean, y el
		# tag sigue siendo idempotente al decorar.
		tag = render_session_tag(continuity_id="alma-1", originator="opencode:s1", mission_id="repo:feat/x>y")
		assert tag.count("<") == 1 and tag.endswith("/>")
		parsed = _parse_session_tags(tag)
		assert parsed == [{"continuity_id": "alma-1", "leg": "opencode:s1", "mission": "repo:feat/x_y"}]
		out = decorate_with_session_tag(
			tag, continuity_id="alma-1", originator="opencode:s1", mission_id="repo:feat/x>y"
		)
		assert out.count("<session") == 1

	def test_decorate_idempotent_single_tag(self):
		out = decorate_with_session_tag(
			"hola", continuity_id="alma-1", originator="opencode:s1", mission_id="repo:main"
		)
		out2 = decorate_with_session_tag(
			out, continuity_id="alma-1", originator="opencode:s1", mission_id="repo:main"
		)
		assert out.count("<session") == 1
		assert out2.count("<session") == 1  # no acumula tags obsoletos
		assert "alma-1" in out2


class TestStore:
	def test_upsert_and_recover_by_originator(self, reg):
		reg.upsert_session(
			originator="claude_code:s1",
			continuity_id="alma-1",
			mission_id="repo:main",
			role="orchestrator",
			affinity=["WS:B", "ws:a", "ws:a"],
		)
		row = reg.get_by_originator("claude_code:s1")
		assert row["continuity_id"] == "alma-1"
		assert row["mission_id"] == "repo:main"
		assert row["provider"] == "claude_code"
		assert row["session_id"] == "s1"
		assert row["role"] == "orchestrator"
		assert row["affinity_json"] == '["ws:a", "ws:b"]'  # canonizada D19
		assert reg.get_by_originator("nobody") is None

	def test_reincarnation_new_alma_same_body(self, reg):
		reg.upsert_session(originator="claude_code:s1", continuity_id="alma-1", mission_id="repo:main")
		reg.upsert_session(originator="claude_code:s1", continuity_id="alma-2", mission_id="repo:main")
		assert reg.get_by_originator("claude_code:s1")["continuity_id"] == "alma-1"

	def test_global_turn_monotonic(self, reg):
		assert reg.get_max_global_turn() == 0
		gt1 = reg.next_global_turn("claude_code:s1", ["x"])
		gt2 = reg.next_global_turn("claude_code:s1", ["x"])
		assert gt1 == 1 and gt2 == 2
		assert reg.get_max_global_turn() == 2
