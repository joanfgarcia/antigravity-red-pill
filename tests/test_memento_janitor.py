"""Fase 3 del RFC-002: JanitorPlugins interaction_ttl y queue_purge_rendered."""

import sqlite3
import time

from red_pill.swarm.agents.janitor_plugins.interaction_ttl import InteractionTTLPlugin
from red_pill.swarm.agents.janitor_plugins.queue_purge_rendered import QueuePurgeRenderedPlugin


class FakeJanitor:
	def __init__(self):
		self.lines = []

	def log(self, msg):
		self.lines.append(msg)


async def test_interaction_ttl_refuses_ttl_below_preheating_window():
	plugin = InteractionTTLPlugin()
	result = await plugin.execute(FakeJanitor(), {"plugins": {"interaction_ttl": {"ttl_hours": 48}}})
	assert result["purged"] == 0 and result["skipped"] == "ttl_below_preheating_window"


async def test_interaction_ttl_purges_only_stale_points():
	from qdrant_client.http import models

	from red_pill.memory import MemoryManager

	mem = MemoryManager()
	fresh_id = mem.record_interaction_pair("turno fresco", "respuesta", originator="test")
	stale_id = mem.record_interaction_pair("turno viejo", "respuesta", originator="test")
	assert fresh_id and stale_id
	mem.client.set_payload("interaction_memories", payload={"timestamp": int(time.time()) - 100 * 3600}, points=[stale_id])

	result = await InteractionTTLPlugin().execute(FakeJanitor(), {}, memory_manager=mem)
	assert result["purged"] == 1 and result["ttl_hours"] == 72

	survivors = mem.client.retrieve("interaction_memories", ids=[fresh_id, stale_id])
	assert [str(p.id) for p in survivors] == [fresh_id]
	# limpieza: no dejar el punto fresco a los demás tests
	mem.client.delete("interaction_memories", points_selector=models.PointIdsList(points=[fresh_id]), wait=True)


async def test_queue_purge_rendered_mcp_groups_and_voice_age(tmp_path):
	"""El pase `mcp:` (única copia en Memento) y el de voz/edad conviven."""
	from red_pill.memento.registry import MementoRegistry

	db = tmp_path / "bunker_queue.db"
	con = sqlite3.connect(db)
	con.execute("CREATE TABLE memory_queue (id INTEGER PRIMARY KEY, prompt TEXT, response TEXT, status TEXT, created_at REAL, originator TEXT)")
	old_day_epoch = 1785542400.0 + 3600  # 2026-08-01, frío (margen 7d desde el 26-08)
	rows = [
		("purgable", "r", "completed", old_day_epoch, "Aleth (Test)"),  # grupo renderizado + frío → fuera
		("pendiente", "r", "pending", old_day_epoch, "Aleth (Test)"),  # no completed → se queda
		("sin render", "r", "completed", old_day_epoch, "otro_origen"),  # frío para el mood → fuera
		("null purgable", "r", "completed", old_day_epoch, None),  # grupo unknown renderizado → fuera
		("reciente", "r", "completed", time.time(), "Aleth (Test)"),  # dentro del margen → se queda
	]
	con.executemany("INSERT INTO memory_queue (prompt, response, status, created_at, originator) VALUES (?,?,?,?,?)", rows)
	con.commit()
	con.close()

	registry = MementoRegistry(path=tmp_path / "reg.json")
	registry.upsert("memory_queue", "mcp:Aleth (Test):2026-08-01", {"dir": "2026-08/memory_queue/x", "month": "2026-08"})
	registry.upsert("memory_queue", "mcp:unknown:2026-08-01", {"dir": "2026-08/memory_queue/y", "month": "2026-08"})
	registry.upsert("memory_queue", f"mcp:Aleth (Test):{time.strftime('%Y-%m-%d')}", {"dir": "2026-08/memory_queue/z", "month": "2026-08"})
	registry.save()

	result = await QueuePurgeRenderedPlugin().execute(FakeJanitor(), {}, queue_db_path=db, registry_path=tmp_path / "reg.json")
	assert result["purged_groups"] == 2, result
	assert result["purged_expired"] == 1, result  # "sin render" ya frío para el mood
	assert result["purged"] == 3

	con = sqlite3.connect(db)
	remaining = sorted(r[0] for r in con.execute("SELECT prompt FROM memory_queue").fetchall())
	con.close()
	assert remaining == ["pendiente", "reciente"]


async def test_queue_purge_rendered_by_voice_and_age(tmp_path):
	"""v2: sin voz del Operador se va ya; con voz, solo cuando caduca para el mood."""

	db = tmp_path / "bunker_queue.db"
	con = sqlite3.connect(db)
	con.execute(
		"CREATE TABLE memory_queue (id INTEGER PRIMARY KEY, prompt TEXT, response TEXT, status TEXT, "
		"created_at REAL, originator TEXT, session_id TEXT)"
	)
	cold = time.time() - 30 * 86400
	rows = [
		("revisa el log del despertar y dime qué ves", "r", "completed", cold, "opencode", "ses_aaa"),
		("revisa el log de hoy, que no me fío", "r", "completed", time.time(), "opencode", "ses_aaa"),
		("<task-notification><task-id>x</task-id></task-notification>", "r", "completed", time.time(), "claude_code", "ses_bbb"),
		("[CORO notify · hilo E-1 · salto 0/2] de: abc", "r", "completed", cold, "opencode", "ses_aaa"),
		("You are a subagent spawned by another session. Lens: gaps.", "r", "completed", cold, "opencode", "ses_ccc"),
		("<user_rules> <RULE[user_global]> CRITICAL: Respond ONLY to the current message", "r", "completed", cold, "opencode", "ses_ccc"),
		("pendiente de drenar", "r", "pending", cold, "opencode", "ses_aaa"),
	]
	con.executemany(
		"INSERT INTO memory_queue (prompt, response, status, created_at, originator, session_id) VALUES (?,?,?,?,?,?)",
		rows,
	)
	con.commit()
	con.close()

	plugin = QueuePurgeRenderedPlugin()
	dry = await plugin.execute(FakeJanitor(), {}, queue_db_path=db, registry_path=tmp_path / "reg.json", dry_run=True)
	assert dry["purged"] == 5, dry  # caducada + 4 sin voz
	assert dry["purged_no_voice"] == 4 and dry["purged_expired"] == 1
	con = sqlite3.connect(db)
	assert con.execute("SELECT COUNT(*) FROM memory_queue").fetchone()[0] == 7, "dry-run no borra"
	con.close()

	result = await plugin.execute(FakeJanitor(), {}, queue_db_path=db, registry_path=tmp_path / "reg.json")
	assert result["purged"] == 5

	con = sqlite3.connect(db)
	remaining = sorted(r[0] for r in con.execute("SELECT prompt FROM memory_queue").fetchall())
	con.close()
	assert remaining == ["pendiente de drenar", "revisa el log de hoy, que no me fío"]
