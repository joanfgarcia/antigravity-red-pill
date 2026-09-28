"""SHARD-01 — helpers de render movidos a módulo neutral (autonomía de Memento).

Verifica: comportamiento, que las fuentes de Memento ya NO importan del paquete
legacy, y que el re-export del plugin legacy apunta a las MISMAS funciones.
"""

from __future__ import annotations

from pathlib import Path

import red_pill.config as cfg
from red_pill.utils.chronicle_render import (
	_render_tool_result,
	_render_tool_use,
	extract_assistant_blocks,
	extract_user_content,
)


def test_render_tool_use_hint(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	assert _render_tool_use("Read", {"file_path": "/x/y.py"}) == "[TOOL: Read file_path=/x/y.py]"
	assert _render_tool_use("Bash", {}) == "[TOOL: Bash]"


def test_render_tool_use_sin_strip(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", False)
	out = _render_tool_use("Read", {"file_path": "/x"})
	assert out.startswith("[TOOL USE: Read(") and "/x" in out


def test_render_tool_result_recorta(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	out = _render_tool_result("t1", "a" * 500)
	assert out.startswith("[TOOL RESULT: aaa") and "chars omitted" in out


def test_extract_user_content_str_y_lista():
	assert extract_user_content({"content": "hola"}) == "hola"
	msg = {"content": [{"type": "text", "text": "uno"}, {"type": "text", "text": "dos"}]}
	assert extract_user_content(msg) == "uno\ndos"


def test_extract_user_content_tool_result():
	msg = {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok done"}]}
	assert "[TOOL RESULT:" in extract_user_content(msg)


def test_extract_assistant_blocks_texto_y_tool(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	msg = {"content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}
	blocks = extract_assistant_blocks(msg)
	assert blocks[0]["message"]["text"] == "hi"
	assert blocks[1]["message"]["text"] == "[TOOL: Bash command=ls]"
	assert extract_assistant_blocks({"content": "solo texto"})[0]["message"]["text"] == "solo texto"


def test_fuentes_memento_no_importan_legacy():
	"""Guardarraíl estructural: chronicle_sources no debe depender del paquete legacy."""
	root = Path(__file__).resolve().parents[1] / "src" / "red_pill" / "chronicle_sources"
	offenders = []
	for py in root.glob("*.py"):
		txt = py.read_text(encoding="utf-8")
		# ignorar menciones en docstrings: solo líneas de import reales
		for line in txt.splitlines():
			ls = line.strip()
			if ls.startswith(("import ", "from ")) and "metabolism.chronicle" in ls:
				offenders.append(f"{py.name}: {ls}")
	assert offenders == [], f"imports legacy en chronicle_sources: {offenders}"


def test_reexport_legacy_es_la_misma_funcion():
	"""El plugin legacy re-exporta las MISMAS funciones (sin duplicar código)."""
	from red_pill.metabolism.chronicle import claude_code_plugin as legacy

	assert legacy.extract_user_content is extract_user_content
	assert legacy.extract_assistant_blocks is extract_assistant_blocks
	assert legacy._render_tool_use is _render_tool_use
	assert legacy._render_tool_result is _render_tool_result
