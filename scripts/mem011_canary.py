#!/usr/bin/env python3
"""MEM-011 · canario de partes por polaroid — UN elemento = UNA sesión.

El job lo lanza el driver `element_job` con el elemento en `RP_ELEMENT` (JSON) y
su índice en `RP_ELEMENT_INDEX`. Este proceso:

1. Enciende `SW_HUB_POLAROID_ENABLED` **solo para sí mismo** (variable de entorno
	antes de importar red-pill). El resto del sistema sigue con el flag OFF: el
	canario no cambia la configuración viva.
2. Re-sintetiza la sesión con el camino real (`resynthesize_session`, force=True):
	escribe las partes y después la raíz, con el mismo código que usará el
	apagado nocturno.
3. Cuenta las partes escritas de esa sesión y devuelve veredicto.

Salida: 0 si escribió; 75 (skip_exit_code del recipe) si `failed` — el driver lo
marca saltado y sigue con el resto (elementos independientes).
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
	# ANTES de importar red-pill: el singleton de config se crea al importar.
	os.environ["SW_HUB_POLAROID_ENABLED"] = "true"

	raw = os.environ.get("RP_ELEMENT") or "{}"
	try:
		element = json.loads(raw)
	except ValueError:
		print(f"[canary] RP_ELEMENT no es JSON: {raw!r}", file=sys.stderr)
		return 2
	session = str(element.get("session") or "").strip()
	collection = str(element.get("collection") or "work_memories").strip()
	index = os.environ.get("RP_ELEMENT_INDEX", "?")
	if not session:
		print("[canary] elemento sin `session`", file=sys.stderr)
		return 2

	from red_pill.config import get_config_cached
	from red_pill.memory import MemoryManager
	from red_pill.metabolism.hub_synthesis import resynthesize_session

	cfg = get_config_cached()
	# `--reuse`: no re-sintetiza una parte cuyo input no ha cambiado (hash); sirve
	# para retomar un elemento a medias sin pagar otra vez lo ya escrito.
	force = "--reuse" not in sys.argv
	print(f"[canary] idx={index} collection={collection} session={session} flag={cfg.SW_HUB_POLAROID_ENABLED} reuse={not force}")

	manager = MemoryManager()
	verdict = resynthesize_session(manager, collection, session, force=force)
	print(f"[canary] veredicto: {verdict}")

	from qdrant_client import models as qm

	parts, _ = manager.client.scroll(
		collection_name=collection,
		scroll_filter=qm.Filter(
			must=[
				qm.FieldCondition(key="session_id", match=qm.MatchValue(value=session)),
				qm.FieldCondition(key="hub_role", match=qm.MatchValue(value="part")),
			]
		),
		limit=1000,
		with_payload=False,
		with_vectors=False,
	)
	print(f"[canary] partes en Qdrant para la sesión: {len(parts)}")
	if verdict == "failed":
		return 75
	return 0


if __name__ == "__main__":
	sys.exit(main())
