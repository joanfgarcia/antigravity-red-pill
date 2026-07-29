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
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.jobs.drivers.base import (
	JobDeferred,
	JobPauseRequested,
	JobStepTimeout,
	ResumableJobDriver,
	StepOutcome,
	append_job_log,
	human_duration,
	job_log_path,
)

logger = logging.getLogger(__name__)

_VALID_MODES = ("single", "bounded", "unbounded")


class _CheckpointWatcher:
	"""Vigila el fichero de checkpoint MIENTRAS corre el step.

	La granularidad que importa no es cuánto vive el proceso, sino cada cuánto
	deja algo registrado: eso es lo que se pierde al interrumpirlo y desde donde
	se retoma. Un step puede contener varios guardados, así que medirlo por el
	mtime de antes y después lo inflaría hasta la duración del step entero.
	Aquí se observa cada escritura, con su intervalo real.
	"""

	def __init__(self, state_path: Optional[Path], job_id: str, poll_seconds: float = 1.0):
		self._state_path = state_path
		self._job_id = job_id
		self._poll = poll_seconds
		self._stop = threading.Event()
		self._thread: Optional[threading.Thread] = None
		self._last_mtime: Optional[float] = None
		self._last_seen: float = 0.0
		self.intervals: List[float] = []
		self.writes: int = 0

	def __enter__(self) -> "_CheckpointWatcher":
		self._last_mtime = self._current_mtime()
		self._last_seen = time.time()
		if self._state_path is not None:
			self._thread = threading.Thread(target=self._watch, name="rp-checkpoint-watch", daemon=True)
			self._thread.start()
		return self

	def __exit__(self, *exc: Any) -> None:
		self._stop.set()
		if self._thread:
			self._thread.join(timeout=max(2.0, self._poll * 2))
		# Última mirada: el guardado más importante es el del final de la época, y
		# el proceso sale acto seguido — entre el último sondeo y su muerte cabe
		# justo esa escritura. Sin este cierre, se perdería la que más importa.
		self._check_once()

	def _watch(self) -> None:
		while not self._stop.wait(self._poll):
			self._check_once()

	def _check_once(self) -> None:
		mtime = self._current_mtime()
		if mtime is None or mtime == self._last_mtime:
			return
		now = time.time()
		if self._last_mtime is not None:
			self.intervals.append(now - self._last_seen)
		self.writes += 1
		note = f" (+{human_duration(self.intervals[-1])} desde el anterior)" if self.intervals else " (primero observado en este step)"
		append_job_log(self._job_id, f"checkpoint escrito por el satélite{note}")
		self._last_mtime, self._last_seen = mtime, now

	def _current_mtime(self) -> Optional[float]:
		try:
			return self._state_path.stat().st_mtime if self._state_path and self._state_path.exists() else None
		except OSError:
			return None


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
	checkpoint_poll_seconds = 1.0  # Sondeo del vigilante de checkpoints (un stat() por segundo)

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

		for code_key in ("defer_exit_code", "pause_exit_code"):
			code = payload.get(code_key)
			if code is not None:
				# 124/137/143 son los códigos canónicos de muerte por cota/señal: si el
				# satélite los usara como señal, un cuelgue real se malinterpretaría eternamente.
				if not isinstance(code, int) or not (1 <= code <= 255) or code in (124, 137, 143):
					raise ValueError(f"payload.{code_key} debe ser un entero 1-255 distinto de 124/137/143 (recibido: {code!r})")
		if payload.get("defer_exit_code") is not None and payload.get("defer_exit_code") == payload.get("pause_exit_code"):
			raise ValueError("defer_exit_code y pause_exit_code no pueden coincidir: significan cosas distintas")

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
		for service in (payload.get("teardown") or {}).get("restore_services") or []:
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
		elapsed, returncode, cadence = self._run_command(payload, cwd, state_path)

		if returncode != 0:
			# El satélite puede declarar un código de salida que significa "ahora no
			# puedo, reintenta" (p.ej. el sueño con la GPU comprometida): deferral
			# limpio (R1) en vez de dar el step por completado o quemar un intento.
			if returncode == payload.get("defer_exit_code"):
				raise JobDeferred(f"el satélite pidió deferral (exit {returncode})")
			# ...o "esto exige juicio del operador" (un examen suspendido K veces):
			# PAUSED con checkpoint intacto, reanudable con `job resume` tras revisar.
			if returncode == payload.get("pause_exit_code"):
				raise JobPauseRequested(f"el satélite pidió revisión del operador (exit {returncode})")
			tail = self._log_tail()
			if self._looks_like_timeout(elapsed, returncode):
				raise JobStepTimeout(elapsed_s=elapsed, bound_s=self.step_timeout_s, ema_s=elapsed, attempt=self.attempts + 1)
			raise RuntimeError(f"step_command falló (rc={returncode}) tras {elapsed / 60:.1f} min: {tail}")

		state = self._read_state(state_path)
		progress, completed = self._evaluate(payload, state)
		meta = self._record_cadence(cadence, elapsed, meta, progress)
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

	def _run_command(self, payload: Dict[str, Any], cwd: str, state_path: Optional[Path] = None) -> Tuple[float, int, "_CheckpointWatcher"]:
		"""Lanza el comando bajo cgroups y devuelve (segundos, returncode, cadencia).

		stdout y stderr se transmiten al log del job — nunca se acumulan en
		memoria ni se pierden tras el banner de systemd-run. En paralelo se
		observa el fichero de checkpoint para saber cada cuánto deja el satélite
		un avance recuperable de verdad.
		"""
		argv = self._build_argv(payload, cwd)
		env = self._build_env(payload)
		log_path = self._log_path()
		log_path.parent.mkdir(parents=True, exist_ok=True)

		started = time.time()
		with open(log_path, "a", encoding="utf-8") as log_file:
			log_file.write(
				f"\n===== step {time.strftime('%Y-%m-%d %H:%M:%S')} | job {self.short_id} | intento {self.attempts + 1} | cota {self.step_timeout_s}s =====\n"
			)
			log_file.flush()
			with _CheckpointWatcher(state_path, self.job_id, self.checkpoint_poll_seconds) as watcher:
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

		return time.time() - started, returncode, watcher

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
		# Absoluto SIN resolve(): el python de un venv es un symlink al intérprete
		# base, y seguirlo lo saca del venv (el intérprete localiza pyvenv.cfg por
		# la ruta con la que se le invoca) — el step moría con ModuleNotFoundError
		# de sus propias dependencias (job ef18de08, 2026-07-28).
		candidate = Path(cwd) / argv[0]
		if not os.path.isabs(argv[0]) and candidate.exists():
			argv[0] = os.path.abspath(candidate)

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
			subprocess.run(["systemctl", "--user", "reset-failed", unit], check=False, capture_output=True, timeout=5)
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
			raise RuntimeError(
				f"reanudación sucia (causa: {reason}): falta el checkpoint {state_path} pese a haber avance previo — revisar antes de relanzar"
			)
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
			return value == completion["equals"] if "equals" in completion else False
		if "contains" in completion:
			return bool(value) and completion["contains"] in value
		return bool(value)

	def _record_cadence(self, watcher: "_CheckpointWatcher", elapsed: float, meta: Dict[str, Any], progress: Dict[str, Any]) -> Dict[str, Any]:
		"""Consolida lo observado: cuántas veces guardó el satélite y cada cuánto.

		Distingue las dos magnitudes que es fácil confundir: la duración del step
		(cuánto vive el proceso) y la cadencia de checkpoint (cuánto trabajo se
		pierde si lo interrumpes). Cuando el satélite guarda una sola vez por
		step, ambas coinciden y el step ES la unidad recuperable; cuando guarda
		varias, el step podría trocearse y el job volverse interrumpible.
		"""
		writes = watcher.writes
		progress["checkpoint_writes_in_step"] = writes
		cadence: float | None = None

		if watcher.intervals:
			cadence = round(sum(watcher.intervals) / len(watcher.intervals), 1)
		elif writes >= 1:
			# Un único guardado: la unidad recuperable es el step completo.
			cadence = round(elapsed, 1)
		else:
			# Sin escrituras observadas no hay medición: `None` (no 0.0) para que
			# el guard de abajo no publique una cadencia inventada de cero.
			stored = meta.get("checkpoint_interval_s")
			cadence = float(stored) if stored is not None else None

		if cadence is not None:
			meta["checkpoint_interval_s"] = cadence
			progress["checkpoint_interval_s"] = cadence
			append_job_log(
				self.job_id,
				f"cadencia observada: {writes} checkpoint(s) en un step de {human_duration(elapsed)} → unidad recuperable ≈ {human_duration(cadence)}",
			)

		return meta

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
