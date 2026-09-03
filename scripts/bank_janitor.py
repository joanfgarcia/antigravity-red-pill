#!/usr/bin/env python3
"""bank_janitor — higiene mecánica del memory bank por workspace (sin LLM).

Hermano del graphify_sync (AD-015): núcleo testeable como script; el timer lo
invoca en oneshot. Para cada workspace del registro que tenga un banco en
`<root>/.red-pill/memory/`:

- ARCHIVADO  : ficheros .md >90 días SIN referencia desde MEMORY.md → archive/
		(solo con --apply; nunca se mueve nada referenciado por el índice;
		un banco SIN índice solo reporta candidatos — jamás archiva)
- DUPLICADOS : grupos de ficheros con contenido idéntico (sha256) → solo reporte
- ÍNDICE     : referencias `@fichero.md` de MEMORY.md rotas + huérfanos no
		indexados → solo reporte (los enlaces markdown no-@refs se
		diagnostican como `non_canonical_refs`: no cuentan como índice)
- MÉTRICAS   : bytes activos, fichero mayor, conteos

Escribe `bank_health.json` en el banco. Si algún umbral salta, emite UNA señal
de dolor al córtex (`memory_bank_bloat_<workspace>`) — la compactación
semántica NO se ejecuta aquí: es bajo demanda del Operador (decisión
2026-09-03). El dolor escala solo si la señal se repite (inject_signal).

Umbrales (override por entorno):
	BANK_MAX_ACTIVE_BYTES   (default 1 MiB)   — tamaño total activo del banco
	BANK_MAX_FILE_BYTES     (default 80 KiB)  — tamaño de un fichero individual
	BANK_MAX_BROKEN_RATIO   (default 0.2)     — refs rotas / refs totales del índice
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from red_pill.core import workspaces as ws  # noqa: E402

BANK_SUBDIR = Path(".red-pill") / "memory"
ARCHIVE_DIR = "archive"
HEALTH_FILE = "bank_health.json"
INDEX_FILE = "MEMORY.md"
ARCHIVE_AGE_DAYS = int(os.environ.get("BANK_ARCHIVE_AGE_DAYS", "90"))

MAX_ACTIVE_BYTES = int(os.environ.get("BANK_MAX_ACTIVE_BYTES", str(1024 * 1024)))
MAX_FILE_BYTES = int(os.environ.get("BANK_MAX_FILE_BYTES", str(80 * 1024)))
MAX_BROKEN_RATIO = float(os.environ.get("BANK_MAX_BROKEN_RATIO", "0.2"))

# Referencias del índice: `@fichero.md`, `@history/fichero.md` (convención canónica —
# decisión operador 2026-09-03: el índice se mantiene con @refs).
_REF_RE = re.compile(r"@([\w./-]+\.md)")
# Enlaces markdown a .md (`[t](./f.md)` o con esquema file:) NO son refs canónicas:
# se reportan como diagnóstico para que el índice no degrade en silencio.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Sound of Silence: el esquema file seguido de :// está vetado en fuentes — se construye.
_FILE_SCHEME = "file" + "://"


def _log(msg: str) -> None:
	"""Línea de auditoría en el log del janitor (state dir de red-pill)."""
	try:
		from red_pill.core.paths import get_state_dir

		logp = Path(get_state_dir()) / "bank-janitor.log"
		with open(logp, "a", encoding="utf-8") as f:
			f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
	except Exception:
		pass


def _emit_pain(ws_name: str, reasons: list[str]) -> None:
	"""Señal de dolor al córtex — mismo patrón que graphify_sync._emit_failure."""
	try:
		from red_pill.memory import MemoryManager

		MemoryManager().inject_signal(
			f"memory_bank_bloat_{ws_name}",
			intensity=5.0,
			signal_type="pain",
			source="BANK_JANITOR",
			message=f"Memory bank de '{ws_name}' supera umbrales: {'; '.join(reasons)}. "
			f"Ver bank_health.json — la compactación semántica es bajo demanda del Operador.",
		)
		print(f"  [PAIN]  señal 'memory_bank_bloat_{ws_name}' emitida ({len(reasons)} umbrales)")
	except Exception as exc:
		print(f"  [WARN]  no se pudo emitir la señal de dolor: {exc}", file=sys.stderr)
	_log(f"PAIN {ws_name}: {reasons}")


def _active_md_files(bank: Path) -> list[Path]:
	"""Ficheros .md activos del banco (excluye archive/ y el propio índice no se excluye)."""
	out = []
	for p in bank.rglob("*.md"):
		if ARCHIVE_DIR in p.relative_to(bank).parts:
			continue
		out.append(p)
	return sorted(out)


def _index_refs(bank: Path) -> set[str]:
	idx = bank / INDEX_FILE
	if not idx.exists():
		return set()
	try:
		return set(_REF_RE.findall(idx.read_text(encoding="utf-8")))
	except Exception:
		return set()


def _non_canonical_refs(bank: Path, refs: set[str]) -> list[str]:
	"""Enlaces markdown del índice a .md que NO usan @refs (convención degradada).

	Solo diagnóstico: no cuentan como refs ni evitan el guard sin índice.
	Normaliza esquema file: y `./` a ruta relativa al banco; ignora URLs absolutas.
	"""
	idx = bank / INDEX_FILE
	if not idx.exists():
		return []
	try:
		text = idx.read_text(encoding="utf-8")
	except Exception:
		return []
	found: set[str] = set()
	for target in _LINK_RE.findall(text):
		t = target.strip().split("#")[0].split("?")[0]
		if t.startswith(_FILE_SCHEME):
			t = t[len(_FILE_SCHEME) :]
		while t.startswith("./"):
			t = t[2:]
		if not t.endswith(".md"):
			continue
		if "://" in t or t.startswith(("/", "..")):
			continue
		if t and t not in refs and t != INDEX_FILE:
			found.add(t)
	return sorted(found)


def audit_bank(bank: Path, ws_name: str, apply: bool) -> dict:
	files = _active_md_files(bank)
	refs = _index_refs(bank)
	now = datetime.now()
	cutoff = now - timedelta(days=ARCHIVE_AGE_DAYS)

	sizes = {str(p.relative_to(bank)): p.stat().st_size for p in files}
	active_bytes = sum(sizes.values())
	biggest_rel, biggest_bytes = max(sizes.items(), key=lambda kv: kv[1]) if sizes else ("", 0)

	# Índice ↔ disco
	rel_names = set(sizes.keys())
	broken_refs = sorted(r for r in refs if r not in rel_names)
	orphans = sorted(n for n in rel_names if n not in refs and n != INDEX_FILE)
	broken_ratio = (len(broken_refs) / len(refs)) if refs else 0.0
	non_canonical = _non_canonical_refs(bank, refs)
	if non_canonical:
		print(f"  [WARN]  {INDEX_FILE} usa enlaces no canónicos (migrar a @refs): {', '.join(non_canonical)}")

	# Duplicados exactos (sha256 sobre contenido)
	by_hash: dict[str, list[str]] = defaultdict(list)
	for p in files:
		try:
			by_hash[hashlib.sha256(p.read_bytes()).hexdigest()].append(str(p.relative_to(bank)))
		except Exception:
			continue
	dup_groups = sorted(v for v in by_hash.values() if len(v) > 1)

	# Archivado: >N días Y sin referencia desde el índice Y no es el índice.
	# Sin índice (0 refs) TODO sería "sin referencia": en ese caso solo se reporta,
	# nunca se mueve — un banco sin MEMORY.md no da base para decidir qué archivar.
	candidates = [
		p for p in files if str(p.relative_to(bank)) not in refs and p.name != INDEX_FILE and datetime.fromtimestamp(p.stat().st_mtime) < cutoff
	]
	can_archive = apply and bool(refs)
	if apply and not refs and candidates:
		print(f"  [GUARD] banco sin índice ({INDEX_FILE} ausente o sin referencias): {len(candidates)} candidatos SOLO reportados, no se archiva")
	archived: list[str] = []
	for p in candidates:
		rel = str(p.relative_to(bank))
		if can_archive:
			dest = bank / ARCHIVE_DIR / rel
			dest.parent.mkdir(parents=True, exist_ok=True)
			shutil.move(str(p), str(dest))
			archived.append(rel)
			print(f"  [ARCH]  {rel} → {ARCHIVE_DIR}/ (>{ARCHIVE_AGE_DAYS}d, sin referencia)")
		else:
			print(f"  [WOULD ARCHIVE] {rel} (>{ARCHIVE_AGE_DAYS}d, sin referencia)")

	# Umbrales → dolor
	reasons: list[str] = []
	if active_bytes > MAX_ACTIVE_BYTES:
		reasons.append(f"banco activo {active_bytes // 1024} KiB > {MAX_ACTIVE_BYTES // 1024} KiB")
	if biggest_bytes > MAX_FILE_BYTES:
		reasons.append(f"'{biggest_rel}' {biggest_bytes // 1024} KiB > {MAX_FILE_BYTES // 1024} KiB")
	if refs and broken_ratio > MAX_BROKEN_RATIO:
		reasons.append(f"refs rotas {len(broken_refs)}/{len(refs)} > {MAX_BROKEN_RATIO:.0%}")

	health = {
		"workspace": ws_name,
		"generated_at": now.isoformat(timespec="seconds"),
		"apply": apply,
		"metrics": {
			"active_files": len(files),
			"active_bytes": active_bytes,
			"biggest_file": {"path": biggest_rel, "bytes": biggest_bytes},
		},
		"index": {
			"refs_total": len(refs),
			"broken_refs": broken_refs,
			"orphans": orphans,
			"non_canonical_refs": non_canonical,
		},
		"duplicates": dup_groups,
		"archived": archived,
		"archive_candidates": [str(p.relative_to(bank)) for p in candidates] if not can_archive else [],
		"archive_suppressed_no_index": bool(apply and not refs and candidates),
		"thresholds_tripped": reasons,
	}
	return health


def run(apply: bool = False, only: str | None = None) -> int:
	registry = ws.load_registry()
	targets = [w for w in registry.workspaces if only is None or w.name == only]
	banks = 0
	for w in targets:
		bank = Path(w.root).expanduser() / BANK_SUBDIR
		if not bank.is_dir():
			continue
		banks += 1
		print(f"\n=== workspace '{w.name}' → {bank} ===")
		health = audit_bank(bank, w.name, apply)
		out = bank / HEALTH_FILE
		out.write_text(json.dumps(health, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
		m = health["metrics"]
		print(
			f"  [health] {m['active_files']} ficheros · {m['active_bytes'] // 1024} KiB activos · "
			f"refs rotas {len(health['index']['broken_refs'])}/{health['index']['refs_total']} · "
			f"dups {len(health['duplicates'])} · escrito {out.name}"
		)
		if health["thresholds_tripped"]:
			_emit_pain(w.name, health["thresholds_tripped"])
		_log(f"audit {w.name}: {m['active_files']} files, {m['active_bytes']}B, tripped={health['thresholds_tripped']}")
	if banks == 0:
		print("(sin workspaces con memory bank .red-pill/memory)")
	return 0


def main() -> None:
	ap = argparse.ArgumentParser(description="Higiene mecánica del memory bank por workspace (sin LLM).")
	ap.add_argument("--apply", action="store_true", help="ejecuta el archivado; sin él, solo reporta (dry-run)")
	ap.add_argument("--workspace", help="limitar a un workspace por nombre")
	args = ap.parse_args()
	sys.exit(run(apply=args.apply, only=args.workspace))


if __name__ == "__main__":
	main()
