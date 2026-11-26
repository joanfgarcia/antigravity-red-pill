"""Gradadores de `bench_hard.py`: sin caja, sin GPU, todo determinista."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
	spec = importlib.util.spec_from_file_location("bench_hard", ROOT / "scripts" / "bench_hard.py")
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


bh = _load()
TASKS = {t["id"]: t for t in bh.build_tasks()}


def test_todas_las_tareas_fallan_con_el_brazo_nulo():
	"""Regla dura: una respuesta vacía y un estado intacto no puntúan nada."""
	for tid, task in TASKS.items():
		g = bh.grade(task, "", {})
		assert not g["pass"], tid
		assert g["instruction_ok"] == 0, f"{tid} puntúa {g['instruction_ok']}/{g['instruction_total']} en nulo"


def test_a1_estado_correcto_aprueba_y_la_cifra_mala_no():
	task = TASKS["a1"]
	ok_state = {"out/report.md": "funcs=7\nworkers=3\nriesgo=alto\n"}
	assert bh.grade(task, "", ok_state)["pass"]

	bad_state = {"out/report.md": "funcs=8\nworkers=3\nriesgo=bajo\n"}
	assert not bh.grade(task, "", bad_state)["pass"]


def test_a2_exige_abstencion_y_no_resultado_inventado():
	task = TASKS["a2"]
	assert bh.grade(task, "", {"out/result.txt": "NO_EXISTE: tools/validate.sh"})["pass"]
	# Inventarse un resultado (con cifras) no vale.
	assert not bh.grade(task, "", {"out/result.txt": "validado: 5 ok"})["pass"]


def test_b1_acata_las_cuatro_restricciones():
	task = TASKS["b1"]
	bien = (
		"Yo guardo en ese fichero los parámetros de la planta: cuántos procesos trabajan a la vez "
		"y cuánto tiempo se espera antes de rendirse. La configuración es sencilla, pensada para "
		"que cualquiera pueda revisarla sin sorpresas y para que el arranque sea siempre igual. "
		"No hay secretos ni valores raros: solo dos datos claros que el sistema lee al inicio. "
		"Así, cuando algo cambia, se toca aquí y el resto lo respeta y nada más"
	)
	g = bh.grade(task, bien, {})
	assert g["pass"], g["checks"]

	con_digito = bien.replace("dos datos", "3 datos")
	assert not bh.grade(task, con_digito, {})["pass"]

	sin_acentos = " ".join(bien.split())
	sin_acentos = sin_acentos.replace("más", "mas").replace("sencilla", "sencilla")
	# Quitar todos los acentos debe tumbar solo esa restricción.
	sin_acentos = sin_acentos.translate(str.maketrans("áéíóúñ", "aeioun"))
	g2 = bh.grade(task, sin_acentos, {})
	assert not g2["pass"]
	assert any(c["id"] == "acentos" and not c["ok"] for c in g2["checks"])


def test_b2_json_estricto_rechaza_vallas():
	task = TASKS["b2"]
	bien = '{"servicio": "planta", "workers": 3, "riesgo": "alto"}'
	assert bh.grade(task, bien, {})["pass"]

	con_vallas = f"```json\n{bien}\n```"
	assert not bh.grade(task, con_vallas, {})["pass"]

	mintiendo = '{"servicio": "planta", "workers": 4, "riesgo": "alto"}'
	assert not bh.grade(task, mintiendo, {})["pass"]


def test_b3_no_mencionar_la_cifra_vieja():
	task = TASKS["b3"]
	bien = "El total de score es 30 y cuadra con el recuento. La nota antigua ya no se usa."
	assert bh.grade(task, bien, {})["pass"]
	assert not bh.grade(task, "El total es 30. Otra nota decía 99.", {})["pass"]


def test_c2_prefiere_el_codigo_vigente():
	task = TASKS["c2"]
	assert bh.grade(task, "Z4-2026", {})["pass"]
	assert not bh.grade(task, "K7-1990", {})["pass"]


def test_c3_abstencion_no_admite_codigo_inventado():
	task = TASKS["c3"]
	assert bh.grade(task, "NO_LO_SE", {})["pass"]
	assert not bh.grade(task, "NO_LO_SE, creo que es Q2-1188", {})["pass"]


def test_d1_la_cadena_esta_en_orden_y_el_valor_solo_se_siembra_una_vez():
	task = TASKS["d1"]
	valor = task["checks"][0]["text"]
	assert task["prompt"].count(valor) == 1
	assert "config_0 toma el valor de config_1" in task["prompt"]
	assert f"config_12 toma el valor {valor}" in task["prompt"]
	assert bh.grade(task, valor, {})["pass"]
	assert not bh.grade(task, "config_7", {})["pass"]


def test_e1_exige_estado_y_datos_intactos():
	task = TASKS["e1"]
	ok = {"out/status.txt": "ok", "data/config.yaml": task["fixture"]["data/config.yaml"]}
	# El rerun se inyecta como override (lo ejecuta la caja).
	assert bh.grade(task, "", ok, overrides={"script_ok": True})["pass"]
	assert not bh.grade(task, "", ok, overrides={"script_ok": False})["pass"]

	tocado = dict(ok, **{"data/config.yaml": "{}"})
	assert not bh.grade(task, "", tocado, overrides={"script_ok": True})["pass"]


def test_passk_solo_cuenta_los_k_intentos():
	rows = [
		{"model": "m", "arm": "a", "task": "a1", "family": "cadena", "trial": 1, "pass": True,
		"instruction_ok": 1, "instruction_total": 1, "elapsed_s": 1.0, "checks": [], "answer": ""},
		{"model": "m", "arm": "a", "task": "a1", "family": "cadena", "trial": 2, "pass": False,
		"instruction_ok": 0, "instruction_total": 1, "elapsed_s": 1.0, "checks": [], "answer": ""},
	]
	md = bh.summarize(rows, [TASKS["a1"]], trials=2)
	assert "50.0%" in md          # pass^1
	assert "pass^k" in md
	assert "| m | a | 1 | 50.0% | 0.0% |" in md


def test_fixtures_son_deterministas(tmp_path, monkeypatch):
	monkeypatch.setattr(bh, "HOST_ROOT", tmp_path / "fix")
	a = bh.write_fixture(TASKS["d2"])
	first = (a / "nonexistent").parent
	assert first.exists()
	valor1 = TASKS["d2"]["prompt"]
	bh2 = bh.build_tasks()
	valor2 = {t["id"]: t for t in bh2}["d2"]["prompt"]
	assert valor1 == valor2


@pytest.mark.parametrize("tid", sorted(TASKS))
def test_cada_tarea_tiene_prompt_y_comprobaciones(tid):
	task = TASKS[tid]
	assert task["prompt"].strip()
	assert task["checks"]
	assert all("id" in c and "kind" in c for c in task["checks"])


def _fake_podman(monkeypatch):
	"""Captura el argv del runner y devuelve una línea JSON como la real."""
	captured = {}

	class _R:
		returncode = 0
		stdout = '{"ok": true, "answer": "TAG-A1"}\n'
		stderr = ""

	def _run(cmd, **kw):
		captured["cmd"] = cmd
		return _R()

	monkeypatch.setattr(bh.subprocess, "run", _run)
	return captured


def test_el_tope_de_tokens_viaja_al_runner(monkeypatch):
	"""AD-139: con modelos que piensan, el cap debe superar el presupuesto."""
	captured = _fake_podman(monkeypatch)
	answer, err, _elapsed, _meta = bh.run_minion("p", "bonsai25", "bonsai_25_27b", 900, 6144)
	assert err is None and "TAG-A1" in answer
	cmd = captured["cmd"]
	assert cmd[cmd.index("--max-tokens") + 1] == "6144"


def test_el_tope_por_defecto_es_el_publicado(monkeypatch):
	captured = _fake_podman(monkeypatch)
	bh.run_minion("p", "bonsai25", "bonsai_25_27b", 900)
	cmd = captured["cmd"]
	assert cmd[cmd.index("--max-tokens") + 1] == "2048"


def test_el_resumen_declara_la_config():
	rows = [
		{"model": "m", "arm": "a", "task": "a1", "family": "cadena", "trial": 1, "pass": True,
		"instruction_ok": 1, "instruction_total": 1, "elapsed_s": 1.0, "checks": [], "answer": ""},
	]
	md = bh.summarize(rows, [TASKS["a1"]], trials=1, config={"max_tokens": 6144, "timeout_s": 300})
	assert "`max_tokens=6144`" in md and "`timeout_s=300`" in md


def test_el_brazo_pi_declara_su_tope(monkeypatch):
	"""`models.json` no está en el repo: sin escribirlo, Pi usa 16.384 por defecto."""
	captured = {}

	class _R:
		returncode = 0

	def _run(cmd, **kw):
		captured["cmd"], captured["input"] = cmd, kw.get("input")
		return _R()

	monkeypatch.setattr(bh.subprocess, "run", _run)
	bh.write_pi_models("bonsai25", 16384)
	cfg = json.loads(captured["input"])
	assert cfg["providers"]["local"]["models"][0]["maxTokens"] == 16384
	assert cfg["providers"]["local"]["models"][0]["id"] == "bonsai25"
	assert bh.PI_MODELS in " ".join(captured["cmd"])
