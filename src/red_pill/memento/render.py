"""Renderer canónico Memento (RFC-002 §4.2): mensajes normalizados → markdown.

Contrato: `memento/index.md` siempre completo y canónico; las split views
`memento/NNN-*.md` son proyecciones derivadas para sesiones densas (umbral
provisional pendiente de la cata Q8). Todo contenido pasa por la limpieza
compartida (§5.2) y el scrubber MUST-9 antes de tocar disco. El hash del
contrato de invalidación (§4.5.1) cubre SOLO el cuerpo — el frontmatter puede
mutar (prev/next del hilo) sin invalidar `distill/`/`refine/`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.memento.clean import normalize_noise
from red_pill.memento.scrub import scrub_secrets

ROLE_LABELS = {"user": "Usuario", "assistant": "Asistente"}
NO_DATE = "(sin fecha)"

_DIR_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_SPLIT_FILE_GLOB = "[0-9][0-9][0-9]-*.md"


def session_dir_slug(session_id: str) -> str:
	"""Nombre de directorio determinista y fs-safe: `opencode:abc-123` → `opencode-abc-123` (§4.2)."""
	slug = _DIR_SLUG_RE.sub("-", session_id.lower()).strip("-")
	return slug or "session"


def _to_datetime(ts: Any) -> Optional[datetime]:
	"""Timestamp de fuente (epoch s, ISO string o None) → datetime UTC."""
	if ts is None:
		return None
	if isinstance(ts, (int, float)):
		try:
			return datetime.fromtimestamp(float(ts), tz=timezone.utc)
		except (OverflowError, OSError, ValueError):
			return None
	if isinstance(ts, str):
		try:
			parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
		except ValueError:
			return None
		if parsed.tzinfo is None:
			parsed = parsed.replace(tzinfo=timezone.utc)
		return parsed.astimezone(timezone.utc)
	return None


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
	return dt.isoformat().replace("+00:00", "Z") if dt else None


def _display(dt: Optional[datetime]) -> str:
	return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else NO_DATE


def _yaml_value(value: Any) -> str:
	if value is None:
		return "null"
	if isinstance(value, bool):
		return "true" if value else "false"
	text = str(value)
	if ": " in text or text.startswith(("'", '"', "[", "{", "*", "&", "!")) or text != text.strip():
		return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
	return text


def compute_hash(body: str) -> str:
	"""`memento_hash` normativo (§4.5.1): sha256 del cuerpo tras el frontmatter."""
	return hashlib.sha256(body.encode("utf-8")).hexdigest()


def extract_body(text: str) -> str:
	"""Cuerpo de un fichero canónico: todo lo que sigue al `---` de cierre del frontmatter."""
	lines = text.split("\n")
	if not lines or lines[0].strip() != "---":
		return text
	for i in range(1, len(lines)):
		if lines[i].strip() == "---":
			return "\n".join(lines[i + 1:])
	return text


@dataclass
class RenderedSession:
	session_id: str
	source: str
	month: str
	created_at: Optional[str]
	updated_at: Optional[str]
	message_count: int
	body_chars: int
	has_splits: bool
	memento_hash: str
	index_text: str
	splits: List[Tuple[str, str]]  # [(filename, text)]

	@property
	def dir_rel(self) -> str:
		return f"{self.month}/{self.source}/{session_dir_slug(self.session_id)}"


def render_session(
	session_id: str,
	source: str,
	originator: str,
	messages: List[Dict[str, Any]],
	*,
	workspace: Optional[str] = None,
	prev_session: Optional[str] = None,
	next_session: Optional[str] = None,
	reconstructed: bool = False,
	step_count: Optional[int] = None,
	split_max_messages: int = 30,
	split_max_chars: int = 24000,
	month_override: Optional[str] = None,
) -> RenderedSession:
	"""Renderiza una sesión al esquema canónico §4.2 (index + splits derivados)."""
	blocks: List[Tuple[str, str]] = []  # (header, content) ya limpios y scrubbeados
	first_dt: Optional[datetime] = None
	last_dt: Optional[datetime] = None
	for message in messages:
		content = scrub_secrets(normalize_noise(str(message.get("content", ""))))
		if not content:
			continue
		dt = _to_datetime(message.get("timestamp"))
		if dt is not None:
			first_dt = first_dt or dt
			last_dt = dt
		label = ROLE_LABELS.get(str(message.get("role")), str(message.get("role", "?")).capitalize())
		blocks.append((f"## {_display(dt)} — {label}", content))

	# Mes inmutable (§4.3): primer mensaje; en reruns manda el registry (month_override).
	month = month_override or (first_dt or datetime.now(timezone.utc)).strftime("%Y-%m")

	# Chunking mecánico para split views: por presupuesto de mensajes/chars.
	chunks: List[List[int]] = []
	current: List[int] = []
	current_chars = 0
	for i, (_header, content) in enumerate(blocks):
		if current and (len(current) >= split_max_messages or current_chars + len(content) > split_max_chars):
			chunks.append(current)
			current, current_chars = [], 0
		current.append(i)
		current_chars += len(content)
	if current:
		chunks.append(current)
	if len(chunks) > 999:  # NNN es 001–999 (§4.5.1): exagerado pero acotado
		chunks[998].extend(idx for chunk in chunks[999:] for idx in chunk)
		chunks = chunks[:999]

	total_chars = sum(len(content) for _h, content in blocks)
	has_splits = len(chunks) >= 2 and (len(blocks) > split_max_messages or total_chars > split_max_chars)

	frontmatter: List[Tuple[str, Any]] = [("session_id", session_id), ("source", source), ("originator", originator)]
	if first_dt:
		frontmatter.append(("created_at", _to_iso(first_dt)))
	if last_dt:
		frontmatter.append(("updated_at", _to_iso(last_dt)))
	if step_count is not None:
		frontmatter.append(("step_count", step_count))
	frontmatter.append(("message_count", len(blocks)))
	if workspace:
		frontmatter.append(("workspace", workspace))
	# prev/next SIEMPRE presentes (null si no hay vecino): el frontmatter mantiene
	# longitud fija y las actualizaciones del hilo no desplazan los line refs del cuerpo.
	frontmatter.append(("prev_session", prev_session))
	frontmatter.append(("next_session", next_session))
	frontmatter.append(("reconstructed", reconstructed))

	fm_lines = ["---"] + [f"{key}: {_yaml_value(value)}" for key, value in frontmatter] + ["---", ""]

	# Posiciones (1-based) de cada bloque en el fichero final, TOC incluido.
	prefix = len(fm_lines) + 2 + (1 + len(chunks) + 1 if has_splits else 0)
	positions: List[Tuple[int, int]] = []
	cursor = prefix + 1
	for _header, content in blocks:
		content_lines = content.count("\n") + 1
		positions.append((cursor, cursor + content_lines))
		cursor += content_lines + 2

	toc_lines: List[str] = []
	split_files: List[Tuple[str, str]] = []
	if has_splits:
		for n, chunk in enumerate(chunks, start=1):
			first, last = chunk[0] + 1, chunk[-1] + 1
			start_line, end_line = positions[chunk[0]][0], positions[chunk[-1]][1]
			stem = f"{n:03d}-mensajes-{first:04d}-{last:04d}"
			toc_lines.append(f"- {n:03d} — Mensajes {first}–{last} (l{start_line}) → [[{stem}]]")
			split_body = [f"> [!ref] memento/index.md#l{start_line}-{end_line}", ""]
			for idx in chunk:
				split_body.extend([blocks[idx][0], blocks[idx][1], ""])
			split_files.append((f"{stem}.md", "\n".join(split_body)))

	lines = list(fm_lines) + [f"# {session_id}", ""]
	if has_splits:
		lines += ["## Secciones"] + toc_lines + [""]
	for header, content in blocks:
		lines += [header, content, ""]

	index_text = "\n".join(lines)
	body = extract_body(index_text)
	return RenderedSession(
		session_id=session_id,
		source=source,
		month=month,
		created_at=_to_iso(first_dt),
		updated_at=_to_iso(last_dt),
		message_count=len(blocks),
		body_chars=len(body),
		has_splits=has_splits,
		memento_hash=compute_hash(body),
		index_text=index_text,
		splits=split_files,
	)


def write_session(root: Path, rendered: RenderedSession) -> Path:
	"""Escribe/reconcilia el directorio de sesión (overwrite idempotente, splits stale fuera)."""
	memento_dir = root / rendered.dir_rel / "memento"
	memento_dir.mkdir(parents=True, exist_ok=True)
	(memento_dir / "index.md").write_text(rendered.index_text, encoding="utf-8")

	desired = {filename for filename, _text in rendered.splits}
	for stale in memento_dir.glob(_SPLIT_FILE_GLOB):
		if stale.name not in desired:
			stale.unlink()
	for filename, text in rendered.splits:
		(memento_dir / filename).write_text(text, encoding="utf-8")
	return root / rendered.dir_rel


def update_frontmatter_links(index_file: Path, prev_session: Optional[str], next_session: Optional[str]) -> bool:
	"""Reescribe SOLO prev/next_session del frontmatter (el hilo SHOULD-12).

	Reemplazo in-place, jamás inserción: el frontmatter conserva su longitud, así
	que ni el cuerpo ni sus line refs ni el `memento_hash` se mueven un ápice.
	"""
	text = index_file.read_text(encoding="utf-8")
	lines = text.split("\n")
	if not lines or lines[0].strip() != "---":
		return False
	close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
	if close is None:
		return False

	replacements = {"prev_session:": f"prev_session: {_yaml_value(prev_session)}", "next_session:": f"next_session: {_yaml_value(next_session)}"}
	changed = False
	for i in range(1, close):
		for prefix, replacement in replacements.items():
			if lines[i].startswith(prefix) and lines[i] != replacement:
				lines[i] = replacement
				changed = True
	if not changed:
		return False
	index_file.write_text("\n".join(lines), encoding="utf-8")
	return True
