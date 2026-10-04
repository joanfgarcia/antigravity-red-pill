"""Composición de prompts por fragmentos (PROMPT-001, F1).

Modelo (RFC PROMPT-001, ratificado 2026-10-04):

- Repo = plantillas: fragmentos globales curados en `src/red_pill/prompts/`
(subdir `fragments/`) y un `manifest.yaml` por componente junto a sus prompts.
- Render en UNA pasada (`string.Template.substitute`): las variables estáticas
(identidad, idioma, scopes) y los fragmentos se resuelven en la generación;
los placeholders de runtime quedan como sentinelas (`@@nombre@@`) y se
sustituyen en la llamada con `str.replace` (sin re-escaneo de `$`, seguro
ante valores con `$` o llaves).
- Firma: `p1:<sha256 completo>` del texto efectivo (estático + sentinelas),
normalizado (NFC, LF). Determinista y sin dependencias de host: mismo repo +
misma configuración efectiva → misma firma.
- Artefacto: best-effort en `~/.local/share/red-pill/prompts/<componente>/`
(tmp + replace, 0700/0600 por la Bio). Si no se puede escribir, se sigue
usando el render en memoria: la ejecución nunca depende del artefacto.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Dict, Mapping, Optional, Sequence, Tuple

SCHEMA = "p1"
_PKG_ROOT = Path(__file__).resolve().parent.parent
_FRAGMENTS_DIR = _PKG_ROOT / "prompts" / "fragments"
_MANIFEST_GLOB = "prompts/manifest.yaml"
_RUNTIME_SENTINEL = "@@{name}@@"
_SENTINEL_RE = re.compile(r"@@([a-z_][a-z0-9_]*)@@")


class PromptError(RuntimeError):
	"""Manifiesto incoherente, placeholder desconocido o valor ausente."""


# Idioma de los textos (PROMPT-001 F3): `auto` deja interpretar al modelo
# (idioma de la fuente); el resto fuerza uno. Valor resuelto desde config.
_LANGUAGE_VALUES = {
	"auto": "the same language as the source text",
	"es": "Spanish",
	"en": "English",
	"ca": "Catalan",
	"gl": "Galician",
	"eu": "Basque",
	"fr": "French",
	"de": "German",
	"pt": "Portuguese",
	"it": "Italian",
}


def _prompt_language_value() -> str:
	import red_pill.config as cfg

	raw = str(getattr(cfg, "MEMENTO_PROMPT_LANGUAGE", "auto") or "auto").strip()
	return _LANGUAGE_VALUES.get(raw.lower(), raw)


_STATIC_PROVIDERS = {"prompt_language": _prompt_language_value}


@dataclass(frozen=True)
class EffectivePrompt:
	component: str
	prompt_id: str
	text: str
	signature: str
	system: Optional[str]
	fragments: Tuple[str, ...]
	static: Tuple[str, ...]
	runtime: Tuple[str, ...]


def _normalize(text: str) -> str:
	return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _hash(text: str) -> str:
	return f"{SCHEMA}:{hashlib.sha256(_normalize(text).encode('utf-8')).hexdigest()}"


def _manifest_path(component: str) -> Path:
	return _PKG_ROOT / component / "prompts" / "manifest.yaml"


@lru_cache(maxsize=None)
def _load_manifest(component: str) -> Dict[str, dict]:
	import yaml

	path = _manifest_path(component)
	if not path.is_file():
		raise PromptError(f"manifiesto no encontrado: {path}")
	data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
	prompts = data.get("prompts")
	if not isinstance(prompts, dict) or not prompts:
		raise PromptError(f"manifiesto sin prompts: {path}")
	for pid, spec in prompts.items():
		if not isinstance(spec, dict) or not spec.get("template"):
			raise PromptError(f"prompt '{pid}' sin template en {path}")
	return prompts


def spec_of(component: str, prompt_id: str) -> dict:
	prompts = _load_manifest(component)
	if prompt_id not in prompts:
		raise PromptError(f"prompt '{prompt_id}' no declarado en {component}")
	return prompts[prompt_id]


def _template_fields(text: str) -> Tuple[set, bool]:
	"""Campos `${var}` usados y flag de sintaxis inválida (`$` suelto)."""
	fields = set()
	invalid = False
	for _lit, named, braced, bad in Template.pattern.findall(text):
		if named:
			fields.add(named)
		elif braced:
			fields.add(braced)
		elif bad:
			invalid = True
	return fields, invalid


def _compose_source(component: str, prompt_id: str, spec: dict) -> str:
	"""Embebe los fragmentos en el source antes del render (una sola pasada).

	Los fragmentos son curados (repo); sus placeholders internos (p. ej.
	`${prompt_language}`) se resuelven en la MISMA sustitución final. Un `$`
	literal en un fragmento debe escaparse como `$$` (lo detecta el validador).
	"""
	template_path = _manifest_path(component).parent / spec["template"]
	if not template_path.is_file():
		raise PromptError(f"template no encontrado: {template_path}")
	source = _normalize(template_path.read_text(encoding="utf-8"))
	fragments = spec.get("fragments")
	if isinstance(fragments, dict):
		for name, rel in fragments.items():
			path = _FRAGMENTS_DIR / rel
			if not path.is_file():
				raise PromptError(f"fragmento '{name}' no encontrado: {path}")
			source = source.replace("${" + name + "}", _normalize(path.read_text(encoding="utf-8")))
	return source


@lru_cache(maxsize=None)
def _render_cached(component: str, prompt_id: str, static_items: Tuple[Tuple[str, str], ...]) -> EffectivePrompt:
	spec = spec_of(component, prompt_id)
	static = dict(static_items)
	source = _compose_source(component, prompt_id, spec)
	fields, invalid = _template_fields(source)
	if invalid:
		raise PromptError(f"'$' inválido en {component}/{prompt_id} (usa $$ para literal)")
	declared = set(spec.get("static") or []) | set(spec.get("runtime") or [])
	missing = fields - declared
	if missing:
		raise PromptError(f"placeholders no declarados en {component}/{prompt_id}: {sorted(missing)}")
	values: Dict[str, str] = {name: static[name] for name in spec.get("static") or []}
	for name in spec.get("runtime") or []:
		values[name] = _RUNTIME_SENTINEL.format(name=name)
	try:
		text = Template(source).substitute(values)
	except KeyError as e:
		raise PromptError(f"placeholder sin valor en {component}/{prompt_id}: {e}") from e
	system_file = spec.get("system")
	system = None
	if system_file:
		system_path = _manifest_path(component).parent / system_file
		if not system_path.is_file():
			raise PromptError(f"system no encontrado: {system_path}")
		system = _normalize(system_path.read_text(encoding="utf-8"))
	ep = EffectivePrompt(
		component=component,
		prompt_id=prompt_id,
		text=text,
		signature=_hash(f"{component}\x1e{prompt_id}\x1e{text}"),
		system=system,
		fragments=tuple(sorted((spec.get("fragments") or {}).keys())),
		static=tuple(sorted(spec.get("static") or [])),
		runtime=tuple(sorted(spec.get("runtime") or [])),
	)
	return ep


def resolve(component: str, prompt_id: str, *, static: Optional[Mapping[str, str]] = None) -> EffectivePrompt:
	spec = spec_of(component, prompt_id)
	merged: Dict[str, str] = {}
	for name in spec.get("static") or []:
		if static and name in static:
			merged[name] = str(static[name])
		elif name in _STATIC_PROVIDERS:
			merged[name] = str(_STATIC_PROVIDERS[name]())
		else:
			raise PromptError(f"valor estático '{name}' requerido por {component}/{prompt_id}")
	static_items = tuple(sorted(merged.items()))
	ep = _render_cached(component, prompt_id, static_items)
	_persist(ep)  # idempotente (early-return si ya existe); best-effort
	return ep


def render(component: str, prompt_id: str, *, static: Optional[Mapping[str, str]] = None, **runtime: str) -> str:
	ep = resolve(component, prompt_id, static=static)
	text = ep.text
	for name in ep.runtime:
		if name not in runtime:
			raise PromptError(f"falta el valor runtime '{name}' para {component}/{prompt_id}")
		text = text.replace(_RUNTIME_SENTINEL.format(name=name), str(runtime[name]))
	leftover = _SENTINEL_RE.findall(text)
	if leftover:
		raise PromptError(f"sentinelas sin resolver en {component}/{prompt_id}: {leftover}")
	return text


def signature(component: str, prompt_id: str, *, static: Optional[Mapping[str, str]] = None) -> str:
	return resolve(component, prompt_id, static=static).signature


def stage_signature(parts: Sequence[Tuple[str, str, Optional[Mapping[str, str]]]], extra: Optional[Mapping[str, str]] = None) -> str:
	"""Firma agregada de una etapa: prompts (componente, id, static) + systems + marcadores.

	Incluye el system prompt de cada entrada (la firma por prompt cubre solo el
	user): cambiar un system cambia la firma de la etapa (A2-B2 del RFC)."""
	chunks = []
	for comp, pid, static in parts:
		ep = resolve(comp, pid, static=static)
		system_sig = _hash(ep.system) if ep.system else "-"
		chunks.append(f"{comp}/{pid}={ep.signature}|system={system_sig}")
	if extra:
		chunks.extend(f"{k}={v}" for k, v in sorted(extra.items()))
	payload = "\x1e".join(chunks)
	return _hash(payload)


def system_text(component: str, prompt_id: str) -> Optional[str]:
	"""System prompt del manifiesto, sin exigir valores estáticos."""
	spec = spec_of(component, prompt_id)
	rel = spec.get("system")
	if not rel:
		return None
	path = _manifest_path(component).parent / rel
	if not path.is_file():
		raise PromptError(f"system no encontrado: {path}")
	return _normalize(path.read_text(encoding="utf-8"))


def _artifacts_dir() -> Path:
	from red_pill.core.paths import get_data_dir

	return get_data_dir() / "prompts"


def artifact_path(ep: EffectivePrompt) -> Optional[Path]:
	try:
		d = _artifacts_dir() / ep.component.replace("/", ".")
		return d / f"{ep.prompt_id}.{ep.signature.split(':', 1)[1][:16]}.txt"
	except Exception:
		return None


_persist_lock = threading.Lock()


def _persist(ep: EffectivePrompt) -> Optional[Path]:
	"""Materializa el prompt efectivo en XDG data (best-effort, atómico, 0700/0600)."""
	path = artifact_path(ep)
	if path is None:
		return None
	with _persist_lock:
		try:
			if path.exists():
				return path
			path.parent.mkdir(parents=True, exist_ok=True)
			try:
				os.chmod(path.parent, 0o700)
			except OSError:
				pass
			fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
			try:
				with os.fdopen(fd, "w", encoding="utf-8") as f:
					f.write(ep.text)
				try:
					os.chmod(tmp, 0o600)
				except OSError:
					pass
				os.replace(tmp, path)
			except Exception:
				Path(tmp).unlink(missing_ok=True)
				raise
			return path
		except Exception:
			return None


def discover_components() -> Sequence[str]:
	comps = []
	for manifest in sorted(_PKG_ROOT.rglob(_MANIFEST_GLOB)):
		rel = manifest.parent.parent.relative_to(_PKG_ROOT)
		comps.append(str(rel))
	return comps


def validate_all() -> list:
	"""Coherencia de manifiestos: templates, system, fragmentos y placeholders."""
	errors: list = []
	for component in discover_components():
		try:
			prompts = _load_manifest(component)
		except PromptError as e:
			errors.append(str(e))
			continue
		base = _manifest_path(component).parent
		for pid, spec in prompts.items():
			frag = spec.get("fragments") or {}
			if not isinstance(frag, dict):
				errors.append(f"{component}/{pid}: 'fragments' debe ser mapping")
				continue
			try:
				source = _compose_source(component, pid, spec)
			except PromptError as e:
				errors.append(str(e))
				continue
			fields, invalid = _template_fields(source)
			if invalid:
				errors.append(f"{component}/{pid}: '$' inválido (usa $$ para literal)")
			declared = set(spec.get("static") or []) | set(spec.get("runtime") or [])
			missing = fields - declared
			unused = declared - fields
			if missing:
				errors.append(f"{component}/{pid}: placeholders sin declarar {sorted(missing)}")
			if unused:
				errors.append(f"{component}/{pid}: declarados sin uso {sorted(unused)}")
			if spec.get("system") and not (base / spec["system"]).is_file():
				errors.append(f"{component}/{pid}: system no existe ({spec['system']})")
	return errors
