"""ScriptJobDriver — driver paramétrico genérico de procesos externos.

Ejecuta cualquier script por pasos sin que el kernel conozca al proyecto
satélite: toda la receta (comando, checkpoint, progreso, preflight) viaja
declarativamente en el payload del job. Ver `Aleth_Core/RFC_GENERIC_SCRIPT_JOB_DRIVER.md`.

	kernel (agnóstico)                  satélite (dueño de su lógica)
	ScriptJobDriver  ←── payload JSON ──  script + checkpoint_file
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.jobs.drivers.base import JobDeferred, JobStepTimeout, ResumableJobDriver, StepOutcome, job_log_path

logger = logging.getLogger(__name__)

_VALID_MODES = ("single", "bounded", "unbounded")


def _dig(data: Dict[str, Any], key_path: str) -> Any:
	"""Lee una clave declarativa del checkpoint, con soporte de ruta `a.b.c`."""
	node: Any = data
	for part in str(key_path).split("."):
		if not isinstance(node, dict) or part not in node:
			return None
		node = node[part]
	return node


class ScriptJobDriver(ResumableJobDriver):
	source = "script_job"
	min_vram_mb = 0  # El preflight declarativo decide; el gate genérico del runner no aplica aquí

	# ── Validación en el submit ────────────────────────────────────────────

	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		"""Rechaza payloads incoherentes AL ENCOLAR, no tres intentos después."""
		if not payload.get("step_command"):
			raise ValueError("payload.step_command es obligatorio")

		command = payload["step_command"]
		if not isinstance(command, (str, list)):
			raise ValueError("payload.step_command debe ser string o lista de argumentos")
		if isinstance(command, list) and not all(isinstance(part, str) for part in command):
			raise ValueError("payload.step_command como lista solo admite strings")

		cwd = payload.get("cwd")
		if cwd and not os.path.isdir(cwd):
			raise ValueError(f"payload.cwd no existe: {cwd}")

		progress = payload.get("progress") or {}
		mode = progress.get("mode", "single")
		if mode not in _VALID_MODES:
			raise ValueError(f"payload.progress.mode debe ser uno de {_VALID_MODES} (recibido: {mode!r})")

		if mode != "single" and not payload.get("checkpoint_file"):
			raise ValueError(f"el modo '{mode}' exige payload.checkpoint_file (solo 'single' puede prescindir de él)")
		if mode != "single" and not progress.get("current_key"):
			raise ValueError(f"el modo '{mode}' exige payload.progress.current_key")
		if mode == "bounded" and not progress.get("total") and not progress.get("total_key"):
			raise ValueError("el modo 'bounded' exige progress.total o progress.total_key")
		if mode == "unbounded" and not (payload.get("completion") or {}).get("key"):
			logger.warning("[SCRIPT JOB] modo 'unbounded' sin completion.key: el job será perpetuo hasta pause/kill.")

		if progress.get("stage_current_key") and not (progress.get("stage_total") or progress.get("stage_total_key")):
			raise ValueError("progress.stage_current_key exige stage_total o stage_total_key")

	# ── Preflight / teardown de entorno ────────────────────────────────────

	def preflight(self, payload: Dict[str, Any]) -> None:
		import red_pill.config as cfg
		from red_pill.core.vram_probe import VramProbe

		pre = payload.get("preflight") or {}

		# Preferente: pedir al proxy dual-bind que vacíe la VRAM sin tumbar el
		# servicio (recarga bajo demanda). Fallback histórico: parar unidades.
		if pre.get("vram_unload"):
			self._request_vram_unload(str(cfg.DUAL_BIND_PROXY_URL))

		for service in pre.get("stop_services") or []:
			self._systemctl("stop", service)

		min_free = int(pre.get("min_free_vram_mb", 0))
		if min_free > 0:
			free_mb = VramProbe.get_free_mb()
			if free_mb < min_free:
				raise JobDeferred(f"VRAM insuficiente ({free_mb}MB libres < {min_free}MB)")

	def teardown(self, payload: Dict[str, Any]) -> None:
		"""Restaura servicios en TODAS las salidas (incluido el deferral nocturno)."""
		for service in ((payload.get("teardown") or {}).get("restore_services") or []):
			self._systemctl("start", service)

	@staticmethod
	def _request_vram_unload(base_url: str) -> None:
		import urllib.request

		try:
			request = urllib.request.Request(f"{base_url.rstrip('/')}/v1/unload", method="POST")
			with urllib.request.urlopen(request, timeout=5) as response:
				if response.status == 200:
					logger.info("[SCRIPT JOB] VRAM liberada en el proxy dual-bind.")
					time.sleep(2.0)  # El driver CUDA no devuelve la memoria al instante
		except Exception as e:
			logger.debug(f"[SCRIPT JOB] Proxy dual-bind inalcanzable para unload: {e}")

	@staticmethod
	def _systemctl(action: str, unit: str) -> None:
		try:
			subprocess.run(["systemctl", "--user", action, unit], check=False, capture_output=True, timeout=30)
		except Exception as e:
			logger.warning(f"[SCRIPT JOB] systemctl {action} {unit} falló: {e}")

	# ── Paso atómico ───────────────────────────────────────────────────────

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		cwd = payload.get("cwd") or os.getcwd()
		state_path = self._resolve_state_path(payload, cwd)
		meta = dict(checkpoint_data.get("_rp_meta") or {})

		# Reanudación tras una interrupción dura: el checkpoint del satélite
		# puede no estar limpio. Se valida ANTES de relanzar — nunca se reinicia
		# desde cero en silencio.
		if checkpoint_data.get("dirty_kill"):
			had_progress = any(key not in ("dirty_kill", "_rp_meta") for key in checkpoint_data)
			self._validate_after_dirty_kill(checkpoint_data["dirty_kill"], state_path, had_progress)

		previous_state = self._read_state(state_path)
		elapsed, returncode = self._run_command(payload, cwd)

		if returncode != 0:
			tail = self._log_tail()
			if self._looks_like_timeout(elapsed, returncode):
				raise JobStepTimeout(elapsed_s=elapsed, bound_s=self.step_timeout_s, ema_s=elapsed, attempt=self.attempts + 1)
			raise RuntimeError(f"step_command falló (rc={returncode}) tras {elapsed / 60:.1f} min: {tail}")

		state = self._read_state(state_path)
		progress, completed = self._evaluate(payload, state)
		meta = self._check_stall(payload, meta, previous_state, state, progress)

		new_checkpoint: Dict[str, Any] = dict(state)
		new_checkpoint["_rp_meta"] = meta

		return StepOutcome(
			completed=completed,
			new_checkpoint=new_checkpoint,
			summary=self._summary(payload, progress, completed, elapsed),
			progress=progress,
		)

	# ── Ejecución del comando ──────────────────────────────────────────────

	def _run_command(self, payload: Dict[str, Any], cwd: str) -> Tuple[float, int]:
		"""Lanza el comando bajo cgroups y devuelve (segundos, returncode).

		stdout y stderr se transmiten al log del job — nunca se acumulan en
		memoria ni se pierden tras el banner de systemd-run.
		"""
		argv = self._build_argv(payload, cwd)
		env = self._build_env(payload)
		log_path = self._log_path()
		log_path.parent.mkdir(parents=True, exist_ok=True)

		started = time.time()
		with open(log_path, "a", encoding="utf-8") as log_file:
			log_file.write(f"\n===== step {time.strftime('%Y-%m-%d %H:%M:%S')} | job {self.short_id} | intento {self.attempts + 1} | cota {self.step_timeout_s}s =====\n")
			log_file.flush()
			try:
				proc = subprocess.run(
					argv,
					cwd=cwd,
					env=env,
					stdout=log_file,
					stderr=subprocess.STDOUT,
					check=False,
					timeout=self.step_timeout_s if (self.step_timeout_s and not self._has_systemd()) else None,
				)
				returncode = proc.returncode
			except subprocess.TimeoutExpired:
				log_file.write("\n[TIMEOUT] step abatido por la cota de tiempo.\n")
				returncode = 124

		return time.time() - started, returncode

	def _build_argv(self, payload: Dict[str, Any], cwd: str) -> List[str]:
		"""Tokeniza el comando y lo envuelve en un scope con nombre.

		El nombre determinista (`redpill-job-<id8>.scope`) es lo que permite el
		`job kill` limpio y `RuntimeMaxSec` como detector de cuelgue: el step
		vencido muere como cgroup completo, hijos CUDA incluidos.
		"""
		command = payload["step_command"]
		# String → shlex (jamás shell=True implícito); lista → tal cual. Quien
		# necesite pipes escribe ["sh", "-c", "..."] de forma explícita.
		argv = list(command) if isinstance(command, list) else shlex.split(command)
		if not argv:
			raise ValueError("step_command vacío tras tokenizar")

		# Rutas relativas al cwd resueltas a absoluto: systemd-run no las resuelve.
		candidate = Path(cwd) / argv[0]
		if not os.path.isabs(argv[0]) and candidate.exists():
			argv[0] = str(candidate.resolve())

		if not self._has_systemd():
			return argv

		memory_max = (payload.get("preflight") or {}).get("memory_max", "10G")
		scope = ["systemd-run", "--user", "--scope", "--quiet", f"--unit=redpill-job-{self.short_id}", "-p", f"MemoryMax={memory_max}"]
		if self.step_timeout_s:
			scope += ["-p", f"RuntimeMaxSec={int(self.step_timeout_s)}"]

		self._clear_stale_scope()
		return scope + argv

	def _build_env(self, payload: Dict[str, Any]) -> Dict[str, str]:
		env = dict(os.environ)
		env.update({str(k): str(v) for k, v in (payload.get("env") or {}).items()})
		env["PYTHONUNBUFFERED"] = "1"  # Sin esto el log del job llega a trozos y tarde
		return env

	@staticmethod
	def _has_systemd() -> bool:
		return shutil.which("systemd-run") is not None

	def _clear_stale_scope(self) -> None:
		"""Retira un scope homónimo huérfano de un crash previo (el flock impide concurrencia real)."""
		unit = f"redpill-job-{self.short_id}.scope"
		try:
			active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit], timeout=5).returncode == 0
			if active:
				logger.warning(f"[SCRIPT JOB] Retirando scope huérfano {unit}.")
				subprocess.run(["systemctl", "--user", "stop", unit], check=False, capture_output=True, timeout=15)
		except Exception:
			pass

	def _looks_like_timeout(self, elapsed: float, returncode: int) -> bool:
		"""¿Lo abatió la cota o falló por sus propios medios?

		Detección por tiempo transcurrido (robusta ante el código de salida que
		propague systemd) y por los códigos canónicos de muerte por señal.
		"""
		if not self.step_timeout_s:
			return False
		if returncode in (124, 137, 143, -9, -15) and elapsed >= self.step_timeout_s * 0.9:
			return True
		return elapsed >= self.step_timeout_s

	# ── Estado, progreso y finalización ────────────────────────────────────

	@staticmethod
	def _resolve_state_path(payload: Dict[str, Any], cwd: str) -> Optional[Path]:
		checkpoint_file = payload.get("checkpoint_file")
		if not checkpoint_file:
			return None
		path = Path(checkpoint_file)
		return path if path.is_absolute() else Path(cwd) / path

	@staticmethod
	def _read_state(state_path: Optional[Path]) -> Dict[str, Any]:
		if not state_path or not state_path.exists():
			return {}
		try:
			with open(state_path, "r", encoding="utf-8") as f:
				data = json.load(f)
			return data if isinstance(data, dict) else {"value": data}
		except json.JSONDecodeError as e:
			raise RuntimeError(f"checkpoint_file corrupto ({state_path}): {e}") from e

	def _validate_after_dirty_kill(self, marker: Dict[str, Any], state_path: Optional[Path], had_progress: bool) -> None:
		"""Tras kill o timeout, el estado del satélite puede no ser reanudable.

		Con el contrato de escritura atómica (tmp + rename) el caso normal es
		limpio; si no lo es, se falla con un mensaje explícito que nombra la
		interrupción previa en lugar de reiniciar el trabajo desde cero.

		Matiz aprendido en la verificación en caliente: si el job cayó durante su
		PRIMER step, no hay checkpoint que validar — empezar de cero es lo
		correcto, no un error. Solo se exige el fichero si ya hubo avance.
		"""
		reason = marker.get("reason", "desconocida")
		if state_path is None:
			return
		if not state_path.exists():
			if not had_progress:
				logger.info(f"[SCRIPT JOB] Reanudando tras interrupción dura ({reason}) sin avance previo: se arranca de cero.")
				return
			raise RuntimeError(f"reanudación sucia (causa: {reason}): falta el checkpoint {state_path} pese a haber avance previo — revisar antes de relanzar")
		self._read_state(state_path)  # Un JSON truncado revienta aquí, con nombre y motivo
		logger.info(f"[SCRIPT JOB] Reanudando tras interrupción dura ({reason}); checkpoint validado.")

	def _evaluate(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
		"""Traduce el estado del satélite a progreso + señal de finalización."""
		spec = payload.get("progress") or {}
		mode = spec.get("mode", "single")
		progress: Dict[str, Any] = {"mode": mode}

		completion = payload.get("completion") or {}
		# `completion` gana en CUALQUIER modo: hay trabajos que terminan por hito
		# evaluado, no por contador (una fase puede cerrar antes o después del total).
		completed_by_signal = self._completion_reached(completion, state) if completion.get("key") else None

		if mode == "single":
			return progress, True if completed_by_signal is None else completed_by_signal

		current = _dig(state, spec["current_key"])
		progress["current"] = current

		total = spec.get("total")
		if spec.get("total_key"):
			total = _dig(state, spec["total_key"]) or total  # Dinámico: currículos que crecen
		if total:
			progress["total"] = total
			if isinstance(current, (int, float)) and isinstance(total, (int, float)) and total > 0:
				progress["percent"] = min(100, int(100 * current / total))

		if spec.get("stage_current_key"):
			stage_current = _dig(state, spec["stage_current_key"])
			stage_total = _dig(state, spec["stage_total_key"]) if spec.get("stage_total_key") else spec.get("stage_total")
			if isinstance(stage_current, (int, float)):
				stage_current += int(spec.get("stage_offset", 0))
			progress.update({"stage_current": stage_current, "stage_total": stage_total, "stage_label": spec.get("stage_label", "fase")})

		if completed_by_signal is not None:
			return progress, completed_by_signal

		# Sin señal declarada: bounded cierra por contador; unbounded es perpetuo.
		if mode == "bounded" and isinstance(current, (int, float)) and isinstance(total, (int, float)):
			return progress, current >= total
		return progress, False

	@staticmethod
	def _completion_reached(completion: Dict[str, Any], state: Dict[str, Any]) -> bool:
		value = _dig(state, completion["key"])
		if "equals" in completion:
			return value == completion["equals"]
		if "contains" in completion:
			return bool(value) and completion["contains"] in value
		return bool(value)

	def _check_stall(
		self,
		payload: Dict[str, Any],
		meta: Dict[str, Any],
		previous_state: Dict[str, Any],
		state: Dict[str, Any],
		progress: Dict[str, Any],
	) -> Dict[str, Any]:
		"""Vigila el bucle estéril: steps que salen con éxito sin avanzar nada.

		Un script con bug que retorna 0 pero no progresa no es fallo, ni cuelgue,
		ni deferral — sin este guard el runner repetiría épocas vacías sin fin.
		"""
		import red_pill.config as cfg

		if payload.get("watchdog") is False:
			return meta

		spec = payload.get("progress") or {}
		if spec.get("current_key"):
			marker = progress.get("current")
			previous_marker = _dig(previous_state, spec["current_key"])
		else:
			marker = json.dumps(state, sort_keys=True, default=str)
			previous_marker = json.dumps(previous_state, sort_keys=True, default=str)

		stalled = previous_state != {} and marker == previous_marker
		meta["stall"] = int(meta.get("stall", 0)) + 1 if stalled else 0

		limit = int(cfg.JOB_STALL_LIMIT)
		if meta["stall"] >= limit:
			raise RuntimeError(f"sin progreso en {limit} steps consecutivos (valor estancado: {marker!r}) — el script sale con éxito pero no avanza")
		return meta

	def _summary(self, payload: Dict[str, Any], progress: Dict[str, Any], completed: bool, elapsed: float) -> str:
		title = payload.get("title") or self.short_id
		if progress.get("mode") == "single":
			return f"{title}: script completado en {elapsed / 60:.1f} min."

		parts = [f"{progress.get('current')}"]
		if progress.get("total"):
			parts.append(f"/{progress['total']}")
		if progress.get("percent") is not None:
			parts.append(f" ({progress['percent']}%)")
		if progress.get("stage_current") is not None:
			parts.append(f" · {progress.get('stage_label', 'fase')} {progress['stage_current']}/{progress.get('stage_total')}")
		state = "completado" if completed else "en curso"
		return f"{title}: {''.join(parts)} — {state} (step {elapsed / 60:.1f} min)."

	# ── Log por job ────────────────────────────────────────────────────────

	def _log_path(self) -> Path:
		return job_log_path(self.job_id)

	def _log_tail(self, lines: int = 25) -> str:
		"""Cola del log — el error real del hijo, no el banner del envoltorio."""
		try:
			content = self._log_path().read_text(encoding="utf-8", errors="replace").strip().splitlines()
			return "\n".join(content[-lines:]) if content else "(sin salida)"
		except Exception:
			return "(log no disponible)"
