"""El fondo del Operador: un dato declarado, no inferido (RFC-AFE-001, D-01).

El ánimo tiene dos ejes y el sistema solo tenía uno. El **fragmento** (lo que
expresa un turno) se puede leer del texto; el **fondo** (cómo está él) no: medido
el 2026-11-14, en 10 de 14 días el fragmento era plano mientras su fondo no lo
era. Agregando el fragmento por día se acertaba 4 de 14. Por eso el fondo se
**pregunta** y se guarda tal cual; la máquina no lo adivina.

Decisiones que este módulo implementa:

- **Un registro por puesto, no por sesión.** `continuity_id` es per-leg (6 filas,
6 ids en el registro): guardar «por alma» habría dado un fondo por pestaña, que
es lo contrario de D-02 («eres la misma en todas las sesiones»). Sin clave.
- **Día natural, no ventana móvil.** Declarado ayer a las 23:55 y leído hoy a las
11:50, dice `ayer` — no «hoy» con 11,9 h de antigüedad, que es el defecto que
este RFC arregla.
- **Sin decaimiento en F1.** El *Fading Affect Bias* de `data/affect_models.yaml`
escala la erosión de engramas por color, no es una ley de ánimo: no tiene τ ni
unidades. F1 solo dice frescura (hoy / ayer / antes / nada). El decaimiento es
F3 con D-04.
- **Escritura serializada.** `flock` + `tmp` único + guarda de monotonía: tres
sesiones vivas escriben el mismo fichero, y una declaración vieja no puede pisar
una nueva (*lost update* silencioso).
"""

from __future__ import annotations

import fcntl
import functools
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FILENAME = "affect_fondo.json"
LOCKNAME = "affect_fondo.lock"
HISTORY_MAX = 10

# Letras aceptadas; el dato canónico (emoción, color, etiqueta) vive en YAML.
LETTERS = ("B", "C", "F", "T", "X", "-")

SIN_SENAL = "ÁNIMO — fondo: sin señal (pregúntale cómo está hoy antes de empujar trabajo)"


class FondoNoSobrescrito(RuntimeError):
	"""La declaración llegó con fecha anterior a la vigente: no se pisa.

	Existe para que el CLI no diga «guardado» cuando no se guardó nada (lo cazó
	el adversarial: con el reloj adelantado el usuario pedía F y recibía «C
	guardado», exit 0).
	"""

	def __init__(self, vigente: Dict[str, Any]):
		super().__init__(f"declaración más reciente en vigor: {vigente.get('letra')}")
		self.vigente = vigente


def _state_dir() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir()


def path() -> Path:
	return _state_dir() / FILENAME


@functools.lru_cache(maxsize=1)
def letters() -> Dict[str, Dict[str, str]]:
	"""Tabla letra → {emotion, color, label}; `{}` si el YAML no se puede leer.

	Cacheada: `get_current_sync_state` la consulta en cada turno. Sin excepción:
	un dato de ánimo ausente no puede tumbar un turno (doctrina del módulo).
	"""
	import yaml

	yml = Path(__file__).resolve().parent.parent / "data" / "affect_letters.yaml"
	try:
		with open(yml, "r", encoding="utf-8") as fh:
			data = yaml.safe_load(fh) or {}
		return {str(k): dict(v or {}) for k, v in data.items()}
	except Exception:
		return {}


def normalizar(letra: str) -> str:
	limpio = str(letra or "").strip().upper()
	if limpio in ("", "NONE", "NADA", "N"):
		return "-"
	if limpio not in LETTERS:
		raise ValueError(f"letra de fondo inválida: {letra!r} (válidas: {', '.join(LETTERS)})")
	return limpio


def _fecha(ts: float) -> datetime:
	return datetime.fromtimestamp(ts)


def _hoy(ts: float, now_ts: Optional[float] = None) -> bool:
	"""Mismo día NATURAL (hora local del puesto), no ventana móvil de 24 h."""
	actual = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
	return _fecha(ts).date() == _fecha(actual).date()


def _ts_valido(valor: Any) -> Optional[float]:
	"""`declared_at` solo vale si es un número positivo: null/0/'' es sin dato."""
	try:
		ts = float(valor)
	except (TypeError, ValueError):
		return None
	return ts if ts > 0 else None


def _es_hoy(registro: Dict[str, Any], now_ts: Optional[float] = None) -> bool:
	"""Mismo día NATURAL en la zona del que declaró, no la del proceso que lee.

	Se guarda `declared_local` (AAAA-MM-DD) al escribir: un CLI con otro `TZ` no
	puede cambiar la respuesta a «¿esto es de hoy?» (lo cazó el adversarial).
	"""
	local = str(registro.get("declared_local") or "")
	if local:
		return local == datetime.now().strftime("%Y-%m-%d")
	ts = _ts_valido(registro.get("declared_at"))
	return bool(ts) and _hoy(ts, now_ts)


