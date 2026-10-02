"""Recall híbrido sobre Memento + diversidad MMR (feedback de recall 2026-09-25).

El recall semántico falla cuando la nota perdió la entidad que la ancla (la nota
de una revisión contractual no nombra a la empresa), pero el árbol Memento conserva el texto
literal de la sesión, donde la entidad sí está. Este módulo recupera engramas por
**palabras clave sobre el árbol** y los devuelve como ids de Qdrant, para fusionar
con el ranking semántico (RRF). Y ofrece **MMR** para que tres paráfrasis del mismo
hecho no ocupen el top-k.

Mapeo determinista, sin índice nuevo: `rg -c` sobre `*/*/*/memento/index.md` da
qué sesiones contienen cada término; `rg -n` en esas sesiones da las líneas; cada
nota ascendida del árbol (`annotate/` y, como fallback, `refine/`) declara su rango
`source_lines` (`memento/index.md#lA-B`) y su `ascended_point_id`/`ascended_to` →
línea ∈ rango ⇒ ese punto. Sin LLM.

Gobernado por `MEMORY_HYBRID_RECALL_ENABLED` y `MEMORY_RECALL_MMR_ENABLED` (RULE 4).
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_INDEX_GLOB = "*/*/*/memento/index.md"
_RANGE_RE = re.compile(r"#l(\d+)-(\d+)")
_TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ][0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_\-\.]{2,}")
_STOP = set(
	"""
	el la los las un una unos unas de del al a en por para con sin sobre entre hasta desde que qué quien quién como cómo
	cuando cuándo donde dónde porque pero sino y o ni se me te le les nos lo su sus mi mis tu tus es son era eran fue
	fueron ser estar está están estaba hay había hacer hace hizo hecho muy más menos ya aún también tan tanto todo toda
	todos todas otro otra otros otras este esta estos estas ese esa esos esas aquel aquella algo nada cada mismo misma
	cuál cuáles dijo dice explicó pidió joan aleth
	the and for with that this from into over what when where which while about have has had was were are is been
	""".split()
)


# ── Términos ────────────────────────────────────────────────────────────────


def salient_terms(query: str, max_terms: int = 4) -> List[str]:
	"""Términos distintivos de la consulta: identificadores y nombres propios primero.

	Prioridad: con dígito o `-_.` (BIT-003, tree_hash, v7.22.0) > con mayúscula
	(Initech) > longitud. Sin stopwords ni palabras de < 4 letras.
	"""
	seen: Dict[str, str] = {}
	for raw in _TOKEN_RE.findall(query or ""):
		tok = raw.strip(".-_")
		if len(tok) < 4 or tok.lower() in _STOP:
			continue
		seen.setdefault(tok.lower(), tok)

	def rank(tok: str) -> Tuple[int, int, int]:
		ident = int(any(c.isdigit() for c in tok) or any(c in "-_." for c in tok))
		proper = int(tok[:1].isupper())
		return (ident, proper, len(tok))

	return sorted(seen.values(), key=rank, reverse=True)[:max_terms]


# ── Búsqueda en el árbol ────────────────────────────────────────────────────


def _rg() -> Optional[str]:
	return shutil.which("rg")


def _session_counts(root: Path, term: str) -> Dict[str, int]:
	"""{dir_rel_de_sesión: nº de líneas con el término} vía `rg -c` (salida compacta)."""
	rg = _rg()
	counts: Dict[str, int] = {}
	if rg is None:
		for index in root.glob(_INDEX_GLOB):
			try:
				n = sum(1 for line in index.read_text(encoding="utf-8", errors="ignore").split("\n") if term.lower() in line.lower())
			except OSError:
				continue
			if n:
				counts[str(index.parent.parent.relative_to(root))] = n
		return counts
	try:
		# cwd=root: rg evalúa `-g` relativo al directorio de trabajo, no a la ruta buscada.
		proc = subprocess.run([rg, "-c", "-i", "-F", "-g", _INDEX_GLOB, "--", term, "."], capture_output=True, text=True, timeout=20, cwd=str(root))
	except Exception as e:
		logger.warning(f"[HYBRID] rg -c falló para {term!r}: {e}")
		return counts
	for line in proc.stdout.splitlines():
		path, _, count = line.rpartition(":")
		if not count.isdigit():
			continue
		counts[str(Path(path).parent.parent)] = int(count)
	return counts


def _term_lines(root: Path, session_dir: str, term: str, max_lines: int = 40) -> List[int]:
	index = root / session_dir / "memento" / "index.md"
	rg = _rg()
	if rg is None:
		try:
			return [
				i for i, line in enumerate(index.read_text(encoding="utf-8", errors="ignore").split("\n"), start=1) if term.lower() in line.lower()
			][:max_lines]
		except OSError:
			return []
	try:
		proc = subprocess.run([rg, "-n", "-i", "-F", "-m", str(max_lines), "--", term, str(index)], capture_output=True, text=True, timeout=10)
	except Exception:
		return []
	out = []
	for line in proc.stdout.splitlines():
		num, _, _ = line.partition(":")
		if num.isdigit():
			out.append(int(num))
	return out


def _frontmatter(path: Path) -> Dict[str, str]:
	fm: Dict[str, str] = {}
	try:
		with open(path, encoding="utf-8", errors="ignore") as f:
			for i, line in enumerate(f):
				if i == 0 and line.strip() == "---":
					continue
				if line.strip() == "---" or i > 40:
					break
				key, sep, value = line.partition(":")
				if sep:
					fm[key.strip()] = value.strip().strip('"')
	except OSError:
		pass
	return fm


def session_notes(root: Path, session_dir: str) -> List[Dict[str, Any]]:
	"""Notas ascendidas de la sesión: [{lo, hi, point_id, collection}].

	`annotate/` manda; `refine/` solo si la sesión no tiene notas de annotate
	(misma política que la ascensión: refine = fallback de sesiones sin notas).
	"""
	notes: List[Dict[str, Any]] = []
	for stage in ("annotate", "refine"):
		for path in sorted((root / session_dir / stage).glob("[0-9][0-9][0-9]-*.md")):
			fm = _frontmatter(path)
			if fm.get("ascended") != "true" or not fm.get("ascended_point_id"):
				continue
			m = _RANGE_RE.search(fm.get("source_lines", ""))
			if not m:
				continue
			notes.append({"lo": int(m.group(1)), "hi": int(m.group(2)), "point_id": fm["ascended_point_id"], "collection": fm.get("ascended_to", "")})
		if notes:
			break
	return notes


def memento_keyword_hits(
	query: str,
	collection: str,
	root: Optional[Path] = None,
	max_sessions: int = 12,
	limit: int = 20,
) -> List[Tuple[str, float]]:
	"""Engramas de `collection` recuperados por palabras clave en el árbol → [(point_id, score)].

	Score = Σ términos (líneas del término dentro del rango de la nota × idf).
	El idf castiga los términos que aparecen en muchas sesiones.
	"""
	if root is None:
		from red_pill.memento import get_memento_root

		root = Path(get_memento_root())
	terms = salient_terms(query)
	if not terms:
		return []
	n_sessions = max(1, sum(1 for _ in root.glob(_INDEX_GLOB)))
	per_term = {t: _session_counts(root, t) for t in terms}
	idf = {t: math.log(1 + n_sessions / (1 + len(c))) for t, c in per_term.items()}
	session_score: Dict[str, float] = {}
	for t, counts in per_term.items():
		for sess, n in counts.items():
			session_score[sess] = session_score.get(sess, 0.0) + idf[t] * (1 + math.log(n))
	top = sorted(session_score, key=session_score.get, reverse=True)[:max_sessions]  # type: ignore[arg-type]

	scores: Dict[str, float] = {}
	for sess in top:
		notes = [n for n in session_notes(root, sess) if not collection or n["collection"] == collection]
		if not notes:
			continue
		for t in terms:
			if sess not in per_term[t]:
				continue
			for line in _term_lines(root, sess, t):
				for note in notes:
					if note["lo"] <= line <= note["hi"]:
						scores[note["point_id"]] = scores.get(note["point_id"], 0.0) + idf[t]
	return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]


# ── Fusión y diversidad ─────────────────────────────────────────────────────


def rrf_scores(rankings: Iterable[Sequence[str]], k: int = 60) -> List[Tuple[str, float]]:
	"""Reciprocal Rank Fusion: Σ 1/(k + rango) → [(id, score)] de mayor a menor.

	Estable ante escalas de score distintas (coseno vs. conteo de términos).
	Empates: gana el primero visto (la lista semántica va primero).
	"""
	score: Dict[str, float] = {}
	first_seen: Dict[str, int] = {}
	order = 0
	for ranking in rankings:
		for rank, pid in enumerate(ranking, start=1):
			score[pid] = score.get(pid, 0.0) + 1.0 / (k + rank)
			if pid not in first_seen:
				first_seen[pid] = order
				order += 1
	return sorted(score.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))


def rrf_merge(rankings: Iterable[Sequence[str]], k: int = 60) -> List[str]:
	"""Ids fusionados por RRF, de más a menos relevante."""
	return [pid for pid, _ in rrf_scores(rankings, k)]


def _unit(v: Any) -> np.ndarray:
	arr = np.asarray(v, dtype=float)
	n = float(np.linalg.norm(arr))
	return arr / n if n else arr


def mmr_select(
	query_vec: Any,
	items: Sequence[Any],
	vectors: Sequence[Any],
	k: int,
	lam: float = 0.7,
	relevance: Optional[Sequence[float]] = None,
) -> List[Any]:
	"""Maximal Marginal Relevance: relevancia − redundancia (coseno entre candidatos).

	`relevance` (opcional) sustituye al coseno con la consulta y se normaliza a
	[0, 1]. Medido 2026-09-25: con el coseno como relevancia, los candidatos que
	aporta la palabra clave (vector malo por definición: por eso no los encontró
	el semántico) nunca ganan, y con relevancias apretadas (0,50-0,52) la
	diversidad desordena el top. Con la puntuación fusionada (RRF, por rango), el
	orden fusionado manda y la redundancia solo desempata paráfrasis.
	`items[i]` va con `vectors[i]`; sin vector = no redundante.
	"""
	if k <= 0 or not items:
		return []
	q = _unit(query_vec)
	units = [(_unit(v) if v is not None else None) for v in vectors]
	if relevance is not None:
		top = max(relevance) or 1.0
		rel = [float(r) / top for r in relevance]
	else:
		rel = [float(u @ q) if u is not None else 0.0 for u in units]
	selected: List[int] = []
	remaining = list(range(len(items)))
	while remaining and len(selected) < k:
		best, best_score = None, -math.inf
		for i in remaining:
			redundancy = 0.0
			ui = units[i]
			if ui is not None:
				sims = [float(ui @ uj) for uj in (units[j] for j in selected) if uj is not None]
				redundancy = max(sims) if sims else 0.0
			score = lam * rel[i] - (1 - lam) * redundancy
			if score > best_score:
				best, best_score = i, score
		assert best is not None
		selected.append(best)
		remaining.remove(best)
	return [items[i] for i in selected]
