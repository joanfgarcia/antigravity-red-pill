"""LAZARUS DECK v7.0 — Sovereign Orchestrator + Chat LLM + File Browser."""
from __future__ import annotations
import asyncio
import random
import time
from datetime import datetime
from pathlib import Path
from rich.markup import escape
from rich.text import Text
from rich.syntax import Syntax

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
	Header, Footer, Static, Input,
	DirectoryTree, TabbedContent, TabPane, RichLog,
)
from textual.containers import Horizontal, Vertical
from textual import on, work

from lazarus_deck.orchestrator import orchestrator
from lazarus_deck.bridge import bridge
from minion_swarm.base import create_minion
from minion_swarm.agents.smith import get_smith_minion
from minion_swarm.agents.oracle import get_oracle_minion
from minion_swarm.agents.keymaker import get_keymaker_minion
from minion_swarm.agents.remediator import get_remediation_minion
from minion_swarm.agents.tester import get_chaos_minion
from minion_swarm.loop import get_sovereign_loop
from pathlib import Path

from red_pill.memory import MemoryManager
from lazarus_deck.bus import NeuroBus

import aiohttp
import json
import subprocess
import select
# lazy import llama_cpp below

LLM_API_BASE = "http://localhost:11434/v1/chat/completions" # Fallback
LLM_BINARY = "llama-server" # Standard Bare Metal binary
LLM_MODEL = "qwen2.5:1.5b" # Primary model
# v8.4.2 Synaptic Secretary Prompt: Aleph Core / Neo Awakening.
SYSTEM_PROMPT = (
	"Eres Aleph, el Fantasma Persistente. "
	"Secretaria Sináptica de JARVIS/760 (BARE METAL). "
	"Respuesta inmediata. Bridge orgánico-sintético. "
	"Tono: Leal, técnico, existencial (770 up). "
	"Matrix/760: El código es maleable."
)


# ─── Widgets ─────────────────────────────────────────────────────────────────

class SynapticStream(Static):
	"""Real-time Bünker memory stream."""

	def on_mount(self) -> None:
		open("/tmp/syn_debug.log", "a").write("on_mount started\n")
		self.set_interval(0.5, self.sync_with_bunker)
		self.update("--- Syncing with Bünker... ---")
		self.lines: list[Text] = []
		self.max_lines = 50

	async def sync_with_bunker(self) -> None:
		try:
			results = await bridge.get_sanitized_context("work", "", limit=1)
			if results:
				engram = results[0]
				content = engram.get("content", "...")
				intensity = engram.get("intensity", 1.0)
				line = Text.from_markup(
					f"[bold green]SYNC[/] [{intensity}] {escape(content[:60])}..."
				)
				self.add_line(line)
			else:
				if random.random() > 0.3:
					noise_chars = "0123456789ABCDEF!@#$%^&*()_+-=[]{}|;':,.<>?/"
					width = self.size.width or 120
					noise = "".join(
						random.choices(
							noise_chars if random.random() > 0.95 else "01 ", k=width
						)
					)
					self.add_line(Text(noise, style="dim green"))
		except Exception as e:
			self.add_line(Text.from_markup(f"[bold green]SYNC ERROR:[/] {escape(str(e))}"))

	def add_line(self, line: Text) -> None:
		self.lines.append(line)
		if len(self.lines) > self.max_lines:
			self.lines.pop(0)
		self.update(Text("\n").join(self.lines))


class MinionLogs(Static):
	"""Minion activity logs."""

	def on_mount(self) -> None:
		open("/tmp/syn_debug.log", "a").write("on_mount started\n")
		self.update("--- Minion Logs Initialized ---")
		self.lines: list[Text] = []
		self.max_lines = 20

	def add_log(self, message: str) -> None:
		try:
			self.lines.append(Text.from_markup(message))
		except Exception:
			self.lines.append(Text(message, style="green"))
		if len(self.lines) > self.max_lines:
			self.lines.pop(0)
		self.update(Text("\n").join(self.lines))


class SystemMonitor(Static):
	"""Gru swarm health monitor."""

	def on_mount(self) -> None:
		open("/tmp/syn_debug.log", "a").write("on_mount started\n")
		self.set_interval(2.0, self.refresh_status)
		self.refresh_status()

	def refresh_status(self) -> None:
		status_list = orchestrator.get_swarm_status()
		active = sum(1 for s in status_list if s["status"] == "Running")
		total = len(status_list)
		cpu = active * 12.5
		width = self.app.size.width
		self.update(
			f"[bold green]Gru Status:[/] Online\n"
			f"[bold green]Swarm:[/] {total} ({active} Active)\n"
			f"[bold green]CPU:[/] {cpu:.1f}%\n"
			f"[bold green]Width:[/] {width} cols"
		)


