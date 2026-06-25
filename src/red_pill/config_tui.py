"""
TUI Dashboard & Configuration Manager for red-pill.
Provides:
	1. Live System Monitor (Systemd timers, LLM health, Qdrant counts, DB queues, CPU/VRAM)
	2. Configuration Editor (Centralized .env editing with validation and comment preservation)
"""

import asyncio
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import DynamicContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Checkbox, Frame, Label, RadioList, TextArea

import red_pill.config as cfg
from red_pill.core.paths import get_config_dir, get_neon_link_db_path

logger = logging.getLogger("red_pill.config_tui")

# Global UI state
active_tab = "monitor"  # "monitor" or "config"
metrics_data = {"health": "Loading...", "timers": "Loading...", "qdrant": "Loading...", "queues": "Loading...", "hardware": "Loading..."}

# Style definition using Cyberpunk ANSI chroma
tui_style = Style.from_dict(
	{
		"dialog": "bg:#111111 #ffffff",
		"dialog.body": "bg:#111111 #cccccc",
		"frame.label": "#ffaa00 bold",
		"status-bar": "bg:#222222 #00ffcc bold",
		"tab-active": "bg:#00ffcc #000000 bold",
		"tab-inactive": "bg:#333333 #cccccc",
		"input-field": "bg:#222222 #ffffff",
		"button": "bg:#333333 #ffffff",
		"button.focused": "bg:#00ffcc #000000 bold",
		"checkbox": "#ffaa00",
		"error": "#ff0055 bold",
		"success": "#00ff66 bold",
	}
)


# 1. .env PARSING & SERIALIZATION (Preserves order & comments)
class EnvConfig:
	def __init__(self, path: Path):
		self.path = path
		self.entries: List[Dict[str, Any]] = []  # List of dicts representing lines
		self.load()

	def load(self):
		if not self.path.exists():
			self.entries = []
			return
		with open(self.path, "r", encoding="utf-8") as f:
			for line in f:
				stripped = line.strip()
				if not stripped or stripped.startswith("#"):
					self.entries.append({"type": "comment", "raw": line})
				elif "=" in line:
					k, v = line.split("=", 1)
					self.entries.append({"type": "kv", "key": k.strip(), "value": v.strip(), "raw": line})
				else:
					self.entries.append({"type": "comment", "raw": line})

	def get(self, key: str, default: str = "") -> str:
		for entry in self.entries:
			if entry["type"] == "kv" and entry["key"] == key:
				return str(entry["value"])
		return default

	def set(self, key: str, value: str):
		# Look for existing key
		for entry in self.entries:
			if entry["type"] == "kv" and entry["key"] == key:
				entry["value"] = value
				return
		# Add new if not found
		self.entries.append({"type": "kv", "key": key, "value": value, "raw": f"{key}={value}\n"})

	def save(self):
		parent = self.path.parent
		parent.mkdir(parents=True, exist_ok=True)

		# Backup
		if self.path.exists():
			shutil.copy2(str(self.path), str(self.path) + ".bak")

		# Atomic write
		tmp_path = str(self.path) + ".tmp"
		with open(tmp_path, "w", encoding="utf-8") as f:
			for entry in self.entries:
				if entry["type"] == "comment":
					f.write(entry["raw"])
				elif entry["type"] == "kv":
					f.write(f"{entry['key']}={entry['value']}\n")
		os.replace(tmp_path, str(self.path))


