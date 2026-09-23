"""Runtime del pase agéntico Memento: modelo servido, fingerprints y transporte LLM."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from . import prompts

logger = logging.getLogger(__name__)


EDGE_ENGINE_URL = "http://localhost:8760/v1/chat/completions"


EDGE_HEALTH_URL = "http://localhost:8760/v1/models"


EDGE_MODEL = "Granite-4.1-8B-Q4_K_M.gguf"



# Trazabilidad de las etapas (2026-09-15): cada distill/refine y el registry guardan
# con qué MODELO real y qué VERSIÓN de prompt se hicieron. Permite saber si un
# engrama se generó con granite o aya, y si los prompts cambiaron desde entonces.
_ENGINE_CACHE: Optional[str] = None




def engine_id() -> str:
	"""Modelo REAL servido por el daemon (consulta /v1/models, cacheada).
	`EDGE_MODEL` es un nombre fijo; el daemon puede servir otro (granite/aya)."""
	global _ENGINE_CACHE
	if _ENGINE_CACHE:
		return _ENGINE_CACHE
	import json
	import urllib.request

	try:
		resp = urllib.request.urlopen(EDGE_HEALTH_URL, timeout=3)
		data = json.loads(resp.read().decode("utf-8"))
		models = data.get("data") or []
		if models:
			_ENGINE_CACHE = str(models[0].get("id") or EDGE_MODEL)
	except Exception:
		_ENGINE_CACHE = EDGE_MODEL
	return str(_ENGINE_CACHE)




def _prompt_hash(*texts: str) -> str:
	import hashlib

	h = hashlib.sha256()
	for t in texts:
		h.update(t.encode("utf-8"))
	return h.hexdigest()[:10]




def distill_prompt_version() -> str:
	"""Fingerprint del prompt de SÍNTESIS (DISTILL_* + VOICE)."""
	return _prompt_hash(prompts.DISTILL_USER, prompts.DISTILL_USER_OPENING, prompts.DISTILL_USER_CONTINUATION, prompts._VOICE_RULE)


def annotate_prompt_version() -> str:
	"""Fingerprint del prompt de ANNOTATE (WORK + SOCIAL + VOICE + Bio de identidad)."""
	return _prompt_hash(prompts.ANNOTATE_WORK_USER, prompts.ANNOTATE_SOCIAL_USER, prompts._VOICE_RULE, prompts.IDENTITY_BIO)


def validate_prompt_version() -> str:
	"""Fingerprint del prompt del VALIDADOR de contenido (MEM-006)."""
	return _prompt_hash(prompts.CONTENT_VALIDATE_USER)




def refine_prompt_version() -> str:
	"""Fingerprint del prompt de REFINADO (WORK + SOCIAL + VOICE)."""
	return _prompt_hash(prompts.REFINE_WORK_USER, prompts.REFINE_SOCIAL_USER, prompts._VOICE_RULE)




# transport(system, user, max_tokens) -> str — inyectable para tests y para futuros bake-offs
Transport = Callable[[str, str, int], str]




def llm_available(url: str = EDGE_HEALTH_URL) -> bool:
	import urllib.request

	try:
		urllib.request.urlopen(url, timeout=3)
		return True
	except Exception:
		return False




# ── Transporte selectivo (RFC-HARNESS-002 §7): el pase Memento lee su demanda
# de inferencia del env RP_LLM_* (inyectado por el driver del job desde la
# receta `llm:`), o cae a los defaults del daemon si no hay override.
#
# n_ctx del modelo servido (2026-09-15): Granite-4.1-8B sirve 10240; tiny-aya
# 32768. El presupuesto de prompt del refine es DINÁMICO según el modelo real,
# resuelto vía model_runtime (fin del MODEL_N_CTX hardcodeado y del hack
# "tiny-aya" en engine_id).
MODEL_N_CTX = 10240  # fallback solo si model_runtime no puede resolver


MODEL_PROMPT_BUDGET = MODEL_N_CTX - 4096  # margen: sistema (~600) + salida (512-1024) + colchón




def _llm_env() -> dict:
	"""Demanda de inferencia del job: RP_LLM_TASK / RP_LLM_MODEL / RP_LLM_THINKING.

	Un job que NO declara `llm:` no las define → el transporte cae al default
	del daemon (comportamiento actual, sin cambios).
	"""
	return {
		"task": os.getenv("RP_LLM_TASK", "").strip(),
		"model": os.getenv("RP_LLM_MODEL", "").strip(),
		"thinking": os.getenv("RP_LLM_THINKING", "").strip(),
	}




def model_prompt_budget() -> int:
	"""Presupuesto de chars del prompt del refine según el modelo resuelto.

	Resuelve la conducta de la tarea (`refine` o `distill` según el env RP_LLM_TASK)
	vía model_runtime: n_ctx del perfil → presupuesto. Si la resolución falla,
	usa el presupuesto por engine_id (fallback histórico).
	"""
	task = _llm_env()["task"] or "refine"
	try:
		from red_pill.core import model_runtime as mr

		resolved = mr.resolve({"task": task})
		n_ctx = resolved.n_ctx
		if n_ctx and n_ctx > 0:
			return int(n_ctx - 4096)
	except Exception:
		pass
	n_ctx = 32768 if "tiny-aya" in engine_id() else MODEL_N_CTX
	return int(n_ctx - 4096)




def _fit_prompt(user: str, hard_cap: int = 20000) -> str:
	"""Cap superior de seguridad: recorta solo prompts claramente excesivos.
	El ajuste fino lo hace el reintento adaptativo de `http_transport` (la ratio
	chars/token varía 1-4, ningún presupuesto fijo es seguro)."""
	if len(user) <= hard_cap:
		return user
	cut = user[:hard_cap]
	cut = cut[: cut.rfind(" ")] if " " in cut else cut
	return cut + "\n[... truncado por presupuesto de contexto]"




def http_transport(system: str, user: str, max_tokens: int, temperature: float = 0.1) -> str:
	"""Envío al LLM local con recorte adaptativo ante 500 por exceso de contexto.

	El llama-server devuelve 500 si el prompt supera n_ctx (10240); la ratio
	chars/token es impredecible (1-4), así que si falla se recorta el user y se
	reintenta (hasta 4 veces) — robusto independientemente de la densidad.

	Watchdog (2026-09-15): timeout por llamada `MEMENTO_LLM_TIMEOUT` (default
	180s). Una generación de distill/refine no debe excederlo; si lo hace, la
	llamada lanza ReadTimeout y el pase lo cuenta como cuelgue (→ deferral tras
	3 consecutivos), en vez de quedarse horas esperando a un daemon que generó
	sin terminar (incidente f6493c71).
	"""
	import requests

	import red_pill.config as cfg

	llm_timeout = int(getattr(cfg, "MEMENTO_LLM_TIMEOUT", 180))
	attempt_user = _fit_prompt(user)
	llm = _llm_env()
	payload: Dict[str, Any] = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": attempt_user}],
		"temperature": temperature, "max_tokens": max_tokens}
	# RFC-HARNESS-002 §7: task/model/thinking desde el env del job (RP_LLM_*).
	# Sin env → sin task/model → el daemon cae a su default (comportamiento actual).
	if llm["task"]:
		payload["task"] = llm["task"]
	if llm["model"]:
		payload["model"] = llm["model"]
	if llm["thinking"]:
		payload["thinking"] = llm["thinking"]
	for _attempt in range(4):
		response = requests.post(EDGE_ENGINE_URL, json=payload, timeout=llm_timeout)
		if response.status_code == 500 and len(attempt_user) > 1500:
			# Probable exceso de contexto: recortar y reintentar.
			new_len = int(len(attempt_user) * 0.6)
			logger.warning(f"LLM 500 (posible contexto) — recortando prompt {len(attempt_user)}→{new_len} chars y reintentando")
			attempt_user = attempt_user[:new_len]
			payload["messages"][1]["content"] = attempt_user
			continue
		response.raise_for_status()
		return str(response.json()["choices"][0]["message"]["content"]).strip()
	# Agotados los reintentos: propagar el error real del último intento.
	response.raise_for_status()
	return ""




def _extract_json(text: str) -> Optional[Dict[str, Any]]:
	start = text.find("{")
	if start < 0:
		return None
	depth = 0
	for i in range(start, len(text)):
		if text[i] == "{":
			depth += 1
		elif text[i] == "}":
			depth -= 1
			if depth == 0:
				try:
					parsed = json.loads(text[start : i + 1])
					return parsed if isinstance(parsed, dict) else None
				except Exception:
					return None
	return None




def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
	"""Refine multi-idea (§5.4.2): extrae el primer array JSON del texto (puede ser vacío)."""
	start = text.find("[")
	if start < 0:
		return None
	depth = 0
	for i in range(start, len(text)):
		if text[i] == "[":
			depth += 1
		elif text[i] == "]":
			depth -= 1
			if depth == 0:
				try:
					parsed = json.loads(text[start : i + 1])
					return parsed if isinstance(parsed, list) else None
				except Exception:
					return None
	return None
