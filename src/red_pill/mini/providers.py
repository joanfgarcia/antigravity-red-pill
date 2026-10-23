"""OpenAI-compatible chat providers for the mini harness (UDS and localhost).

Forge speaks HTTP over a Unix socket to `llama-server --host *.sock`; Loom speaks
HTTP to the FLM server on loopback (v0). Both return the raw OpenAI `message`
dict, including `tool_calls`, so the tool loop is provider-agnostic.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class ProviderError(RuntimeError):
	"""Provider transport or protocol failure (no `choices`, HTTP error, timeout)."""


def _payload(messages: List[Dict[str, Any]], tools: Optional[List[dict]], tool_choice: Any, temperature: float, max_tokens: int, model: Optional[str]) -> dict:
	payload: Dict[str, Any] = {
		"messages": messages,
		"temperature": temperature,
		"max_tokens": max_tokens,
		"stream": False,
	}
	if model:
		payload["model"] = model
	if tools is not None:
		payload["tools"] = tools
		payload["tool_choice"] = tool_choice or "auto"
	return payload


def _message_from_response(raw: bytes, status: int) -> Dict[str, Any]:
	try:
		data = json.loads(raw.decode("utf-8", "replace"))
	except json.JSONDecodeError as e:
		raise ProviderError(f"HTTP {status}: non-JSON response: {raw[:300]!r}") from e
	choices = data.get("choices") if isinstance(data, dict) else None
	if not choices:
		detail = data.get("error") if isinstance(data, dict) else None
		raise ProviderError(f"HTTP {status}: no choices ({detail or raw[:300]!r})")
	return choices[0].get("message") or {}


class UnixHTTPProvider:
	"""OpenAI chat over an HTTP request on a Unix domain socket."""

	def __init__(self, socket_path: str, *, model: Optional[str] = None, timeout: int = 300):
		self.socket_path = str(socket_path)
		self.model = model
		self.timeout = int(timeout)

	class _Connection(http.client.HTTPConnection):
		def __init__(self, path: str, timeout: int):
			super().__init__("localhost", timeout=timeout)
			self._path = path

		def connect(self) -> None:
			self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			self.sock.settimeout(self.timeout)
			self.sock.connect(self._path)

	def health(self, timeout: int = 5) -> bool:
		try:
			conn = self._Connection(self.socket_path, timeout)
			conn.request("GET", "/health")
			resp = conn.getresponse()
			resp.read()
			return resp.status == 200
		except Exception:
			return False

	def chat(
		self,
		messages: List[Dict[str, Any]],
		*,
		tools: Optional[List[dict]] = None,
		tool_choice: Any = None,
		temperature: float = 0.2,
		max_tokens: int = 1024,
		timeout: Optional[int] = None,
	) -> Dict[str, Any]:
		conn = self._Connection(self.socket_path, int(timeout or self.timeout))
		body = json.dumps(_payload(messages, tools, tool_choice, temperature, max_tokens, self.model))
		try:
			conn.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
			resp = conn.getresponse()
			raw = resp.read()
			return _message_from_response(raw, resp.status)
		except (OSError, socket.timeout) as e:
			raise ProviderError(f"UDS {self.socket_path}: {e}") from e
		finally:
			conn.close()


class HTTPProvider:
	"""OpenAI chat over loopback HTTP (FLM v0)."""

	def __init__(self, base_url: str, *, model: Optional[str] = None, timeout: int = 360):
		self.base_url = str(base_url).rstrip("/")
		self.model = model
		self.timeout = int(timeout)

	def health(self, timeout: int = 5) -> bool:
		# FLM exposes /v1/models but not /health (404). Accept either readiness probe.
		for path in ("/health", "/v1/models"):
			try:
				with urllib.request.urlopen(f"{self.base_url}{path}", timeout=timeout) as resp:
					if int(getattr(resp, "status", 200)) == 200:
						return True
			except Exception:
				continue
		return False

	def chat(
		self,
		messages: List[Dict[str, Any]],
		*,
		tools: Optional[List[dict]] = None,
		tool_choice: Any = None,
		temperature: float = 0.2,
		max_tokens: int = 1024,
		timeout: Optional[int] = None,
	) -> Dict[str, Any]:
		body = json.dumps(_payload(messages, tools, tool_choice, temperature, max_tokens, self.model)).encode("utf-8")
		req = urllib.request.Request(
			f"{self.base_url}/v1/chat/completions",
			data=body,
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=int(timeout or self.timeout)) as resp:
				return _message_from_response(resp.read(), int(getattr(resp, "status", 200)))
		except urllib.error.HTTPError as e:
			raw = e.read()
			raise ProviderError(f"HTTP {e.code}: {raw[:300]!r}") from e
		except (urllib.error.URLError, OSError) as e:
			raise ProviderError(f"HTTP {self.base_url}: {e}") from e