# 2. HEALTH & METRICS RETRIEVAL (Run in executor threads)
def fetch_systemd_vitals() -> str:
	"""Gathers health vitals from doctor logic (systemd daemons)."""
	out = []
	try:
		# Check failed user systemd services
		res = subprocess.run(
			["systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=5,
		)
		failed = [line.strip() for line in res.stdout.splitlines() if line.strip()]
		if failed:
			out.append("🔴 Systemd Failures:\n" + "\n".join(f"  • {f}" for f in failed))
		else:
			out.append("🟢 Systemd Services: OK (No failed units)")
	except Exception as e:
		out.append(f"🟡 Systemd Check Failed: {e}")
	return "\n".join(out)


def fetch_systemd_timers() -> str:
	"""Check systemd redpill timers."""
	out = []
	try:
		res = subprocess.run(
			["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "redpill-*.timer"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=5,
		)
		rows = [line.split() for line in res.stdout.splitlines() if line.strip().startswith("redpill-")]
		if not rows:
			out.append("🔴 No active redpill-*.timer units found.")
		else:
			out.append("📅 Active Timers:")
			for parts in rows:
				unit = parts[0]
				active = parts[2] if len(parts) > 2 else "unknown"
				status_icon = "🟢" if active == "active" else "🔴"
				out.append(f"  {status_icon} {unit}: {active}")
	except Exception as e:
		out.append(f"🟡 Timers Check Failed: {e}")
	return "\n".join(out)


def fetch_qdrant_counts() -> str:
	"""Connect to Qdrant and get point counts for key collections."""
	out = []
	try:
		from qdrant_client import QdrantClient

		conf = cfg.get_config()
		url = f"http://{conf.QDRANT_HOST}:{conf.QDRANT_PORT}"
		client = QdrantClient(url=url, api_key=conf.QDRANT_API_KEY, timeout=5)

		# Ping connection
		client.get_collections()
		out.append(f"🟢 Qdrant Client: Connected ({url})")

		for coll in ["work_memories", "social_memories", "system_signals"]:
			try:
				count_res = client.count(collection_name=coll, exact=True)
				out.append(f"  • {coll}: {count_res.count} points")
			except Exception:
				out.append(f"  • {coll}: Collection missing/unreachable")
	except Exception as e:
		out.append(f"🔴 Qdrant Connection Failed: {e}")
	return "\n".join(out)


def fetch_sqlite_queues() -> str:
	"""Fetch pending and dead message counts from SQLite events.db."""
	out = []
	db_path = get_neon_link_db_path()
	if not db_path.exists():
		return f"🟡 SQLite Database not found at {db_path}"

	try:
		conn = sqlite3.connect(str(db_path), timeout=2.0)
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		# Inbox status counts
		cursor.execute("SELECT status, count(*) as cnt FROM inbox GROUP BY status")
		inbox_rows = cursor.fetchall()
		inbox_str = ", ".join(f"{r['status']}: {r['cnt']}" for r in inbox_rows) or "0 PENDING"
		out.append(f"📥 Inbox Queue: {inbox_str}")

		# Outbox status counts
		cursor.execute("SELECT status, count(*) as cnt FROM outbox GROUP BY status")
		outbox_rows = cursor.fetchall()
		outbox_str = ", ".join(f"{r['status'] or 'PENDING'}: {r['cnt']}" for r in outbox_rows) or "0 PENDING"
		out.append(f"📤 Outbox Queue: {outbox_str}")

		# Dead letters
		cursor.execute("SELECT count(*) FROM dead_letters")
		dead_count = cursor.fetchone()[0]
		dead_icon = "🟢" if dead_count == 0 else "🔴"
		out.append(f"{dead_icon} Dead Letters: {dead_count} messages")

		conn.close()
	except Exception as e:
		out.append(f"🟡 SQLite Query Failed: {e}")
	return "\n".join(out)


def fetch_hardware_telemetry() -> str:
	"""Fetches GPU VRAM and CPU utilization."""
	out = []
	try:
		# CPU percentage
		import psutil

		cpu = psutil.cpu_percent()
		out.append(f"💻 CPU Utilization: {cpu}%")
	except Exception:
		out.append("💻 CPU: N/A")

	try:
		# NVIDIA VRAM usage
		nvidia_smi = shutil.which("nvidia-smi")
		if nvidia_smi:
			res = subprocess.run(
				[nvidia_smi, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
				timeout=5,
			)
			parts = res.stdout.strip().split(",")
			if len(parts) == 2:
				used = parts[0].strip()
				total = parts[1].strip()
				out.append(f"📟 GPU VRAM Used: {used} MB / {total} MB")
			else:
				out.append("📟 GPU VRAM: Detection error")
		else:
			out.append("📟 GPU: No Nvidia GPU detected (nvidia-smi absent)")
	except Exception as e:
		out.append(f"📟 GPU: Failed to probe: {e}")
	return "\n".join(out)


async def update_metrics_loop(app: Application):
	"""Asynchronously updates metrics every 5 seconds while TUI is running."""
	while True:
		if active_tab == "monitor":
			try:
				health = await asyncio.to_thread(fetch_systemd_vitals)
				timers = await asyncio.to_thread(fetch_systemd_timers)
				qdrant = await asyncio.to_thread(fetch_qdrant_counts)
				queues = await asyncio.to_thread(fetch_sqlite_queues)
				hw = await asyncio.to_thread(fetch_hardware_telemetry)

				metrics_data["health"] = health
				metrics_data["timers"] = timers
				metrics_data["qdrant"] = qdrant
				metrics_data["queues"] = queues
				metrics_data["hardware"] = hw

				# Trigger UI redraw
				app.invalidate()
			except Exception as err:
				logger.error(f"Error updating metrics: {err}")
		await asyncio.sleep(5)


# 3. TUI APPLICATION LAYOUT
def build_tui_app() -> Application:
	env_path = get_config_dir() / ".env"
	env = EnvConfig(env_path)

	# Setup Configuration Form Widgets
	qdrant_host_txt = TextArea(text=env.get("QDRANT_HOST", "localhost"), multiline=False, style="class:input-field")
	qdrant_port_txt = TextArea(text=env.get("QDRANT_PORT", "6333"), multiline=False, style="class:input-field")
	qdrant_key_txt = TextArea(text=env.get("QDRANT_API_KEY", ""), multiline=False, style="class:input-field", password=True)

	# IDE Backend
	backend_choices = [
		("auto", "Auto (Select agy if present, else grpc)"),
		("agy", "Agy CLI (Antigravity Bridge)"),
		("grpc", "gRPC Legacy Bridge"),
		("claude", "Claude Code CLI Bridge"),
		("local", "Local LLM Bridge (SIP/samantha)"),
	]
	ide_backend_radio = RadioList(values=backend_choices)
	current_backend = env.get("IDE_BACKEND", "auto")
	# Pre-select matching enum
	if current_backend in [c[0] for c in backend_choices]:
		ide_backend_radio.current_value = current_backend
	else:
		ide_backend_radio.current_value = "auto"

	# Booleans
	autonomous_agy_cb = Checkbox(text="Enable Background/Autonomous Agy Operations (AUTONOMOUS_AGY_ENABLED)")
	autonomous_agy_cb.checked = env.get("AUTONOMOUS_AGY_ENABLED", "False").lower() == "true"

	cloud_vault_cb = Checkbox(text="Enable Google Drive Backups (CLOUD_VAULT_ENABLED)")
	cloud_vault_cb.checked = env.get("CLOUD_VAULT_ENABLED", "True").lower() == "true"

	notification_sound_cb = Checkbox(text="Enable Auditory Notifications (NOTIFICATION_SOUND)")
	notification_sound_cb.checked = env.get("NOTIFICATION_SOUND", "False").lower() == "true"

	# Paths
	workspace_root_txt = TextArea(text=env.get("WORKSPACE_ROOT", str(Path.home() / "Documents" / "IA")), multiline=False, style="class:input-field")
	aleth_core_txt = TextArea(
		text=env.get("ALETH_CORE_DIR", str(Path.home() / "Documents" / "IA" / "Aleth_Core")), multiline=False, style="class:input-field"
	)
	cloud_folder_txt = TextArea(text=env.get("CLOUD_VAULT_FOLDER_ID", ""), multiline=False, style="class:input-field")

	# Metabolism/Cadence
	sleep_chunk_txt = TextArea(text=env.get("SLEEP_CHUNK_SIZE", "1000"), multiline=False, style="class:input-field")
	sleep_cull_txt = TextArea(text=env.get("SLEEP_CULL_THRESHOLD", "0.1"), multiline=False, style="class:input-field")
	cadence_burst_txt = TextArea(text=env.get("CADENCE_BURST_THRESHOLD", "30.0"), multiline=False, style="class:input-field")
	cadence_absence_txt = TextArea(text=env.get("CADENCE_ABSENCE_THRESHOLD", "172800"), multiline=False, style="class:input-field")

	save_status_text = ""
	save_status_style = "class:success"

	def get_save_status() -> List[tuple[str, str]]:
		return [(save_status_style, save_status_text)]

	save_status_label = Label(text=get_save_status)

	# ----------------- Laying out Tab Components -----------------

	# Tab 1: Live Monitor Body
	monitor_body = HSplit(
		[
			Frame(body=Window(content=FormattedTextControl(lambda: metrics_data["health"])), title="[1] Systemd Vitals"),
			Frame(body=Window(content=FormattedTextControl(lambda: metrics_data["timers"])), title="[2] Systemd Timers"),
			Frame(body=Window(content=FormattedTextControl(lambda: metrics_data["qdrant"])), title="[3] Qdrant Engine Status"),
			Frame(body=Window(content=FormattedTextControl(lambda: metrics_data["queues"])), title="[4] Inbox & Outbox Queues"),
			Frame(body=Window(content=FormattedTextControl(lambda: metrics_data["hardware"])), title="[5] Host Hardware Telemetry"),
		],
		padding=1,
	)

	# Tab 2: Config Editor Form (Wrapped in HSplit)
	config_body = HSplit(
		[
			Frame(
				body=HSplit(
					[
						VSplit([Label(text="Qdrant Host:     ", width=18), qdrant_host_txt]),
						VSplit([Label(text="Qdrant Port:     ", width=18), qdrant_port_txt]),
						VSplit([Label(text="Qdrant API Key:  ", width=18), qdrant_key_txt]),
					]
				),
				title="Bünker / Qdrant Engine",
			),
			Frame(
				body=HSplit(
					[
						Label(text="Execution IDE Backend:"),
						ide_backend_radio,
						Window(height=1),
						autonomous_agy_cb,
					]
				),
				title="IDE Bridge & Swarm Settings",
			),
			Frame(
				body=HSplit(
					[
						VSplit([Label(text="Workspace Root:  ", width=18), workspace_root_txt]),
						VSplit([Label(text="Aleth Core Dir:  ", width=18), aleth_core_txt]),
						Window(height=1),
						cloud_vault_cb,
						VSplit([Label(text="Vault Folder ID: ", width=18), cloud_folder_txt]),
					]
				),
				title="Core Paths & Cloud Sync",
			),
			Frame(
				body=HSplit(
					[
						VSplit([Label(text="Sleep Chunk Size:", width=18), sleep_chunk_txt]),
						VSplit([Label(text="Sleep Cull Thres:", width=18), sleep_cull_txt]),
						VSplit([Label(text="Burst Threshold: ", width=18), cadence_burst_txt]),
						VSplit([Label(text="Absence Timeout: ", width=18), cadence_absence_txt]),
						Window(height=1),
						notification_sound_cb,
					]
				),
				title="Metabolism, Cadence & Sound",
			),
			save_status_label,
		],
		padding=1,
	)

	# Header / Tab Switcher component
	def get_header_text():
		active_style = "class:tab-active"
		inactive_style = "class:tab-inactive"

		tab_mon = active_style if active_tab == "monitor" else inactive_style
		tab_cfg = active_style if active_tab == "config" else inactive_style

		return [
			("", " 🧬 RED PILL PROTOCOL CONSOLE | "),
			(tab_mon, " [F1] SYSTEM MONITOR "),
			("", "  "),
			(tab_cfg, " [F2] CONFIG EDITOR "),
			("", " \n"),
		]

	header_window = Window(content=FormattedTextControl(get_header_text), height=2, style="class:status-bar")

	# Footer Status Bar
	footer_window = Window(
		content=FormattedTextControl(" Hotkeys: [F1] Monitor | [F2] Config | [F10] Save & Exit | [Esc] Discard & Exit"),
		height=1,
		style="class:status-bar",
	)

	# Container switcher using prompt_toolkit's Condition
	body_container = DynamicContainer(lambda: monitor_body if active_tab == "monitor" else config_body)

	root_container = HSplit([header_window, body_container, footer_window])

	# ----------------- Keybindings -----------------
	kb = KeyBindings()

	@kb.add("f1")
	def _(event):
		global active_tab
		active_tab = "monitor"

	@kb.add("f2")
	def _(event):
		global active_tab
		active_tab = "config"

	@kb.add("escape")
	def _(event):
		event.app.exit(result=False)

	# Navigation bindings for form/radio lists
	@kb.add("tab")
	def _(event):
		# Focus next widget
		event.app.layout.focus_next()

	@kb.add("s-tab")
	def _(event):
		# Focus previous widget
		event.app.layout.focus_previous()

	@kb.add("f10")
	def _(event):
		nonlocal save_status_text, save_status_style
		# Validation & Save Configuration
		try:
			# Verify integers
			port = int(qdrant_port_txt.text.strip())
			chunk = int(sleep_chunk_txt.text.strip())
			absence = int(cadence_absence_txt.text.strip())
			# Verify floats
			cull = float(sleep_cull_txt.text.strip())
			burst = float(cadence_burst_txt.text.strip())
		except ValueError as err:
			save_status_text = f"❌ Validation Error: Numeric fields require valid numbers. ({err})"
			save_status_style = "class:error"
			return

		# Apply values to .env
		env.set("QDRANT_HOST", qdrant_host_txt.text.strip())
		env.set("QDRANT_PORT", str(port))
		env.set("QDRANT_API_KEY", qdrant_key_txt.text.strip())
		env.set("IDE_BACKEND", ide_backend_radio.current_value)
		env.set("AUTONOMOUS_AGY_ENABLED", "True" if autonomous_agy_cb.checked else "False")
		env.set("CLOUD_VAULT_ENABLED", "True" if cloud_vault_cb.checked else "False")
		env.set("CLOUD_VAULT_FOLDER_ID", cloud_folder_txt.text.strip())
		env.set("WORKSPACE_ROOT", workspace_root_txt.text.strip())
		env.set("ALETH_CORE_DIR", aleth_core_txt.text.strip())
		env.set("SLEEP_CHUNK_SIZE", str(chunk))
		env.set("SLEEP_CULL_THRESHOLD", str(cull))
		env.set("CADENCE_BURST_THRESHOLD", str(burst))
		env.set("CADENCE_ABSENCE_THRESHOLD", str(absence))
		env.set("NOTIFICATION_SOUND", "True" if notification_sound_cb.checked else "False")

		try:
			env.save()
			save_status_text = "✓ Configuration saved atomically to ~/.config/red-pill/.env. Backup created."
			save_status_style = "class:success"

			# Exit app with success signal after small delay to show message
			async def exit_after_delay():
				await asyncio.sleep(1.0)
				event.app.exit(result=True)

			asyncio.create_task(exit_after_delay())
		except Exception as e:
			save_status_text = f"❌ Save Failed: {e}"
			save_status_style = "class:error"

	# Build and return the prompt_toolkit Application object
	app: Application[Any] = Application(layout=Layout(root_container), key_bindings=kb, style=tui_style, full_screen=True)
	return app


def run_tui() -> int:
	"""Main TUI execution loop. Runs asynchronously to allow background metric updates."""
	if not sys.stdout.isatty():
		print("[ERROR] Configuration TUI requires an interactive terminal (TTY).")
		return 1

	try:
		app = build_tui_app()

		# Set up event loop and execute background update task
		loop = asyncio.get_event_loop()
		loop.create_task(update_metrics_loop(app))

		success = loop.run_until_complete(app.run_async())
		if success:
			print("\n🟢 [SUCCESS] Configuration updated successfully.")
			return 0
		else:
			print("\n🟡 [DISCARDED] Changes discarded. Exit.")
			return 0
	except Exception as err:
		print(f"\n🔴 [CRASH] TUI initialization failed: {err}")
		return 1


if __name__ == "__main__":
	sys.exit(run_tui())
