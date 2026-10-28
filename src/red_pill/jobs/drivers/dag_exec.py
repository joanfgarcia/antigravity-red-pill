"""DAG atomic-stage execution: GPU probe, step timeout/budget and minion run.

Extracted from `dag.py` (SHARD-PS-04 / option B) as `DagExecMixin`, so the call
sites (`self._run_atomic`, `self._stage_timeout`, …) are unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from red_pill.jobs.drivers.dag_manifest import _PROTECTED_STAGE_PARAMS, _TYPE_AGENT, _render_item

logger = logging.getLogger(__name__)


def _stage_affinity(payload: Dict[str, Any], workdir: str) -> list:
	"""Afinidad de la etapa, en la forma que espera `claim_key` (D12/D19).

	Se reutiliza `derive_affinity` para que un claim y una sesión hablen el mismo
	idioma (`campaign:`, `mission:`, `ws:`). Si el payload declara afinidad
	explícita, esa manda: es un acto del Operador, no del driver.
	"""
	try:
		from red_pill.core.affinity import derive_affinity, parse_affinity

		explicit = parse_affinity(payload.get("affinity"))
		if explicit:
			return explicit
		return derive_affinity(
			workdir=workdir,
			mission_id=str(payload.get("mission_id") or "") or None,
			campaign_id=str(payload.get("campaign_id") or "") or None,
		)
	except Exception:
		# Sin afinidad derivable, el claim se apoya solo en branch/worktree/ruta;
		# `claim_key` sigue siendo determinista (lista vacía es una afinidad válida).
		return []


def _workdir_branch(workdir: str) -> str:
	"""Rama del worktree (vacía si no es repo). Cacheado por `gitinfo`."""
	try:
		from red_pill.core.gitinfo import git_snapshot

		return str(git_snapshot(workdir).get("branch") or "")
	except Exception:
		return ""


def _gpu_health_probe() -> Tuple[bool, int, int]:
	"""Probe de salud GPU real (D7), generalizado desde sleep.py: nvidia-smi exit 0
	+ VRAM efectiva + -ngl efectivo. Devuelve (usable, free_mb, ngl).
	"""
	if not shutil.which("nvidia-smi"):
		return False, 0, 0
	try:
		free_out = subprocess.run(
			["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
			capture_output=True,
			text=True,
			timeout=5,
		)
		if free_out.returncode != 0:
			return False, 0, 0
		free_mb = int(free_out.stdout.strip().split("\n")[0].strip())
	except Exception:
		return False, 0, 0

	ngl = -1
	try:
		ps = subprocess.run(["pgrep", "-af", "llama-server"], capture_output=True, text=True, timeout=5)
		for line in (ps.stdout or "").splitlines():
			low = line.lower()
			if "-ngl" in low:
				parts = line.split()
				for i, part in enumerate(parts):
					if part.startswith("-ngl"):
						try:
							# Soporta `-ngl=33`, `-ngl33` y `-ngl 33` (valor en el
							# siguiente token).
							if "=" in part:
								ngl = int(part.split("=")[-1])
							elif part != "-ngl" and part[4:].lstrip("-").isdigit():
								ngl = int(part[4:])
							elif i + 1 < len(parts):
								ngl = int(parts[i + 1])
						except Exception:
							ngl = 0
						break
	except Exception:
		pass

	return True, free_mb, ngl


class DagExecMixin:
	"""Execution hooks mixed into `DagJobDriver` (methods keep `self` access)."""

	if TYPE_CHECKING:
		from pathlib import Path

		# Members provided by the sibling mixin / ResumableJobDriver at runtime.
		job_id: str
		step_timeout_s: int
		_step_started: Optional[float]

		def _workdir(self, payload: Dict[str, Any]) -> Path: ...

	# ── GPU probe por etapa (fleco 1) ──────────────────────────────────────────
	def _preflight_stage_gpu(self, stage: Dict[str, Any], stage_path: str, payload: Dict[str, Any]) -> None:
		"""Probe de salud GPU real por etapa — espera (JobDeferred), nunca CPU disfrazada."""
		from red_pill.jobs.drivers.base import JobDeferred

		if not stage.get("requires_gpu"):
			return
		from red_pill.metabolism.ephemeral_server import _check_llm_available

		if _check_llm_available():
			usable, _free, ngl = _gpu_health_probe()
			if usable and (ngl == -1 or ngl > 0):
				return
		usable, free_mb, ngl = _gpu_health_probe()
		if not usable:
			raise JobDeferred(f"GPU no disponible para etapa '{stage_path}' (nvidia-smi no responde).")
		if ngl == 0:
			raise JobDeferred(f"LLM sirve en CPU disfrazada (-ngl 0) para etapa '{stage_path}': esperando GPU.")
		import red_pill.config as cfg

		min_free = int(payload.get("min_vram_mb", getattr(cfg, "SLEEP_MIN_FREE_VRAM_MB", 3500)))
		if free_mb < min_free:
			raise JobDeferred(f"VRAM insuficiente para etapa '{stage_path}' ({free_mb}MB libres < {min_free}MB).")

	# ── Cota de tiempo (política del RUNNER, aplicada aquí) ───────────────────
	def _budget_left(self) -> Optional[float]:
		"""Segundos que quedan de la cota del step, o None si no hay cota."""
		if not self.step_timeout_s or self._step_started is None:
			return None
		return self.step_timeout_s - (time.monotonic() - self._step_started)

	def _budget_spent(self) -> bool:
		"""True si la cota del step se agotó (frontera: ceder, no abatir)."""
		left = self._budget_left()
		return left is not None and left <= 0

	def _stage_timeout(self, stage: Dict[str, Any], payload: Dict[str, Any]) -> int:
		"""Timeout de la etapa ACOTADO por lo que queda del presupuesto del step.

		Sin esto, `control.max_step_minutes` es decorativo: cada etapa aplicaba su
		propio timeout y la suma de etapas secuenciales no tenía techo (una etapa
		colgada bloqueaba el runner entero, con el run-lock R6 impidiendo que
		otro entrara).

		El tope solo se aplica mientras quede presupuesto; una etapa ya lanzada
		en un grupo paralelo conserva su timeout declarado (recortarlo a cero la
		haría fallar por una cota que no es suya). El corte real está en la
		frontera de grupo, cediendo con lo hecho.

		Las instancias de FAN-OUT (`_item`) NO se recortan: cada una es una tarea
		atómica larga (1 sesión) con su cota completa. Recortarla por lo que
		quede del presupuesto del step (que comparten N hermanas en secuencia)
		abate sesiones legítimamente largas — incidente 2026-09-17 (redistill-2
		recortada a 565s). El watchdog adaptativo del runner sigue cubriendo un
		colgado real.
		"""
		declared = int(stage.get("timeout") or payload.get("timeout", 600))
		if stage.get("_item") is not None:
			return declared
		left = self._budget_left()
		if left is None or left <= 0:
			return declared
		return max(1, min(declared, int(left)))

	# ── Fase 4 (E3): claims de etapa ─────────────────────────────────────────
	def _claim_params(self, payload: Dict[str, Any], workdir: str, stage_path: str) -> Optional[Dict[str, Any]]:
		"""Argumentos del claim, o None si el job no tiene alma.

		Sin `continuity_id` no hay dueño posible y el claim no sobreviviría a un
		cambio de cuerpo (D18): se mantiene el comportamiento legacy (D-02) y el
		job corre sin reclamar. Nunca se inventa un dueño.
		"""
		continuity = str(payload.get("continuity_id") or "").strip()
		if not continuity:
			return None
		try:
			ttl = int(payload.get("claim_ttl_s") or 0) or None
		except Exception:
			ttl = None
		params: Dict[str, Any] = {
			"stage_path": stage_path,
			"affinity": _stage_affinity(payload, workdir),
			"branch": str(payload.get("branch") or "") or _workdir_branch(workdir),
			"worktree": workdir,
			"continuity_id": continuity,
			"originator": f"dag:{getattr(self, 'job_id', '') or 'unknown'}",
			"intent": str(payload.get("title") or "") or None,
		}
		if ttl:
			params["ttl_seconds"] = ttl
		return params

	def _claim_stage(self, payload: Dict[str, Any], stage_path: str, workdir: str):
		"""Reclama la etapa. None si el job no tiene alma (legacy, sin claim)."""
		params = self._claim_params(payload, workdir, stage_path)
		if params is None:
			return None
		try:
			from red_pill.session.stage_claims import try_claim_stage

			return try_claim_stage(**params)
		except Exception as e:
			# Non-fatal: un fallo del subsistema de claims no puede impedir que el
			# DAG avance. Se registra y se ejecuta sin claim (fail-open AQUÍ, donde
			# el riesgo es duplicar trabajo, no corromper: el claim es cooperativo).
			logger.warning(f"[DagJob] claim no disponible para '{stage_path}': {e}")
			return None

	def _release_stage_claim(self, payload: Dict[str, Any], stage_path: str, workdir: str) -> None:
		"""Suelta el claim de la etapa. Non-fatal."""
		params = self._claim_params(payload, workdir, stage_path)
		if params is None:
			return
		try:
			from red_pill.session.stage_claims import release_claim

			release_claim(**params)
		except Exception as e:
			logger.warning(f"[DagJob] no se pudo soltar el claim de '{stage_path}': {e}")

	@staticmethod
	def _renew_interval(ttl_seconds: int) -> float:
		"""Cada cuánto late la renovación: un tercio del TTL, con suelo de 5 s.

		Un tercio deja dos oportunidades de renovar antes de que expire: un fallo
		puntual de la BD no cuesta el claim. El suelo evita martillear con TTLs
		cortos (tests, etapas pequeñas).
		"""
		try:
			ttl = int(ttl_seconds) or 0
		except Exception:
			ttl = 0
		if ttl <= 0:
			from red_pill.session.stage_claims import DEFAULT_TTL_S

			ttl = DEFAULT_TTL_S
		return max(5.0, ttl / 3.0)

	def _start_claim_renewer(self, payload: Dict[str, Any], stage_path: str, workdir: str) -> Optional[threading.Event]:
		"""Arranca el latido de renovación (D9-a). Devuelve el evento de parada.

		El hilo es daemon y no bloquea: si el proceso muere, el claim caduca solo
		por TTL, que es exactamente la red de seguridad que queremos.
		"""
		params = self._claim_params(payload, workdir, stage_path)
		if params is None:
			return None
		from red_pill.session.stage_claims import DEFAULT_TTL_S, renew_claim

		try:
			ttl = int(params.get("ttl_seconds") or DEFAULT_TTL_S)
		except Exception:
			ttl = DEFAULT_TTL_S
		stop = threading.Event()
		interval = self._renew_interval(ttl)

		def _beat() -> None:
			while not stop.wait(interval):
				try:
					if not renew_claim(**params):
						# El claim ya no es nuestro o expiró: otro pudo robarlo. La
						# etapa sigue (tirarla sería peor que el posible solape), pero
						# queda registrado: es la señal de que el TTL se quedó corto.
						logger.warning(f"[DagJob] el claim de '{stage_path}' no se pudo renovar (expirado o robado); la etapa continúa")
				except Exception as e:
					logger.warning(f"[DagJob] renovación del claim de '{stage_path}' falló: {e}")

		threading.Thread(target=_beat, name=f"claim-renew-{stage_path[-24:]}", daemon=True).start()
		return stop

	# ── Ejecución de una etapa ATOMICA ────────────────────────────────────────
	def _run_atomic(self, payload: Dict[str, Any], stage: Dict[str, Any], stage_path: str, gate: Any = None) -> str:
		"""Ejecuta UN minion (factory + execute directo — decisión 2026-08-07) y
		devuelve su resumen.

		Serialización (opción 3 del RFC): los minions de LÓGICA devuelven su dict
		en memoria y el DAG lo escribe en `.cell/reports/<ruta>.json` — ahí ese
		fichero ES el reporte. Las etapas AGÉNTICAS son distintas: el agente
		escribe él mismo su reporte conforme al schema de su rol en esa ruta (el
		contrato zero-trust de forge: validate-report.mjs / gate-check.mjs leen
		ese fichero), así que el envelope del minion va a `<ruta>.envelope.json`
		y NO pisa la evidencia del rol.

		`gate` es el `_GroupPauseGate` del grupo paralelo (None si secuencial).
		La sonda de pausa a mitad de fase SOLO se inyecta si la etapa es
		`pausable` (default true): una etapa no-pausable nunca se auto-pausa y su
		trabajo jamás se descarta.
		"""
		if stage.get("fan_out_from"):
			raise RuntimeError(f"dag stage '{stage_path}' es plantilla de fan_out y no debe ejecutarse directa (fuente no completada).")
		from red_pill.jobs.drivers.base import JobDeferred

		self._preflight_stage_gpu(stage, stage_path, payload)
		workdir = self._workdir(payload)

		# ── Fase 4 (E3): reclamar la etapa antes de ejecutarla ────────────────
		# Si otra alma la tiene reclamada, NO se ejecuta: se difiere el step.
		# `JobDeferred` es el mecanismo correcto (no un "skip" que finge
		# completar): preserva lo que las hermanas paralelas ya completaron, no
		# consume intentos y el runner reentra cuando el claim expire. Nunca se
		# marca completada una etapa que no se ejecutó.
		claims_on = bool(payload.get("stage_claims", True))
		claim = self._claim_stage(payload, stage_path, str(workdir)) if claims_on else None
		if claim is not None and not claim.claimed:
			raise JobDeferred(
				f"etapa '{stage_path}' reclamada por otra alma ({claim.owner or 'desconocida'}, {claim.reason}); "
				"se reintenta cuando expire el claim"
			)
		renewer: Optional[threading.Event] = None
		try:
			if claim is not None and claim.claimed:
				# Fase 4 (E4, D9-a): latido que renueva el claim mientras la etapa
				# corre. Sin esto, una etapa de más de `ttl` pierde el claim a mitad
				# y otro driver la roba mientras sigue en vuelo — dos ejecutando lo
				# mismo. Es un latido PROPIO y no un hook de checkpoint: las etapas
				# atómicas pueden no emitir checkpoints intermedios, así que atar la
				# renovación a ellos no cubriría justo los casos largos.
				renewer = self._start_claim_renewer(payload, stage_path, str(workdir))
			return self._run_atomic_inner(payload, stage, stage_path, gate, workdir)
		finally:
			if renewer is not None:
				renewer.set()  # para el latido antes de soltar (evita renovar lo liberado)
			if claim is not None and claim.claimed:
				# Se suelta al terminar (o al diferir/pausar).
				self._release_stage_claim(payload, stage_path, str(workdir))

	def _run_atomic_inner(self, payload: Dict[str, Any], stage: Dict[str, Any], stage_path: str, gate: Any, workdir: Any) -> str:
		"""Cuerpo original de `_run_atomic` (sin claim). Ver `_run_atomic`."""

		from red_pill.jobs.drivers.base import build_pause_probe
		from red_pill.swarm.factory import MinionFactory

		minion = MinionFactory.create(str(stage.get("minion")))
		if minion is None:
			raise RuntimeError(f"dag stage '{stage_path}' minion no registrado.")

		task = stage.get("prompt") or stage.get("command") or ""
		# Instancia de fan-out (RFC §4.6): inyectar el item y renderizar `{{item}}`
		# en prompt/command; el minion lo recibe además como kwargs["item"].
		item = stage.get("_item")
		kwargs: Dict[str, Any] = {"cwd": str(workdir), "timeout": self._stage_timeout(stage, payload)}
		identity: Dict[str, Any] = {}
		continuity = payload.get("continuity_id")
		if continuity:
			identity = {
				"continuity_id": str(continuity),
				"mission_id": str(payload.get("mission_id") or ""),
				"job_id": str(getattr(self, "job_id", "") or ""),
				"originator": f"dag:{self.job_id}" if getattr(self, "job_id", None) else "",
				"role": str(payload.get("role") or "job"),
			}
			parent = payload.get("parent_mission_id")
			if parent:
				identity["parent_mission_id"] = str(parent)
			kwargs.update(identity)
		if item is not None:
			task = _render_item(task, item)
			kwargs["item"] = item
		for key in ("backend", "model", "effort", "mode"):
			if stage.get(key) or payload.get(key):
				kwargs[key] = stage.get(key) or payload.get(key)
		# Origin fluye del payload (o de la etapa) a los minions agénticos para
		# que el cron no confunda una sesión de un DAG con actividad del operador.
		if stage.get("origin") or payload.get("origin"):
			kwargs["origin"] = stage.get("origin") or payload.get("origin")
		if stage.get("command"):
			kwargs["command"] = task
		if isinstance(stage.get("params"), dict):
			protected = _PROTECTED_STAGE_PARAMS & set(stage["params"])
			if protected:
				raise ValueError(f"dag_job stage '{stage_path}' params no puede fijar claves de política: {sorted(protected)}")
			kwargs.update({k: _render_item(v, item) if item is not None else v for k, v in stage["params"].items()})
		if identity and stage.get("type") == _TYPE_AGENT:
			task = (
				task
				+ "\n\n<redpill-identity>\n"
				+ "\n".join(f"{key}: {value}" for key, value in identity.items())
				+ "\n</redpill-identity>"
			)
		# AD-030 (v3): el bloque `llm:` POR ETAPA en el manifest del
		# dag_job (coherencia DAG-001: cada instancia DISTILL×N/REFINE×M del
		# fan-out futuro declara su modelo/modo). Los minions command lo reciben
		# como env RP_LLM_*; los agénticos hablan con el daemon directamente.
		stage_llm = stage.get("llm") or {}
		if isinstance(stage_llm, dict) and stage_llm:
			try:
				from red_pill.jobs.drivers.base import inject_llm_env

				llm_env = inject_llm_env({"llm": stage_llm}, job_id=self.job_id, cwd=str(workdir))
			except ValueError as e:
				raise RuntimeError(f"dag stage '{stage_path}' llm inválido: {e}") from e
			if llm_env:
				base_env = dict(os.environ)
				base_env.update(llm_env)
				kwargs["env"] = base_env
		# Contexto del job para minions de lógica (sueño): la sonda de pausa a
		# mitad de fase (solo si la etapa es `pausable`) y el cutoff que ancla el
		# drenaje al momento en que ARRANCÓ el job (persistido en el checkpoint,
		# inmune a pause/resume).
		if identity:
			env = dict(kwargs.get("env") or os.environ)
			env.update({f"REDPILL_{key.upper()}": str(value) for key, value in identity.items()})
			kwargs["env"] = env
		kwargs.setdefault(
			"pause_probe",
			build_pause_probe(self.job_id, gate=gate) if stage.get("pausable", True) else None,
		)
		kwargs.setdefault("sleep_cutoff_ts", getattr(self, "_sleep_cutoff_ts", 0.0))
		kwargs["job_id"] = self.job_id  # hard: neither payload nor params may divert it (SHARD-PSEC-01)

		# Fine intra-stage progress channel (RFC-JOBDAG-002): a single helper enables
		# `$RP_PROGRESS_FILE` for the child; `job list` reads it (best-effort) only for
		# PROCESSING jobs. Uniform across the script/element/dag drivers — the child
		# decides whether to publish, so no per-stage opt-in is required.
		if self.job_id:
			from red_pill.core.progress import enable_stage_progress

			kwargs["env"] = enable_stage_progress(dict(kwargs.get("env") or os.environ), self.job_id)

		result = asyncio.run(minion.execute(task, **kwargs))

		reports_dir = workdir / ".cell" / "reports"
		suffix = ".envelope.json" if stage.get("type") == _TYPE_AGENT else ".json"
		report_path = reports_dir / f"{stage_path}{suffix}"
		if not report_path.resolve().is_relative_to(reports_dir.resolve()):
			raise ValueError(f"dag stage '{stage_path}' report path escapes '.cell/reports'.")
		report_path.parent.mkdir(parents=True, exist_ok=True)
		report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

		status = result.get("status")
		if status in ("failed", "error") or (result.get("returncode") not in (None, 0)):
			raise RuntimeError(f"dag stage '{stage_path}' failed: {result.get('error') or result.get('stderr') or ''}")
		summary = str(result.get("summary") or result.get("status") or result.get("response") or stage_path)
		return summary
