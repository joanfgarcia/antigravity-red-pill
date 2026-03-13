import json
import logging
import os
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import red_pill.config as cfg
from red_pill.memory import MemoryManager

logger = logging.getLogger("red_pill.sip")


class SovereignInferenceProxy(BaseHTTPRequestHandler):
	"""
	Sovereign Inference Proxy (SIP)
	Intercepts LLM traffic via UNIX Socket to record interactions automatically.
	"""

	def log_message(self, format, *args):
		# Silence standard HTTP logging
		return

	def do_POST(self):
		if self.path == "/v1/chat/completions":
			self.handle_inference()
		else:
			self.forward_request()

	def handle_inference(self):
		content_length = int(self.headers["Content-Length"])
		post_data = self.rfile.read(content_length)

		try:
			req_json = json.loads(post_data.decode("utf-8"))
		except Exception as e:
			self.send_error(400, f"Invalid JSON: {e}")
			return

		target_url = cfg.MLX_LM_URL

		try:
			resp = requests.post(target_url, json=req_json, headers=dict(self.headers), timeout=120)

			# Extract and capture
			self.capture_interaction(req_json, resp.json())

			self.send_response(resp.status_code)
			for key, value in resp.headers.items():
				if key.lower() not in ["content-encoding", "transfer-encoding", "content-length"]:
					self.send_header(key, value)

			resp_content = resp.content
			self.send_header("Content-Length", str(len(resp_content)))
			self.end_headers()
			self.wfile.write(resp_content)

		except Exception as e:
			logger.error(f"SIP Forwarding Error: {e}")
			self.send_error(502, f"Bad Gateway: {e}")

	def capture_interaction(self, request, response):
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
				threading.Thread(target=self._save_to_bunker, args=(prompt, resp_text), daemon=True).start()

		except Exception as e:
			logger.error(f"SIP Capture Error: {e}")

	def _save_to_bunker(self, prompt, response):
		try:
			mgr = MemoryManager()
			mgr.record_interaction_pair(prompt, response, role="assistant")
			logger.debug("SIP: Interaction recorded successfully.")
		except Exception as e:
			logger.error(f"SIP Persistence Failure: {e}")

	def forward_request(self):
		content_length = int(self.headers.get("Content-Length", 0))
		post_data = self.rfile.read(content_length) if content_length > 0 else None

		base_url = cfg.MLX_LM_URL.replace("/v1/chat/completions", "")
		target_url = f"{base_url}{self.path}"

		try:
			resp = requests.request(method=self.command, url=target_url, data=post_data, headers=dict(self.headers), timeout=30)
			self.send_response(resp.status_code)
			for key, value in resp.headers.items():
				if key.lower() not in ["content-encoding", "transfer-encoding", "content-length"]:
					self.send_header(key, value)
			self.send_header("Content-Length", str(len(resp.content)))
			self.end_headers()
			self.wfile.write(resp.content)
		except Exception as e:
			self.send_error(502, f"Gateway Error: {e}")


class UnixHTTPServer(socketserver.UnixStreamServer, HTTPServer):
	def server_bind(self):
		socketserver.UnixStreamServer.server_bind(self)
		self.server_name = "localhost"
		self.server_port = 0


def run_sip(socket_path=None):
	if socket_path is None:
		socket_path = cfg.SIP_SOCKET_PATH

	if os.path.exists(socket_path):
		os.remove(socket_path)

	logger.info(f"Sovereign Inference Proxy (SIP) active at UNIX Socket: {socket_path}")
	httpd = UnixHTTPServer(socket_path, SovereignInferenceProxy)

	# Ensure local only access
	os.chmod(socket_path, 0o600)

	httpd.serve_forever()