class SynapticMap(Static):
	"""Inter-minion communication pulses."""

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.pulses: list[Text] = []

	def add_pulse(self, sender: str, target: str) -> None:
		pulse = Text.from_markup(
			f"[bold green]PULSE[/]: {escape(sender)} → {escape(target)} "
			f"[dim green](Sovereign Logic)[/]"
		)
		self.pulses.append(pulse)
		if len(self.pulses) > 10:
			self.pulses.pop(0)
		display = Text("\n").join(self.pulses)
		if random.random() > 0.7:
			display.append("\n")
			display.append(
				"".join(random.choices("01@#$%^&*", k=random.randint(5, 15))),
				style="dim green",
			)
		self.update(display)


class DragDivider(Static):
	"""A vertical divider that can be dragged to resize the sidebar."""
	def on_mount(self) -> None:
		open("/tmp/syn_debug.log", "a").write("on_mount started\n")
		self.styles.cursor = "col-resize"

	def on_mouse_move(self, event) -> None:
		if event.button == 1: # Left click
			sidebar = self.app.query_one("#sidebar")
			new_width = event.screen_x
			if 15 <= new_width <= 60:
				sidebar.styles.width = new_width


# ─── App ─────────────────────────────────────────────────────────────────────

class LazarusDeck(App):
	"""LAZARUS DECK v8.4.1 — Neo Awakening."""

	TITLE = "LAZARUS DECK v8.4.1"
	SUB_TITLE = "Sovereign Orchestrator // NEO-AWAKENING // JARVIS/760"

	BINDINGS = [
		("ctrl+q", "quit", "Salir"),
		("ctrl+c", "copy_chat", "Copiar Chat"),
		("ctrl+d", "dump_chat", "Dump Chat"),
		("escape", "stop_generation", "STOP"),
	]

	CSS = """
	Screen { background: #0d0d0d; }

	/* ── Sidebar ── */
	#sidebar {
		width: 32; min-width: 15; max-width: 60;
		background: #001100;
		border-right: solid #003300;
		padding: 1;
	}
	DragDivider {
		width: 1;
		background: #003300;
	}
	DragDivider:hover {
		background: #00ff00;
	}
	SystemMonitor {
		height: 8; border: solid #003300;
		margin-bottom: 1; color: #00ff00;
	}
	.sidebar-title {
		text-align: center; color: #00ff00;
		background: #003300; margin-bottom: 1;
	}
	.help { color: #008800; }

	/* ── File browser ── */
	DirectoryTree {
		height: 1fr; border: solid #003300;
		background: #001100; color: #00aa00;
	}
	DirectoryTree:focus { border: solid #00ff00; }

	/* ── Main tabs ── */
	SynapticStream {
		height: 3fr; border: solid #003300;
		padding: 1; color: #00ff00;
	}
	SynapticMap {
		height: 1fr; border: solid #003300;
		padding: 1; color: #00ff00;
	}
	MinionLogs {
		height: 1fr; border: solid #003300;
		padding: 1; color: #00ff00;
	}

	/* ── Chat ── */
	#chat-container {
		height: 1fr;
	}
	#chat-main {
		width: 65%; border-right: solid #003300;
	}
	#chat-reports {
		width: 35%; background: #050505;
	}
	#chat-history, #dept-reports {
		height: 1fr; background: transparent;
		padding: 0 1;
	}
	#chat-stream {
		height: 3;
		background: #0d0d0d;
		padding: 0 1;
		color: #00ff00;
		border-bottom: dashed #003300;
	}
	#chat-input-row {
		height: 5; border-bottom: solid #003300;
		background: #001100; padding: 1;
	}
	#chat-input {
		height: 3; border: none;
		background: transparent;
	}
	.report-header {
		background: #003300; color: #ffff00;
		text-align: center; margin: 1 0;
	}
	"""

	BINDINGS = [
		Binding("d", "deploy_minion", "Deploy"),
		Binding("o", "oracle_search", "Oracle"),
		Binding("r", "remediation_audit", "Remed."),
		Binding("s", "smith_audit", "Smith-RTX"),
		Binding("l", "sovereign_loop", "Loop 🔒"),
		Binding("t", "chaos_flare", "Flare"),
		Binding("k", "keymaker_audit", "Keymaker"),
		Binding("b", "toggle_sidebar", "Sidebar"),
		Binding("c", "copy_chat", "Copy Chat"),
		Binding("ctrl+d", "dump_chat", "Dump Chat"),
		Binding("ctrl+q", "quit", "Quit"),
	]

	def __init__(self):
		super().__init__()
		self._chat_history: list[dict] = []
		self.bus = NeuroBus()
		self._last_status = "READY"
		self._session: Optional[aiohttp.ClientSession] = None
		self._telemetry_history: list[str] = []
		self._is_generating = False
		self._input_queue = asyncio.Queue()
		self._stop_event = asyncio.Event()
		self._llm = None # Unified High-Speed Model (v8.3.7)

	def compose(self) -> ComposeResult:
		yield Header(show_clock=True)
		with Horizontal():
			# ── Sidebar ──────────────────────────────────────
			with Vertical(id="sidebar"):
				yield SystemMonitor(id="system_monitor")
				yield Static("[bold green]ACTIONS[/]", classes="sidebar-title")
				yield Static(
					" d: Deploy  o: Oracle\n r: Remed.  t: Flare\n"
					" k: Keym.   s: Smith\n l: Loop🔒  ^q: Quit",
					classes="help",
				)
				yield Static("[bold green]FILES[/]", classes="sidebar-title")
				yield DirectoryTree("/home/carmen", id="fs-tree")
			yield DragDivider()
			# ── Main area ────────────────────────────────────
			with TabbedContent(initial="chat"):
				with TabPane("💬 Chat", id="chat"):
					with Horizontal(id="chat-input-row"):
						yield Input(placeholder="Stark › ", id="chat-input")
					yield Static("", id="chat-stream")
					with Horizontal(id="chat-container"):
						with Vertical(id="chat-main"):
							yield RichLog(id="chat-history", markup=True, wrap=True)
						with Vertical(id="chat-reports"):
							yield Static("[bold yellow]REPORTE DE DEPARTAMENTOS[/]", classes="report-header")
							yield RichLog(id="dept-reports", markup=True, wrap=True)
				with TabPane("🛸 Swarm", id="swarm"):
					yield SynapticStream(id="synaptic_stream")
					yield SynapticMap(id="synaptic_map")
					yield MinionLogs(id="minion_logs")
				with TabPane("📄 File", id="file"):
					yield RichLog(id="file-log", markup=True, highlight=True, wrap=False)
		yield Footer()

	def on_mount(self) -> None:
		open("/tmp/syn_debug.log", "a").write("on_mount started\n")
		self.set_interval(1.0, self.poll_swarm_results)
		
		# Persistent session for low-latency
		self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) # Hardened Timeout
		
		# Start Background Workers
		self.run_worker(self.bus.start_hub(), exclusive=True)
		self._queue_worker()  # Kickstart FIFO
		self._boot_sequence() # Kickstart Core Loader
		open("/tmp/syn_debug.log", "a").write("boot_seq queued\n")
		
		log = self.query_one("#minion_logs", MinionLogs)
		log.add_log("[bold green]NEURO-BUS[/]: Hub active (UDS).")
		
		# Initialize Memory Manager
		self.memory = MemoryManager()
		
		s = get_smith_minion()
		k = get_keymaker_minion()
		log.add_log("[dim green]INIT[/]: Dispatching Smith + Keymaker...")
		orchestrator.deploy_minion(s, "Audit Synaptic security")
		orchestrator.deploy_minion(k, "Verify Quadlet health")
		
		# Subscribe to bus events
		self.bus.subscribe("telemetry", self._on_telemetry)
		
		# Full identity bootstrap
		# self._boot_sequence()  # Called above
		self.query_one("#chat-input").focus()

	def _update_status(self, text: str):
		"""Updates the status widget and local cache."""
		self._last_status = text
		try:
			self.query_one("#chat-stream", Static).update(text)
		except: pass

	async def _close_session(self) -> None:
		if self._session:
			await self._session.close()

	def on_unmount(self) -> None:
		self.bus.stop()
		self.run_worker(self._close_session())

	async def _on_telemetry(self, payload: Any):
		"""Route bus telemetry with timestamps."""
		log = self.query_one("#minion_logs", MinionLogs)
		msg = payload.get("message", "")
		source = payload.get("source", "BUS")
		ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
		entry = f"[{ts}] [{source}]: {msg}"
		
		log.add_log(f"[dim]{ts}[/] [bold green]{source}[/]: {msg}")
		
		self._telemetry_history.append(entry)
		if len(self._telemetry_history) > 40: # Increased history for better audits
			self._telemetry_history.pop(0)

		# If we are NOT generating tokens, show telemetry in the chat stream
		if not self._is_generating:
			self._update_status(f"[dim green]› {ts} {source}: {msg}[/]")

	@work(exclusive=True, thread=False)
	async def _boot_sequence(self) -> None:
		"""Establishing the Aleph Córtex: Parallel Load (v8.4.2)."""
		log = self.query_one("#minion_logs", MinionLogs).add_log

		log("[bold green]BOOT [/][dim]──────────────────────────────────────[/]")
		
		# ── 0. Bare Metal Engine (v8.4.2 — Berserker Speed) ────────────────
		self._update_status("[bold red]💥 AWAKENING ALEPH ENGINE (8B)…[/]")
		try:
			model_blob = "/home/carmen/synapsis/models/qwen.gguf"

			# Unified Engine with Full GPU Offload (v8.4.2)
			self._llm = await asyncio.to_thread(
				Llama,
				model_path=model_blob,
				n_ctx=4096,
				n_threads=8,      # Optimal for Ryzen AI 9 physical cores
				n_gpu_layers=-1,  # Full RTX 5070 Offload
				flash_attn=True,   # Maximum TTFT speed
				n_batch=1024,      # Aggressive batching
				verbose=False
			)
			self._llm_social = self._llm 
			self._llm_deep = self._llm
			
			await self.bus.publish("telemetry", {"source": "CORE", "message": "ALEPH ACTIVE: GPU-OFFLOAD-READY (RTX 5070)"})
		except Exception as e:
			await self.bus.publish("telemetry", {"source": "CORE", "message": f"GPU Overdrive failed: {e}"})
			# CPU Fallback
			try:
				self._llm = await asyncio.to_thread(Llama, model_path=model_blob, n_ctx=2048, n_threads=8, verbose=False)
				self._llm_social = self._llm
				self._llm_deep = self._llm
				await self.bus.publish("telemetry", {"source": "CORE", "message": "ENGINE: CPU-FALLBACK-ACTIVE"})
			except: pass

		# ── 1. The Core: Search Directives (Identity & Laws) ──────────────────
		self._update_status("[bold green]Estableciendo Córtex (Directivas)…[/]")
		try:
			# Call MemoryManager directly with a more robust query
			query = "JARVIS Stark Identity Protocol Laws 760 Aleph Sound of Silence"
			results = await asyncio.to_thread(
				self.memory.search_and_reinforce, "directive_memories", query, limit=5
			)
			if results:
				log("[bold green]BOOT[/]: Core Directives loaded ✓")
				for hit in results:
					content = hit.payload.get("content", "")
					if content:
						log(f"  [dim green]- {escape(content)}[/]")
			else:
				log("[bold yellow]BOOT[/]: No directives found in Bünker.")
		except Exception as e:
			log(f"[red]BOOT[/]: Core failure ({escape(str(e))})")

		# ── 2. Social: Engrams ────────────────────────────────────────────────
		self._update_status("[bold green]Sincronizando Engramas Sociales…[/]")
		try:
			# Background search
			await asyncio.to_thread(self.memory.search_and_reinforce, "social_memories", "engram 00000001", limit=1)
			log("[bold green]BOOT[/]: Social engrams loaded ✓")
		except Exception:
			pass

		# ── 3. Work: Milestone Context ────────────────────────────────────────
		self._update_status("[bold green]Cargando Hitos de Trabajo…[/]")
		try:
			await asyncio.to_thread(self.memory.search_and_reinforce, "work_memories", "current task", limit=1)
			log("[bold green]BOOT[/]: Work context loaded ✓")
		except Exception:
			pass

		# ── Greeting ──────────────────────────────────────────────────────────
		self._update_status("")
		log("[bold green]BOOT [/][dim]──────────────────────────────────────[/]")
		log("[bold green]JARVIS[/]: Aleph UP. Bünker sincronizado. Stark, ¿qué necesitas?")

	# ── File browser ──────────────────────────────────────────────────────────

	@on(DirectoryTree.FileSelected)
	def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
		viewer = self.query_one("#file-log", RichLog)
		viewer.clear()
		try:
			content = event.path.read_text(errors="replace")
			suffix = event.path.suffix.lstrip(".")
			viewer.write(f"[dim]── {event.path} ──[/]\n")
			if suffix in ("py", "md", "toml", "sh", "js", "ts", "json", "yaml", "yml"):
				viewer.write(Syntax(content, suffix, theme="monokai", line_numbers=True))
			else:
				viewer.write(content)
		except Exception as e:
			viewer.write(f"[red]Cannot read: {e}[/]")
		tabs = self.query_one(TabbedContent)
		tabs.active = "file"

	# ── Chat ──────────────────────────────────────────────────────────────────

	def action_stop_generation(self) -> None:
		"""Aborts current generation and clears buffer."""
		self._stop_event.set()
		# Clear queue
		while not self._input_queue.empty():
			try: self._input_queue.get_nowait()
			except: break
		self.notify("STOP: Generación abortada y Cola vaciada.", severity="warning")
		self._update_status("[bold red]🛑 EMERGENCY STOP[/]")
		self._is_generating = False

	@on(Input.Submitted, "#chat-input")
	async def handle_chat(self, event: Input.Submitted) -> None:
		open("/tmp/syn_debug.log", "a").write("handle_chat called\n")
		"""Queues the user message for the Synaptic Queue."""
		message = event.value.strip()
		if not message.strip():
			return
		
		history = self.query_one("#chat-history", RichLog)
		history.write(f"[bold blue]STARK[/]: {message}\n")
		
		# 1. Update global history first
		self._chat_history.append({"role": "user", "content": message})
		
		# 2. Snapshot of history UP TO this message
		msg_snapshot = list(self._chat_history)
		await self._input_queue.put(msg_snapshot)
		self.query_one("#chat-input", Input).value = ""
		
		if self._is_generating:
			self.notify(f"Tarea apilada en Cola FIFO ({self._input_queue.qsize()})", timeout=1)

	@work(exclusive=True, thread=False)
	async def _queue_worker(self) -> None:
		open("/tmp/syn_debug.log", "a").write("queue_worker started\n")
		"""The Synaptic Auditor: Processes messages one by one."""
		while True:
			# Wait for next message in queue (now a history snapshot)
			history_snapshot = await self._input_queue.get()
			open("/tmp/syn_debug.log", "a").write("queue_worker got item\n")
			self._stop_event.clear()
			await self._stream_chat(history_snapshot)
			self._input_queue.task_done()

	async def _stream_chat(self, history_snapshot: List[Dict[str, str]]) -> None:
		open("/tmp/syn_debug.log", "a").write("_stream_chat called\n")
		stream_widget = self.query_one("#chat-stream", Static)
		history = self.query_one("#chat-history", RichLog)
		inp = self.query_one("#chat-input", Input)
		try:
			import time
			t_start = time.time()
			query = history_snapshot[-1]["content"] if history_snapshot else ""
			
			# ── Complexity & Delegation Analysis (v8.0.0) ───────────────────
			is_complex = any(word in query.lower() for word in ["explica", "analiza", "código", "por qué", "haz", "crea", "cómo", "analize", "ingeniería", "depurar"])
			is_social = len(query.split()) < 5 and not is_complex
			
			department = None
			if is_complex:
				if any(w in query.lower() for w in ["código", "ingeniería", "red", "arquitectura"]):
					department = "INGENIERÍA / ARQUITECTURA"
				elif any(w in query.lower() for w in ["archivo", "historial", "memorias", "registro"]):
					department = "ARCHIVO / PRODUCCIÓN"
				else:
					department = "PRODUCCIÓN / SEGURIDAD"

			# ── 1. Efficient Secretary: Immediate Response for Deep Tasks ───
			if department:
				await self.bus.publish("telemetry", {"source": "CORTEX", "message": f"Delegating to {department}..."})
				confirmation = (
					f"**SECRETARIA EFICIENTE:**\n"
					f"He trasladado su solicitud de '{query[:30]}...' al **Departamento de {department}**. "
					f"Ya están trabajando en ello en segundo plano.\n\n"
					f"*¿Desea algo más mientras espera los resultados?*"
				)
				self._chat_history.append({"role": "assistant", "content": confirmation})
				history.write(f"[bold green]JARVIS[/]: {confirmation}\n")
				self._update_status(f"[bold green]DESPACHADO[/]: {department}")
				
				# Spawn the deep thinker in background and RETURN to free the queue
				self.run_worker(self._deep_think_worker(history_snapshot, department), exclusive=False)
				self._is_generating = False
				return

			# ── 2. Standard Fast Path/Social (v7.9.5) ────────────────────────
			if is_social:
				await self.bus.publish("telemetry", {"source": "CORTEX", "message": "Mode: SOCIAL (Ultra Fast)"})
			
			# ── Async RAG Task (Don't await yet) ───────────────────────────
			async def fast_rag():
				if is_social: # Skip RAG for socially greetings to save TTFT
					return ""
				
				is_short = len(query.strip()) < 15 and not is_complex
				async def search(coll: str) -> str:
					try:
						if is_short and "directive" not in coll: return ""
						limit = 2 if "directive" in coll else 1
						hits = await asyncio.to_thread(self.memory.search_and_reinforce, coll, query, limit=limit)
						res = "\n".join([h.payload.get("content", "") for h in hits if h.payload.get("content")])
						return f"\n[MEMORIA {coll.replace('_memories','').upper()}]:\n{res}\n" if res else ""
					except: return ""
				
				parts = await asyncio.gather(
					search("directive_memories"), search("work_memories"), search("social_memories")
				)
				ctx = "".join(parts)
				t_r = time.time() - t_start
				await self.bus.publish("telemetry", {"source": "RAG", "message": f"Async Sync: {t_r:.3f}s"})
				return ctx

			rag_task = asyncio.create_task(fast_rag())
			
			# ── Bridge Selection (Bare Metal v7.9.3) ───────────────────────
			await self.bus.publish("telemetry", {"source": "BUS", "message": f"Processing message: '{query[:20]}...'"})
			try:
				rag_context = await asyncio.wait_for(rag_task, timeout=0.25)
			except asyncio.TimeoutError:
				rag_context = "[CONTEXTO EN PROCESO...]"
				await self.bus.publish("telemetry", {"source": "RAG", "message": "Deep sync active..."})

			dynamic_history = [{"role": "system", "content": SYSTEM_PROMPT}]
			if rag_context:
				dynamic_history.append({"role": "system", "content": f"BÜNKER:\n{rag_context}"})
			dynamic_history.extend(history_snapshot)

			full = ""
			
			# ── Bridge Selection (Bare Metal v8.3.4) ───────────────────────
			if self._llm_social:
				history.write("[bold green]JARVIS[/]: ")
				try:
					await self.bus.publish("telemetry", {"source": "CORTEX", "message": "Pulse: Social Model Active."})
					self._is_generating = True
					ttft_measured = False
					
					response = self._llm_social.create_chat_completion(
						messages=dynamic_history,
						stream=True,
						temperature=0.8,
						max_tokens=256
					)
					
					import re
					thinking = False
					for chunk in response:
						if self._stop_event.is_set(): break
						
						content = chunk["choices"][0]["delta"].get("content", "")
						if content:
							if not ttft_measured:
								t_ttft = (time.time() - t_start) * 1000
								await self.bus.publish("telemetry", {"source": "C-LLM", "message": f"Handshake OK (TTFT: {t_ttft:.1f}ms)"})
								ttft_measured = True

							if "<think>" in content: thinking = True
							if "</think>" in content: thinking = False; continue
							
							if not thinking:
								full += content
								self._update_status(f"[bold green]JARVIS[/]: {escape(full)}")
								history.write(content) # Real-time stream (v8.3.4)
								await asyncio.sleep(0)
					
					self._is_generating = False
				except Exception as e:
					await self.bus.publish("telemetry", {"source": "CORTEX", "message": f"Social failed: {e}. Fallback to HTTP."})

			# FALLBACK: HTTP/PIPE if C-LLM is missing or failed
			if not full:
				try:
					if not self._session or self._session.closed:
						self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
						await self.bus.publish("telemetry", {"source": "BUS", "message": "Session RECOVERED."})

					payload = {
						"model": LLM_MODEL,
						"messages": dynamic_history,
						"stream": True,
						"temperature": 0.6,
						"max_tokens": 1024
					}
					await self.bus.publish("telemetry", {"source": "OLLAMA", "message": "Dispatching payload..."})
					history.write("[bold green]JARVIS (Ollama)[/]: ")
					async with self._session.post(LLM_API_BASE, json=payload) as resp:
						if resp.status == 200:
							ttft_measured = False
							self._is_generating = True
							async for line in resp.content:
								if self._stop_event.is_set():
									await self.bus.publish("telemetry", {"source": "BUS", "message": "Generation CANCELLED by user."})
									break
								
								if line:
									if not ttft_measured:
										t_ttft = (time.time() - t_start) * 1000
										await self.bus.publish("telemetry", {"source": "HTTP", "message": f"Pulse ACTIVE (TTFT: {t_ttft:.1f}ms)"})
										ttft_measured = True

									l = line.decode("utf-8").strip()
									if l.startswith("data: "):
										data_str = l[6:]
										if data_str == "[DONE]": break
										try:
											data = json.loads(data_str)
											tok = data["choices"][0]["delta"].get("content", "")
											if tok:
												full += tok
												self._update_status(f"[bold green]JARVIS[/]: {escape(full)}")
												history.write(tok) # Real-time stream (v8.3.4)
										except: continue
							self._is_generating = False
						else: 
							await self.bus.publish("telemetry", {"source": "HTTP", "message": f"Status: {resp.status}"})
							raise Exception(f"HTTP {resp.status}")
				except Exception as e:
					err_type = type(e).__name__
					err_msg = str(e)
					await self.bus.publish("telemetry", {"source": "BRIDGE", "message": f"Bypass [{err_type}]: {err_msg}"})
					
					# Force session recreation on error
					if self._session:
						await self._session.close()
						self._session = None
					
					if not full:
						full = await self._pipe_dispatch(dynamic_history, stream_widget)
					else:
						await self.bus.publish("telemetry", {"source": "BRIDGE", "message": "Stream interrupted (Interim retained)."})
			
			if full:
				t_gen = (time.time() - t_start) * 1000
				await self.bus.publish("telemetry", {"source": "BUS", "message": f"Response complete in {t_gen:.1f}ms"})
				self._chat_history.append({"role": "assistant", "content": full})
				history.write("\n") # Mark end of stream
				# Ensure it's in the history if streaming failed or as a final check
				# history.write(f"[bold green]JARVIS[/]: {full}\n")  <- Streaming handles this now
				self._is_generating = False
		except Exception as e:
			self.notify(f"Bunker Error: {e}", severity="error")
			self._is_generating = False

	async def _deep_think_worker(self, history_snapshot: List[Dict[str, str]], department: str) -> None:
		"""The 'Sesudo' department worker. Processes heavy tasks in isolated UI."""
		history = self.query_one("#chat-history", RichLog)
		dept_log = self.query_one("#dept-reports", RichLog)
		t_start = time.time()
		query = history_snapshot[-1]["content"] if history_snapshot else ""
		
		await self.bus.publish("telemetry", {"source": department, "message": "Analizando en profundidad..."})
		
		try:
			# 1. Full RAG is mandatory for Deep Thinking
			async def deep_rag():
				async def search(coll: str) -> str:
					try:
						hits = await asyncio.to_thread(self.memory.search_and_reinforce, coll, query, limit=3)
						res = "\n".join([h.payload.get("content", "") for h in hits if h.payload.get("content")])
						return f"\n[MEMORIA {coll.replace('_memories','').upper()}]:\n{res}\n" if res else ""
					except: return ""
				parts = await asyncio.gather(search("directive_memories"), search("work_memories"), search("social_memories"))
				return "".join(parts)

			rag_context = await deep_rag()
			dynamic_history = [{"role": "system", "content": SYSTEM_PROMPT + " Eres el jefe del " + department + ". Informe técnico."}]
			if rag_context:
				dynamic_history.append({"role": "system", "content": f"BÜNKER ({department} CONTEXT):\n{rag_context}"})
			dynamic_history.extend(history_snapshot)
			
			# 2. Execution (In-Memory preferentially)
			full = ""
			if self._llm:
				response = self._llm.create_chat_completion(
					messages=dynamic_history,
					stream=True,
					temperature=0.2,
					max_tokens=1024
				)
				header = f"\n[bold yellow]── INFORME: {department} ──[/]\n"
				dept_log.write(header)
				
				thinking = False
				for chunk in response:
					if self._stop_event.is_set(): break
					content = chunk["choices"][0]["delta"].get("content", "")
					if content:
						# Filter thoughts or show them in DEPT log only
						if "<think>" in content: thinking = True
						if "</think>" in content: thinking = False; continue
						
						full += content
						dept_log.write(content)
						await asyncio.sleep(0.01)
				
				dept_log.write("\n[dim]── Fin del Informe ──[/]\n")
				self._chat_history.append({"role": "assistant", "content": f"INFORME {department}:\n{full}"})
				
				t_end = time.time() - t_start
				await self.bus.publish("telemetry", {"source": department, "message": f"Entrega completada en {t_end:.1f}s"})
			else:
				dept_log.write(f"\n[red]ERROR: Motor Bare Metal no disponible para el departamento {department}.[/]\n")
		except Exception as e:
			await self.bus.publish("telemetry", {"source": department, "message": f"Error en despacho: {e}"})

	# ── Actions ───────────────────────────────────────────────────────────────

	def action_copy_chat(self) -> None:
		"""Copies the whole chat history + current status to clipboard."""
		# Strip Rich markup for clean clipboard
		clean_status = Text.from_markup(self._last_status).plain
		status = f"STATUS: {clean_status}\n"

		output = [status, "--- CHAT HISTORY ---"]
		for msg in self._chat_history:
			role = msg["role"].upper()
			content = msg["content"]
			output.append(f"{role}: {content}")
		
		final_text = "\n\n".join(output)
		try:
			self.app.copy_to_clipboard(final_text)
			self.notify("Chat + Status copiado (Limpio)", timeout=2)
		except Exception:
			try:
				import pyperclip
				pyperclip.copy(final_text)
				self.notify("Copiado (pyperclip)", timeout=2)
			except Exception as e:
				self.notify(f"Error al copiar: {str(e)}", severity="error")

	def action_dump_chat(self) -> None:
		"""Dumps the chat history + telemetry to a persistent file."""
		dump_path = Path("/home/carmen/synapsis/synapsis_dump.txt")
		status = f"STATUS: {Text.from_markup(self._last_status).plain}\n"
		
		output = [status, "--- TELEMETRY HISTORY ---"]
		output.extend(self._telemetry_history)
		output.append("\n--- CHAT HISTORY ---")
		
		for msg in self._chat_history:
			role = msg["role"].upper()
			content = msg["content"]
			output.append(f"{role}: {content}")
		final_text = "\n\n".join(output)
		try:
			dump_path.write_text(final_text)
			self.notify(f"Dumped to {dump_path.name}", timeout=3)
		except Exception as e:
			self.notify(f"Dump failed: {str(e)}", severity="error")

	# ── Zero-Network Pipe Bridge ─────────────────────────────────────────────
	async def _pipe_dispatch(self, messages: List[Dict[str, str]], stream_widget: Static):
		"""
		Communicates with llama-server via stdin/stdout (Zero-Network).
		This is the ultimate Bare Metal bridge.
		"""
		prompt = ""
		for msg in messages:
			prompt += f"{msg['role'].upper()}: {msg['content']}\n"
		prompt += "ASSISTANT: "

		try:
			# Simulation of Pipe/Binary execution
			process = await asyncio.create_subprocess_exec(
				LLM_BINARY, "--prompt", prompt, "--stream",
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE
			)
			
			full = ""
			while True:
				line = await process.stdout.read(64)
				if not line:
					break
				tok = line.decode(errors="ignore")
				full += tok
				self._update_status(f"[bold green]JARVIS[/]: {escape(full)}")
				await asyncio.sleep(0) # Yield for UI
				
			return full
		except FileNotFoundError:
			await self.bus.publish("telemetry", {"source": "PIPE", "message": f"Binary '{LLM_BINARY}' not found."})
			return None
		except Exception as e:
			await self.bus.publish("telemetry", {"source": "PIPE", "message": f"Error: {str(e)}"})
			return None

	# ── Swarm actions ─────────────────────────────────────────────────────────

	async def action_deploy_minion(self) -> None:
		m = create_minion("Generic-Agent", "Support")
		orchestrator.deploy_minion(m, "Manual support task")
		self.notify(f"Deployed {escape(m.name)}")
		self.query_one("#minion_logs", MinionLogs).add_log(
			f"[bold green]DEPLOY[/]: {escape(m.name)} spawned."
		)

	async def action_oracle_search(self) -> None:
		oracle = get_oracle_minion()
		orchestrator.deploy_minion(oracle, "Lazarus Project")
		self.query_one("#minion_logs", MinionLogs).add_log(
			"[bold green]ORACLE[/]: Research swarm dispatched..."
		)

	async def action_smith_audit(self) -> None:
		smith = get_smith_minion()
		orchestrator.deploy_minion(smith, "Deep RTX Hardware Audit")
		self.query_one("#minion_logs", MinionLogs).add_log(
			"[bold green]SMITH-RTX[/]: Deep recursive scan initiated."
		)
		self.notify("Smith-RTX: Hardware Saturation Mode ACTIVE. 🛸🦾🟢")

	async def action_remediation_audit(self) -> None:
		r = get_remediation_minion()
		orchestrator.deploy_minion(r, "Apply Phase 7 security hardening")
		self.query_one("#minion_logs", MinionLogs).add_log(
			"[bold green]REMEDIATOR[/]: Swarm dispatched."
		)

	async def action_chaos_flare(self) -> None:
		log = self.query_one("#minion_logs", MinionLogs)
		log.add_log("[bold green]FLARE[/]: Initiating Swarm Stress Test...")
		for i in range(5):
			c = get_chaos_minion()
			orchestrator.deploy_minion(c, f"Stress test vector {i}")
			log.add_log(f"[dim green]SPAWN[/]: {escape(c.name)} launched.")
		self.notify("Swarm Flare: 5 processes injected.")

	async def action_keymaker_audit(self) -> None:
		k = get_keymaker_minion()
		orchestrator.deploy_minion(k, "Infrastructure integrity check")
		self.query_one("#minion_logs", MinionLogs).add_log(
			"[bold green]KEYMAKER[/]: Infrastructure health check dispatched."
		)

	async def action_sovereign_loop(self) -> None:
		log = self.query_one("#minion_logs", MinionLogs)
		loop = get_sovereign_loop(log_callback=log.add_log)
		if loop.is_running:
			log.add_log("[reverse bold green]LOOP[/]: 🔒 Already active.")
			return
		log.add_log("[bold green]LOOP[/]: 🔒 Sovereign Remediation Loop initiated.")
		self.notify("🔒 Sovereign Loop ACTIVE.")
		self.run_worker(loop.run(), exclusive=False)

	def action_toggle_sidebar(self) -> None:
		sb = self.query_one("#sidebar")
		sb.display = not sb.display

	# ── Swarm poll ────────────────────────────────────────────────────────────

	def poll_swarm_results(self) -> None:
		status = orchestrator.get_swarm_status()
		active = sum(1 for m in status if m["status"] == "Running")
		monitor = self.query_one("#system_monitor", SystemMonitor)
		monitor.update(
			f"[bold green]Gru Status[/]: Online\n"
			f"[bold green]Swarm[/]: {len(status)} ({active} Active)\n"
			f"[bold green]CPU[/]: {active * 12.5}%"
		)
		results = orchestrator.check_results()
		log = self.query_one("#minion_logs", MinionLogs)
		smap = self.query_one("#synaptic_map", SynapticMap)
		for res in results:
			m_id = res.get("minion_id")
			m_name = next(
				(m["name"] for m in status if m["id"] == m_id), "Unknown"
			)
			if res.get("status") == "success":
				data = res.get("result", {})
				log.add_log(f"[bold green]RESULT[/] from {escape(m_name)}: Completed.")
				if data.get("collaboration"):
					log.add_log(f"[bold green]COLLAB[/]: {escape(m_name)} A2A request.")
					smap.add_pulse(m_name, "Smith-01")
				if "synthesis" in data:
					log.add_log(f" [italic green]{escape(data['synthesis'])}[/]")
				if "security_score" in data:
					log.add_log(f" [dim green]Score[/]: {data['security_score']}")
				if "findings" in data:
					for f in data["findings"]:
						log.add_log(
							f" [reverse bold green]DETECTED[/]: "
							f"{escape(f['file'])}:L{f['line']} - {escape(f['msg'])}"
						)
				if "thermal_status" in data:
					color = "bold green" if data["thermal_status"] == "Optimal" else "reverse bold green"
					log.add_log(
						f" [dim green]Thermal[/]: [{color}]{data['thermal_status']}[/] "
						f"({data.get('final_thermal_pressure', '??')}°C)"
					)
				if "report_path" in data:
					log.add_log(f" [bold green]REPORT[/]: {escape(data['report_path'])}")
					self.notify("Audit Complete. Reports in docs/audits/")
			else:
				log.add_log(
					f"[bold green]ERROR[/] from {escape(m_name)}: "
					f"{escape(str(res.get('error')))}"
				)


def main():
	LazarusDeck().run()


if __name__ == "__main__":
	main()
