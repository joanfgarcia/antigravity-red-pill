"""Composición de prompts por fragmentos (PROMPT-001, F1).

Modelo (RFC PROMPT-001, ratificado 2026-10-04):

- Repo = plantillas: fragmentos globales curados en `src/red_pill/prompts/`
(subdir `fragments/`) y un `manifest.yaml` por componente junto a sus prompts.
- Render en UNA pasada (`string.Template.substitute`) directa desde el source
compuesto (fragmentos embebidos): estáticos + runtime se sustituyen de golpe y
los valores nunca se re-escanean (seguro ante `$` o `@@x@@` en datos).
- Firma y artefacto: `resolve()` materializa el prompt EFECTIVO con los runtime
como sentinelas (`@@nombre@@`) — `p1:<sha256>`, normalizado (NFC, LF), sin
dependencias de host; el artefacto vive en `~/.local/share/red-pill/prompts/`.
- Cachés por proceso (sin hot-reload: los prompts se leen al arranque, RFC §3.1);
`cache_clear()` para tests/dev.
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
	return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).lstrip("\ufeff")


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
	try:
		data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
	except (yaml.YAMLError, UnicodeDecodeError, OSError) as e:
		raise PromptError(f"manifiesto ilegible: {path}: {e}") from e
	prompts = data.get("prompts")
	if not isinstance(prompts, dict) or not prompts:
		raise PromptError(f"manifiesto sin prompts: {path}")
	for pid, spec in prompts.items():
		if not isinstance(spec, dict) or not spec.get("template"):
			raise PromptError(f"prompt '{pid}' sin template en {path}")
	return prompts


def is_declared(component: str, prompt_id: str) -> bool:
	"""True si el prompt está declarado en el manifiesto del componente."""
	try:
		return prompt_id in _load_manifest(component)
	except PromptError:
		return False


def cache_clear() -> None:
	"""Limpia las cachés del loader (tests/dev; en producción se lee al arranque)."""
	_load_manifest.cache_clear()
	_render_cached.cache_clear()
	_source_cached.cache_clear()
	_system_cached.cache_clear()


def spec_of(component: str, prompt_id: str) -> dict:
	prompts = _load_manifest(component)
	if prompt_id not in prompts:
		raise PromptError(f"prompt '{prompt_id}' no declarado en {component}")
	return prompts[prompt_id]


def _template_fields(text: str) -> Tuple[set, bool]:
	"""Campos `${var}` usados y flag de sintaxis inválida (`$` suelto)."""
	fields = set()
	invalid = False
	for match in Template.pattern.finditer(text):
		named = match.group("named")
		braced = match.group("braced")
		if named:
			fields.add(named)
		elif braced:
			fields.add(braced)
		elif match.group("invalid") is not None:
			# El grupo `invalid` del patrón captura cadena vacía (no None) para
			# `$` no válido; la truthiness antigua hacía la rama inalcanzable.
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
	try:
		source = _normalize(template_path.read_text(encoding="utf-8"))
	except (UnicodeDecodeError, OSError) as e:
		raise PromptError(f"template ilegible: {template_path}: {e}") from e
	fragments = spec.get("fragments")
	if isinstance(fragments, dict):
		for name, rel in fragments.items():
			path = _FRAGMENTS_DIR / rel
			if not path.is_file():
				raise PromptError(f"fragmento '{name}' no encontrado: {path}")
			try:
				content = _normalize(path.read_text(encoding="utf-8"))
			except (UnicodeDecodeError, OSError) as e:
				raise PromptError(f"fragmento ilegible: {path}: {e}") from e
			source = source.replace("${" + name + "}", content)
	return source


@lru_cache(maxsize=None)
def _source_cached(component: str, prompt_id: str) -> str:
	"""Source compuesto (fragmentos embebidos), cacheado. Sin hot-reload:
	en producción los prompts se leen al arranque (RFC PROMPT-001 §3.1)."""
	return _compose_source(component, prompt_id, spec_of(component, prompt_id))


@lru_cache(maxsize=None)
def _system_cached(component: str, prompt_id: str) -> Optional[str]:
	spec = spec_of(component, prompt_id)
	rel = spec.get("system")
	if not rel:
		return None
	path = _manifest_path(component).parent / rel
	if not path.is_file():
		raise PromptError(f"system no encontrado: {path}")
	try:
		return _normalize(path.read_text(encoding="utf-8"))
	except (UnicodeDecodeError, OSError) as e:
		raise PromptError(f"system ilegible: {path}: {e}") from e


@lru_cache(maxsize=None)
def _render_cached(component: str, prompt_id: str, static_items: Tuple[Tuple[str, str], ...]) -> EffectivePrompt:
	spec = spec_of(component, prompt_id)
	static = dict(static_items)
	source = _source_cached(component, prompt_id)
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
	except (KeyError, ValueError) as e:
		raise PromptError(f"placeholder inválido o sin valor en {component}/{prompt_id}: {e}") from e
	ep = EffectivePrompt(
		component=component,
		prompt_id=prompt_id,
		text=text,
		signature=_hash(f"{component}\x1e{prompt_id}\x1e{text}"),
		system=_system_cached(component, prompt_id),
		fragments=tuple(sorted((spec.get("fragments") or {}).keys())),
		static=tuple(sorted(spec.get("static") or [])),
		runtime=tuple(sorted(spec.get("runtime") or [])),
	)
	return ep


def _merged_static(component: str, prompt_id: str, spec: dict, static: Optional[Mapping[str, str]]) -> Dict[str, str]:
	merged: Dict[str, str] = {}
	for name in spec.get("static") or []:
		if static and name in static:
			merged[name] = str(static[name])
		elif name in _STATIC_PROVIDERS:
			merged[name] = str(_STATIC_PROVIDERS[name]())
		else:
			raise PromptError(f"valor estático '{name}' requerido por {component}/{prompt_id}")
	return merged


def resolve(component: str, prompt_id: str, *, static: Optional[Mapping[str, str]] = None) -> EffectivePrompt:
	spec = spec_of(component, prompt_id)
	static_items = tuple(sorted(_merged_static(component, prompt_id, spec, static).items()))
	ep = _render_cached(component, prompt_id, static_items)
	_persist(ep)  # idempotente (early-return si ya existe); best-effort
	return ep


def render(component: str, prompt_id: str, *, static: Optional[Mapping[str, str]] = None, **runtime: str) -> str:
	"""Render del prompt efectivo en UNA pasada con TODOS los valores.

	No hay sustitución por sentinelas en llamada: el source compuesto se
	sustituye una sola vez (estáticos + runtime), así un valor de usuario que
	contenga `@@x@@` o `$` viaja literal y no se re-escanea."""
	spec = spec_of(component, prompt_id)
	declared_runtime = set(spec.get("runtime") or [])
	missing = declared_runtime - set(runtime)
	if missing:
		raise PromptError(f"faltan valores runtime {sorted(missing)} para {component}/{prompt_id}")
	unknown = set(runtime) - declared_runtime
	if unknown:
		raise PromptError(f"valores runtime no declarados {sorted(unknown)} para {component}/{prompt_id}")
	values: Dict[str, str] = dict(_merged_static(component, prompt_id, spec, static))
	values.update({name: str(value) for name, value in runtime.items()})
	try:
		return Template(_source_cached(component, prompt_id)).substitute(values)
	except (KeyError, ValueError) as e:
		raise PromptError(f"placeholder inválido o sin valor en {component}/{prompt_id}: {e}") from e


def signature(component: str, prompt_id: str, *, static: Optional[Mapping[str, str]] = None) -> str:
	return resolve(component, prompt_id, static=static).signature


def stage_signature(parts: Sequence[Tuple[str, str, Optional[Mapping[str, str]]]], extra: Optional[Mapping[str, str]] = None) -> str:
	"""Firma agregada de una etapa: prompts (componente, id, static) + systems + marcadores.

	Incluye el system prompt de cada entrada (la firma por prompt cubre solo el
	user): cambiar un system cambia la firma de la etapa (A2-B2 del RFC). Las
	piezas van con prefijo de longitud para que el separador no sea ambiguo."""
	chunks = []
	for comp, pid, static in parts:
		ep = resolve(comp, pid, static=static)
		system_sig = _hash(ep.system) if ep.system else "-"
		chunks.append(f"{comp}/{pid}={ep.signature}|system={system_sig}")
	if extra:
		chunks.extend(f"{k}={v}" for k, v in sorted(extra.items()))
	payload = "\x1e".join(f"{len(chunk)}:{chunk}" for chunk in chunks)
	return _hash(payload)


def system_text(component: str, prompt_id: str) -> Optional[str]:
	"""System prompt del manifiesto, sin exigir valores estáticos."""
	return _system_cached(component, prompt_id)


def _artifacts_dir() -> Path:
	from red_pill.core.paths import get_data_dir

	return get_data_dir() / "prompts"


def artifact_path(ep: EffectivePrompt) -> Optional[Path]:
	try:
		component_dir = _safe_name(ep.component.replace("/", "."))
		prompt_name = _safe_name(ep.prompt_id)
		d = _artifacts_dir() / component_dir
		return d / f"{prompt_name}.{ep.signature.split(':', 1)[1][:16]}.txt"
	except Exception:
		return None


def _safe_name(name: str) -> str:
	"""Nombre de fichero seguro (sin traversal ni separadores)."""
	clean = re.sub(r"[^A-Za-z0-9_.-]", "_", name).strip("._") or "prompt"
	if ".." in clean:
		clean = clean.replace("..", "__")
	return clean


_persist_lock = threading.Lock()


def _persist(ep: EffectivePrompt) -> Optional[Path]:
	"""Materializa el prompt efectivo en XDG data (best-effort, atómico).

	- Dir creado 0700 (no re-chmod de dirs existentes: respeta 0500 del operador).
	- Fichero 0600; si ya existe, repara permisos y no reescribe."""
	path = artifact_path(ep)
	if path is None:
		return None
	with _persist_lock:
		try:
			if path.exists():
				try:
					if path.stat().st_mode & 0o777 != 0o600:
						os.chmod(path, 0o600)
				except OSError:
					pass
				return path
			path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
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
	"""Coherencia de manifiestos: templates, system, fragmentos y placeholders.

	Crash-safe: cualquier componente/prompt ilegible se reporta como error, nunca
	aborta el validador."""
	errors: list = []
	for component in discover_components():
		try:
			prompts = _load_manifest(component)
		except Exception as e:  # noqa: BLE001 — el contrato es devolver errores
			errors.append(str(e))
			continue
		base = _manifest_path(component).parent
		for pid, spec in prompts.items():
			try:
				frag = spec.get("fragments") or {}
				if not isinstance(frag, dict):
					errors.append(f"{component}/{pid}: 'fragments' debe ser mapping")
					continue
				for key in ("static", "runtime"):
					value = spec.get(key) or []
					if not isinstance(value, list):
						errors.append(f"{component}/{pid}: '{key}' debe ser lista")
				tpl_path = base / spec["template"]
				if not tpl_path.is_file():
					errors.append(f"{component}/{pid}: template no existe ({tpl_path})")
					continue
				raw = _normalize(tpl_path.read_text(encoding="utf-8"))
				for name, rel in frag.items():
					if f"${{{name}}}" not in raw:
						errors.append(f"{component}/{pid}: fragmento '{name}' declarado pero no usado")
				source = _compose_source(component, pid, spec)
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
				if spec.get("system"):
					sys_path = base / spec["system"]
					if not sys_path.is_file():
						errors.append(f"{component}/{pid}: system no existe ({spec['system']})")
					else:
						sys_fields, sys_invalid = _template_fields(_normalize(sys_path.read_text(encoding="utf-8")))
						if sys_fields or sys_invalid:
							errors.append(f"{component}/{pid}: system no admite placeholders")
			except Exception as e:  # noqa: BLE001 — un prompt roto no tumba el gate
				errors.append(f"{component}/{pid}: {e}")
	return errors
