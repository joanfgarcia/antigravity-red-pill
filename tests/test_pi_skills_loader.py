"""Integración: los skills del repo pasan el loader REAL de pi-coding-agent.

Pi sigue el Agent Skills standard con warnings; un skill con nombre inválido
(snake_case, mayúsculas…) produce `warning`. Este test carga `skills/`,
`seeds/opencode/skills/` y `seeds/pi/skills/` con el loader de Pi y exige
cero warnings. Skip si node/pi-coding-agent no están disponibles (el CI puede
no tenerlos). Se ejecuta en read-only: nada se escribe ni en `~/.pi` ni en el
repo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _pi_index_js() -> str | None:
	pi = shutil.which("pi")
	if not pi:
		return None
	real = os.path.realpath(pi)
	# .../node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js
	dist_dir = os.path.dirname(os.path.dirname(real))
	pkg_root = os.path.dirname(dist_dir)
	candidate = os.path.join(dist_dir, "index.js")
	if os.path.exists(candidate) and os.path.isdir(os.path.join(pkg_root, "node_modules", "typebox")):
		return candidate
	return None


PI_INDEX = _pi_index_js()
pytestmark = pytest.mark.skipif(PI_INDEX is None, reason="node + pi-coding-agent no disponibles")


def _load_dirs():
	dirs = [
		os.path.join(REPO_ROOT, "skills"),
		os.path.join(REPO_ROOT, "seeds", "opencode", "skills"),
		os.path.join(REPO_ROOT, "seeds", "pi", "skills"),
	]
	# Solo directorios con al menos un skill real (seeds/pi/skills puede estar vacío)
	out = []
	for d in dirs:
		if os.path.isdir(d) and any(os.path.isdir(os.path.join(d, e)) and os.path.exists(os.path.join(d, e, "SKILL.md")) for e in os.listdir(d)):
			out.append(d)
	return out


def test_pi_loader_carga_skills_sin_warnings():
	script = (
		"const { loadSkillsFromDir } = await import("
		+ json.dumps(PI_INDEX)
		+ ");\n"
		+ "const out = [];\n"
		+ "for (const dir of "
		+ json.dumps(_load_dirs())
		+ ") { const r = loadSkillsFromDir({ dir, source: dir }); out.push({ dir, n: r.skills.length, warns: r.diagnostics.filter(d => d.type === 'warning').map(d => d.path + ' :: ' + d.message) }); }\n"
		+ "console.log(JSON.stringify(out));"
	)
	res = subprocess.run(["node", "-e", script], capture_output=True, text=True)
	assert res.returncode == 0, res.stderr
	results = json.loads(res.stdout.strip().splitlines()[-1])
	assert results, "no se cargaron directorios de skills"
	for r in results:
		assert r["n"] > 0, f"{r['dir']}: cero skills cargados"
		assert not r["warns"], f"{r['dir']}: warnings de Pi: {r['warns']}"
