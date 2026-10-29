"""Backend local uniforme: el daemon no sabe qué motor hay detrás.

El daemon usa exactamente dos cosas del objeto de modelo:

	model.tokenize(texto.encode("utf-8"))
	model.create_chat_completion(messages=..., stream=..., **kwargs)

y los handlers de `red_pill.inference.runtime` sólo tocan `llm.chat_format` y
`getattr(llm, "_chat_handlers", None)`. Con eso basta para que el daemon sirva
igual un modelo cargado en proceso (`llama-cpp-python`) que uno servido por el
binario de un fork (`PTQ1_0`, `PQ2_0`, `i2_s`), **sin ramificar en su código**.

Motivo (2026-10-29): `bonsai_2_27b` es PTQ1_0 y `llama-cpp-python` no lo carga.
Cambiar el daemon por dentro obligaría a tocarlo cada vez que cambie un motor;
esta indirección lo deja fuera del problema.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# Claves de llama-cpp-python que no viajan al servidor HTTP (sólo tienen sentido
# en proceso). Se descartan en vez de reenviarse: el servidor las rechazaría.
_INPROCESS_ONLY = {
	"chat_format",
	"chat_handler",
	"chat_template",
	"model",
	"echo",
	"logits_processor",
	"logprobs",
	"grammar",
	"mirostat_mode",
	"mirostat_tau",
	"mirostat_eta",
	"tfs_z",
	"typical_p",
	"repeat_last_n",
	"penalize_nl",
	"min_keep",
}


class ForkChatBackend:
	"""Objeto con la interfaz de `llama_cpp.Llama`, servido por un binario de fork.

	No lleva el ciclo de vida: eso es de `RuntimeServer` (AD-049). Aquí sólo se
	traduce la interfaz en proceso a la API HTTP del servidor.
	"""

	def __init__(self, server: Any, *, request_timeout: float = 600.0):
		self.server = server
		self.request_timeout = request_timeout
		# Los handlers escriben aquí; en el camino HTTP el template lo pone el
		# servidor (--jinja), así que el valor es informativo.
		self.chat_format: Optional[str] = None

	def stop(self) -> None:
		"""Suelta el servidor del fork (libera VRAM). El daemon lo llama al desmontar."""
		try:
			self.server.stop()
		except Exception as e:  # pragma: no cover - defensivo
			logger.warning(f"[FORK-BACKEND] fallo al parar el servidor: {e}")

	# ── tokenize ───────────────────────────────────────────────────────────

	def tokenize(self, text: Any, **_: Any) -> List[int]:
		data = text if isinstance(text, (bytes, bytearray)) else str(text).encode("utf-8")
		body = json.dumps({"content": data.decode("utf-8", errors="replace")}).encode("utf-8")
		req = urllib.request.Request(
			f"{self.server.base_url}/tokenize",
			data=body,
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=60) as resp:
				payload = json.loads(resp.read().decode("utf-8"))
		except Exception as e:  # pragma: no cover - depende del servidor
			logger.warning(f"[FORK-BACKEND] /tokenize falló: {e}")
			return []
		tokens = payload.get("tokens") or []
		return [int(t) for t in tokens if isinstance(t, (int, float))]

	# ── chat ───────────────────────────────────────────────────────────────

	def create_chat_completion(self, messages: List[Dict[str, Any]], *, stream: bool = False, **kwargs: Any) -> Any:
		body: Dict[str, Any] = {"messages": messages, "stream": bool(stream)}
		for clave, valor in kwargs.items():
			if clave in _INPROCESS_ONLY or valor is None:
				continue
			body[clave] = valor
		if stream:
			return self._stream(body)
		payload = self._post_chat(body)
		return payload

	def _post_chat(self, body: Dict[str, Any]) -> Dict[str, Any]:
		req = urllib.request.Request(
			f"{self.server.base_url}/v1/chat/completions",
			data=json.dumps(body).encode("utf-8"),
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
				payload = json.loads(resp.read().decode("utf-8"))
		except Exception as e:
			raise RuntimeError(f"[FORK-BACKEND] chat falló: {e}") from e
		if not isinstance(payload, dict):
			raise RuntimeError("[FORK-BACKEND] respuesta no-dict del servidor")
		return payload

	def _stream(self, body: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
		"""Traduce el SSE del servidor al formato de chunk de llama-cpp-python."""
		req = urllib.request.Request(
			f"{self.server.base_url}/v1/chat/completions",
			data=json.dumps(body).encode("utf-8"),
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
			for linea in resp:
				texto = linea.decode("utf-8", errors="replace").strip()
				if not texto.startswith("data:"):
					continue
				carga = texto[len("data:"):].strip()
				if carga == "[DONE]":
					return
				try:
					evento = json.loads(carga)
				except json.JSONDecodeError:
					continue
				yield evento


def build_local_backend(resolved: Any, *, server_factory: Optional[Any] = None,
                        unload_daemon: bool = False) -> Any:
	"""Devuelve el objeto de modelo para un perfil resuelto.

	- runtime de fork → `ForkChatBackend` sobre su `RuntimeServer`.
	- runtime stock → `llama_cpp.Llama` cargado en proceso, como siempre.

	La firma es la que el daemon ya espera: `tokenize` + `create_chat_completion`.
	"""
	from red_pill.core.runtime_registry import RuntimeRegistry

	# `runtime` es el dict ya resuelto; el id es `runtime_id` (str).
	runtime_id = getattr(resolved, "runtime_id", None) or RuntimeRegistry.default_id()
	entry = RuntimeRegistry.get(runtime_id) or {}

	if entry.get("kind") == "llama_cpp_fork":
		profile_name = getattr(resolved, "profile_name", None)
		if not profile_name:
			raise RuntimeError(f"runtime '{runtime_id}' sin `profile_name` en el perfil resuelto")
		if server_factory is None:
			from red_pill.inference.runtime_server import RuntimeServer

			server_factory = RuntimeServer
		extra = list(getattr(resolved, "extra_server_args", None) or [])
		# Red de seguridad, no mecanismo: el sitio correcto para las peculiaridades
		# de un modelo es `extra_server_args` en su perfil. Si el perfil declara
		# thinking off y NO declara el flag, se inyecta y se avisa — porque sin él
		# el template razona, se come el presupuesto y `content` vuelve vacío.
		if str(getattr(resolved, "thinking", "off") or "off").lower() == "off" and "--reasoning" not in extra:
			logger.warning(
				f"[LOCAL-BACKEND] '{profile_name}' declara thinking off sin `extra_server_args`: "
				"inyectando --reasoning off (decláralo en el perfil para no depender de esto)"
			)
			extra += ["--reasoning", "off", "--reasoning-budget", "0"]
		server = server_factory(
			profile_name,
			ctx=getattr(resolved, "n_ctx", None),
			kv_type=getattr(resolved, "kv_cache_type", None),
			extra_args=extra,
			unload_daemon=unload_daemon,
		).start()
		logger.info(f"[LOCAL-BACKEND] '{profile_name}' servido por el binario de '{runtime_id}'")
		return ForkChatBackend(server)

	from llama_cpp import Llama

	from red_pill.core import model_runtime as mr

	flash_attn = mr.effective_flash_attn(resolved, "gpu")
	logger.info(f"[LOCAL-BACKEND] '{getattr(resolved, 'profile_name', '?')}' en proceso (llama-cpp-python)")
	return Llama(
		model_path=resolved.model_path,
		chat_format=getattr(resolved, "chat_format", None),
		n_ctx=int(getattr(resolved, "n_ctx", 4096) or 4096),
		n_gpu_layers=int(getattr(resolved, "n_gpu_layers", -1)),
		verbose=False,
	)
