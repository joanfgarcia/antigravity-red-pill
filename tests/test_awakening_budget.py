"""AWAKEN-002 — tope diario de despertares y Derecho al Silencio.

Ejercita `_process_awakening` con el `get_connection` REAL sobre un events.db
temporal (así la migración de `execution_ledger.counted` corre de verdad):
- el silencio se clasifica por la frase canónica AL PRINCIPIO de una respuesta
  corta, no por substring;
- AWAKENING_SILENCE_COUNTS=True restaura el cómputo antiguo;
- los silencios no bloquean el siguiente despertar productivo;
- la frontera del día es la hora local;
- un error deja counted=1.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import red_pill.core.agent_worker as aw
from red_pill.core.agent_worker import MAX_AWAKENINGS_PER_DAY, IDEWorker, is_silence_response

CANONICAL_SILENCE = "Ejercicio consciente del Derecho al Silencio. Estado del Búnker: calma."
REPORT = "Revisé el planner y dejé dos notas. " * 20


def _seed_events_db(db_path: Path) -> None:
	conn = sqlite3.connect(str(db_path))
	conn.executescript(
		"""
		CREATE TABLE inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE,
			channel TEXT NOT NULL, channel_user_id TEXT NOT NULL, cascade_id TEXT,
			payload TEXT NOT NULL, status TEXT DEFAULT 'PENDING', retries INTEGER DEFAULT 0,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
		CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT,
			channel_user_id TEXT, cascade_id TEXT, payload TEXT);
		CREATE TABLE telegram_sessions (channel_user_id TEXT PRIMARY KEY, cascade_id TEXT,
			cascade_type TEXT, model TEXT, backend TEXT, accumulated_len INTEGER);
		CREATE TABLE dead_letters (id INTEGER PRIMARY KEY AUTOINCREMENT, original_table TEXT NOT NULL,
			original_id INTEGER NOT NULL, channel TEXT NOT NULL, channel_user_id TEXT NOT NULL,
			payload TEXT NOT NULL, error_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
		INSERT INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES ('op', 'c1', 'local_session');
		"""
	)
	conn.commit()
	conn.close()


class _Bridge:
	def __init__(self, response="", ok=True, error="boom", exc=None):
		self.response, self.ok, self.error, self.exc = response, ok, error, exc
		self.calls = 0

	def prompt(self, text, timeout=None, **kw):
		self.calls += 1
		if self.exc is not None:
			raise self.exc
		return SimpleNamespace(ok=self.ok, response=self.response, error=self.error, model="m", conversation_id="conv")


@pytest.fixture
def events_db(tmp_path, monkeypatch):
	db_path = tmp_path / "events.db"
	_seed_events_db(db_path)
	monkeypatch.setattr(aw, "DB_PATH", db_path)
	return db_path


@pytest.fixture
def awaken(events_db, monkeypatch):
	"""Ejecuta un despertar con la respuesta dada y devuelve (fila del ledger, outbox, bridge)."""
	monkeypatch.setattr(aw, "_awakening_channel_directive", lambda operator=None: "CANAL")

	def _run(response="", ok=True, exc=None):
		worker = IDEWorker.__new__(IDEWorker)
		worker._touch_lease = lambda: None
		worker._bridge_awakening = _Bridge(response=response, ok=ok, exc=exc)
		conn = aw.get_connection()
		conn.execute("INSERT INTO inbox (channel, channel_user_id, payload) VALUES ('system', 'autonomous_awakening', '{}')")
		msg_id = conn.execute("SELECT max(id) FROM inbox").fetchone()[0]
		conn.commit()
		worker._process_awakening("despierta", [msg_id], conn.cursor(), conn)
		conn.commit()
		ledger = conn.execute("SELECT status, counted FROM execution_ledger ORDER BY id DESC LIMIT 1").fetchone()
		outbox = [json.loads(r["payload"])["text"] for r in conn.execute("SELECT payload FROM outbox")]
		inbox = conn.execute("SELECT status, retries FROM inbox WHERE id = ?", (msg_id,)).fetchone()
		conn.close()
		return SimpleNamespace(ledger=ledger, outbox=outbox, inbox=inbox, bridge=worker._bridge_awakening)

	return _run


def _set_silence_counts(monkeypatch, value: bool):
	monkeypatch.setenv("AWAKENING_SILENCE_COUNTS", "true" if value else "false")
	aw.cfg.get_config.cache_clear()


def _fill_ledger(db_path: Path, n: int, *, counted: int, started_at: str | None = None) -> None:
	conn = aw.get_connection()
	for _ in range(n):
		if started_at:
			conn.execute(
				"INSERT INTO execution_ledger (exec_type, status, counted, started_at) VALUES ('awakening', 'completed', ?, ?)",
				(counted, started_at),
			)
		else:
			conn.execute("INSERT INTO execution_ledger (exec_type, status, counted) VALUES ('awakening', 'completed', ?)", (counted,))
	conn.commit()
	conn.close()


# ── Clasificación del silencio ───────────────────────────────────────────────


@pytest.mark.parametrize(
	"text",
	[
		CANONICAL_SILENCE,
		f"  {CANONICAL_SILENCE}\n",
		f"**{CANONICAL_SILENCE}**",
		f"'{CANONICAL_SILENCE}'",
		"Ejercicio consciente del Derecho al Silencio.",
	],
)
def test_canonical_silence_is_silence(text):
	assert is_silence_response(text)


@pytest.mark.parametrize(
	"text",
	[
		f"{REPORT}\nCierro con: {CANONICAL_SILENCE}",  # termina con la frase
		f"Hoy no ejercí el «{CANONICAL_SILENCE}»: arreglé el janitor. {REPORT}",  # la cita
		f"{CANONICAL_SILENCE} {REPORT}",  # empieza con ella pero es un informe largo
		"",
		"Nada que reportar.",
	],
)
def test_report_quoting_the_phrase_is_not_silence(text):
	assert not is_silence_response(text)


def test_long_report_quoting_silence_is_delivered_and_counted(awaken):
	"""Regresión MEDIA: un despertar productivo que cita la frase ya no queda
	counted=0 ni se pierde por el camino a Telegram."""
	run = awaken(response=f"{REPORT}\n{CANONICAL_SILENCE}")
	assert run.ledger["counted"] == 1
	assert len(run.outbox) == 1 and REPORT.strip() in run.outbox[0]


def test_silence_not_counted_nor_delivered(awaken):
	run = awaken(response=CANONICAL_SILENCE)
	assert run.ledger["status"] == "completed" and run.ledger["counted"] == 0
	assert run.outbox == []
	assert run.inbox["status"] == "PROCESSED"


def test_silence_counts_flag_restores_old_accounting(awaken, monkeypatch):
	_set_silence_counts(monkeypatch, True)
	run = awaken(response=CANONICAL_SILENCE)
	assert run.ledger["counted"] == 1, "AWAKENING_SILENCE_COUNTS=True: el silencio consume tope"
	assert run.outbox == [], "aun contando, el silencio no va a Telegram"


def test_eight_silences_do_not_block_next_productive_awakening(awaken):
	for _ in range(MAX_AWAKENINGS_PER_DAY):
		assert awaken(response=CANONICAL_SILENCE).ledger["counted"] == 0
	run = awaken(response=REPORT)
	assert run.bridge.calls == 1, "el tope no debe descartar el despertar productivo"
	assert run.ledger["counted"] == 1 and len(run.outbox) == 1


def test_budget_exhausted_by_productive_awakenings(awaken, events_db):
	_fill_ledger(events_db, MAX_AWAKENINGS_PER_DAY, counted=1)
	run = awaken(response=REPORT)
	assert run.bridge.calls == 0
	assert run.inbox["status"] == "PROCESSED"


def test_error_leaves_counted(awaken):
	"""Un error consumió recursos: cuenta contra el tope (counted=1)."""
	run = awaken(ok=False)
	assert run.ledger["status"] == "error" and run.ledger["counted"] == 1
	assert run.outbox == []


# ── Frontera del día en hora local ───────────────────────────────────────────


@pytest.fixture
def local_tz():
	"""Fija TZ del proceso (SQLite 'localtime' usa la libc) y la restaura."""
	previous = os.environ.get("TZ")

	def _set(name: str) -> None:
		os.environ["TZ"] = name
		time.tzset()

	yield _set
	if previous is None:
		os.environ.pop("TZ", None)
	else:
		os.environ["TZ"] = previous
	time.tzset()


def test_daily_cap_resets_at_local_midnight(awaken, events_db, local_tz):
	"""El tope se reinicia a medianoche LOCAL, no UTC. Se elige una zona en la
	que la fecha local difiere de la UTC ahora mismo y se sitúan 8 despertares
	en el hueco entre ambas medianoches."""
	now_utc = datetime.datetime.now(datetime.timezone.utc)
	today_utc = now_utc.date()
	if now_utc.hour >= 10:
		# UTC+14: ya es "mañana" en local. Las 09:00 UTC de hoy son ayer en local
		# → no cuentan (con fecha UTC sí habrían agotado el tope).
		local_tz("Etc/GMT-14")
		started_at = f"{today_utc} 09:00:00"
		expect_exhausted = False
	else:
		# UTC-12: aún es "ayer" en local. Las 23:00 UTC de ayer son hoy en local
		# → cuentan (con fecha UTC no habrían contado).
		local_tz("Etc/GMT+12")
		started_at = f"{today_utc - datetime.timedelta(days=1)} 23:00:00"
		expect_exhausted = True

	_fill_ledger(events_db, MAX_AWAKENINGS_PER_DAY, counted=1, started_at=started_at)
	run = awaken(response=REPORT)
	assert (run.bridge.calls == 0) is expect_exhausted
