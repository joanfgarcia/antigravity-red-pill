#!/usr/bin/env python3
"""Contabilidad de lo olvidado: qué está en Qdrant, qué sigue en Memento y qué no tiene copia.

Solo lectura. Responde a la pregunta del Operador: «¿qué hemos olvidado sin darnos
cuenta?». Tres capas, de más frágil a más durable:

1. **Qdrant** (memoria viva): 7.500 engramas ascendidos.
2. **Memento** (notas destiladas): miles de `.md` por mes y fuente — es la fuente
   de la re-ascensión.
3. **Raw** (`session_mirror`): los turnos originales.

Una sesión de Memento sin ningún engrama en Qdrant **no está perdida**: está
pendiente de re-ascender. Lo que sí sería pérdida es un raw sin Memento y sin
engrama; eso es lo que este script busca.

Uso:
.venv/bin/python scripts/olvido_audit_losses.py [--json PATH]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import sys
from pathlib import Path

from qdrant_client import QdrantClient

COLLECTIONS = ("work_memories", "social_memories", "story_memories", "interaction_memories")
REGISTRY = Path.home() / ".local/share/red-pill/memento_registry.json"
MEMENTO_DIR = Path.home() / ".local/share/red-pill/memento"


def _client() -> QdrantClient:
	url = os.environ.get("QDRANT_URL")
	key = os.environ.get("QDRANT_API_KEY")
	if not url or not key:
		try:
			from red_pill.config import _cfg

			cfg = _cfg()
			url = url or cfg.QDRANT_URL
			key = key or cfg.QDRANT_API_KEY
		except Exception:
			pass
	return QdrantClient(url=url or "http://localhost:6333", api_key=key or None)


def _scroll(client, collection: str) -> list:
	if not client.collection_exists(collection):
		return []
	out, offset = [], None
	while True:
		batch, offset = client.scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
		out.extend(batch)
		if offset is None:
			return out


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--json", metavar="PATH", help="Volcar el informe en JSON")
	args = ap.parse_args()

	client = _client()
	live_sessions: set[str] = set()
	per_month_live: collections.Counter = collections.Counter()
	for collection in COLLECTIONS:
		for point in _scroll(client, collection):
			payload = point.payload or {}
			sid = str(payload.get("session_id") or "")
			if sid:
				live_sessions.add(sid)
			created = payload.get("created_at")
			if isinstance(created, (int, float)):
				import datetime as dt

				per_month_live[dt.datetime.fromtimestamp(float(created)).strftime("%Y-%m")] += 1

	registry = json.loads(REGISTRY.read_text(encoding="utf-8")).get("registry") or {}
	registered: dict[str, list[tuple[str, str]]] = {}
	for source, items in registry.items():
		for sid, meta in items.items():
			registered.setdefault(source, []).append((sid, str(meta.get("month") or "")))

	report: dict = {"memento": {}, "raw": {}, "months": {}}
	for source, items in sorted(registered.items()):
		total = len(items)
		covered = sum(1 for sid, _ in items if sid in live_sessions)
		report["memento"][source] = {"registered": total, "with_engram": covered, "pending": total - covered}
		for _, month in items:
			report["months"].setdefault(month or "?", {"registered": 0, "with_engram": 0})["registered"] += 1
	# segunda pasada para `with_engram` por mes (evita indexar mal en la tupla)
	for source, items in registered.items():
		for sid, month in items:
			if sid in live_sessions:
				report["months"].setdefault(month or "?", {"registered": 0, "with_engram": 0})["with_engram"] += 1

	# Raw: sesiones vistas en el espejo que no tienen engrama ni memento
	raw_sessions: set[str] = set()
	try:
		from red_pill.core.paths import get_session_db

		with sqlite3.connect(str(get_session_db())) as conn:
			for (originator,) in conn.execute("SELECT DISTINCT originator FROM session_mirror WHERE originator IS NOT NULL"):
				raw_sessions.add(str(originator))
	except Exception as exc:
		report["raw"]["error"] = str(exc)

	memento_ids = {sid for items in registered.values() for sid, _ in items}
	report["raw"]["sessions"] = len(raw_sessions)
	report["raw"]["with_engram"] = len(raw_sessions & live_sessions)
	report["raw"]["no_engram_no_memento"] = sorted(s for s in raw_sessions if s not in live_sessions and s not in memento_ids)[:50]
	report["raw"]["no_engram_no_memento_count"] = sum(1 for s in raw_sessions if s not in live_sessions and s not in memento_ids)

	report["memento_files"] = {
		"md": sum(1 for _ in MEMENTO_DIR.rglob("*.md")) if MEMENTO_DIR.exists() else 0,
		"months": sorted(p.name for p in MEMENTO_DIR.iterdir() if p.is_dir()) if MEMENTO_DIR.exists() else [],
	}
	raw_sources: dict = {}
	try:
		with sqlite3.connect(str(Path.home() / ".local/share/opencode/opencode.db")) as conn:
			raw_sources["opencode_db_sessions"] = conn.execute("SELECT count(*) FROM session").fetchone()[0]
	except Exception as exc:
		raw_sources["opencode_db_sessions"] = f"n/d ({type(exc).__name__})"
	try:
		raw_sources["claude_code_jsonl"] = sum(1 for _ in (Path.home() / ".claude/projects").rglob("*.jsonl"))
	except Exception:
		raw_sources["claude_code_jsonl"] = "n/d"
	report["raw_sources"] = raw_sources
	# Capa 2-bis: Memento NO solo guarda la nota, copia el raw de la conversación.
	mirror = {"files": 0, "mb": 0.0}
	try:
		for f in MEMENTO_DIR.rglob("raw/raw.json"):
			mirror["files"] += 1
			mirror["mb"] += f.stat().st_size / (1024 * 1024)
		mirror["mb"] = round(mirror["mb"], 1)
	except Exception:
		pass
	report["memento_raw_mirror"] = mirror
	report["live_sessions"] = len(live_sessions)
	report["live_by_month"] = dict(sorted(per_month_live.items()))

	print("== CAPA 1 · Qdrant (memoria viva) ==")
	print(f"sesiones representadas: {len(live_sessions)}")
	print(f"engramas por mes: {report['live_by_month']}")
	print("\n== CAPA 2 · Memento (re-ascendible) ==")
	print(f"{'fuente':<20}{'registradas':>12}{'con engrama':>13}{'pendientes':>12}")
	for source, row in report["memento"].items():
		print(f"{source:<20}{row['registered']:>12}{row['with_engram']:>13}{row['pending']:>12}")
	print(f"\nficheros .md en Memento: {report['memento_files']['md']} · meses: {', '.join(report['memento_files']['months'])}")
	mirror = report.get("memento_raw_mirror") or {}
	print(f"raw COPIADO por Memento: {mirror.get('files')} sesiones · {mirror.get('mb')} MB (message_rows + part_rows verbatim)")
	print("\n== CAPA 3 · Espejo de turnos (session_mirror) — NO es el raw ==")
	print("Es solo el espejo de turnos desde 2026-09-08; el raw real vive en cada IDE:")
	print(f"  opencode.db: {report['raw_sources'].get('opencode_db_sessions')} sesiones")
	print(f"  claude_code: {report['raw_sources'].get('claude_code_jsonl')} ficheros .jsonl")
	print(f"sesiones en el espejo: {report['raw'].get('sessions')} · con engrama: {report['raw'].get('with_engram')}")
	print(f"sin engrama NI memento (posible pérdida real): {report['raw'].get('no_engram_no_memento_count')}")

	if args.json:
		Path(args.json).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
		print(f"\ninforme: {args.json}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
