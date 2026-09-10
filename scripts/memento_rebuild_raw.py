#!/usr/bin/env python3
"""
Reconstruye `raw/` de sesiones antigravity sin copia verbatim a partir de su
`memento/index.md` (texto refinado reconstruido desde archive_memories).

Origen (2026-09-10): el pipeline nocturno exportó 98 sesiones antigravity con
`messages=[]` (descifrado fallido) y el store nativo se purgó → no hay verbatim
en ningún lado. Pero 83 de ellas conservan su `index.md` con contenido real
(`reconstructed: true`). Aquí se regenera un `raw/raw.json` con el esquema del
export nativo de antigravity (`{cascade_id, title, step_count, messages}`) para
que `load_raw` del plugin lo acepte, y se marca `raw/meta.json` con
`reconstructed: true` + `reconstructed_from: "index.md"` para que quede claro
que NO es el verbatim original.

El marcado es esencial (decisión del operador, 2026-09-10): el raw reconstruido
NO es fidelidad exacta — es la mejor copia disponible. Nada que ver con el
verbatim nativo.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memento_rebuild_raw")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_BLOCK_RE = re.compile(r"^## (?P<ts>[^\n]+) — (?P<role>[^\n]+)$")


def _parse_index_messages(index_md: Path) -> list[dict]:
    """Extrae los mensajes del index.md: bloques `## <ts> — <role>` + contenido."""
    lines = index_md.read_text(encoding="utf-8").split("\n")
    messages = []
    current = None
    for line in lines:
        m = _BLOCK_RE.match(line)
        if m:
            if current and current["content"].strip():
                messages.append(current)
            current = {
                "role": m.group("role").strip().lower(),
                "content": "",
                "timestamp": m.group("ts").strip(),
            }
        elif current is not None:
            current["content"] += line + "\n"
    if current and current["content"].strip():
        messages.append(current)
    return messages


def _role_to_native(role: str) -> str:
    """Mapea Usuario/Asistente/None → role del export nativo."""
    role = (role or "").strip().lower()
    if role in ("usuario", "user"):
        return "user"
    if role in ("asistente", "assistant"):
        return "assistant"
    # `## ts — None` en el index reconstruido: sin role explícito → user
    return "user"


def rebuild_raw_for(root: Path, registry: dict, source: str = "antigravity") -> tuple[int, int]:
    """Reconstruye raw/ para las sesiones sin copia verbatim. → (hechas, saltadas)."""
    done, skipped = 0, 0
    for session_id, entry in registry.get(source, {}).items():
        dir_rel = entry.get("dir")
        if not dir_rel:
            continue
        session_dir = root / dir_rel
        raw_dir = session_dir / "raw"
        index_md = session_dir / "memento" / "index.md"

        # Ya tiene raw/ con contenido: si es nativo (NO reconstruido) → no tocar.
        # Si es reconstruido (meta marca reconstructed:true) → permitir re-escribir
        # (corrige roles/parsing sin borrar verbatim originales).
        if raw_dir.is_dir() and any(raw_dir.glob("raw.*")):
            meta_path = raw_dir / "meta.json"
            is_rebuilt = meta_path.exists() and json.loads(meta_path.read_text(encoding="utf-8")).get("reconstructed")
            if not is_rebuilt:
                skipped += 1
                continue
        if not index_md.exists():
            logger.warning(f"[{source}] sin index.md para {session_id} — omitida")
            skipped += 1
            continue

        messages = _parse_index_messages(index_md)
        if not messages:
            logger.warning(f"[{source}] {session_id}: index.md sin mensajes parseables — omitida")
            skipped += 1
            continue

        raw_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "cascade_id": session_id,
            "title": "Unknown",
            "step_count": entry.get("step_count", 0),
            "created_time": entry.get("created_at", ""),
            "last_modified_time": entry.get("updated_at", ""),
            "messages": [
                {"role": _role_to_native(m["role"]), "content": m["content"].strip(), "timestamp": m["timestamp"]}
                for m in messages
            ],
        }
        (raw_dir / "raw.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = {
            "session_id": session_id,
            "source": source,
            "conversation_id": session_id,
            "step_count": entry.get("step_count", 0),
            "workspace": entry.get("workspace"),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            # MARCADO (decisión 2026-09-10): NO es verbatim original.
            "reconstructed": True,
            "reconstructed_from": "index.md",
            "note": "raw reconstruido desde memento/index.md (sin copia verbatim disponible); NO fidelidad exacta",
        }
        (raw_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        done += 1
        logger.info(f"[{source}] raw reconstruido para {session_id} ({len(messages)} mensajes)")

    return done, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruye raw/ desde index.md (sesiones sin verbatim).")
    parser.add_argument("--source", default="antigravity", help="Fuente a procesar (default: antigravity)")
    parser.add_argument("--dry-run", action="store_true", help="Solo contar sin escribir")
    args = parser.parse_args()

    from red_pill.memento.registry import MementoRegistry

    root = Path("/home/joan/.local/share/red-pill/memento")
    registry = MementoRegistry()

    done, skipped = 0, 0
    candidates = 0
    for session_id, entry in registry.state["registry"].get(args.source, {}).items():
        dir_rel = entry.get("dir")
        if not dir_rel:
            continue
        session_dir = root / dir_rel
        raw_dir = session_dir / "raw"
        index_md = session_dir / "memento" / "index.md"
        if raw_dir.is_dir() and any(raw_dir.glob("raw.*")):
            continue
        if index_md.exists() and index_md.stat().st_size > 500:
            candidates += 1

    if args.dry_run:
        print(f"Candidatas a reconstruir (sin raw, con index.md >500b): {candidates}")
        return

    done, skipped = rebuild_raw_for(root, registry.state["registry"], args.source)
    logger.info(f"Reconstruidas: {done} | saltadas (ya raw o sin contenido): {skipped}")


if __name__ == "__main__":
    main()
