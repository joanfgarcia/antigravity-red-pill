"""Puerto de resumen para el compactor de contexto (B-02).

El compactor no habla con el modelo de la conversación: pide un resumen a un
motor separado. Este módulo define el puerto y tres adaptadores:

- `SamanthaSummarizer`: cola local barata (Samantha on-demand).
- `MementoSummarizer`: transporte local de Memento, para calidad/manual/handoff.
- `ExtractiveSummarizer`: fallback determinista sin LLM.
- `FallbackSummarizer`: encadena primario + fallback sin bloquear el turno.

El prompt operativo vive en `session/prompts/compactor_summary_*` y es distinto
del prompt de memoria curada de Memento: aquí importan decisiones, refs,
pendientes, blockers y próximo paso.
"""

from __future__ import annotations

import re
from typing import Callable, Optional, Protocol, runtime_checkable

from red_pill.core import prompts as core


class SummaryUnavailable(RuntimeError):
	"""El motor no devolvió un resumen utilizable."""


@runtime_checkable
class Summarizer(Protocol):
	"""Contrato mínimo: un tramo de texto entra, un resumen sale."""

	name: str

	def summarize(self, *, text: str, instructions: Optional[str] = None, max_tokens: int = 600) -> str: ...


def _neutralize(text: str) -> str:
	"""El historial es DATO: no puede cerrar los delimitadores del prompt."""
	return str(text or "").replace("</historial>", "<\\/historial>")


def render_compaction_prompt(text: str, instructions: Optional[str]) -> str:
	"""Prompt operativo único para todos los motores LLM."""
	return core.render(
		"session",
		"compactor_summary_user",
		history=_neutralize(text),
		instructions=str(instructions or "(sin instrucciones adicionales)"),
	)


def compaction_system_prompt() -> str:
	return core.system_text("session", "compactor_summary_user") or ""


class SamanthaSummarizer:
	"""Resumen vía Samantha local (misma vía que `compact_session` de Telegram)."""

	name = "samantha"

	def __init__(
		self,
		invoke: Optional[Callable[..., Optional[str]]] = None,
		*,
		model: str = "samantha",
	):
		self._invoke = invoke
		self.model = model

	def summarize(self, *, text: str, instructions: Optional[str] = None, max_tokens: int = 600) -> str:
		if not str(text or "").strip():
			raise SummaryUnavailable("historial vacío")
		prompt = render_compaction_prompt(text, instructions)
		system = compaction_system_prompt()
		try:
			if self._invoke is None:
				from red_pill.inference.samantha_on_demand import invoke
				raw = invoke(prompt=prompt, system_prompt=system, max_tokens=max_tokens)
			else:
				raw = self._invoke(prompt=prompt, system_prompt=system, max_tokens=max_tokens)
		except Exception as exc:  # noqa: BLE001 — el caller decide el fallback
			raise SummaryUnavailable(f"Samantha falló: {exc}") from exc
		summary = str(raw or "").strip()
		if not summary:
			raise SummaryUnavailable("Samantha devolvió vacío")
		return summary


class MementoSummarizer:
	"""Resumen vía el transporte local de Memento (calidad/manual/handoff)."""

	name = "memento"

	def __init__(
		self,
		transport: Optional[Callable[[str, str, int], str]] = None,
		*,
		model: str = "memento",
	):
		self._transport = transport
		self.model = model

	def summarize(self, *, text: str, instructions: Optional[str] = None, max_tokens: int = 600) -> str:
		if not str(text or "").strip():
			raise SummaryUnavailable("historial vacío")
		system = compaction_system_prompt()
		prompt = render_compaction_prompt(text, instructions)
		try:
			if self._transport is None:
				from red_pill.memento.agentic.runtime import http_transport
				raw = http_transport(system, prompt, max_tokens)
			else:
				raw = self._transport(system, prompt, max_tokens)
		except Exception as exc:  # noqa: BLE001
			raise SummaryUnavailable(f"Memento falló: {exc}") from exc
		summary = str(raw or "").strip()
		if not summary:
			raise SummaryUnavailable("Memento devolvió vacío")
		return summary


_SIGNAL_RE = re.compile(
	r"(?i)(decisi[oó]n|decid|pendiente|falta|blocker|bloque|error|fallo|test|commit|"
	r"ref|ruta|archivo|run_id|siguiente|pr[oó]xim|riesgo|no se pudo|todo|fixme)"
)


class ExtractiveSummarizer:
	"""Fallback sin LLM: conserva las líneas con mayor señal operativa."""

	name = "extractive"

	def summarize(self, *, text: str, instructions: Optional[str] = None, max_tokens: int = 600) -> str:
		raw_lines = [line.strip() for line in str(text or "").splitlines()]
		lines = [line for line in raw_lines if line]
		if not lines:
			raise SummaryUnavailable("historial vacío")
		head = lines[:3]
		tail = lines[-5:]
		signals = [line for line in lines if _SIGNAL_RE.search(line)]
		selected = []
		for line in head + signals + tail:
			if line not in selected:
				selected.append(line)
		if not selected:
			selected = lines[-8:]
		budget = max(400, int(max_tokens) * 4)
		out = ["## Resumen extractivo (fallback)"]
		for line in selected:
			candidate = line if len(line) <= 500 else line[:497] + "..."
			if sum(len(x) + 1 for x in out) + len(candidate) > budget:
				break
			out.append(f"- {candidate}")
		if len(out) == 1:
			out.append(f"- {lines[-1][:500]}")
		return "\n".join(out)


class FallbackSummarizer:
	"""Primario con red determinista; nunca deja el turno sin contexto."""

	def __init__(self, primary: Summarizer, fallback: Optional[Summarizer] = None):
		self.primary = primary
		self.fallback = fallback or ExtractiveSummarizer()
		self.name = f"{primary.name}+fallback"
		self.last_engine = primary.name

	def summarize(self, *, text: str, instructions: Optional[str] = None, max_tokens: int = 600) -> str:
		try:
			summary = self.primary.summarize(text=text, instructions=instructions, max_tokens=max_tokens)
			self.last_engine = self.primary.name
			return summary
		except Exception:  # noqa: BLE001 — fallback por diseño
			summary = self.fallback.summarize(text=text, instructions=instructions, max_tokens=max_tokens)
			self.last_engine = self.fallback.name
			return summary


def build_summarizer(engine: str = "samantha") -> Summarizer:
	"""Fábrica: `samantha` y `memento` llevan fallback; `extractive` es puro."""
	key = str(engine or "samantha").strip().lower()
	if key == "samantha":
		return FallbackSummarizer(SamanthaSummarizer())
	if key == "memento":
		return FallbackSummarizer(MementoSummarizer())
	if key == "extractive":
		return ExtractiveSummarizer()
	raise ValueError(f"motor de resumen desconocido: {engine!r}")
