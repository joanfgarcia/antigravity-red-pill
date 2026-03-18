import asyncio
import json
import logging
import os
import threading

import requests

import red_pill.config as cfg
from red_pill.memory import MemoryManager

logger = logging.getLogger("red_pill.sip")


def _capture_interaction(request, response):
	try:
		messages = request.get("messages", [])
		if not messages:
			return

		prompt = ""
		for m in reversed(messages):
			if m.get("role") == "user":
				prompt = m.get("content", "")
				break

		choices = response.get("choices", [])
		if not choices:
			return

		resp_text = choices[0].get("message", {}).get("content", "")

		if prompt and resp_text:
			threading.Thread(target=_save_to_bunker, args=(prompt, resp_text), daemon=True).start()

	except Exception as e:
		logger.error(f"SIP Capture Error: {e}")


def _save_to_bunker(prompt, response):
	try:
		mgr = MemoryManager()
		mgr.record_interaction_pair(prompt, response, role="assistant")
		logger.debug("SIP: Interaction recorded successfully.")
	except Exception as e:
		logger.error(f"SIP Persistence Failure: {e}")


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
	try:
		request_line = await reader.readline()
		if not request_line:
			return

		parts = request_line.decode("utf-8").strip().split()
		if len(parts) < 3:
			return
		method, path, version = parts[0], parts[1], parts[2]

		headers = {}
		content_length = 0
		while True:
			line = await reader.readline()
			line_str = line.decode("utf-8").strip()
			if not line_str:
				break
			key, val = line_str.split(":", 1)
			key, val = key.strip(), val.strip()
			headers[key] = val
			if key.lower() == "content-length":
				content_length = int(val)

		body = await reader.readexactly(content_length) if content_length > 0 else b""

		loop = asyncio.get_running_loop()

		# Forwarding headers safely
		out_headers = dict(headers)
		# Strip host to avoid host mismatch at the target API
		out_headers.pop("Host", None)
		out_headers.pop("host", None)

		if path == "/v1/chat/completions" and method == "POST":
			try:
				req_json = json.loads(body.decode("utf-8"))
			except Exception as e:
				writer.write(f"{version} 400 Bad Request\r\n\r\nInvalid JSON: {e}".encode("utf-8"))
				await writer.drain()
				return

			target_url = cfg.MLX_LM_URL

			def fetch():
				return requests.post(target_url, json=req_json, headers=out_headers, timeout=120)

			try:
				resp = await loop.run_in_executor(None, fetch)
				try:
					resp_json = resp.json()
					_capture_interaction(req_json, resp_json)
				except Exception:
					pass

				writer.write(f"{version} {resp.status_code} OK\r\n".encode("utf-8"))
				for k, v in resp.headers.items():
					if k.lower() not in ["content-encoding", "transfer-encoding", "content-length"]:
						writer.write(f"{k}: {v}\r\n".encode("utf-8"))
				writer.write(f"Content-Length: {len(resp.content)}\r\n\r\n".encode("utf-8"))
				writer.write(resp.content)
				await writer.drain()
			except Exception as e:
				logger.error(f"SIP Forwarding Error: {e}")
				writer.write(f"{version} 502 Bad Gateway\r\n\r\n{str(e)}".encode("utf-8"))
				await writer.drain()

		else:
			base_url = cfg.MLX_LM_URL.replace("/v1/chat/completions", "")
			target_url = f"{base_url}{path}"

			def fetch_fwd():
				return requests.request(method=method, url=target_url, data=body, headers=out_headers, timeout=30)

			try:
				resp = await loop.run_in_executor(None, fetch_fwd)
				writer.write(f"{version} {resp.status_code} OK\r\n".encode("utf-8"))
				for k, v in resp.headers.items():
					if k.lower() not in ["content-encoding", "transfer-encoding", "content-length"]:
						writer.write(f"{k}: {v}\r\n".encode("utf-8"))
				writer.write(f"Content-Length: {len(resp.content)}\r\n\r\n".encode("utf-8"))
				writer.write(resp.content)
				await writer.drain()
			except Exception as e:
				writer.write(f"{version} 502 Bad Gateway\r\n\r\n{str(e)}".encode("utf-8"))
				await writer.drain()

	except asyncio.CancelledError:
		pass
	except Exception as e:
		logger.error(f"SIP Async Error: {e}")
	finally:
		if not writer.is_closing():
			writer.close()
			try:
				await writer.wait_closed()
			except Exception:
				pass


async def serve_sip(socket_path):
	if os.path.exists(socket_path):
		os.remove(socket_path)

	server = await asyncio.start_unix_server(handle_client, path=socket_path)
	os.chmod(socket_path, 0o600)
	logger.info(f"Sovereign Inference Proxy (SIP) active at Async UNIX Socket: {socket_path}")

	async with server:
		await server.serve_forever()


def run_sip(socket_path=None):
	"""Sync entrypoint for backwards compatibility"""
	if socket_path is None:
		socket_path = cfg.SIP_SOCKET_PATH
	try:
		asyncio.run(serve_sip(socket_path))
	except KeyboardInterrupt:
		logger.info("SIP Terminated.")
