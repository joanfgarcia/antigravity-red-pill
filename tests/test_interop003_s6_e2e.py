"""RFC-INTEROP-003 S6.2 — E2E real: el handshake del hijo opencode ve continuity_id.

No corre por defecto: necesita el CLI de opencode, credenciales del proveedor y
gasta una llamada real. Activar con `REDPILL_E2E_OPENCODE=1` (modelo opcional en
`REDPILL_E2E_OPENCODE_MODEL`).

Evidencia de campo 2026-10-25 (agentic_job `b0120626`):

S62 CONTINUITY=01a17389-8cf5-75d6-9220-6922ff654c20 \
LEG=job:b0120626-e96f-45f8-9aba-50b86b7b48fe MISSION=repo:next
"""
from __future__ import annotations

import os

import pytest

from red_pill.core.paths import get_state_dir
from red_pill.swarm.bridges.opencode import OpenCodeBridge, _resolve_opencode_bin

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"
MODEL = os.getenv("REDPILL_E2E_OPENCODE_MODEL", "opencode-go/deepseek-v4.1-flash")

PROMPT = (
	"Validación S6.2. No modifiques ficheros. Llama a la herramienta "
	'`sovereign_handshake` con {"user_prompt":"S6.2 E2E","mode":"low"} y responde '
	"EXACTAMENTE: S62 CONTINUITY=<continuity_id> LEG=<leg> MISSION=<mission>"
)

pytestmark = [
	pytest.mark.integration,
	pytest.mark.timeout(240),  # pyproject fija 10s; el hijo real tarda más
	pytest.mark.skipif(os.getenv("REDPILL_E2E_OPENCODE") != "1", reason="E2E real desactivado (REDPILL_E2E_OPENCODE=1)"),
	pytest.mark.skipif(_resolve_opencode_bin() is None, reason="opencode CLI no disponible"),
]


def test_opencode_child_handshake_sees_continuity(tmp_path):
	bridge_path = get_state_dir() / "opencode_session.json"
	backup = bridge_path.read_bytes() if bridge_path.exists() else None
	try:
		bridge = OpenCodeBridge(
			continuity_id=CID,
			mission_id="mission:e2e",
			parent_mission_id="repo:e2e",
			originator="job:e2e-s62",
			role="job",
			job_id="e2e-s62",
		)
		result = bridge.prompt(PROMPT, model=MODEL, cwd=str(tmp_path), timeout=180)
		assert result.ok, result.error
		assert f"CONTINUITY={CID}" in result.response, result.response
		assert "LEG=job:e2e-s62" in result.response, result.response
		assert "MISSION=repo:e2e" in result.response, result.response
	finally:
		# El plugin del hijo pisa el bridge global (limitación A2 conocida); el
		# test no debe robarle el cwd/identidad a la sesión que lo lanzó.
		if backup is not None:
			bridge_path.write_bytes(backup)
