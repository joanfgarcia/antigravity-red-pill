"""ElementJobDriver — driver MAP reanudable: N elementos, un step por elemento.

Template del patrón recurrente "bucle sobre exactamente N elementos, pausable
por elemento" (2026-09-15, diseñado tras el incidente de la redestilación
`f6493c71`): destilar N sesiones, recalcular N ficheros, emitir N reportes... un
job genérico que recorre una lista de elementos con una función por elemento.

- **Inicialización**: obtiene la lista de elementos de forma declarativa:
	`elements` (lista inline), `elements_file` (JSON en disco) o
	`elements_command` (un comando que imprime el JSON de la lista). N se fija en
	el primer step y se guarda en el checkpoint → el bucle procesa EXACTAMENTE N
	elementos aunque la fuente cambie a mitad.
- **Bucle**: UN step = UN elemento. La función de invocación es `step_command`
	(cualquier comando del proyecto), que recibe el elemento por env `RP_ELEMENT`
	(JSON serializado) y, si el payload lo pide, también como argumento.
- **Watchdog**: `control.max_step_minutes` mata el step (cgroup, hijos CUDA
	incluidos) si un elemento cuelga → JobStepTimeout. Un elemento que "ahora no
	puede" (defer_exit_code) o que "exige revisión" (pause_exit_code) se señala.
- **Pausable / reanudable**: el índice vive en el checkpoint del driver; resume
	exacto en la frontera del elemento. `job_pause`/`job_resume` operan ahí.

El driver es agnóstico del satélite (igual que `script_job`): el proyecto aporta
el comando por elemento y el origen de la lista en su receta YAML.
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
from typing import Any, Dict, List, Tuple

from red_pill.jobs.drivers import register_driver
from red_pill.jobs.drivers.base import (
	JobDeferred,
	JobPauseRequested,
	JobStepTimeout,
	ResumableJobDriver,
	StepOutcome,
	job_log_path,
)

logger = logging.getLogger(__name__)


@register_driver
class ElementJobDriver(ResumableJobDriver):
	source = "element_job"
	min_vram_mb = 0  # El preflight declarativo decide (igual que script_job)

	# ── Validación en el submit ────────────────────────────────────────────

	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		step = payload.get("step_command")
		if not step:
			raise ValueError("payload.step_command es obligatorio (la función por elemento)")
		if not isinstance(step, (str, list)):
			raise ValueError("payload.step_command debe ser string o lista de argumentos")
		if not any(k in payload for k in ("elements", "elements_file", "elements_command")):
			raise ValueError("payload debe declarar `elements`, `elements_file` o `elements_command`")
		if payload.get("elements_file"):
			path = cls._resolve_path(payload["elements_file"], payload.get("cwd") or os.getcwd())
			if not path.exists():
				raise ValueError(f"payload.elements_file no existe: {path}")
		for code_key in ("defer_exit_code", "pause_exit_code", "skip_exit_code"):
			code = payload.get(code_key)
			if code is not None and (not isinstance(code, int) or not (1 <= code <= 255) or code in (124, 137, 143)):
				raise ValueError(f"payload.{code_key} debe ser un entero 1-255 distinto de 124/137/143")
		exit_codes = {k: payload.get(k) for k in ("defer_exit_code", "pause_exit_code", "skip_exit_code") if payload.get(k) is not None}
		if len(set(exit_codes.values())) != len(exit_codes):
			raise ValueError("defer_exit_code, pause_exit_code y skip_exit_code no pueden coincidir")

	# ── Preflight (requisitos declarativos) ────────────────────────────────

	def preflight(self, payload: Dict[str, Any]) -> None:
		pre = payload.get("preflight") or {}
		if pre.get("llm_required") and not self._llm_healthy(self._llm_port()):
			raise JobDeferred("LLM local no responde — se difiere hasta que la GPU/LLM se libere")

	@staticmethod
	def _llm_port() -> int:
		try:
			import red_pill.config as cfg

			env = getattr(cfg, "MLX_LM_URL", "") or ""
			if env and ":" in env:
				import re

				m = re.search(r":(\d+)", env)
				if m:
					return int(m.group(1))
		except Exception:
			pass
		return 8760

	@staticmethod
	def _llm_healthy(port: int) -> bool:
		import urllib.request

		for path in ("/health", "/v1/models"):
			try:
				resp = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)
				if resp.status == 200:
					return True
			except Exception:
				continue
		return False

	# ── Inicialización: origen de los elementos ────────────────────────────

	@staticmethod
	def _resolve_path(ref: str, cwd: str) -> Path:
		p = Path(ref)
		return p if p.is_absolute() else Path(cwd) / p

	def _load_elements(self, payload: Dict[str, Any], cwd: str) -> List[Any]:
		"""Resuelve la lista de elementos (inline, fichero o comando)."""
		if "elements" in payload:
			items = payload["elements"]
			if not isinstance(items, list):
				raise RuntimeError("payload.elements debe ser una lista")
			return list(items)
		if "elements_file" in payload:
			try:
				data = json.loads(self._resolve_path(payload["elements_file"], cwd).read_text(encoding="utf-8"))
			except Exception as e:
				raise RuntimeError(f"elements_file ilegible: {e}") from e
			if not isinstance(data, list):
				raise RuntimeError("elements_file debe contener un array JSON")
			return list(data)
		# elements_command: un comando que imprime el JSON de la lista
		argv = payload["elements_command"]
		argv = list(argv) if isinstance(argv, list) else shlex.split(argv)
		proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60)
		if proc.returncode != 0:
			raise RuntimeError(f"elements_command falló (rc={proc.returncode}): {proc.stderr.strip()[:200]}")
		try:
			data = json.loads(proc.stdout)
		except Exception as e:
			raise RuntimeError(f"elements_command no imprimió un JSON array válido: {e}") from e
		if not isinstance(data, list):
			raise RuntimeError("elements_command debe imprimir un array JSON")
		return list(data)

	# ── Paso atómico: UN elemento ──────────────────────────────────────────

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		cwd = payload.get("cwd") or os.getcwd()
		total = int(checkpoint_data.get("total", -1))
		index = int(checkpoint_data.get("index", 0))
		skipped: List[int] = list(checkpoint_data.get("skipped") or [])

		if total < 0:
			# Primer step: fija la LISTA y N, y la congela en el checkpoint.
			elements = self._load_elements(payload, cwd)
			total = len(elements)
		else:
			elements = checkpoint_data.get("elements")
			if elements is None:
				# Reanudación de un checkpoint anterior sin lista congelada: re-lee.
				elements = self._load_elements(payload, cwd)
		if index >= total:
			return StepOutcome(
				completed=True,
				new_checkpoint={"index": total, "total": total, "elements": elements, "skipped": skipped},
				summary=f"{payload.get('title') or self.short_id}: {total} elementos procesados ({len(skipped)} saltados).",
				progress={"current": total, "total": total, "percent": 100},
			)
		if index >= len(elements):
			# La lista se CONGELÓ en el primer step; si un checkpoint viejo no la
			# trae y la fuente es dinámica (se encoge al consumir), el índice ya no
			# existe. Mejor fallar con instrucción que repetir inestable.
			raise RuntimeError(
				f"elemento {index} fuera de rango: la lista congelada tiene {len(elements)} < {total} "
				f"(¿checkpoint previo al fix de lista congelada?) — descarta el job y re-encola"
			)

		element = elements[index]

		# skip/next del operador (`job_skip`): no ejecutar el elemento actual,
		# avanzar el índice marcándolo `skipped` y consumir la marca (no viaja
		# al siguiente step). Es la misma frontera que pause/resume.
		if checkpoint_data.get("skip_next"):
			skipped.append(index)
			index += 1
			percent = min(100, int(100 * index / total)) if total > 0 else 100
			return StepOutcome(
				completed=index >= total,
				new_checkpoint={"index": index, "total": total, "elements": elements, "skipped": skipped},
				summary=f"{payload.get('title') or self.short_id}: elemento {index}/{total} saltado (skip del operador).",
				progress={"current": index, "total": total, "percent": percent},
			)

		elapsed, returncode = self._run_command(payload, cwd, element, index)

		if returncode != 0:
			if returncode == payload.get("defer_exit_code"):
				raise JobDeferred(f"el elemento {index} pidió deferral (exit {returncode})")
			if returncode == payload.get("pause_exit_code"):
				raise JobPauseRequested(f"el elemento {index} pidió revisión del operador (exit {returncode})")
			if returncode == payload.get("skip_exit_code"):
				# "salta este elemento, no lo reintentes": se marca y avanza el índice.
				skipped.append(index)
				index += 1
				percent = min(100, int(100 * index / total)) if total > 0 else 100
				return StepOutcome(
					completed=index >= total,
					new_checkpoint={"index": index, "total": total, "elements": elements, "skipped": skipped},
					summary=f"{payload.get('title') or self.short_id}: elemento {index}/{total} saltado (skip_exit_code {returncode}).",
					progress={"current": index, "total": total, "percent": percent},
				)
			if self._looks_like_timeout(elapsed, returncode):
				raise JobStepTimeout(elapsed_s=elapsed, bound_s=self.step_timeout_s, ema_s=elapsed, attempt=self.attempts + 1)
			tail = self._log_tail()
			raise RuntimeError(f"elemento {index} falló (rc={returncode}) tras {elapsed / 60:.1f} min: {tail}")

		index += 1
		new_checkpoint = {"index": index, "total": total, "elements": elements, "skipped": skipped}
		percent = min(100, int(100 * index / total)) if total > 0 else 100
		return StepOutcome(
			completed=index >= total,
			new_checkpoint=new_checkpoint,
			summary=f"{payload.get('title') or self.short_id}: elemento {index}/{total} procesado (step {elapsed / 60:.1f} min).",
			progress={"current": index, "total": total, "percent": percent},
		)

	# ── Ejecución del comando por elemento (systemd-run + RP_ELEMENT) ──────

	def _run_command(self, payload: Dict[str, Any], cwd: str, element: Any, index: int) -> Tuple[float, int]:
		argv = self._build_argv(payload, cwd)
		env = self._build_env(payload, cwd, element, index)
		log_path = self._log_path()
		log_path.parent.mkdir(parents=True, exist_ok=True)

		started = time.time()
		with open(log_path, "a", encoding="utf-8") as log_file:
			log_file.write(f"\n===== elemento {index} | job {self.short_id} | intento {self.attempts + 1} | cota {self.step_timeout_s}s =====\n")
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
		command = payload["step_command"]
		argv = list(command) if isinstance(command, list) else shlex.split(command)
		candidate = Path(cwd) / argv[0]
		if not os.path.isabs(argv[0]) and candidate.exists():
			argv[0] = os.path.abspath(candidate)
		if not self._has_systemd():
			return argv
		scope = ["systemd-run", "--user", "--scope", "--quiet", f"--unit=redpill-job-{self.short_id}", "-p", "MemoryMax=10G"]
		if self.step_timeout_s:
			scope += ["-p", f"RuntimeMaxSec={int(self.step_timeout_s)}"]
		self._clear_stale_scope()
		return scope + argv

	def _build_env(self, payload: Dict[str, Any], cwd: str, element: Any, index: int) -> Dict[str, str]:
		env = dict(os.environ)
		env.update({str(k): str(v) for k, v in (payload.get("env") or {}).items()})
		# El elemento a tratar: JSON serializado + índice (para logs y selección).
		env["RP_ELEMENT"] = json.dumps(element, ensure_ascii=False)
		env["RP_ELEMENT_INDEX"] = str(index)
		if payload.get("defer_exit_code") is not None:
			env["RP_DEFER_EXIT_CODE"] = str(payload["defer_exit_code"])
		if payload.get("pause_exit_code") is not None:
			env["RP_PAUSE_EXIT_CODE"] = str(payload["pause_exit_code"])
		if payload.get("skip_exit_code") is not None:
			env["RP_SKIP_EXIT_CODE"] = str(payload["skip_exit_code"])
		env["PYTHONUNBUFFERED"] = "1"
		return env

	@staticmethod
	def _has_systemd() -> bool:
		return shutil.which("systemd-run") is not None

	def _clear_stale_scope(self) -> None:
		unit = f"redpill-job-{self.short_id}.scope"
		try:
			active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit], timeout=5).returncode == 0
			if active:
				subprocess.run(["systemctl", "--user", "stop", unit], check=False, capture_output=True, timeout=15)
			subprocess.run(["systemctl", "--user", "reset-failed", unit], check=False, capture_output=True, timeout=5)
		except Exception:
			pass

	def _looks_like_timeout(self, elapsed: float, returncode: int) -> bool:
		if not self.step_timeout_s:
			return False
		if returncode in (124, 137, 143, -9, -15) and elapsed >= self.step_timeout_s * 0.9:
			return True
		return elapsed >= self.step_timeout_s

	def _log_path(self) -> Path:
		return job_log_path(self.job_id)

	def _log_tail(self, lines: int = 25) -> str:
		try:
			content = self._log_path().read_text(encoding="utf-8", errors="replace").strip().splitlines()
			return "\n".join(content[-lines:]) if content else "(sin salida)"
		except Exception:
			return "(log no disponible)"
