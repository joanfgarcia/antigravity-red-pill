"""Canal de notas del despertar (AWAKEN-002, direcciones 1 y 3).

El desk (`${AGENT_CORE_DIR}/awakening/notes/`) es un buzón de mano a mano.
Dirección 1 (operador → despertar): una nota sin `para:` (o `para: despertar`) son deberes que el Fixer deja para el siguiente despertar; el despertar las lee como primer paso de su plan.
Dirección 3 (despertar → operador): una nota `para: <Operador>` es una decisión pendiente; el handshake interactivo cuenta las que aún no llevan `## Leída` del operador y lo dice en una línea del digest.

Diseño (AWAKEN-002): una nota por archivo; `done/` no es barrera (se puede releer); las notas admiten comentarios en medio; cada nota y anotación se firma (`— <nombre> · <ISO ts>`). Sin git. Solo lo firmado por el Operador es deber; el despertar nunca firma como el Operador.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

NOTES_SUBDIR = "notes"
DONE_SUBDIR = "done"
_AWAKENING_SUBDIR = "awakening"

_READ_HEADER_RE = re.compile(r"^#{1,6}\s*Le[íi]da\b(.*)$", re.IGNORECASE)
_SIGNATURE_RE = re.compile(r"[—–-]\s*(?P<name>[^·\n]+?)\s*·\s*(?P<ts>[^\n]+?)\s*$", re.MULTILINE)
_PARA_RE = re.compile(r"^\s*para\s*:\s*(?P<target>.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def operator_name() -> str:
	"""Nombre del Operador (destino canónico de las notas direccion 3)."""
	try:
		from red_pill import config as cfg

		return cfg.get_config().OPERATOR_DISPLAY_NAME
	except Exception:
		return os.getenv("USER_NAME") or os.getenv("USER") or "Operador"


def _now_iso() -> str:
	return datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")


def signature(name: str, ts: Optional[str] = None) -> str:
	"""Firma canónica: `— <nombre> · <ISO ts>`."""
	return f"— {name} · {ts or _now_iso()}"


def get_awakening_root(desk: Optional[Path | str] = None) -> Path:
	if desk is not None:
		return Path(desk) / _AWAKENING_SUBDIR
	from red_pill.core.paths import get_agent_core_root

	return get_agent_core_root() / _AWAKENING_SUBDIR


def get_notes_root(desk: Optional[Path | str] = None) -> Path:
	return get_awakening_root(desk) / NOTES_SUBDIR


def get_done_root(desk: Optional[Path | str] = None) -> Path:
	return get_awakening_root(desk) / DONE_SUBDIR


def ensure_channel(desk: Optional[Path | str] = None) -> Path:
	"""Crea `notes/` y `done/` si no existen. Idempotente."""
	notes = get_notes_root(desk)
	done = get_done_root(desk)
	notes.mkdir(parents=True, exist_ok=True)
	done.mkdir(parents=True, exist_ok=True)
	return notes


def parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
	"""`(frontmatter, cuerpo)`. Bloque YAML entre `---` al inicio (si lo hay)."""
	lines = text.split("\n")
	if not lines or lines[0].strip() != "---":
		return {}, text.strip()
	close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
	if close is None:
		return {}, text.strip()
	try:
		fm = yaml.safe_load("\n".join(lines[1:close])) or {}
	except Exception:
		fm = {}
	if not isinstance(fm, dict):
		fm = {}
	return fm, "\n".join(lines[close + 1 :]).strip()


@dataclass
class ReadMark:
	"""[`## Leída`] entrada de registro de lectura de una nota."""

	ts: str = ""
	author: str = ""
	outcome: str = ""
	raw: str = ""


@dataclass
class Note:
	"""Una nota del canal."""

	path: Path
	title: str = ""
	target: str = ""
	frontmatter: Dict[str, Any] = field(default_factory=dict)
	body: str = ""
	marks: List[ReadMark] = field(default_factory=list)
	done: bool = False

	@property
	def slug(self) -> str:
		return self.path.stem

	@property
	def signature(self) -> Optional[str]:
		m = _SIGNATURE_RE.search(self.body)
		return m.group("name").strip() if m else None

	def targets_operator(self, operator: Optional[str] = None) -> bool:
		operator = operator or operator_name()
		target = (self.target or self.frontmatter.get("para") or "").strip()
		return bool(target) and target.casefold() == str(operator).casefold()

	def operator_read(self, operator: Optional[str] = None) -> bool:
		operator = operator or operator_name()
		return any(m.author.casefold() == str(operator).casefold() for m in self.marks)

	def pending_for_operator(self, operator: Optional[str] = None) -> bool:
		return self.targets_operator(operator) and not self.operator_read(operator)


def _parse_marks(body: str) -> List[ReadMark]:
	marks: List[ReadMark] = []
	lines = body.split("\n")
	i = 0
	while i < len(lines):
		m = _READ_HEADER_RE.match(lines[i])
		if not m:
			i += 1
			continue
		block_start = i + 1
		j = block_start
		while j < len(lines) and not re.match(r"^#{1,6}\s", lines[j]):
			j += 1
		block = "\n".join(lines[block_start:j]).strip()
		sig = _SIGNATURE_RE.search(block)
		outcome = next((ln.strip() for ln in block.split("\n") if ln.strip() and not _SIGNATURE_RE.search(ln)), "")
		marks.append(
			ReadMark(
				ts=(sig.group("ts").strip() if sig else m.group(1).strip()),
				author=(sig.group("name").strip() if sig else ""),
				outcome=outcome,
				raw=block,
			)
		)
		i = j
	return marks


def parse_note(path: Path | str, done: Optional[bool] = None) -> Note:
	path = Path(path)
	text = path.read_text(encoding="utf-8")
	fm, body = parse_frontmatter(text)
	title = str(fm.get("title") or fm.get("titulo") or "").strip()
	target = str(fm.get("para") or "").strip()
	if not target:
		pm = _PARA_RE.search(body)
		if pm:
			target = pm.group("target").strip()
	if not title:
		head = next((ln.lstrip("# ").strip() for ln in body.split("\n") if ln.strip().startswith("#")), "")
		title = head or path.stem
	if done is None:
		done = path.parent.name == DONE_SUBDIR
	return Note(
		path=path,
		title=title,
		target=target,
		frontmatter=fm,
		body=body,
		marks=_parse_marks(body),
		done=done,
	)


def list_notes(desk: Optional[Path | str] = None, include_done: bool = False) -> List[Note]:
	"""Notas de `notes/` (y `done/` si `include_done`), por mtime ascendente."""
	roots: list[tuple[Path, bool]] = [(get_notes_root(desk), False)]
	if include_done:
		roots.append((get_done_root(desk), True))
	notes: list[Note] = []
	for root, is_done in roots:
		if not root.is_dir():
			continue
		for f in sorted(root.glob("*.md")):
			try:
				notes.append(parse_note(f, done=is_done))
			except OSError:
				continue
	return notes


def pending_for_operator(desk: Optional[Path | str] = None, operator: Optional[str] = None) -> List[Note]:
	"""Notas `para: <Operador>` pendientes (dirección 3)."""
	return [n for n in list_notes(desk) if n.pending_for_operator(operator)]


def count_for_operator(desk: Optional[Path | str] = None, operator: Optional[str] = None) -> int:
	"""Recuento barato para el digest del handshake (A-1)."""
	return len(pending_for_operator(desk, operator))


def duty_notes(desk: Optional[Path | str] = None, operator: Optional[str] = None) -> List[Note]:
	"""Deberes pendientes (dirección 1): notas que NO son para el Operador y que
	aún no llevan `## Leída` del despertar."""
	return [n for n in list_notes(desk) if not n.targets_operator(operator) and not n.marks]


def note_filename(ts: Optional[datetime] = None, slug: str = "nota") -> str:
	ts = ts or datetime.now()
	clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug.strip()).strip("-").lower() or "nota"
	return f"{ts.strftime('%Y%m%d_%H%M')}_{clean}.md"
