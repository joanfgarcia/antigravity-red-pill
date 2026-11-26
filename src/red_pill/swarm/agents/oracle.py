"""Oracle — recuperación de contexto en el Bünker.

Contrato (2026-11-26): **recupera y devuelve las fuentes**, no las re-resume.
El consumidor es un agente con la query delante; un segundo LLM resumiendo era un
paso lossy (perdía ids/fechas y podía inventar) que además cargaba granite
in-process en el backend MCP, compitiendo por la VRAM con el sueño.

La síntesis existe como modo OPCIONAL (`synthesize=True`) y va por el daemon
compartido, nunca por un GGUF cargado en este proceso. Si el daemon no responde,
el informe sale en crudo: jamás se finge una síntesis.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from red_pill.swarm.base import Minion

logger = logging.getLogger(__name__)

#: Tope de cuerpo por fragmento en el informe (las notas rondan 300-500 chars;
#: el tope evita mensajes de decenas de miles de caracteres sin cortar la cola).
REPORT_CHARS_PER_HIT = 700


class OracleMinion(Minion):
	"""Context Research & Memory Retrieval Agent.

	Integra con el Bünker para recall profundo y entrega un dossier con fuentes.
	"""

	name: str = "Oracle-01"
	specialization: str = "Knowledge Synthesis & RAG Research"
	collections: List[str] = ["work_memories", "social_memories"]

	async def execute(self, task: str, synthesize: bool = False, **kwargs) -> Dict[str, Any]:
		"""Recupera contexto para `task` y devuelve un dossier con fuentes.

		`synthesize=True` añade un resumen OPCIONAL por el daemon. El modo por
		defecto es `raw`: los fragmentos, tal cual, con su score y su id.
		"""
		from red_pill.memory import MemoryManager

		manager = MemoryManager()

		self.log(f"Recuperando contexto para: {task}")

		collections = kwargs.get("collections") or self.collections

		hits: List[Dict[str, Any]] = []
		for collection in collections:
			found = manager.search_and_reinforce(collection, task, limit=3, caller="oracle", hybrid=True)
			# La cascada evocativa del recall añade puntos asociados más allá del
			# `limit` (por diseño). El dossier mantiene el contrato: 3 por colección.
			for rank, hit in enumerate(found[:3], 1):
				payload = getattr(hit, "payload", None) or {}
				content = str(payload.get("content") or "")
				if not content.strip():
					continue
				hits.append(
					{
						"collection": collection,
						"rank": rank,
						"score": round(float(getattr(hit, "score", 0.0) or 0.0), 3),
						"point_id": str(getattr(hit, "id", "") or payload.get("point_id") or ""),
						"title": str(payload.get("title") or ""),
						"content": content,
						"created_at": payload.get("created_at"),
					}
				)

		synthesis: Optional[str] = None
		mode = "raw"
		if synthesize and hits:
			synthesis = _synthesize_with_daemon("\n---\n".join(h["content"] for h in hits), task)
			if synthesis:
				mode = "synthesized"

		return {
			"status": "success",
			"mode": mode,
			"query": task,
			"hits": hits,
			"synthesis": synthesis,
			"source_count": len(hits),
		}


def _short_date(value: Any) -> str:
	"""Fecha corta para el dossier (epoch o ISO); vacío si no hay dato."""
	if value in (None, ""):
		return ""
	try:
		return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d")
	except (TypeError, ValueError):
		return str(value)[:10]


def _hit_meta(hit: Dict[str, Any], with_collection: bool = False) -> str:
	"""Línea de procedencia: score · colección (opcional) · título · id · fecha."""
	parts = [f"#{hit.get('rank')}"] if hit.get("rank") else []
	parts.append(f"cos {float(hit.get('score') or 0.0):.3f}")
	if with_collection:
		parts.append(str(hit.get("collection") or "?"))
	title = str(hit.get("title") or "").strip()
	if title:
		parts.append(title)
	parts.append(f"id={str(hit.get('point_id') or '')[:8]}")
	date = _short_date(hit.get("created_at"))
	if date:
		parts.append(date)
	return "- " + " · ".join(parts)


def render_report(result: Dict[str, Any], max_chars: int = REPORT_CHARS_PER_HIT) -> str:
	"""Informe legible para el inbox: dossier en crudo o síntesis (marcada lossy)."""
	query = str(result.get("query") or "")
	hits = result.get("hits") or []
	mode = str(result.get("mode") or "raw")

	if mode == "synthesized" and result.get("synthesis"):
		lines = [
			f"ORACLE SYNTHESIS (lossy) — {len(hits)} fuente(s)",
			f"query: {query}",
			"",
			str(result["synthesis"]).strip(),
			"",
			"Fuentes:",
		]
		for hit in hits:
			lines.append(_hit_meta(hit, with_collection=True))
		return "\n".join(lines)

	if not hits:
		return f"ORACLE CONTEXT (raw)\nquery: {query}\n\nSin resultados en las colecciones consultadas."

	lines = [f"ORACLE CONTEXT (raw) — {len(hits)} fragmento(s)", f"query: {query}", ""]
	last_collection = None
	for hit in hits:
		collection = hit.get("collection")
		if collection != last_collection:
			lines.append(f"## {collection}")
			last_collection = collection
		lines.append(_hit_meta(hit))
		body = str(hit.get("content") or "").strip()
		if len(body) > max_chars:
			body = body[:max_chars].rstrip() + "…"
		lines.append(f"  {body}")
	return "\n".join(lines)


def _synthesize_with_daemon(background: str, query: str, timeout: int = 60) -> Optional[str]:
	"""Síntesis OPCIONAL contra el endpoint compartido (swap de modelos del daemon).

	No carga un GGUF en este proceso: en un puesto de 8 GB competiría con el 27B
	del sueño. Ante cualquier fallo devuelve None y el pase entrega contexto crudo.
	"""
	try:
		import requests

		from red_pill.core.llm_endpoint import llm_chat_url

		response = requests.post(
			llm_chat_url(),
			json={
				"messages": [
					{
						"role": "system",
						"content": (
							"Sintetiza el contexto recuperado para la consulta. Usa solo lo que "
							"aparezca en el contexto; si falta un dato, dilo en vez de suponerlo."
						),
					},
					{"role": "user", "content": f"Contexto:\n{background}\n\nConsulta: {query}"},
				],
				"temperature": 0.2,
				"max_tokens": 512,
			},
			timeout=timeout,
		)
		response.raise_for_status()
		data = response.json()
		text = str(data["choices"][0]["message"]["content"]).strip()
		return text or None
	except Exception as exc:  # noqa: BLE001 — nunca romper el research por la síntesis
		logger.warning("Oracle: síntesis por daemon no disponible (%s) — se entrega contexto crudo", exc)
		return None
