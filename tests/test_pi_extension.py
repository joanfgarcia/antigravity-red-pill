"""Contrato de la extensión pi (`seeds/pi/extensions/red-pill.ts`).

No hay harness de pi en CI para un test conductual, así que se valida el
CONTRATO del artefacto desplegado: compila con `bun build` (sin placeholders) y
conserva los símbolos de la paridad Alma y Coro (handshake MCP con originator
compuesto) y NO reintroduce los mecanismos retirados (link en el hook / tagScan).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED = REPO_ROOT / "seeds" / "pi" / "extensions" / "red-pill.ts"

pytestmark = pytest.mark.skipif(shutil.which("bun") is None, reason="bun no disponible")

_EXTERNAL = [
	"--external",
	"@earendil-works/pi-coding-agent",
	"--external",
	"typebox",
	"--external",
	"@earendil-works/pi-mcp",
]


def _substituted(tmp_path: Path) -> Path:
	src = SEED.read_text(encoding="utf-8")
	src = src.replace("${RED_PILL_DIR}", str(REPO_ROOT)).replace("${UV}", shutil.which("uv") or "uv")
	out = tmp_path / "red-pill.ts"
	out.write_text(src, encoding="utf-8")
	return out


def test_pi_extension_compila(tmp_path):
	out = _substituted(tmp_path)
	res = subprocess.run(
		["bun", "build", str(out), "--target=node", *_EXTERNAL, "--outfile", str(tmp_path / "out.js")],
		capture_output=True,
		text=True,
		timeout=60,
	)
	assert res.returncode == 0, f"bun build falló:\n{res.stdout}\n{res.stderr}"


def test_pi_extension_paridad_alma():
	src = SEED.read_text(encoding="utf-8")
	# Handshake MCP con cuerpo compuesto (paridad F5).
	assert "async function handshake(" in src
	assert "callTool(\"sovereign_handshake\"" in src
	assert "`pi:${sessionId}`" in src
	assert "void handshake(" in src
	# No reintroducir el link en el hook ni el tagScan (retirados: un solo escritor).
	assert "linkSessionIdentity" not in src
	assert "tagScan" not in src
