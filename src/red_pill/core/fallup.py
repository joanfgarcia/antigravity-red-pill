"""fallup — watcher CPU→GPU v2 (anti-flapping, testeable, sin deps de daemon).

Fuente de verdad para el bloque fallup del daemon (`run_dual_bind.py`, generado
desde `scripts/setup_background_model.sh`). Este módulo NO toca el daemon, no
hace I/O salvo `ModelRegistry`/`VramProbe` (inyectables por parámetro para
tests puros), y nunca muta perfiles.

Corrige los blockers del panel adversarial (FALLUP-WATCHER v2, 2026-09-27):
- R1 flapping: margen 0.5GB sobre tier de ENTRADA + peor-caso dinámico
	+ 12 checks estables + idle 60s (el margen global de 500MB era
	insuficiente frente al swing 6.5GB de la VRAM viva 7.27GB↔0.73GB;
	tiers granite_8b 1.5(n gl 0)/6.5(-1 6144)/7.2(10240)/7.7(12288)/8.2(16384);
	margen sobre el tier máximo exigiría 8.2GB en tarjeta de 8.15GB —
	corrección del juez 2026-09-27 con el fallup real 7.27GB→10240).
- R2 TOCTOU: el caller re-chequea `elapsed2` tras adquirir el lock y mira
	`lock._waiters` (una request encolada aún no bumpeó `last_active`).
- R3 prioridad: LOW_TIMEOUT=10s/HIGH=300s → umbral fijo 15s era código muerto
	en low y evicción prematura en high; el watcher exige idle>=60s y excluye
	`low` (el timeout de low ya descarga de todos modos).
- R4 perfil: en CPU `current.n_gpu_layers==0`, chequearlo es dead-code; aquí
	dry-run de la resolución sobre copia (`ModelRegistry`), y el próximo request
	puede ser otro perfil (tiny_aya 4.0GB, llama_32 3.5GB) o experimental sin
	tiers (→ `no-gpu-tier-fits` / `experimental-no-tiers`).
- P3: `_fallup_enabled()` (model_runtime.py:161, antes cero usos) ahora gatea
	vía `fallup_enabled()`.

Tunables: FALLUP_MIN_IDLE_S=60, FALLUP_STABLE_CHECKS=12, FALLUP_MARGIN_GB=0.5.
Ventana de deploy: solo con nightly idle + daemon idle (ver AD-030.F1).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tunables v2 (documentados en AD-030.F1) ─────────────────────────────────
# NOTA DEL JUEZ (2026-09-27): el panel pidió +1.0GB sobre el tier MÁXIMO que
# encaja, pero eso exige 8.2GB en una tarjeta de 8.15GB (granite 7.2+1.0) y
# habría bloqueado el fallup real de esta noche (7.27GB → GPU 10240, estable
# y sin OOM). El margen va sobre el tier de ENTRADA (mínimo GPU del perfil)
# + peor-caso dinámico; la ventana de 60s/12 checks cubre el swing de VRAM.
FALLUP_MIN_IDLE_S = 60
FALLUP_STABLE_CHECKS = 12
FALLUP_MARGIN_GB = 0.5

# Piso documentado (entrada GPU de granite_8b, 6.5GB). La fuente dinámica es
# worst_case_gpu_min_free_gb(); esta constante es el fallback si el registro
# está vacío o falla (nunca bloquea el watcher por un error de lectura).
FALLUP_WORST_CASE_MIN_FREE_GB = 6.5

# Tiers con min_free_gb >= 100 son centinelas "nunca" (p.ej. 999) — se excluyen
# del cálculo del peor caso y del dry-run (con VRAM real nunca matchean, pero
# con free gigante en tests sí lo harían y volverían el watcher código muerto).
_SENTINEL_MIN_FREE_GB = 100.0


def fallup_enabled() -> bool:
	"""Gate caliente `model_runtime.yaml: fallup` (P3: antes cero usos)."""
	try:
		from red_pill.core import model_runtime as _mr

		fn = getattr(_mr, "_fallup_enabled", None)
		if callable(fn):
			return bool(fn())
	except Exception as e:
		logger.warning(f"[fallup] _fallup_enabled() falló ({e}); asumiendo True")
	return True


def worst_case_gpu_min_free_gb() -> float:
	"""Peor caso de entrada a GPU entre perfiles con tiers (dinámico).

	Máximo, entre perfiles con `vram_tiers`, del UMBRAL MÍNIMO de entrada a GPU
	(mínimo `min_free_gb` entre tiers con `n_gpu_layers != 0` de cada perfil).
	Ignora perfiles sin tiers (experimental/custom) y tiers centinela >=100
	(999 = "nunca en GPU"). Se restringe a perfiles con capability
	`distillation` (la carga del daemon: sueño/Memento/conversación) — incluir
	a `hermes_8b` (7.2GB, sin distillation) o `samantha` (999, CPU-only)
	elevaría el umbral a 7.2-8.2GB+margen (imposible en 8GB, watcher muerto);
	el peor caso útil es granite_8b 6.5. Si no hay perfiles distillation,
	cae al máximo entre todos (sentinelas excluidos).
	Si el registro está vacío → piso FALLUP_WORST_CASE_MIN_FREE_GB (6.5).
	"""
	try:
		from red_pill.core.model_registry import ModelRegistry

		profiles = ModelRegistry.get_all_profiles()
	except Exception as e:
		logger.warning(f"[fallup] ModelRegistry inaccesible ({e}); piso 6.5")
		return FALLUP_WORST_CASE_MIN_FREE_GB

	def _entries(subset: dict) -> list[float]:
		outs: list[float] = []
		for _name, prof in (subset or {}).items():
			if not isinstance(prof, dict):
				continue
			hw = prof.get("hardware_affinity", {}) or {}
			tiers = hw.get("vram_tiers")
			if not tiers:
				continue  # experimental/custom sin tiers → ignorado
			gpu_mins: list[float] = []
			for t in tiers:
				try:
					if int(t.get("n_gpu_layers", 0) or 0) == 0:
						continue
					mf = float(t.get("min_free_gb", 0))
				except Exception:
					continue
				if mf >= _SENTINEL_MIN_FREE_GB:
					continue  # centinela 999 → ignorado
				gpu_mins.append(mf)
			if gpu_mins:
				outs.append(min(gpu_mins))
		return outs

	try:
		distill_subset = {n: p for n, p in (profiles or {}).items() if isinstance(p, dict) and "distillation" in (p.get("capabilities") or [])}
		per_profile_entry = _entries(distill_subset) or _entries(profiles or {})
	except Exception as e:
		logger.warning(f"[fallup] cálculo de peor caso falló ({e}); piso 6.5")
		return FALLUP_WORST_CASE_MIN_FREE_GB
	if not per_profile_entry:
		return FALLUP_WORST_CASE_MIN_FREE_GB
	return max(per_profile_entry)


def entry_min_gpu_free_gb(profile_name: Optional[str]) -> Optional[float]:
	"""Umbral MÍNIMO de entrada a GPU del perfil (mínimo `min_free_gb` entre
	tiers con `n_gpu_layers != 0`, centinelas >=100 excluidos). None si el
	perfil no tiene tiers GPU (experimental/custom/solo-CPU).

	Copia, nunca muta. Es la base del margen de la regla 9: el margen va
	sobre la ENTRADA (lo mínimo para cargar en GPU), no sobre el tier máximo
	que encaja (que en granite exigiría 8.2GB en una tarjeta de 8.15GB y
	volvería el watcher código muerto — hallazgo del juez 2026-09-27 con el
	fallup real de 7.27GB→10240 como evidencia).
	"""
	if not profile_name:
		return None
	try:
		from red_pill.core.model_registry import ModelRegistry

		profile = ModelRegistry.get_profile(profile_name)
	except Exception:
		return None
	if not profile or not isinstance(profile, dict):
		return None
	tiers = (profile.get("hardware_affinity", {}) or {}).get("vram_tiers")
	if not tiers:
		return None
	mins: list[float] = []
	for t in tiers:
		try:
			if int((t or {}).get("n_gpu_layers", 0) or 0) == 0:
				continue
			mf = float((t or {}).get("min_free_gb", 0))
		except Exception:
			continue
		if mf >= _SENTINEL_MIN_FREE_GB:
			continue
		mins.append(mf)
	return min(mins) if mins else None


def dry_run_gpu_tier(profile_name: Optional[str], *, free_mb: Optional[int] = None) -> Optional[Dict]:
	"""Tier GPU que correspondería con la VRAM ACTUAL, sin mutar nada.

	Copia la resolución vía `ModelRegistry.get_resolved_hardware_affinity`
	(cuando `free_mb` es None, la VRAM la mide el propio registry) y devuelve
	el tier GPU (`dict` copia con `min_free_gb`/`n_gpu_layers`/`n_ctx`) o None
	si toca CPU (ningún tier GPU encaja) o el perfil no tiene tiers
	(experimental/custom sin tiers). Nunca muta el perfil ni el registry.

	`free_mb` inyectable para tests puros (evita la segunda query de VRAM).
	"""
	if not profile_name:
		return None
	try:
		from red_pill.core.model_registry import ModelRegistry
	except Exception:
		return None
	try:
		profile = ModelRegistry.get_profile(profile_name)
	except Exception:
		return None
	if not profile or not isinstance(profile, dict):
		return None
	hw = profile.get("hardware_affinity", {}) or {}
	tiers = hw.get("vram_tiers")
	if not tiers:
		return None  # sin tiers → CPU/experimental
	# Ordenar GPU tiers por exigencia ascendente (copia, nunca muta).
	try:
		gpu_tiers = sorted(
			[t for t in tiers if int((t or {}).get("n_gpu_layers", 0) or 0) != 0],
			key=lambda t: float(t.get("min_free_gb", 0)),
		)
	except Exception:
		return None
	if not gpu_tiers:
		return None
	if free_mb is None:
		# Copia resolución vía el registry (mide VRAM actual internamente).
		try:
			resolved = ModelRegistry.get_resolved_hardware_affinity(profile_name)
		except Exception:
			return None
		# resolved es dict nuevo (el registry construye copia) → no mutamos.
		try:
			if int(resolved.get("n_gpu_layers", 0) or 0) == 0:
				return None  # toca CPU con la VRAM actual
		except Exception:
			return None
		# Enriquecer con min_free_gb: re-derivar el tier que encaja con la
		# VRAM actual (segunda lectura contigua en el tiempo; el caller en
		# producción pasa free_mb para evitarla — ver should_fallup).
		try:
			from red_pill.core.vram_probe import VramProbe

			free_gb = float(VramProbe.get_free_mb()) / 1024.0
		except Exception:
			return None
		matched: Optional[Dict] = None
		for t in gpu_tiers:
			try:
				mf = float(t.get("min_free_gb", 0))
			except Exception:
				continue
			if mf >= _SENTINEL_MIN_FREE_GB:
				continue
			if free_gb >= mf:
				matched = t
		if matched is None:
			return None
		return dict(matched)
	# Rama pura para tests: usar free_mb inyectado (sin I/O).
	try:
		free_gb = float(free_mb) / 1024.0
	except Exception:
		return None
	matched = None
	for t in gpu_tiers:
		try:
			mf = float(t.get("min_free_gb", 0))
		except Exception:
			continue
		if mf >= _SENTINEL_MIN_FREE_GB:
			continue
		if free_gb >= mf:
			matched = t
	if matched is None:
		return None
	return dict(matched)


def should_fallup(
	mode: Optional[str],
	profile_name: Optional[str],
	is_experimental: bool,
	last_priority: Optional[str],
	idle_s: float,
	free_mb: int,
	stable_count: int,
	reserved_exclusive: bool,
	fallup_enabled_flag: bool,
	*,
	tier: Optional[Dict] = None,
	worst_case_gb: Optional[float] = None,
) -> Tuple[bool, str]:
	"""¿Debe el watcher descargar el worker CPU para volver a GPU?

	Orden de reglas (razones estables para observabilidad en /status):
	1. mode=="cpu" si no → (False, "not-cpu")
	2. fallup_enabled si no → (False, "fallup-disabled")
	3. profile_name is not None si no → (False, "nothing-loaded")
	4. is_experimental → (False, "experimental-no-tiers")
	5. last_priority=="low" → (False, "low-priority-idle-unloads-anyway")
	6. idle_s>=60 si no → (False, "not-idle")
	7. reserved_exclusive → (False, "gpu-reserved")
	8. tier=dry_run_gpu_tier(profile) None → (False, "no-gpu-tier-fits")
	9. free_gb >= entry_min(profile)+0.5 si no → (False, "margin").
	10. stable_count>=12 si no → (False, "unstable")
	11. free_gb >= worst_case+0.5 si no → (False, "worst-case")
	12. si todo ok → (True, "stable-fallup")

	`free_mb` y `tier` como args → test puro (sin I/O cuando se inyectan).
	`worst_case_gb` inyectable para tests (por defecto dinámico).
	El parámetro se llama `fallup_enabled_flag` para no sombrear la función
	`fallup_enabled()`; el daemon lo llama con `fallup_enabled` posicional.
	"""
	# 1. Solo el modo CPU puede ascender (nunca descenso GPU→GPU ni idle en GPU).
	if mode != "cpu":
		return (False, "not-cpu")
	# 2. Gate caliente (P3: _fallup_enabled() ya no está muerto).
	if not fallup_enabled_flag:
		return (False, "fallup-disabled")
	# 3. Nada cargado → nada que ascender (ramas None).
	if profile_name is None:
		return (False, "nothing-loaded")
	# 4. Experimental sin tiers → sin dry-run posible.
	if is_experimental:
		return (False, "experimental-no-tiers")
	# 5. Prioridad low: el timeout de low (10s) ya descarga de todos modos;
	# el watcher no evicta en low (R3: umbral fijo 15s era código muerto).
	if last_priority == "low":
		return (False, "low-priority-idle-unloads-anyway")
	# 6. Idle mínimo 60s (R3: ni 10s de low ni 300s de high; 60s es el suelo).
	try:
		idle = float(idle_s)
	except Exception:
		idle = 0.0
	if idle < FALLUP_MIN_IDLE_S:
		return (False, "not-idle")
	# 7. Reserva exclusiva GPU (E2: GpuReservationManager) → no tocar.
	if reserved_exclusive:
		return (False, "gpu-reserved")
	# 8. Dry-run del tier GPU con la VRAM actual (R4: nunca current.n_gpu_layers,
	# que en CPU es 0 y sería dead-code; copia, nunca muta).
	_tier = tier
	if _tier is None:
		try:
			_tier = dry_run_gpu_tier(profile_name, free_mb=free_mb)
		except Exception:
			_tier = None
	if _tier is None:
		return (False, "no-gpu-tier-fits")
	try:
		if int(_tier.get("n_gpu_layers", 0) or 0) == 0:
			return (False, "no-gpu-tier-fits")
	except Exception:
		return (False, "no-gpu-tier-fits")
	# 9. Margen 0.5GB sobre el tier de ENTRADA (juez 2026-09-27: margen sobre
	# el tier máximo que encaja exigiría 8.2GB en tarjeta de 8.15GB para
	# granite — código muerto; el fallup real de 7.27GB→10240 es la prueba).
	try:
		_entry_min = entry_min_gpu_free_gb(profile_name)
	except Exception:
		_entry_min = None
	if _entry_min is None:
		return (False, "no-gpu-tier-fits")
	try:
		free_gb = float(free_mb) / 1024.0
	except Exception:
		free_gb = 0.0
	if free_gb < float(_entry_min) + FALLUP_MARGIN_GB:
		return (False, "margin")
	# 10. Estabilidad: 12 checks seguidos con tier encajando (R1 flapping).
	try:
		stable = int(stable_count)
	except Exception:
		stable = 0
	if stable < FALLUP_STABLE_CHECKS:
		return (False, "unstable")
	# 11. Peor caso dinámico + margen (R1: el próximo request puede ser granite
	# 8b 6.5GB aunque el perfil barato actual quepa; evita re-flap nocturno).
	_worst = worst_case_gb
	if _worst is None:
		try:
			_worst = worst_case_gpu_min_free_gb()
		except Exception:
			_worst = FALLUP_WORST_CASE_MIN_FREE_GB
	try:
		_worst_f = float(_worst)
	except Exception:
		_worst_f = FALLUP_WORST_CASE_MIN_FREE_GB
	if free_gb < _worst_f + FALLUP_MARGIN_GB:
		return (False, "worst-case")
	# 12. Todo ok: ascenso estable.
	return (True, "stable-fallup")
