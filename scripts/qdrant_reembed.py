#!/usr/bin/env python3
"""qdrant_reembed.py — re-embebido de una colección de Qdrant desde su `content`.

Motivación (2026-09-25): al cambiar el modelo de embeddings, los vectores
antiguos pueden no corresponder a ningún campo de texto guardado (coseno bajo
contra `content` re-embebido con el modelo vigente) y quedan prácticamente
inencontrables. Re-embeber desde `content` los deja coherentes con la búsqueda.

Contrato:
- **Dry-run por defecto**: mide cuántos vectores no casan (coseno < umbral) sin
escribir nada. `--apply` escribe.
- **Solo toca lo que no casa**: un punto con coseno >= umbral no se reescribe →
idempotente y convergente (re-ejecutar tras completar = 0 escrituras).
- **Solo el vector**: `update_vectors`; payload, ids y estabilidad intactos.
- **Snapshot antes de la primera escritura** (una vez por barrido; su nombre queda
en el checkpoint). `--no-snapshot` solo para fixtures.
- **Reanudable**: checkpoint JSON (`$RP_CHECKPOINT_FILE` o `--checkpoint`) con el
offset de scroll; cada invocación procesa como mucho `--max-points` y sale 0 →
el `script_job` encadena pasos y `pause` corta limpio entre tramos. Al terminar
escribe `done: true`.
- Puntos sin `content` → se cuentan (`sin_texto`) y no se tocan.
- **Qué se embebe** lo decide `red_pill.memento.embed_text.embedding_text_for`, el
mismo punto único que usa la escritura: los engramas de Memento con
`MEMENTO_EMBED_ENRICHED=true` embeben `tema · reliquias · cuerpo sin muletilla`;
el resto, el `content` tal cual. Así un re-embebido sigue siempre al flag.

Supera a `scripts/reembed_collections.py` (v7.5.0, cambio de modelo del 14-jul),
que re-embebía sin comparar ni snapshot.

Uso:
	uv run python scripts/qdrant_reembed.py --collection <col>                  # dry-run completo
	uv run python scripts/qdrant_reembed.py --collection <col> --max-points 5000 # dry-run de un tramo
	uv run python scripts/qdrant_reembed.py --collection <col> --apply           # escribe
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

_SCROLL_PAGE = 256


def _load_checkpoint(path: Optional[Path]) -> Dict[str, Any]:
	if path is None or not path.exists():
		return {}
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}


def _save_checkpoint(path: Optional[Path], state: Dict[str, Any]) -> None:
	if path is None:
		return
	state["updated_at"] = datetime.now(timezone.utc).isoformat()
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
	tmp.replace(path)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
	na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
	if na == 0.0 or nb == 0.0:
		return 0.0
	return float(a @ b / (na * nb))


def _vector_of(point: Any) -> Optional[List[float]]:
	vec = point.vector
	if isinstance(vec, dict):  # colecciones con vectores con nombre: el primero
		vec = next(iter(vec.values()), None)
	return vec


def reembed_page(points: List[Any], encoder: Any, field: str, threshold: float) -> Dict[str, Any]:
	"""Compara cada vector guardado con el re-embebido de su `field`.

	Devuelve los puntos a reescribir (id + vector nuevo) y los contadores. Puro
	respecto a Qdrant: no escribe nada (lo hace el llamante con `--apply`).
	"""
	from red_pill.memento.embed_text import embedding_text_for

	texts: List[str] = []
	candidates: List[Any] = []
	sin_texto = 0
	for p in points:
		text = str((p.payload or {}).get(field) or "").strip()
		if not text or _vector_of(p) is None:
			sin_texto += 1
			continue
		texts.append(embedding_text_for(text, p.payload))
		candidates.append(p)
	updates: List[Dict[str, Any]] = []
	cosines: List[float] = []
	if texts:
		for p, new in zip(candidates, encoder.embed(texts, batch_size=64)):
			new_arr = np.asarray(new, dtype=float)
			cos = _cosine(np.asarray(_vector_of(p), dtype=float), new_arr)
			cosines.append(cos)
			if cos < threshold:
				updates.append({"id": p.id, "vector": new_arr.tolist()})
	return {"updates": updates, "cosines": cosines, "sin_texto": sin_texto, "scanned": len(points)}


def run(
	client: Any,
	encoder: Any,
	collection: str,
	apply: bool,
	checkpoint: Optional[Path],
	threshold: float = 0.99,
	field: str = "content",
	max_points: int = 0,
	snapshot: bool = True,
) -> Dict[str, Any]:
	"""Un tramo del barrido. Devuelve el estado (el mismo que va al checkpoint)."""
	state = _load_checkpoint(checkpoint) if apply else {}
	if state.get("done") and state.get("collection") == collection:
		print(f"[reembed] {collection}: barrido ya completado ({state.get('updated', 0)} reescritos) — nada que hacer")
		return state
	if not state or state.get("collection") != collection:
		state = {
			"collection": collection,
			"field": field,
			"threshold": threshold,
			"offset": None,
			"scanned": 0,
			"updated": 0,
			"sin_texto": 0,
			"done": False,
		}
	state["total"] = client.count(collection_name=collection, exact=True).count

	if apply and snapshot and not state.get("snapshot"):
		try:
			snap = client.create_snapshot(collection_name=collection)
		except Exception as e:
			raise SystemExit(f"[reembed] no se pudo crear snapshot de {collection}: {e} — abortando (usa --no-snapshot para forzar)")
		state["snapshot"] = snap.name
		print(f"[reembed] snapshot {collection}: {snap.name}")
		_save_checkpoint(checkpoint, state)

	processed = 0
	low = 0
	offset = state.get("offset")
	while True:
		points, next_offset = client.scroll(collection_name=collection, limit=_SCROLL_PAGE, offset=offset, with_vectors=True, with_payload=[field, "node_type", "theme", "relics"])
		if not points:
			next_offset = None
		page = reembed_page(points, encoder, field, threshold)
		if apply and page["updates"]:
			from qdrant_client import models

			client.update_vectors(
				collection_name=collection,
				points=[models.PointVectors(id=u["id"], vector=u["vector"]) for u in page["updates"]],
				wait=True,
			)
		low += len(page["updates"])
		state["scanned"] += page["scanned"]
		state["sin_texto"] += page["sin_texto"]
		state["updated" if apply else "would_update"] = state.get("updated" if apply else "would_update", 0) + len(page["updates"])
		processed += page["scanned"]
		offset = next_offset
		state["offset"] = offset
		state["done"] = offset is None
		_save_checkpoint(checkpoint, state)
		if state["done"] or (max_points and processed >= max_points):
			break

	verb = "reescritos" if apply else "a reescribir (dry-run)"
	print(
		f"[reembed] {collection}: tramo de {processed} puntos · {low} {verb} (coseno < {threshold}) · "
		f"acumulado {state['scanned']}/{state['total']} · sin_texto {state['sin_texto']} · done={state['done']}"
	)
	return state


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--collection", required=True, help="Colección a re-embeber (obligatorio).")
	parser.add_argument("--apply", action="store_true", help="Escribe los vectores nuevos (sin esto: dry-run).")
	parser.add_argument("--threshold", type=float, default=0.99, help="Coseno por debajo del cual se reescribe (default 0.99).")
	parser.add_argument("--field", default="content", help="Campo del payload que se embebe (default: content, como memory.py).")
	parser.add_argument("--max-points", type=int, default=0, help="Máximo de puntos por invocación (0 = todo). Con --apply, el job encadena tramos.")
	parser.add_argument("--checkpoint", type=Path, default=None, help="Checkpoint JSON (default: $RP_CHECKPOINT_FILE).")
	parser.add_argument("--no-snapshot", action="store_true", help="Omite el snapshot previo (no recomendado).")
	args = parser.parse_args()

	collection = args.collection
	element = os.environ.get("RP_ELEMENT")
	if element:
		# element_job (una colección por elemento): checkpoint propio por colección.
		collection = str(json.loads(element).get("collection") or collection)
	checkpoint = args.checkpoint or (Path(os.environ["RP_CHECKPOINT_FILE"]) if os.environ.get("RP_CHECKPOINT_FILE") else None)
	if checkpoint is None and element:
		checkpoint = Path("state") / f"qdrant_reembed_{collection}.json"
	if args.apply and checkpoint is None:
		sys.exit("[reembed] --apply exige checkpoint (--checkpoint o $RP_CHECKPOINT_FILE): el barrido debe ser reanudable")

	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	mm.embeddings.get_vector("warmup")  # inicializa el encoder (carga perezosa)
	run(
		mm.client,
		mm.embeddings.encoder,
		collection,
		apply=args.apply,
		checkpoint=checkpoint,
		threshold=args.threshold,
		field=args.field,
		max_points=args.max_points,
		snapshot=not args.no_snapshot,
	)


if __name__ == "__main__":
	main()
