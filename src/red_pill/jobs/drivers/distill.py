"""DistillJobDriver — Driver para re-sintetización atómica V3 de Hubs de Memoria.

Ejecuta el barrido de migración a V3 (voz en 1ª/2ª persona, textura, reliquias)
por steps atómicos diferibles sobre la cola central bunker_queue.db.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from qdrant_client import models

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome
from red_pill.memory import MemoryManager
from red_pill.metabolism.distiller import (
	audit_engram_quality,
	build_emotional_vector,
	distill_engram,
	merge_relics,
	synthesize_hub_v2,
	_is_template_echo,
)
from red_pill.metabolism.sleep import chunk_text

logger = logging.getLogger(__name__)


class DistillJobDriver(ResumableJobDriver):
	source = "distill_job"
	min_vram_mb = 0

	def preflight(self, payload: Dict[str, Any]) -> None:
		from red_pill.core.vram_probe import VramProbe
		from red_pill.metabolism.phases.consolidation import _check_llm_available

		# Si el modelo residente en GPU está activo y respondiendo consultas, procedemos directamente
		if _check_llm_available():
			return

		free_mb = VramProbe.get_free_mb()
		if free_mb < self.min_vram_mb:
			raise JobDeferred(f"VRAM insuficiente para re-síntesis metabólica ({free_mb}MB libres < {self.min_vram_mb}MB)")

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		batch_size = int(payload.get("batch_size", 20))
		smart_audit = bool(payload.get("smart_audit", True))
		collections = payload.get("collections") or ["work_memories", "social_memories"]

		mm = MemoryManager()
		client = mm.client

		processed_so_far = int(checkpoint_data.get("processed", 0))
		total_remaining = 0
		points_to_process = []

		for col in collections:
			if not client.collection_exists(col):
				continue
			try:
				pts, _ = client.scroll(
					collection_name=col,
					scroll_filter=models.Filter(
						must_not=[
							models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent")),
							models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="sequence_chunk")),
							models.FieldCondition(key="distiller_version", match=models.MatchValue(value="v3")),
						]
					),
					limit=batch_size * 2,
					with_payload=True,
				)
				total_remaining += len(pts)
				for p in pts:
					if len(points_to_process) < batch_size:
						points_to_process.append((col, p))
			except Exception as e:
				logger.warning(f"[DISTILL DRIVER] Error leyendo {col}: {e}")

		if not points_to_process:
			return StepOutcome(
				completed=True,
				new_checkpoint=checkpoint_data,
				summary=f"Re-síntesis V3 completada. Total procesados: {processed_so_far}.",
				progress={"current": processed_so_far, "total": processed_so_far, "percent": 100},
			)

		upgraded_in_step = 0
		for col, point in points_to_process:
			p_load = point.payload or {}
			summary = str(p_load.get("summary") or p_load.get("content") or "")
			has_texture = bool(p_load.get("texture"))

			needs_upgrade = (
				audit_engram_quality(summary)
				if smart_audit
				else (not has_texture or summary.startswith("Joan ") or " informed that" in summary)
			)

			if not needs_upgrade:
				# Marcar como V3 para no volver a auditar este punto
				client.set_payload(collection_name=col, payload={"distiller_version": "v3"}, points=[point.id])
				upgraded_in_step += 1
				continue

			raw_id = p_load.get("source_buffer_id") or (p_load.get("metadata", {}) or {}).get("source_buffer_id")
			source_text = str(p_load.get("content", ""))
			if raw_id:
				try:
					raws, _ = client.scroll(
						collection_name=col,
						scroll_filter=models.Filter(
							must=[
								models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent")),
								models.FieldCondition(key="source_buffer_id", match=models.MatchValue(value=raw_id)),
							]
						),
						limit=1,
						with_payload=True,
					)
					if raws:
						source_text = str((raws[0].payload or {}).get("content", "")) or source_text
				except Exception:
					pass

			if not source_text:
				client.set_payload(collection_name=col, payload={"distiller_version": "v3"}, points=[point.id])
				upgraded_in_step += 1
				continue

			chunks = chunk_text(source_text)
			distilled = [distill_engram(c) for c in chunks if not _is_template_echo(c)]
			distilled = [d for d in distilled if not d.get("_is_fallback")]
			if not distilled:
				client.set_payload(collection_name=col, payload={"distiller_version": "v3"}, points=[point.id])
				upgraded_in_step += 1
				continue

			hub = synthesize_hub_v2(distilled)
			upgrade_payload = {
				"summary": f"{hub['title']}\n{hub['summary']}" if hub.get("title") else hub["summary"],
				"texture": hub.get("texture", ""),
				"lang": hub.get("lang", ""),
				"relics": merge_relics(distilled),
				"distiller_version": "v3",
				"hub_depth": p_load.get("hub_depth") or 2,
				"emotional_vector": build_emotional_vector(
					[{"child_id": "", "emotion": d["emotion"], "intensity": d["intensity"], "category": d["category"]} for d in distilled]
				),
				"category_reviewed_at": time.time(),
			}
			client.set_payload(collection_name=col, payload=upgrade_payload, points=[point.id])
			upgraded_in_step += 1

		new_total_processed = processed_so_far + upgraded_in_step
		new_checkpoint = {"processed": new_total_processed, "last_step": time.time()}

		return StepOutcome(
			completed=False,
			new_checkpoint=new_checkpoint,
			summary=f"Lote V3 completado ({upgraded_in_step} engramas en este paso)",
			progress={"current": new_total_processed, "total": new_total_processed + total_remaining, "percent": 0},
		)
