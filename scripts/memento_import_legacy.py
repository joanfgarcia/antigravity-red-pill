#!/usr/bin/env python3
"""memento_import_legacy.py — importa sesiones verbatim de una colección Qdrant legacy al árbol Memento.

Recuperación en upgrades 7.x → 8.x: cuando el store nativo de un IDE/CLI ya no
existe y la única copia verbatim vive en una colección Qdrant que guarda turnos
con `session_id`, `sequence_index`, `role` y `raw_content`/`refined_content`, este
importador reconstruye el render Memento (`index.md`) y una copia `raw/` para que
`migrate_single_writer.py` pueda verificar cobertura.

El nombre de la colección entra por CLI: el código no asume ninguna. La fuente de
sesión se infiere del prefijo del `session_id` (`telegram:<uuid>` → `telegram`) o
se usa `--source` (default `antigravity`, que acuñó ids sin prefijo). Los puntos
`idea_fragment` se ignoran.

uv run python scripts/memento_import_legacy.py --collection <nombre>            # dry-run
uv run python scripts/memento_import_legacy.py --collection <nombre> --apply    # importa
uv run python scripts/memento_import_legacy.py --collection <nombre> --only telegram:<uuid>

Nota: `raw/raw.json` de una sesión importada es un esquema neutral (no el del
plugin de la fuente), así que `memento_migrate.py --from-raw` no la re-renderiza;
para regenerarla, re-ejecuta este importador (idempotente: salta lo ya cubierto).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memento_import_legacy")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FRAGMENT_TYPE = "idea_fragment"


def _infer_source(session_id: str, fallback: str) -> str:
	"""Fuente de la sesión por prefijo del id; fallback si no lleva prefijo."""
	return session_id.split(":", 1)[0] if ":" in session_id else fallback


def _group_sessions(points: List[Any]) -> Dict[str, List[dict]]:
	"""Agrupa payloads por `session_id`, ignorando fragmentos y puntos sin sesión."""
	sessions: Dict[str, List[dict]] = {}
	for p in points:
		payload = getattr(p, "payload", None) or {}
		sid = payload.get("session_id")
		if not sid or payload.get("type") == FRAGMENT_TYPE:
			continue
		sessions.setdefault(str(sid), []).append(payload)
	return sessions


def _messages(payloads: List[dict]) -> List[Dict[str, Any]]:
	"""Turnos ordenados por `sequence_index` → mensajes canónicos (role/content/timestamp)."""
	messages: List[Dict[str, Any]] = []
	for payload in sorted(payloads, key=lambda x: int(x.get("sequence_index") or 0)):
		content = payload.get("raw_content") or payload.get("refined_content") or payload.get("content") or ""
		if not str(content).strip():
			continue
		messages.append({"role": payload.get("role") or "unknown", "content": content, "timestamp": payload.get("created_at")})
	return messages


def import_legacy(collection: str, apply: bool, only: Optional[str] = None, source: str = "antigravity", force: bool = False, max_points: int = 0) -> Dict[str, int]:
	"""Reconstruye el árbol Memento desde una colección Qdrant legacy. Dry-run salvo `apply`."""
	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.coverage import classify_session
	from red_pill.memento.registry import MementoRegistry
	from red_pill.memento.render import render_session, write_session
	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	if not mm.client.collection_exists(collection):
		raise SystemExit(f"[IMPORT] la colección '{collection}' no existe.")
	if not apply:
		logger.info("DRY-RUN (usa --apply para escribir)")

	points, offset = [], None
	while True:
		batch, offset = mm.client.scroll(collection, limit=1000, with_payload=True, with_vectors=False, offset=offset)
		points.extend(batch)
		if offset is None or (max_points and len(points) >= max_points):
			break
	sessions = _group_sessions(points)

	root = get_memento_root()
	reg = MementoRegistry()
	split_max_messages = int(getattr(cfg, "MEMENTO_SPLIT_MAX_MESSAGES", 30))
	split_max_chars = int(getattr(cfg, "MEMENTO_SPLIT_MAX_CHARS", 24000))
	now = datetime.now(timezone.utc).isoformat()
	stats = {"sessions": len(sessions), "imported": 0, "skipped": 0}

	for sid in sorted(sessions):
		if only and sid != only:
			continue
		src = _infer_source(sid, source)
		entry = reg.get(src, sid) or {}
		if not force and entry.get("dir") and classify_session(root, entry["dir"]):
			stats["skipped"] += 1
			continue
		messages = _messages(sessions[sid])
		if not messages:
			stats["skipped"] += 1
			continue
		if not apply:
			stats["imported"] += 1
			continue
		rendered = render_session(
			sid, src, src, messages,
			reconstructed=True, step_count=len(messages),
			split_max_messages=split_max_messages, split_max_chars=split_max_chars,
			month_override=entry.get("month"),
		)
		session_dir = write_session(root, rendered)
		raw_dir = session_dir / "raw"
		raw_dir.mkdir(parents=True, exist_ok=True)
		(raw_dir / "raw.json").write_text(
			json.dumps({"session_id": sid, "source": src, "messages": messages}, ensure_ascii=False, indent=2), encoding="utf-8"
		)
		(raw_dir / "meta.json").write_text(
			json.dumps({"session_id": sid, "source": src, "imported": True, "collection": collection, "imported_at": now}, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
		reg.upsert(src, sid, {
			"dir": rendered.dir_rel, "month": rendered.month, "created_at": rendered.created_at,
			"rendered_at": now, "message_count": rendered.message_count, "step_count": len(messages),
			"body_chars": rendered.body_chars, "has_splits": rendered.has_splits,
			"memento_hash": rendered.memento_hash, "reconstructed": True,
		})
		stats["imported"] += 1

	if apply:
		reg.save()
	return stats


def main() -> int:
	ap = argparse.ArgumentParser(description="Importa sesiones verbatim de una colección Qdrant legacy al árbol Memento (migración 7.x→8.x).")
	ap.add_argument("--collection", required=True, help="Colección Qdrant legacy con turnos verbatim (obligatorio).")
	ap.add_argument("--apply", action="store_true", help="Escribe el render + raw/ (por defecto: dry-run).")
	ap.add_argument("--only", default=None, help="Solo un session_id concreto.")
	ap.add_argument("--source", default="antigravity", help="Fuente para ids sin prefijo (default: antigravity).")
	ap.add_argument("--force", action="store_true", help="Re-importar aunque la sesión ya esté cubierta.")
	ap.add_argument("--max-points", type=int, default=0, help="Máximo de puntos a leer (0 = todos).")
	args = ap.parse_args()

	stats = import_legacy(args.collection, args.apply, only=args.only, source=args.source, force=args.force, max_points=args.max_points)
	verb = "importadas" if args.apply else "a importar"
	print(f"[IMPORT] colección '{args.collection}': {stats['sessions']} sesión(es), {stats['imported']} {verb}, {stats['skipped']} ya cubiertas.")
	if not args.apply:
		print("[IMPORT] DRY-RUN — usa --apply para escribir el árbol Memento.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
