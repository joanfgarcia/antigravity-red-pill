"""Pase agéntico Memento: Distill → Refine sobre ficheros (RFC-002 §4.5, Fase 3.5).

Reescritura file-based de los chronicle_distill/refine de Qdrant: entrada
`memento/index.md`, unidades de trabajo = los splits mecánicos (ya dimensionados
a la ventana del modelo local, Q8), salida `distill/NNN-*.md` y `refine/NNN-*.md`
con los esquemas del RFC. Prompts v1 — las técnicas por-hardware se afinarán
según diseño §4.5. El gate de curación corre EN SOMBRA (§4.6): la decisión
would-ingest se calcula, se sella `significance` en el frontmatter (in-place,
sin mover line refs) y se cuenta en el registry — nada cambia en Qdrant.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from red_pill.memento.render import compute_hash, extract_body, update_frontmatter_fields

logger = logging.getLogger(__name__)

EDGE_ENGINE_URL = "http://localhost:8760/v1/chat/completions"
EDGE_MODEL = "samantha-mistral-instruct-7b.i1-Q4_K_M.gguf"

# transport(system, user, max_tokens) -> str — inyectable para tests y para futuros bake-offs
Transport = Callable[[str, str, int], str]

_TITLE_SLUG_RE = re.compile(r"[^a-z0-9]+")

DISTILL_SYSTEM = (
	"You are Samantha, the Bünker Scribe. You produce structured, high-density JSON distillations of agentic coding dialogue. Output ONLY valid JSON."
)
DISTILL_USER = """Distill this conversation chunk into a navigable section.

Rules:
- "title": specific, ≤80 chars, Spanish.
- "summary": ≤10 lines, Spanish — core technical decisions, insights, emotional load. Drop tool noise and filler.
- "keywords": 3-8 lowercase terms.
- Output ONLY the JSON object: {{"title": "...", "summary": "...", "keywords": ["..."]}}

Chunk:
{content}
"""

REFINE_SYSTEM = (
	"You are Samantha, the Bünker Curator. You judge which distilled sections carry durable value for long-term memory. Output ONLY valid JSON."
)
REFINE_USER = """Judge this distilled section for long-term memory.

Rules:
- "significance": 0.0-1.0 (durable value: decisions, insights, milestones high; routine plumbing low).
- "emotion": one color of [gray, blue, cyan, green, yellow, orange, red, purple].
- "intensity": 0.0-1.0.
- "theme": short snake_case topic.
- "relics": 0-4 memorable literal phrases from the section.
- "cross_refs": subset of these candidate session ids that this section genuinely relates to: {candidates}
- Output ONLY the JSON object: {{"significance": 0.0, "emotion": "gray", "intensity": 0.0, "theme": "...", "relics": [], "cross_refs": []}}

