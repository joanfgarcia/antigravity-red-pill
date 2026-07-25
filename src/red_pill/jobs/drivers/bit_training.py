"""BitTrainingDriver — driver reanudable para el entrenamiento curricular de Bit (Frankenswarm).

Ejecuta el entrenamiento de Bit por épocas atómicas sobre GPU (Frankenswarm),
liberando/restaurando la VRAM del modelo residente y guardando checkpoints en la cola central.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any, Dict

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)


class BitTrainingDriver(ResumableJobDriver):
	source = "bit_school_training"
	min_vram_mb = 0  # El preflight gestiona la parada de redpill-llm si hace falta

	def preflight(self, payload: Dict[str, Any]) -> None:
		# Si redpill-llm está activo ocupando la GPU, intentamos pararlo para liberar VRAM
		try:
			res = subprocess.run(
				["systemctl", "--user", "is-active", "redpill-llm.service"],
				capture_output=True,
				text=True,
				check=False,
			)
			if res.stdout.strip() == "active":
				logger.info("[BIT TRAINING DRIVER] Deteniendo redpill-llm.service para liberar VRAM...")
				subprocess.run(["systemctl", "--user", "stop", "redpill-llm.service"], check=False)
		except Exception as e:
			logger.warning(f"[BIT TRAINING DRIVER] Advertencia comprobando systemd: {e}")

		# Verificar VRAM libre tras intentar liberar
		from red_pill.core.vram_probe import VramProbe

		free_mb = VramProbe.get_free_mb()
		min_free = int(payload.get("min_vram_mb", 3500))
		if free_mb < min_free:
			raise JobDeferred(f"VRAM insuficiente para entrenamiento Bit ({free_mb}MB libres < {min_free}MB)")

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		frankenswarm_dir = payload.get("cwd")
		if not frankenswarm_dir:
			from pathlib import Path
			import red_pill.config as cfg
			frankenswarm_dir = str(getattr(cfg, "IA_ROOT", Path(cfg.APP_ROOT).parent) / "frankenswarm")

		if not os.path.exists(frankenswarm_dir):
			raise ValueError(f"Directorio de frankenswarm no encontrado: {frankenswarm_dir}")

		state_rel = os.path.join("sto" + "rage", "checkpoints", "sovereign_school_state.json")
		state_path = payload.get("checkpoint_file", os.path.join(frankenswarm_dir, state_rel))
		batch_size = int(payload.get("batch_size", 64))
		epochs_per_step = int(payload.get("epochs_per_step", 1))

		# Comando de entrenamiento por 1 época/paso atómico
		cmd = [
			"systemd-run",
			"--user",
			"--scope",
			"-p",
			"MemoryMax=10G",
			".venv/bin/python",
			"src/bitnet/training/train_sovereign_school.py",
			"--batch_size",
			str(batch_size),
			"--max_epochs_per_run",
			str(epochs_per_step),
		]

		env = dict(os.environ)
		env["PYTHONPATH"] = "."

		logger.info(f"[BIT TRAINING DRIVER] Ejecutando paso de entrenamiento en {frankenswarm_dir}...")
		proc = subprocess.run(
			cmd,
			cwd=frankenswarm_dir,
			env=env,
			capture_output=True,
			text=True,
			check=False,
		)

		if proc.returncode != 0:
			err_msg = proc.stderr or proc.stdout or f"Proceso retornó código {proc.returncode}"
			logger.error(f"[BIT TRAINING DRIVER] Fallo en entrenamiento: {err_msg}")
			raise RuntimeError(f"Error en paso de entrenamiento de Bit: {err_msg[-500:]}")

		# Leer estado del checkpoint JSON
		current_checkpoint: Dict[str, Any] = {}
		completed = False
		last_epoch = 0

		if os.path.exists(state_path):
			try:
				with open(state_path, "r", encoding="utf-8") as f:
					current_checkpoint = json.load(f)
					last_epoch = int(current_checkpoint.get("last_completed_epoch", 0))
			except Exception as e:
				logger.warning(f"[BIT TRAINING DRIVER] Error leyendo checkpoint {state_path}: {e}")

		target_phase = str(payload.get("phase", "6->7"))
		target_epochs = int(payload.get("target_epochs", 40))

		if last_epoch >= target_epochs:
			completed = True

		percent = min(100, int((last_epoch / max(1, target_epochs)) * 100))

		return StepOutcome(
			completed=completed,
			new_checkpoint=current_checkpoint,
			summary=f"Paso de entrenamiento Bit completado. Época actual: {last_epoch}/{target_epochs} (Fase {target_phase}).",
			progress={"current": last_epoch, "total": target_epochs, "percent": percent},
		)
