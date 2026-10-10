"""Afinidad determinista de sesión (single-writer de memoria, MULTISES-001 §3.3).

Conjunto de strings que identifica en qué proyecto/trabajo está una sesión:
`campaign:<id>` + `mission:<id>` + explícitos + `ws:<workspace>`. Se usa como filtro
anticontaminación (semáforo de situación, pre-heating): dos sesiones afines se
ven; ajenas, no. Cero LLM, cero inferencia: lo que no está, no está.

`ws:` se resuelve contra el **registro de workspaces** (`workspaces.yaml`, D17),
nunca `basename(cwd)` a pelo — MEM-007 midió un `ws:IA` espurio con el cwd padre.
Si el path no pertenece a ningún workspace registrado, se omite (no se inventa).

Canonización global (D19): la forma canónica para persistir/claim_key es
`lower/trim` + `sorted(dedup)` → `canonize_affinity()`. `derive_affinity()` devuelve
orden de inserción determinista (el `sorted` se aplica al persistir).

Vacío → SILENT (sin scoping). No se inventa afinidad.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple


def _registry_signature() -> Optional[Tuple[str, Optional[int], Optional[int]]]:
	"""Firma `(path, mtime_ns, size)` del registro de workspaces — clave de caché.

	Cambia cuando el `workspaces.yaml` cambia en disco, de modo que la caché se
	invalida sola sin leer el YAML en cada turno (D17 + presupuesto de turno)."""
	try:
		from red_pill.core.workspaces import registry_path

		p = registry_path()
		st = p.stat()
		return (str(p), st.st_mtime_ns, st.st_size)
	except Exception:
		return None


_ws_cache: Dict[str, Optional[str]] = {}
_ws_cache_sig: object = object()


def resolve_workspace(workdir: Optional[str]) -> Optional[str]:
	"""Nombre del workspace registrado que contiene `workdir`, o `None` (D17).

	Cacheado por firma del registro: resolver afinidad no re-lee/parsea el YAML
	cada turno. `None` si el path no cae en ningún workspace registrado — no se
	deriva de `basename` (evita `ws:` espurios)."""
	if not workdir:
		return None
	global _ws_cache, _ws_cache_sig
	sig = _registry_signature()
	if sig != _ws_cache_sig:
		_ws_cache = {}
		_ws_cache_sig = sig
	key = str(workdir)
	if key not in _ws_cache:
		try:
			from red_pill.core.workspaces import owning_workspace

			_ws_cache[key] = owning_workspace(workdir)
		except Exception:
			_ws_cache[key] = None
	return _ws_cache[key]


def derive_affinity(
	workdir: Optional[str] = None,
	mission_id: Optional[str] = None,
	explicit: Optional[Iterable[str]] = None,
	campaign_id: Optional[str] = None,
) -> List[str]:
	"""Deriva la afinidad determinista (orden de inserción estable, sin duplicados).

	Orden de merge (§3.3): `campaña + misión + explícita + ws`.
	- `explicit`: afinidades ya etiquetadas (env `AFFINITY`, frontmatter, payload).
	- `mission_id`: misión en curso → `mission:<id>`. Si el id ya viene con el
		scope `mission:` (p.ej. `mission:adhoc-<fecha>`), NO se re-prefija (evita
		`mission:mission:…`).
	- `campaign_id`: campaña (cruce de proyectos) → `campaign:<id>`.
	- `workdir`: CWD del IDE / `manifest.workdir` → `ws:<workspace>` resuelto
		contra el registro (D17); omitido si no pertenece a ningún workspace.

	La canonización D19 (`lower/trim` + `sorted(dedup)`) es responsabilidad del
	persistidor (`canonize_affinity`); aquí se preserva el orden de inserción.
	"""
	out: List[str] = []
	cid = str(campaign_id).strip() if campaign_id else ""
	if cid:
		out.append(f"campaign:{cid}")
	mid = str(mission_id).strip() if mission_id else ""
	if mid:
		out.append(mid if mid.startswith("mission:") else f"mission:{mid}")
	if explicit:
		out.extend(str(a).strip() for a in explicit if str(a).strip())
	ws = resolve_workspace(workdir)
	if ws:
		out.append(f"ws:{ws}")
	seen: set = set()
	dedup: List[str] = []
	for a in out:
		if a not in seen:
			seen.add(a)
			dedup.append(a)
	return dedup


def canonize_affinity(values: Iterable[str]) -> List[str]:
	"""Forma canónica D19 para persistir/`claim_key`: `lower/trim` + `sorted(dedup)`.

	`BIT` vs `bit` no puede romper el coro: es la forma que se escribe en
	`affinity_json` y de la que se deriva el `claim_key` (D12)."""
	return sorted({str(v).strip().lower() for v in values if str(v).strip()})


def parse_affinity(raw: object) -> List[str]:
	"""Normaliza una afinidad ya almacenada (JSON list o CSV) a `list[str]`."""
	if raw is None:
		return []
	if isinstance(raw, list):
		return [str(a) for a in raw if str(a).strip()]
	text = str(raw).strip()
	if not text:
		return []
	if text.startswith("["):
		import json

		try:
			return parse_affinity(json.loads(text))
		except Exception:
			return []
	return [p.strip() for p in text.split(",") if p.strip()]
