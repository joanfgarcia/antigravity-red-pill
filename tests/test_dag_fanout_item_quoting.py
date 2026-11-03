"""`{{item}}` en un `command` debe sobrevivir a `shlex.split`.

Fallo real (ciclo nocturno 2026-11-03, job `e7b68d36`): 1 de 126 ítems del
fan-out `memento-distill` murió con `usage:` — el item
`memory_queue:mcp:Aleth (Gemini 1.5 Flash):2026-10-27` se sustituía crudo en
`--target {{item}}` y el `shlex.split` del minion lo partía en cinco argv.
El prompt agéntico NO se cita (sería prosa con comillas).
"""

from __future__ import annotations

import shlex

from red_pill.jobs.drivers.dag_manifest import _render_item

SPACED = "memory_queue:mcp:Aleth (Gemini 1.5 Flash):2026-10-27"
TEMPLATE = ".venv/bin/python scripts/memento_agentic.py --phase distill --target {{item}}"


def test_command_item_with_spaces_is_one_argv():
	rendered = _render_item(TEMPLATE, SPACED, shell_safe=True)
	argv = shlex.split(rendered)
	assert argv[-1] == SPACED
	assert argv[-2] == "--target"
	assert len(argv) == 6


def test_command_item_without_spaces_is_unchanged():
	plain = "opencode:opencode:ses_e9f357cbbffeyAANaN4H5WVTml"
	var = _render_item(TEMPLATE, plain, shell_safe=True)
	assert var.endswith("--target " + plain)
	assert shlex.split(var)[-1] == plain


def test_variants_and_dict_items_are_quoted_too():
	rendered = _render_item("--target {{item.id}} --label {{item}}", {"id": "a b", "n": 1}, shell_safe=True)
	argv = shlex.split(rendered)
	assert argv == ["--target", "a b", "--label", '{"id": "a b", "n": 1}']


def test_prompt_render_stays_untouched():
	"""Sin `shell_safe` (prompt agéntico) el item entra crudo, sin comillas."""
	assert _render_item("destila {{item}}", SPACED) == "destila " + SPACED


def test_non_fanout_text_is_returned_as_is():
	assert _render_item("sin marcador", SPACED, shell_safe=True) == "sin marcador"
