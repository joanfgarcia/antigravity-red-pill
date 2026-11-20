#!/usr/bin/env python3
"""RFC-OLV-001 · F0 — sonda de producción: ¿miente `recall_count`?

Crea una colección efímera (`olvido_f0_probe`), escribe un recuerdo, lo recupera
por el camino real (`search_and_reinforce`) y comprueba que el contador sube.
La colección se borra siempre, pase lo que pase.

Uso:
.venv/bin/python scripts/olvido_f0_probe.py

Exit codes: 0 = el contador funciona · 1 = miente (la escalera debe quedar apagada).
"""

from __future__ import annotations

import sys

from red_pill.memory import MemoryManager

COLLECTION = "olvido_f0_probe"
TEXT = "sonda F0: el contador de recuperaciones debe subir exactamente una vez"


def main() -> int:
	mm = MemoryManager()
	client = mm.client
	try:
		if client.collection_exists(COLLECTION):
			client.delete_collection(COLLECTION)
		mm._ensure_collection(COLLECTION)
		mm.add_memory(collection=COLLECTION, text=TEXT, metadata={"origin": "f0_probe"}, emotion="neutral", intensity=0.5)

		points = client.scroll(collection_name=COLLECTION, limit=10, with_payload=True)[0]
		if len(points) != 1:
			print(f"F0 FAIL: se esperaba 1 punto, hay {len(points)}")
			return 1
		pid = points[0].id
		before = points[0].payload or {}

		hits = mm.search_and_reinforce(COLLECTION, TEXT, limit=1, caller="f0_probe")
		if not hits:
			print("F0 FAIL: la recuperación no devolvió nada")
			return 1

		after = client.retrieve(collection_name=COLLECTION, ids=[pid], with_payload=True)[0].payload or {}
		delta = int(after.get("recall_count") or 0) - int(before.get("recall_count") or 0)
		print(f"recall_count: {before.get('recall_count')} -> {after.get('recall_count')} (delta={delta})")
		print(f"last_recalled_at: {before.get('last_recalled_at')} -> {after.get('last_recalled_at')}")
		if delta != 1:
			print("F0 FAIL: el contador no se incrementa en una recuperación real ⇒ escalera APAGADA (D-12)")
			return 1
		print("F0 OK: el contador se incrementa exactamente una vez por recuperación")
		return 0
	finally:
		try:
			if client.collection_exists(COLLECTION):
				client.delete_collection(COLLECTION)
		except Exception as e:  # nunca dejar basura en el Búnker
			print(f"aviso: no se pudo borrar {COLLECTION}: {e}", file=sys.stderr)


if __name__ == "__main__":
	sys.exit(main())
