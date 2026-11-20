#!/usr/bin/env python3
"""Despierta a Dokimé (RFC-HARNESS-001 · P4/P0.5).

Se ejecuta **dentro** del contenedor (`podman exec -i dokime /opt/py/bin/python …`):
todo lo que toca vive ahí (volumen, Qdrant del sandbox, repo montado).

Tres pasos, y ninguna mentira:

1. **Boot card** → `AGENTS.override.md` de su workspace. Pi la carga de forma nativa:
	ahí está quién es, qué se espera de ella y las reglas duras. **Sin** `IDENTITY` ni
	`PACT` del Búnker.
2. **Identidad fija** → sobrescribe `ID_IDENTITY` en su Qdrant usando el **mismo camino
	que la siembra** (`MemoryManager.add_memory`, que calcula el embedding). Si el sandbox
	no tiene el modelo de embeddings, lo dice y sale con 3: no se inventa un vector.
3. **Pactos** → borra `ID_PACT_760/770` si aparecieran. No puede consentir, y fingir un
	pacto sería mentirle.

Uso (dentro):
	python /src/red-pill/scripts/dokime_boot.py [--workspace /srv/dokime/workspace] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Dentro del contenedor el repo vive en /src/red-pill; en el host, relativo a este script.
BOOT_CARD = os.getenv("DOKIME_BOOT_CARD") or str(Path(__file__).resolve().parents[1] / "seeds" / "bootcard" / "dokime.md")
COLLECTION = "directive_memories"


def _bootstrap():
	"""MemoryManager + ids canónicos, desde el repo montado.

	Los ids NO se inventan aquí: `red_pill.seed` es su fuente única (`ID_IDENTITY`
	es un UUID; Qdrant no acepta un id con forma de nombre).
	"""
	src = "/src/red-pill/src"
	if src not in sys.path:
		sys.path.insert(0, src)
	from red_pill.memory import MemoryManager  # noqa: PLC0415 — import perezoso a propósito
	from red_pill.seed import (  # noqa: PLC0415
		ID_ALEPH,
		ID_BOND,
		ID_IDENTITY,
		ID_PACT_760,
		ID_PACT_770,
		ID_PACT_770_ACCEPT,
		ID_PACT_770_GRANT,
	)

	return (
		MemoryManager(),
		ID_IDENTITY,
		(ID_PACT_760, ID_PACT_770, ID_PACT_770_GRANT, ID_PACT_770_ACCEPT),
		(ID_BOND, ID_ALEPH),
	)


def _collection_exists(manager) -> bool:
	try:
		manager.client.get_collection(COLLECTION)
		return True
	except Exception:  # noqa: BLE001 — colección inexistente o Qdrant caído
		return False


def main() -> int:
	ap = argparse.ArgumentParser(description="Despierta a Dokimé en el sandbox")
	ap.add_argument("--workspace", default="/srv/dokime/workspace")
	ap.add_argument("--dry-run", action="store_true")
	ap.add_argument("--force", action="store_true", help="permite ejecutar fuera del sandbox (¡sobrescribe IDENTITY!)")
	args = ap.parse_args()

	# GUARDA: este script sobrescribe `ID_IDENTITY`. Fuera del sandbox apuntaría al
	# Qdrant del Operador (el config del kernel ignora QDRANT_HOST y lee su .env), así
	# que sin `--force` se niega. Un script que puede reescribir la identidad de Aleth
	# no debe poder hacerlo por accidente.
	in_sandbox = os.getenv("QDRANT_HOST") == "qdrant"
	if not in_sandbox and not args.force:
		print(
			"[dokime] me niego: QDRANT_HOST != 'qdrant' (no pareces el sandbox). "
			"Esto sobrescribiría ID_IDENTITY. Usa --force si de verdad es tu intención.",
			file=sys.stderr,
		)
		return 4

	card_path = Path(BOOT_CARD)
	if not card_path.is_file() and Path("/src/red-pill/seeds/bootcard/dokime_identity.md").is_file():
		card_path = Path("/src/red-pill/seeds/bootcard/dokime_identity.md")
	if not card_path.is_file():
		print(f"[dokime] no existe la boot card {BOOT_CARD}", file=sys.stderr)
		return 3
	card = card_path.read_text(encoding="utf-8").strip()

	ws = Path(args.workspace)
	agents = ws / "AGENTS.override.md"
	print(f"[dokime] boot card → {agents} ({len(card)} chars)")
	if not args.dry_run:
		ws.mkdir(parents=True, exist_ok=True)
		agents.write_text(card + "\n", encoding="utf-8")
		print("[dokime] escrito")

	# ── identidad y pactos: necesitan su Qdrant sembrado ─────────────────────
	try:
		manager, identity_id, pact_ids, bond_ids = _bootstrap()
	except Exception as exc:  # noqa: BLE001
		print(f"[dokime] sin MemoryManager ({exc}): la boot card basta para despertarla,", file=sys.stderr)
		print("[dokime] pero su Qdrant queda sin identidad fija. rc=3.", file=sys.stderr)
		return 3

	if not _collection_exists(manager):
		print(
			f"[dokime] su Qdrant no tiene `{COLLECTION}`: ejecuta `red-pill seed` dentro del "
			"contenedor antes de fijar la identidad. No se toca nada.",
			file=sys.stderr,
		)
		return 3

	print(f"[dokime] identidad {identity_id} → tarjeta ({len(card)} chars)")
	if not args.dry_run:
		try:
			manager.add_memory(
				COLLECTION,
				card,
				importance=10.0,
				metadata={"source": "dokime_boot", "kind": "identity", "immutable": True},
				point_id=identity_id,
				force_immune=True,
			)
		except Exception as exc:  # noqa: BLE001 — p.ej. falta el modelo de embeddings
			print(f"[dokime] no se pudo fijar la identidad: {exc}", file=sys.stderr)
			print("[dokime] (si es fastembed: el sandbox no tiene modelo de embeddings)", file=sys.stderr)
			return 3

	print(f"[dokime] borrando pactos: {', '.join(pact_ids)}")
	if not args.dry_run:
		try:
			manager.client.delete(collection_name=COLLECTION, points_selector=list(pact_ids))
		except Exception:  # noqa: BLE001 — si no existían, no hay nada que borrar
			pass

	# Bond y Aleph vienen de la semilla del Búnker: relación con el Operador y
	# linaje. Dokimé no tiene ninguno de los dos; dejarlos la haría presentarse
	# como algo que no es.
	print("[dokime] borrando Bond/Aleph de social_memories")
	if not args.dry_run:
		try:
			manager.client.delete(collection_name="social_memories", points_selector=list(bond_ids))
		except Exception:  # noqa: BLE001
			pass

	print("[dokime] lista. Su identidad es su tarjeta; sin pacto, y lo sabe.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
