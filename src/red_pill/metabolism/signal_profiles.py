"""Taxonomía del dolor (AD-108): cada clase tiene su ley, no una tasa global.

Una picadura de mosquito no se comporta como una hemorragia: la primera no
escala porque no tiene consecuencia; la segunda no escala porque ya está arriba.
Las ganas de orinar escalan pero se limpian; el hambre escala y si no se atiende
termina en SYSTEM-FAILURE. Dos ejes separan las clases: velocidad de aparición y
reversibilidad de la consecuencia.

La ley es una sola y se parametriza por clase:

	edad_h     = (ahora - first_seen_at) / 3600
	intensidad = clamp(base + pendiente * edad_h, base, techo)
	si acantilado_h and edad_h >= acantilado_h: intensidad = 10 (system_failure)

El reloj es tiempo real, nunca ticks: la intensidad no puede depender de cuántas
veces miramos. Los perfiles viven en `configs/signals/signal_profiles.yaml`
(data-over-code); el fallback de este módulo existe solo para que un install
incompleto no tumbe al daemon, y un test fija que ambos digan lo mismo.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

ACK_FREEZE = "freeze"  # sin acantilado: el acuse para el reloj
ACK_SILENCE = "silence"  # con acantilado: silencia el aviso, el reloj sigue
ACK_NONE = "none"  # eventos: no se reconocen, ya ocurrieron

DEFAULT_STAGES: Dict[str, float] = {"info": 0.0, "warning": 4.0, "error": 7.0, "system_failure": 9.95}

# Espejo del YAML canónico: solo se usa si el fichero no existe.
_BUILTIN_CLASSES: Dict[str, Dict[str, Any]] = {
	"irritacion": {"base": 1.5, "slope_per_hour": 0.0, "ceiling": 3.0, "cliff_hours": None, "ack_mode": ACK_FREEZE},
	"necesidad": {"base": 2.5, "slope_per_hour": 0.6, "ceiling": 7.0, "cliff_hours": None, "ack_mode": ACK_FREEZE},
	"sed": {"base": 2.5, "slope_per_hour": 0.25, "ceiling": 8.9, "cliff_hours": 720.0, "ack_mode": ACK_SILENCE},
	"herida": {"base": 7.5, "slope_per_hour": 0.0, "ceiling": 8.5, "cliff_hours": 0.5, "ack_mode": ACK_SILENCE},
	"fallo": {"base": 10.0, "slope_per_hour": 0.0, "ceiling": 10.0, "cliff_hours": None, "ack_mode": ACK_NONE},
}


@dataclass(frozen=True)
class SignalClass:
	"""Ley de escalado de una clase de dolor."""

	name: str
	base: float
	slope_per_hour: float
	ceiling: float
	cliff_hours: Optional[float]
	ack_mode: str

	def age_to_cliff(self, age_hours: float) -> bool:
		return self.cliff_hours is not None and self.cliff_hours > 0 and age_hours >= self.cliff_hours


@dataclass(frozen=True)
class SignalCatalog:
	"""Taxonomía completa: clases, etapas y el mapa señal→clase."""

	classes: Dict[str, SignalClass] = field(default_factory=dict)
	stages: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_STAGES))
	default_class: str = "necesidad"
	signals: Dict[str, Dict[str, Any]] = field(default_factory=dict)

	def class_for(self, signal_name: str) -> SignalClass:
		entry = self.signals.get(signal_name) or {}
		name = str(entry.get("class") or self.default_class)
		return self.classes.get(name) or self.classes[self.default_class]

	def profile_for(self, signal_name: str) -> Tuple[SignalClass, Dict[str, Any]]:
		"""Clase efectiva + overrides por señal (p. ej. `cliff_hours` propio)."""
		return self.class_for(signal_name), dict(self.signals.get(signal_name) or {})

	def stage_for(self, intensity: float) -> str:
		return stage_for(intensity, self.stages)


def stage_for(intensity: float, stages: Optional[Dict[str, float]] = None) -> str:
	"""Etiqueta legible del 0–10: info < warning < error < system_failure."""
	thresholds = stages or DEFAULT_STAGES
	label = "info"
	for name, floor in sorted(thresholds.items(), key=lambda kv: float(kv[1])):
		if intensity >= float(floor):
			label = name
	return label


def compute_intensity(profile: SignalClass, base: float, age_hours: float) -> Tuple[float, str]:
	"""Aplica la ley de la clase. Devuelve (intensidad, etapa).

	`base` es la severidad que declara el productor (o la de la clase si no la
	declara); la clase manda en pendiente, techo y acantilado.
	"""
	age = max(0.0, float(age_hours))
	if profile.age_to_cliff(age):
		return 10.0, "system_failure"
	# Clase `fallo`: es un evento que ya ocurrió, no un estado que se declare. Nace
	# en su base (10) aunque el productor pase una severidad menor.
	effective_base = profile.base if profile.ack_mode == ACK_NONE else float(base)
	grown = effective_base + profile.slope_per_hour * age
	intensity = min(max(grown, effective_base), profile.ceiling)
	return intensity, stage_for(intensity)


def _build_class(name: str, raw: Dict[str, Any]) -> SignalClass:
	cliff = raw.get("cliff_hours")
	return SignalClass(
		name=name,
		base=float(raw.get("base", 2.5)),
		slope_per_hour=float(raw.get("slope_per_hour", 0.0)),
		ceiling=float(raw.get("ceiling", 10.0)),
		cliff_hours=float(cliff) if isinstance(cliff, (int, float)) and cliff > 0 else None,
		ack_mode=str(raw.get("ack_mode") or ACK_FREEZE),
	)


def build_catalog(raw: Optional[Dict[str, Any]] = None) -> SignalCatalog:
	data = raw or {"classes": _BUILTIN_CLASSES, "default_class": "necesidad", "signals": {}}
	classes = {name: _build_class(name, spec or {}) for name, spec in (data.get("classes") or {}).items()}
	if not classes:
		classes = {name: _build_class(name, spec) for name, spec in _BUILTIN_CLASSES.items()}
	default = str(data.get("default_class") or "necesidad")
	if default not in classes:
		default = next(iter(classes))
	return SignalCatalog(
		classes=classes,
		stages={str(k): float(v) for k, v in (data.get("stages") or DEFAULT_STAGES).items()},
		default_class=default,
		signals={str(k): dict(v or {}) for k, v in (data.get("signals") or {}).items()},
	)


_CACHE: Optional[Tuple[Path, float, SignalCatalog]] = None


def load_catalog(path: Optional[Path] = None, *, force: bool = False) -> SignalCatalog:
	"""Catálogo vigente, con caché por mtime para el hot reload del operador."""
	global _CACHE
	if path is None:
		from red_pill.core.paths import get_signal_profiles_path

		path = get_signal_profiles_path()
	path = Path(path)
	try:
		mtime = path.stat().st_mtime
	except OSError:
		logger.debug(f"signal_profiles: {path} no existe; se usa el fallback interno")
		return build_catalog()
	if not force and _CACHE and _CACHE[0] == path and _CACHE[1] == mtime:
		return _CACHE[2]
	try:
		import yaml

		data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
		catalog = build_catalog(data)
	except Exception as exc:
		logger.warning(f"signal_profiles: no se pudo leer {path} ({exc}); fallback interno")
		return build_catalog()
	_CACHE = (path, mtime, catalog)
	return catalog