def _leer_crudo() -> Optional[Dict[str, Any]]:
	try:
		raw = path().read_text(encoding="utf-8")
		data = json.loads(raw)
		if not isinstance(data, dict) or "letra" not in data:
			return None
		return data
	except (OSError, ValueError, TypeError):
		# Corrupto o ausente es «sin señal», nunca una excepción en el turno.
		return None


def read(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
	"""Registro vigente con `age_h` y `es_hoy` añadidos; `None` si no hay."""
	registro = _leer_crudo()
	if not registro:
		return None
	ts = _ts_valido(registro.get("declared_at"))
	if ts is None:
		return None
	actual = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	registro = dict(registro)
	registro["age_h"] = round(max(0.0, (actual - ts) / 3600.0), 1)
	registro["es_hoy"] = _es_hoy(registro, actual)
	return registro


def write(
	letra: str,
	*,
	note: str = "",
	by: str = "operator",
	now: Optional[float] = None,
) -> Dict[str, Any]:
	"""Guarda una declaración del Operador y devuelve el registro resultante.

	- Valida la letra (ValueError si no existe).
	- Toma un lock de fichero: varias sesiones pueden declarar a la vez.
	- Guarda de monotonía: una declaración con fecha anterior NO sobrescribe la
	vigente (una sesión reanudada no puede retroceder el fondo).
	"""
	limpio = normalizar(letra)
	ts = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	registro = {
		"letra": limpio,
		"note": str(note or "")[:280],
		"declared_at": ts,
		"declared_local": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
		"updated_by": str(by or "operator")[:60],
	}

	directorio = _state_dir()
	directorio.mkdir(parents=True, exist_ok=True)
	lock_path = directorio / LOCKNAME
	with open(lock_path, "w", encoding="utf-8") as lock:
		fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
		try:
			previo = _leer_crudo() or {}
			historial: List[Dict[str, Any]] = list(previo.get("history") or [])
			try:
				previo_ts = float(previo.get("declared_at") or 0)
			except (TypeError, ValueError):
				previo_ts = 0.0
			if previo_ts > ts:
				raise FondoNoSobrescrito(read(now=ts) or dict(previo, es_hoy=True, age_h=0.0))
			if previo.get("letra"):
				historial.append({"letra": previo.get("letra"), "declared_at": previo_ts, "by": previo.get("updated_by")})
			registro["history"] = historial[-HISTORY_MAX:]
			payload = json.dumps(registro, ensure_ascii=False, indent=1)
			fd, tmp = tempfile.mkstemp(dir=str(directorio), prefix=".affect_fondo.", suffix=".tmp")
			try:
				with os.fdopen(fd, "w", encoding="utf-8") as fh:
					fh.write(payload)
				os.replace(tmp, path())
			finally:
				if os.path.exists(tmp):
					os.unlink(tmp)
		finally:
			fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
	return read(now=ts) or dict(registro, es_hoy=True, age_h=0.0)


def describe(registro: Optional[Dict[str, Any]], now: Optional[float] = None) -> str:
	"""Los tres textos del bloque, byte-exactos (contrato de F1).

	- hoy   → `ÁNIMO — fondo: C · cansancio · declarado hoy 08:12 (hace 3.2 h)`
	- antes → `ÁNIMO — fondo: B · bien · declarado ayer 21:40 — puede no ser de hoy`
	- nada  → `ÁNIMO — fondo: sin señal (pregúntale cómo está hoy antes de empujar trabajo)`
	"""
	if not registro:
		return SIN_SENAL
	tabla = letters().get(str(registro.get("letra")), {})
	etiqueta = tabla.get("label") or str(registro.get("letra"))
	ts = _ts_valido(registro.get("declared_at"))
	if ts is None:
		return SIN_SENAL
	actual = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	declarado = _fecha(ts)
	if _es_hoy(registro, actual):
		edad = round(max(0.0, (actual - ts) / 3600.0), 1)
		return f"ÁNIMO — fondo: {registro.get('letra')} · {etiqueta} · declarado hoy {declarado.strftime('%H:%M')} (hace {edad:.1f} h)"
	dias = (_fecha(actual).date() - declarado.date()).days
	dia = "ayer" if dias == 1 else declarado.strftime("%d-%m")
	return f"ÁNIMO — fondo: {registro.get('letra')} · {etiqueta} · declarado {dia} {declarado.strftime('%H:%M')} — puede no ser de hoy"


def enabled() -> bool:
	import red_pill.config as cfg

	return bool(getattr(cfg, "AFFECT_FONDO_ENABLED", False))


def block(now: Optional[float] = None) -> str:
	"""Bloque del despertar; cadena vacía si el flag está apagado."""
	if not enabled():
		return ""
	return describe(read(now=now), now=now)
