"""Puerta local del broker para `session deliver --event` (S2.1).

No arranca el CLI entero: comprueba el contrato del handler (gate de broker,
filtro por evento y holder). La entrega real la cubren los tests de `delivery`.
"""

from __future__ import annotations

import argparse
from unittest.mock import patch

from red_pill.cli_services import handle_session

EVENT = "a" * 32


def _args(**over):
	base = {
		"session_cmd": "deliver",
		"continuity": "soul-1",
		"event": EVENT,
		"originator": None,
		"limit": 20,
		"dry_run": False,
		"summary": False,
		"broker": True,
		"json": True,
	}
	base.update(over)
	return argparse.Namespace(**base)


def test_broker_flag_y_env_autorizan(monkeypatch):
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	monkeypatch.setenv("REDPILL_BROKER", "1")
	report = {"continuity_id": "soul-1", "event_id": EVENT, "leg": "", "handed_off": [], "deferred": [], "skipped": [], "given_up": []}
	with patch("red_pill.session.delivery.deliver_events", return_value=report) as call:
		handle_session(_args())
	assert call.call_args.kwargs["event_id"] == EVENT
	assert call.call_args.kwargs["holder"] == "cli-broker"


def test_sin_env_de_broker_no_entrega(monkeypatch):
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	monkeypatch.delenv("REDPILL_BROKER", raising=False)
	with patch("red_pill.session.delivery.deliver_events") as call:
		handle_session(_args())
	call.assert_not_called()


def test_dry_run_filtra_por_evento(monkeypatch):
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	monkeypatch.delenv("REDPILL_BROKER", raising=False)
	with patch("red_pill.session.delivery.pending_for_soul", return_value=[]) as call:
		handle_session(_args(dry_run=True))
	assert call.call_args.kwargs["event_id"] == EVENT
