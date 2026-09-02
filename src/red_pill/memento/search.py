"""Búsqueda full-text sobre el árbol Memento (RFC-002 §4.7, Fase 2).

`rg` cuando está disponible (rápido, respeta los globs canónicos), fallback
puro-Python si no. El objetivo canónico es `memento/index.md`; `distill/` y
`refine/` son scopes secundarios de recall estructurado. `raw/` queda SIEMPRE
fuera (sin scrub, no es objetivo de búsqueda).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCOPE_GLOBS = {
	"memento": ["memento/index.md"],
	"distill": ["distill/*.md"],
	"refine": ["refine/*.md"],
	"all": ["memento/index.md", "distill/*.md", "refine/*.md"],
}


def _session_meta(index_dir: Path) -> Dict[str, str]:
	"""session_id/source/workspace desde el frontmatter del index.md de la sesión (lectura corta)."""
	meta: Dict[str, str] = {}
	index_file = index_dir / "memento" / "index.md"
	if not index_file.exists():
		return meta
	try:
		with open(index_file, encoding="utf-8") as f:
			for i, line in enumerate(f):
				if i > 16 or (i > 0 and line.strip() == "---"):
					break
				if ":" in line:
					key, _, value = line.partition(":")
					if key.strip() in ("session_id", "source", "workspace"):
						meta[key.strip()] = value.strip().strip('"')
	except Exception:
		pass
	return meta


def _rg_search(root: Path, query: str, globs: List[str], prefix: str, limit: int) -> Optional[List[Dict[str, Any]]]:
	rg = shutil.which("rg")
	if rg is None:
		return None
	cmd = [rg, "-n", "-i", "--no-heading", "--max-count", "3", "-m", str(limit)]
	for glob in globs:
		cmd += ["-g", f"{prefix}{glob}"]
	cmd += ["-e", query, str(root)]
	try:
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
	except Exception as e:
		logger.warning(f"rg search failed, falling back to python scan: {e}")
		return None
	if proc.returncode not in (0, 1):  # 1 = sin matches
		logger.warning(f"rg exited {proc.returncode}: {proc.stderr[:200]}")
		return None
	hits = []
	for raw_line in proc.stdout.splitlines():
		path_str, _, rest = raw_line.partition(":")
		line_no, _, snippet = rest.partition(":")
		if path_str and line_no.isdigit():
			hits.append({"file": Path(path_str), "line": int(line_no), "snippet": snippet.strip()})
	return hits


def _python_search(root: Path, query: str, globs: List[str], prefix: str, limit: int) -> List[Dict[str, Any]]:
	pattern = re.compile(re.escape(query), re.IGNORECASE)
	hits: List[Dict[str, Any]] = []
	for glob in globs:
		for file in sorted(root.glob(f"{prefix}{glob}")):
			try:
				for line_no, line in enumerate(file.read_text(encoding="utf-8").split("\n"), start=1):
					if pattern.search(line):
						hits.append({"file": file, "line": line_no, "snippet": line.strip()})
						break  # un hit por fichero en el fallback: barato y suficiente
			except Exception:
				continue
			if len(hits) >= limit:
				return hits
	return hits


def search_memento(
	query: str,
	*,
	source: Optional[str] = None,
	month: Optional[str] = None,
	workspace: Optional[str] = None,
	scope: str = "memento",
	limit: int = 20,
	root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
	"""→ [{path, line, snippet, session_id, source, month}] — path relativo a la raíz Memento."""
	if root is None:
		from red_pill.memento import get_memento_root

		root = get_memento_root()
	globs = _SCOPE_GLOBS.get(scope, _SCOPE_GLOBS["memento"])
	prefix = f"{month or '*'}/{source or '*'}/*/"

	hits = _rg_search(root, query, globs, prefix, max(limit * 3, limit))
	if not hits:
		# rg vacío (rc=1, p.ej. glob sin coincidencia con la estructura del árbol,
		# como en ripgrep 15 donde `*` no cruza separadores) o no disponible →
		# siempre intentar el escaneo python como respaldo.
		hits = _python_search(root, query, globs, prefix, max(limit * 3, limit))

	results: List[Dict[str, Any]] = []
	for hit in hits:
		rel = hit["file"].relative_to(root)
		session_dir = root / rel.parts[0] / rel.parts[1] / rel.parts[2]
		meta = _session_meta(session_dir)
		if workspace and meta.get("workspace") != workspace:
			continue
		results.append(
			{
				"path": str(rel),
				"line": hit["line"],
				"snippet": hit["snippet"][:300],
				"session_id": meta.get("session_id", rel.parts[2]),
				"source": meta.get("source", rel.parts[1]),
				"month": rel.parts[0],
			}
		)
		if len(results) >= limit:
			break
	return results
