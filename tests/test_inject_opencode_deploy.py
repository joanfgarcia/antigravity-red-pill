"""Tests de despliegue del adapter opencode (scripts/inject/opencode/inject.py).

Regresión 2026-09-07: `repo_root` se resolvía como `scripts/` en vez de la raíz
del repo → `inject_cli.py` (el camino real de `bunker update`/`install`) no
desplegaba ni anchors ni skills. El skill `dag` llevaba tiempo en `seeds/`
sin llegar al arnés por esta causa.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

# Raíz del repo derivada del propio test (tests/ → ../): no hay rutas fijas.
# El repo se despliega donde quiera el operador (sharing, antigravity-red-pill,
# cualquier checkout) — nada de caminos hardcodeados a máquina.
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ADAPTER_PATH = os.path.join(REPO_ROOT, "scripts", "inject", "opencode", "inject.py")


def _load_adapter() -> object:
	spec = importlib.util.spec_from_file_location("opencode_inject_under_test", ADAPTER_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["opencode_inject_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def adapter():
	return _load_adapter()


def test_deep_merge_reemplaza_command_mcp(adapter) -> None:
	"""Un command MCP se reemplaza; concatenarlo rompía el proxy con el directo."""
	base = {"mcp": {"RedPill-Kernel": {"command": ["direct", "old"], "environment": {"A": "1"}}}}
	overlay = {"mcp": {"RedPill-Kernel": {"command": ["proxy", "new"], "environment": {"B": "2"}}}}
	out = adapter._deep_merge(base, overlay)
	assert out["mcp"]["RedPill-Kernel"]["command"] == ["proxy", "new"]
	assert out["mcp"]["RedPill-Kernel"]["environment"] == {"A": "1", "B": "2"}
	assert adapter._deep_merge({"plugin": ["a"]}, {"plugin": ["a", "b"]})["plugin"] == ["a", "b"]


def test_repo_root_apunta_a_la_raiz_del_repo(adapter) -> None:
	# El adapter deriva repo_root en inject(); verificamos que la ruta resuelve a
	# la RAÍZ del repo (no a scripts/) — el nombre del directorio cambia según el
	# checkout (local: sharing, CI: antigravity-red-pill), así que se valida por
	# contenido, no por nombre.
	resolved = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(adapter.__file__)), "..", "..", ".."))
	# .git es directorio en un checkout normal y fichero en un worktree: ambos valen.
	assert os.path.exists(os.path.join(resolved, ".git")), f"no es la raíz del repo: {resolved}"
	assert os.path.isdir(os.path.join(resolved, "seeds", "opencode", "skills", "dag"))
	assert os.path.exists(os.path.join(resolved, "seeds", "anchors", "job_dag_execution.md"))


def test_inject_limpio_despliega_anchor_y_skills(adapter, tmp_path) -> None:
	"""Instalación limpia: AGENTS.md + skill job-manager/dag/forge/scout."""
	import argparse
	import os

	tmp = str(tmp_path)
	monkeypatch_detect = lambda: tmp  # noqa: E731
	adapter._detect_config_dir = monkeypatch_detect

	args = argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False)
	n = adapter.inject(args)

	redpill = os.path.join(tmp, "AGENTS.md")
	assert os.path.exists(redpill), "AGENTS.md no generado"
	text = open(redpill, encoding="utf-8").read()
	assert "job_dag_execution" in text, "anchor job_dag_execution ausente en AGENTS.md"

	for skill in ("job-manager", "dag", "forge", "scout"):
		path = os.path.join(tmp, "skills", skill, "SKILL.md")
		assert os.path.exists(path), f"skill '{skill}' no desplegado en instalación limpia"
	# Skill multi-fichero: los companions (no solo SKILL.md) también viajan.
	ledger = os.path.join(tmp, "skills", "context-distiller", "snapshot_read.py")
	assert os.path.exists(ledger), "companion de skill multi-fichero no desplegado"
	assert n > 0


def test_inject_idempotente(adapter, tmp_path) -> None:
	"""Segunda pasada sobre instalación existente: sin cambios (bunker update)."""
	import argparse
	import os

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	args = argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False)

	adapter.inject(args)
	# tocar el anchor para forzar divergencia
	redpill = os.path.join(tmp, "AGENTS.md")
	original = open(redpill, encoding="utf-8").read()
	n2 = adapter.inject(args)
	assert n2 == 0, "segunda pasada debería ser idempotente (sin bloques modificados)"
	assert open(redpill, encoding="utf-8").read() == original


def test_package_json_v2_type_module(adapter, tmp_path) -> None:
	"""Instalación limpia en V2: package.json ESM, sin pin V1."""
	import argparse
	import json
	import os

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	args = argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False)
	adapter.inject(args)

	pkg_path = os.path.join(tmp, "package.json")
	assert os.path.exists(pkg_path), "package.json no creado"
	pkg = json.load(open(pkg_path, encoding="utf-8"))
	assert pkg.get("type") == "module"
	assert "@opencode-ai/plugin" not in pkg.get("dependencies", {})


def test_package_json_v2_limpia_pin_y_preserva_deps(adapter, tmp_path) -> None:
	"""Instalación existente V1: quita el pin V1, preserva deps ajenas y marca ESM."""
	import argparse
	import json
	import os

	tmp = str(tmp_path)
	pkg_path = os.path.join(tmp, "package.json")
	with open(pkg_path, "w", encoding="utf-8") as f:
		json.dump({"dependencies": {"@opencode-ai/plugin": "1.18.3", "better-sqlite3": "^12.11.1"}}, f)

	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	args = argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=False, update=False)
	adapter.inject(args)

	pkg = json.load(open(pkg_path, encoding="utf-8"))
	assert "@opencode-ai/plugin" not in pkg.get("dependencies", {})
	assert pkg["dependencies"]["better-sqlite3"] == "^12.11.1", "dep ajena perdida"
	assert pkg.get("type") == "module"
	assert os.path.exists(pkg_path + ".bak"), "backup no creado"

	before = open(pkg_path, encoding="utf-8").read()
	adapter.inject(args)
	assert open(pkg_path, encoding="utf-8").read() == before, "no idempotente"


def _block_version() -> dict:
	"""BLOCK_VERSION de scripts/inject_anchor.py (la fuente única de versiones de bloque)."""
	path = os.path.join(REPO_ROOT, "scripts", "inject_anchor.py")
	spec = importlib.util.spec_from_file_location("inject_anchor_versions_under_test", path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_anchor_versions_under_test"] = mod  # @dataclass lo busca en sys.modules
	spec.loader.exec_module(mod)
	return dict(mod.BLOCK_VERSION)


def test_red_pill_md_lleva_las_versiones_de_inject_anchor(adapter, tmp_path) -> None:
	"""Regresión: el adapter (camino de `bunker update`) tenía su propia tabla de
	versiones y escribía `knowledge_access v=2` / `sovereign_handshake v=1`."""
	import argparse
	import re

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	adapter.inject(argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False))

	text = open(os.path.join(tmp, "AGENTS.md"), encoding="utf-8").read()
	found = {name: int(v) for name, v in re.findall(r"<!-- REDPILL:BEGIN (\w+) v=(\d+) -->", text)}
	expected = _block_version()
	assert found == {name: expected[name] for name in found}
	assert {"sovereign_handshake", "knowledge_access"} <= set(found)


def test_inject_opencode_standalone_usa_la_misma_tabla() -> None:
	"""scripts/inject_opencode.py tampoco mantiene una copia propia de las versiones."""
	path = os.path.join(REPO_ROOT, "scripts", "inject_opencode.py")
	spec = importlib.util.spec_from_file_location("inject_opencode_under_test", path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_opencode_under_test"] = mod
	spec.loader.exec_module(mod)
	assert dict(mod.BLOCK_VERSION) == _block_version()
	assert "BLOCK_VERSION = {" not in open(path, encoding="utf-8").read()


def test_agents_md_resuelve_placeholders_relay(adapter, tmp_path) -> None:
	"""Regresión: el adapter escribía los `${RELAY_*}` del seed VERBATIM (sin
	ide_call_vars), así que opencode recibía `sovereign_handshake v=1` con
	placeholders sin resolver. Debe resolverse con la frase hook-aware."""
	import argparse

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	adapter.inject(argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False))

	text = open(os.path.join(tmp, "AGENTS.md"), encoding="utf-8").read()
	assert "${RELAY_" not in text, "placeholders ${RELAY_*} sin resolver en AGENTS.md"
	assert "only `user_prompt`" in text, "frase hook-aware ausente (opencode debe pasar solo user_prompt)"
	assert "no editor hook" not in text, "opencode tiene editor hook: no debe recibir la variante sin hook"


def _load_standalone_module():
	path = os.path.join(REPO_ROOT, "scripts", "inject_opencode.py")
	spec = importlib.util.spec_from_file_location("inject_opencode_relay_under_test", path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_opencode_relay_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def _config_common():
	path = os.path.join(REPO_ROOT, "scripts", "_config_common.py")
	spec = importlib.util.spec_from_file_location("config_common_under_test", path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["config_common_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def test_inject_opencode_standalone_resuelve_placeholders_relay(tmp_path) -> None:
	"""El inyector standalone (no el adapter) resuelve `${RELAY_*}` con la frase
	de opencode y no filtra la variante sin hook."""
	import argparse

	mod = _load_standalone_module()
	cc = _config_common()
	variables = cc.build_vars(argparse.Namespace(uv_path=None, redpill_dir=REPO_ROOT, workspace=None))
	variables.update(cc.agent_core_vars())

	dest = os.path.join(str(tmp_path), "RED_PILL.md")
	seeds_dir = os.path.join(REPO_ROOT, "seeds", "anchors")
	mod.write_instructions(dest, seeds_dir, variables, backup=False, update=False)

	text = open(dest, encoding="utf-8").read()
	assert "${RELAY_" not in text, "placeholders ${RELAY_*} sin resolver (standalone)"
	assert "only `user_prompt`" in text, "frase hook-aware ausente (standalone)"
	assert "no editor hook" not in text, "opencode tiene editor hook: no debe recibir la variante sin hook"


# ── _merge_config: merge sobre config EXISTENTE (regresión de aliasing) ──────
def test_merge_config_escribe_sobre_existente(adapter, tmp_path) -> None:
	"""Regresión: `_deep_merge` mutaba y devolvía `existing`, así que
	`merged == existing` era siempre True → NUNCA escribía sobre una config ya
	existente (el reseed no aplicaba cambios)."""
	import json

	cfg = os.path.join(str(tmp_path), "opencode.jsonc")
	with open(cfg, "w", encoding="utf-8") as f:
		json.dump({"model": "OLD", "mcp": {"X": {"command": "z"}}}, f)

	template = {"model": "NEW", "mcp": {"RedPill-Kernel": {"environment": {"REDPILL_HARNESS": "opencode"}}}}
	changed = adapter._merge_config(cfg, template, backup=False)

	assert changed is True, "no escribió sobre config existente"
	merged = json.load(open(cfg, encoding="utf-8"))
	assert merged["model"] == "NEW"  # valor actualizado
	assert merged["mcp"]["X"] == {"command": "z"}  # clave ajena preservada
	assert merged["mcp"]["RedPill-Kernel"]["environment"]["REDPILL_HARNESS"] == "opencode"


def test_merge_config_idempotente(adapter, tmp_path) -> None:
	cfg = os.path.join(str(tmp_path), "opencode.jsonc")
	template = {"model": "NEW", "mcp": {"RedPill-Kernel": {"environment": {"REDPILL_HARNESS": "opencode"}}}}
	assert adapter._merge_config(cfg, template, backup=False) is True  # primera (crea)
	before = open(cfg, encoding="utf-8").read()
	assert adapter._merge_config(cfg, template, backup=False) is False  # segunda: sin cambios
	assert open(cfg, encoding="utf-8").read() == before


def test_merge_config_no_muta_el_template(adapter, tmp_path) -> None:
	"""El merge no debe mutar el template (se comparte entre destinos)."""
	template = {"a": {"b": 1}}
	cfg = os.path.join(str(tmp_path), "c.jsonc")
	adapter._merge_config(cfg, template, backup=False)
	assert template == {"a": {"b": 1}}, "el template fue mutado por el merge"


def _block_anchors() -> tuple:
	"""BLOCK_ANCHORS de scripts/inject_anchor.py (roster canónico)."""
	path = os.path.join(REPO_ROOT, "scripts", "inject_anchor.py")
	spec = importlib.util.spec_from_file_location("inject_anchor_anchors_under_test", path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_anchor_anchors_under_test"] = mod
	spec.loader.exec_module(mod)
	return tuple(mod.BLOCK_ANCHORS)


def test_roster_de_anclas_compartido() -> None:
	"""Regresión: `inject_opencode` (y su adapter) mantenían su propia lista, sin
	`identity_pact`; cada target derivaba a un juego de reglas distinto. Ahora el
	roster es único (el de `inject_anchor`) y toda ancla tiene versión."""
	anchors = _block_anchors()
	assert anchors == tuple(_block_version().keys())
	assert "identity_pact" in anchors
	for path in (
		os.path.join(REPO_ROOT, "scripts", "inject_opencode.py"),
		os.path.join(REPO_ROOT, "scripts", "inject", "opencode", "inject.py"),
	):
		assert "BLOCK_ANCHORS" in open(path, encoding="utf-8").read()


def test_write_instructions_escribe_todo_el_roster(tmp_path) -> None:
	"""El inyector standalone escribe las 6 anclas (incluida `identity_pact`)."""
	import re

	mod = _load_standalone_module()
	seeds_dir = os.path.join(REPO_ROOT, "seeds", "anchors")
	dest = os.path.join(str(tmp_path), "RED_PILL.md")
	mod.write_instructions(dest, seeds_dir, {}, backup=False, update=False)

	text = open(dest, encoding="utf-8").read()
	found = set(re.findall(r"<!-- REDPILL:BEGIN (\w+) v=\d+ -->", text))
	assert set(_block_anchors()) <= found
	assert "identity_pact" in found


def test_instrucciones_globales_viven_en_agents_md(adapter, tmp_path) -> None:
	"""V2 sólo carga de forma nativa, y en cualquier workspace, los `AGENTS.md`.

	Regresión 2026-10-27: el seed apuntaba a `instructions: ["RED_PILL.md"]`, una
	ruta RELATIVA que V2 resuelve desde el workspace hacia arriba. En cualquier otro
	proyecto no se encontraba y OpenCode la ignoraba EN SILENCIO: el handshake
	obligatorio (`sovereign_handshake`) desapareció del contexto del agente.
	El bloque debe vivir en el `AGENTS.md` global del config dir, que se carga
	siempre, independientemente del workspace.
	"""
	import argparse
	import json
	import os
	import re

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	adapter.inject(argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False))

	agents = os.path.join(tmp, "AGENTS.md")
	assert os.path.exists(agents), "AGENTS.md global no generado"
	text = open(agents, encoding="utf-8").read()
	assert re.search(r"<!-- REDPILL:BEGIN sovereign_handshake v=\d+ -->", text)

	cfg = json.loads(open(os.path.join(tmp, "opencode.jsonc"), encoding="utf-8").read())
	assert not any("RED_PILL.md" in e for e in (cfg.get("instructions") or [])), (
		"`instructions` no debe apuntar al viejo RED_PILL.md: la ruta relativa se ignora en silencio"
	)


def test_migra_instalacion_con_instructions_legacy(adapter, tmp_path) -> None:
	"""Una instalación previa con `instructions: ["RED_PILL.md"]` y el fichero
	suelto converge: entrada retirada y fichero retirado (era sólo nuestro)."""
	import argparse
	import json
	import os

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	cfg_path = os.path.join(tmp, "opencode.jsonc")
	with open(cfg_path, "w", encoding="utf-8") as f:
		json.dump(
			{
				"instructions": ["RED_PILL.md", "docs/mias.md"],
				"references": {"keep": {"path": "/x"}},
			},
			f,
		)
	legacy = os.path.join(tmp, "RED_PILL.md")
	with open(legacy, "w", encoding="utf-8") as f:
		f.write("<!-- REDPILL:BEGIN sovereign_handshake v=3 -->\nbloque\n<!-- REDPILL:END sovereign_handshake -->\n")

	adapter.inject(argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False))

	cfg = json.loads(open(cfg_path, encoding="utf-8").read())
	assert cfg["instructions"] == ["docs/mias.md"], "sólo debe caer la entrada legacy"
	assert cfg["references"]["keep"]["path"] == "/x", "config ajena preservada"
	assert not os.path.exists(legacy), "RED_PILL.md legacy (sólo bloques) debe retirarse"
	assert os.path.exists(os.path.join(tmp, "AGENTS.md"))


def test_red_pill_md_con_contenido_propio_se_conserva(adapter, tmp_path) -> None:
	import argparse
	import os

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	legacy = os.path.join(tmp, "RED_PILL.md")
	with open(legacy, "w", encoding="utf-8") as f:
		f.write("# mis notas\n<!-- REDPILL:BEGIN sovereign_handshake v=3 -->\nbloque\n<!-- REDPILL:END sovereign_handshake -->\n")

	adapter.inject(argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False))
	assert os.path.exists(legacy), "un fichero con contenido del operador no se toca"


def test_registro_de_anchors_apunta_a_agents_md() -> None:
	import importlib.util
	import sys

	path = os.path.join(REPO_ROOT, "scripts", "inject_anchor.py")
	spec = importlib.util.spec_from_file_location("inject_anchor_under_test", path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_anchor_under_test"] = mod
	spec.loader.exec_module(mod)
	target = mod.REGISTRY_BY_IDE["opencode"]
	assert target.path == "~/.config/opencode/AGENTS.md"
	assert mod.OPENCODE_INSTRUCTIONS_FILE == "AGENTS.md"


def _inject(adapter, tmp_path, **kw):
	import argparse

	adapter._detect_config_dir = lambda: str(tmp_path)  # noqa: E731
	args = argparse.Namespace(
		redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False, **kw
	)
	return adapter.inject(args)


def test_remove_desinstala_de_verdad(adapter, tmp_path) -> None:
	"""Regresión 2026-10-27: `inject_cli --ide opencode --remove` era un no-op.

	El adapter (camino de install/update, vía `inject_cli.py`) no tenía rama de
	borrado: desinstalar dejaba bloques, skills, agentes y plugin vivos. Sólo el
	`inject_opencode.py` standalone lo implementaba, y ese no es el que corre.
	"""
	import os

	tmp = str(tmp_path)
	assert _inject(adapter, tmp_path) > 0
	assert os.path.exists(os.path.join(tmp, "AGENTS.md"))
	cfg_antes = open(os.path.join(tmp, "opencode.jsonc"), encoding="utf-8").read()

	removed = _inject(adapter, tmp_path, remove=True)
	assert removed > 0, "el remove no retiró nada"
	assert not os.path.exists(os.path.join(tmp, "AGENTS.md")), "AGENTS.md vacío debe irse"
	for sub in ("skills", "agents", "plugins"):
		path = os.path.join(tmp, sub)
		assert not os.listdir(path) if os.path.isdir(path) else True, f"{sub} dejó restos"
	# La config NO se toca: deshacer el merge de claves ajenas no es posible.
	assert open(os.path.join(tmp, "opencode.jsonc"), encoding="utf-8").read() == cfg_antes


def test_remove_conserva_el_agents_md_del_operador(adapter, tmp_path) -> None:
	import os

	tmp = str(tmp_path)
	_inject(adapter, tmp_path)
	agents = os.path.join(tmp, "AGENTS.md")
	with open(agents, "a", encoding="utf-8") as f:
		f.write("\n## Reglas mías\n- no tocar producción\n")

	_inject(adapter, tmp_path, remove=True)

	assert os.path.exists(agents), "el operador tenía contenido propio: no se borra"
	rest = open(agents, encoding="utf-8").read()
	assert "no tocar producción" in rest
	assert "REDPILL:" not in rest, "los bloques nuestros sí deben irse"


def test_remove_es_idempotente(adapter, tmp_path) -> None:
	_inject(adapter, tmp_path)
	_inject(adapter, tmp_path, remove=True)
	assert _inject(adapter, tmp_path, remove=True) == 0