Section (title: {title}):
{summary}
"""


def slugify_title(title: str, max_len: int = 40) -> str:
	slug = _TITLE_SLUG_RE.sub("-", title.lower()).strip("-")[:max_len].strip("-")
	return slug or "seccion"


def llm_available(url: str = EDGE_ENGINE_URL) -> bool:
	import urllib.request

	try:
		urllib.request.urlopen(url.rsplit("/", 2)[0], timeout=3)
		return True
	except Exception:
		return False


def http_transport(system: str, user: str, max_tokens: int) -> str:
	import requests

	payload = {
		"model": EDGE_MODEL,
		"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
		"temperature": 0.1,
		"max_tokens": max_tokens,
	}
	response = requests.post(EDGE_ENGINE_URL, json=payload, timeout=120)
	response.raise_for_status()
	return str(response.json()["choices"][0]["message"]["content"]).strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
	start = text.find("{")
	if start < 0:
		return None
	depth = 0
	for i in range(start, len(text)):
		if text[i] == "{":
			depth += 1
		elif text[i] == "}":
			depth -= 1
			if depth == 0:
				try:
					parsed = json.loads(text[start : i + 1])
					return parsed if isinstance(parsed, dict) else None
				except Exception:
					return None
	return None


def _work_units(session_dir: Path) -> List[Tuple[str, str, str]]:
	"""[(NNN, source_lines_ref, content)] — los splits si existen; si no, el index entero."""
	memento_dir = session_dir / "memento"
	splits = sorted(memento_dir.glob("[0-9][0-9][0-9]-*.md"))
	units = []
	for i, split in enumerate(splits, start=1):
		text = split.read_text(encoding="utf-8")
		first_line, _, rest = text.partition("\n")
		ref = first_line.replace("> [!ref] ", "").strip() if first_line.startswith("> [!ref]") else "memento/index.md"
		units.append((f"{i:03d}", ref, rest.strip()))
	if units:
		return units
	index_text = (memento_dir / "index.md").read_text(encoding="utf-8")
	total_lines = index_text.count("\n") + 1
	return [("001", f"memento/index.md#l1-{total_lines}", extract_body(index_text).strip())]


def _frontmatter_block(fields: List[Tuple[str, Any]]) -> str:
	def value_of(v: Any) -> str:
		if isinstance(v, (list, dict)):
			return json.dumps(v, ensure_ascii=False)
		if isinstance(v, float):
			return f"{v:.2f}"
		return json.dumps(v, ensure_ascii=False) if isinstance(v, str) and ": " in v else str(v)

	return "\n".join(["---"] + [f"{k}: {value_of(v)}" for k, v in fields] + ["---"])


def distill_session(root: Path, dir_rel: str, session_id: str, source: str, transport: Transport) -> List[Dict[str, Any]]:
	"""Escribe distill/NNN-<slug>.md por unidad de trabajo. → metadatos de las secciones."""
	session_dir = root / dir_rel
	distill_dir = session_dir / "distill"
	distill_dir.mkdir(parents=True, exist_ok=True)
	for stale in distill_dir.glob("*.md"):
		stale.unlink()  # regeneración completa, jamás parcheo (§4.5.1)

	sections = []
	for nnn, ref, content in _work_units(session_dir):
		raw = transport(DISTILL_SYSTEM, DISTILL_USER.format(content=content), 512)
		parsed = _extract_json(raw) or {}
		title = str(parsed.get("title") or f"Sección {nnn}")[:80]
		summary = str(parsed.get("summary") or content[:400]).strip()
		keywords = [str(k) for k in parsed.get("keywords", [])][:8]
		slug = slugify_title(title)
		filename = f"{nnn}-{slug}.md"
		frontmatter = _frontmatter_block(
			[
				("session_id", session_id),
				("source", source),
				("section", int(nnn)),
				("title", title),
				("keywords", keywords),
				("source_lines", ref),
				("source_ref", "memento/index.md"),
			]
		)
		(distill_dir / filename).write_text(f"{frontmatter}\n\n{summary}\n", encoding="utf-8")
		sections.append({"nnn": nnn, "file": filename, "title": title, "summary": summary, "source_lines": ref})
	return sections


def cross_ref_candidates(registry: Any, source: str, session_id: str, limit: int = 12) -> List[str]:
	"""Candidatos mecánicos (§4.5): sesiones de cualquier fuente con solape temporal o mismo workspace."""
	own = registry.get(source, session_id) or {}
	own_day = (own.get("created_at") or "")[:10]
	own_workspace = own.get("workspace")
	candidates = []
	for other_source, sessions in registry.state["registry"].items():
		for other_id, entry in sessions.items():
			if other_id == session_id or not entry.get("dir"):
				continue
			same_day = own_day and (entry.get("created_at") or "")[:10] == own_day
			same_workspace = own_workspace and entry.get("workspace") == own_workspace
			if same_day or same_workspace:
				candidates.append(other_id)
	return sorted(candidates)[:limit]


def refine_session(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	sections: List[Dict[str, Any]],
	candidates: List[str],
	transport: Transport,
	min_significance: float,
) -> float:
	"""Escribe refine/NNN-<slug>.md para las secciones con valor durable. → significance máxima."""
	refine_dir = root / dir_rel / "refine"
	refine_dir.mkdir(parents=True, exist_ok=True)
	for stale in refine_dir.glob("*.md"):
		stale.unlink()

	max_significance = 0.0
	for section in sections:
		raw = transport(REFINE_SYSTEM, REFINE_USER.format(candidates=json.dumps(candidates), title=section["title"], summary=section["summary"]), 384)
		parsed = _extract_json(raw) or {}
		try:
			significance = max(0.0, min(1.0, float(parsed.get("significance", 0.0))))
		except (TypeError, ValueError):
			significance = 0.0
		max_significance = max(max_significance, significance)
		if significance < min_significance:
			continue
		cross_refs = [c for c in parsed.get("cross_refs", []) if c in candidates]
		frontmatter = _frontmatter_block(
			[
				("session_id", session_id),
				("source", source),
				("distill_ref", f"distill/{section['file']}"),
				("source_lines", section["source_lines"]),
				("significance", significance),
				("emotion", str(parsed.get("emotion", "gray"))),
				("intensity", float(parsed.get("intensity", 0.0) or 0.0)),
				("texture", {"theme": str(parsed.get("theme", "")), "relics": [str(r) for r in parsed.get("relics", [])][:4]}),
				("cross_refs", cross_refs),
			]
		)
		(refine_dir / section["file"]).write_text(f"{frontmatter}\n\n{section['summary']}\n", encoding="utf-8")
	return max_significance


def pending_agentic(registry: Any) -> List[Tuple[str, str, str]]:
	"""[(source, session_id, reason)] — sesiones renderizadas sin pase agéntico o con distill stale (§4.5.1)."""
	pending = []
	for source, sessions in registry.state["registry"].items():
		for session_id, entry in sessions.items():
			if not entry.get("dir"):
				continue
			agentic = entry.get("agentic")
			if not agentic:
				pending.append((source, session_id, "missing"))
			elif agentic.get("hash") != entry.get("memento_hash"):
				pending.append((source, session_id, "stale"))
	return pending


def run_agentic(root: Path, registry: Any, targets: List[Tuple[str, str]], transport: Transport) -> Dict[str, int]:
	"""Distill → Refine → sello de significance + decisión shadow del gate, por sesión."""
	from datetime import datetime, timezone

	import red_pill.config as cfg

	min_significance = float(getattr(cfg, "MEMENTO_REFINE_MIN_SIGNIFICANCE", 0.3))
	gate_threshold = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE", 0.5))
	stats = {"processed": 0, "failed": 0, "would_ingest": 0}

	for source, session_id in targets:
		entry = registry.get(source, session_id)
		if not entry or not entry.get("dir"):
			continue
		try:
			sections = distill_session(root, entry["dir"], session_id, source, transport)
			candidates = cross_ref_candidates(registry, source, session_id)
			max_significance = refine_session(root, entry["dir"], session_id, source, sections, candidates, transport, min_significance)
		except Exception as e:
			logger.warning(f"Agentic pass failed for {session_id}: {e}")
			stats["failed"] += 1
			continue

		would_ingest = max_significance >= gate_threshold
		index_file = root / entry["dir"] / "memento" / "index.md"
		if index_file.exists():
			update_frontmatter_fields(index_file, {"significance": round(max_significance, 2)})
			# invariante §4.5.1: el sello NO puede mover el cuerpo
			assert compute_hash(extract_body(index_file.read_text(encoding="utf-8"))) == entry.get("memento_hash"), (
				"significance stamp moved the body"
			)
		entry["agentic"] = {
			"distilled_at": datetime.now(timezone.utc).isoformat(),
			"hash": entry.get("memento_hash"),
			"sections": len(sections),
			"max_significance": round(max_significance, 2),
			"gate_would_ingest": would_ingest,
		}
		stats["processed"] += 1
		stats["would_ingest"] += int(would_ingest)
	return stats
