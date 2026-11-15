"""El fondo declarado por el Operador (RFC-AFE-001 F1).

Contrato que fijan estos tests: un registro por puesto (no por sesión), día
natural (no ventana móvil), escritura serializada con guarda de monotonía, y
lectura que degrada a `sin señal` en vez de romper el turno.
"""

import json
import time
from datetime import datetime

import pytest

from red_pill.config import CHROMA_TONE_MAPPING
from red_pill.core import affect_fondo as fondo


@pytest.fixture
def aislado(tmp_path, monkeypatch):
	monkeypatch.setattr(fondo, "_state_dir", lambda: tmp_path)
	monkeypatch.setattr("red_pill.config.AFFECT_FONDO_ENABLED", True, raising=False)
	return tmp_path


def _ts(y, m, d, hh, mm):
	return datetime(y, m, d, hh, mm).timestamp()


def test_toda_letra_mapea_y_su_color_existe():
	tabla = fondo.letters()
	assert set(tabla) == set(fondo.LETTERS)
	for letra, dato in tabla.items():
		assert dato.get("label"), f"{letra} sin etiqueta"
		assert dato.get("emotion"), f"{letra} sin emoción"
		assert dato.get("color") in CHROMA_TONE_MAPPING, f"{letra} → color inexistente: {dato.get('color')}"


def test_tres_textos_byte_exactos(aislado):
	now = _ts(2026, 11, 14, 11, 20)
	fondo.write("C", now=_ts(2026, 11, 14, 8, 12))
	assert fondo.describe(fondo.read(now=now), now=now) == ("ÁNIMO — fondo: C · cansancio · declarado hoy 08:12 (hace 3.1 h)")
	(aislado / fondo.FILENAME).unlink()  # otra declaración, otro caso
	fondo.write("B", now=_ts(2026, 11, 13, 21, 40))
	assert fondo.describe(fondo.read(now=now), now=now) == ("ÁNIMO — fondo: B · bien · declarado ayer 21:40 — puede no ser de hoy")


def test_sin_fondo_es_sin_senal_byte_exacto(aislado):
	assert fondo.describe(fondo.read()) == ("ÁNIMO — fondo: sin señal (pregúntale cómo está hoy antes de empujar trabajo)")
	assert fondo.block() == fondo.SIN_SENAL


def test_dia_natural_no_ventana_movil(aislado):
	"""Declarado ayer 23:55 y leído hoy 11:50: dice ayer, no «hoy (hace 11.9 h)»."""
	fondo.write("T", now=_ts(2026, 11, 13, 23, 55))
	texto = fondo.describe(fondo.read(now=_ts(2026, 11, 14, 11, 50)), now=_ts(2026, 11, 14, 11, 50))
	assert "ayer 23:55" in texto and "(hace" not in texto


def test_tres_sesiones_leen_el_mismo_fondo(aislado):
	"""El invariante de D-02: no hay un fondo por sesión (no hay clave por leg).

	A escribe, B lee lo de A, B escribe y C ve lo de B con A en el historial.
	"""
	fondo.write("F", by="ses_A", now=time.time() - 60)
	visto_por_b = fondo.read()
	assert visto_por_b["letra"] == "F" and visto_por_b["updated_by"] == "ses_A"
	fondo.write("C", by="ses_B", now=time.time())
	visto_por_c = fondo.read()
	assert visto_por_c["letra"] == "C" and visto_por_c["updated_by"] == "ses_B"
	assert [h["by"] for h in visto_por_c["history"]][-1] == "ses_A"


def test_guarda_de_monotonia(aislado):
	fondo.write("B", by="nueva", now=_ts(2026, 11, 14, 10, 0))
	with pytest.raises(fondo.FondoNoSobrescrito):
		fondo.write("F", by="vieja", now=_ts(2026, 11, 14, 9, 0))
	assert fondo.read()["letra"] == "B", "una declaración más vieja no puede pisar la vigente"
	assert fondo.read()["updated_by"] == "nueva"


def test_historial_acotado_y_con_autor(aislado):
	for i in range(15):
		fondo.write("C" if i % 2 else "B", by=f"ses_{i}", now=time.time() - (15 - i))
	registro = fondo.read()
	assert len(registro["history"]) == fondo.HISTORY_MAX
	assert registro["updated_by"] == "ses_14"


def test_json_corrupto_degrada_a_sin_senal(aislado):
	(aislado / fondo.FILENAME).write_text("{ esto no es json", encoding="utf-8")
	assert fondo.read() is None
	assert fondo.block() == fondo.SIN_SENAL


def test_declared_at_nulo_es_sin_senal(aislado):
	"""Un `null` no puede publicar un fondo del 01-01-1970 (lo cazó el adversarial)."""
	(aislado / fondo.FILENAME).write_text(json.dumps({"letra": "C", "declared_at": None}), encoding="utf-8")
	assert fondo.read() is None
	assert fondo.describe(fondo.read()) == fondo.SIN_SENAL


def test_escritura_vieja_no_se_reporta_como_guardada(aislado):
	fondo.write("C", now=time.time() + 3600)  # reloj adelantado
	with pytest.raises(fondo.FondoNoSobrescrito):
		fondo.write("F", now=time.time())
	assert fondo.read()["letra"] == "C"


def test_flag_apagado_no_cambia_el_tono(aislado, monkeypatch):
	"""Sombra quiere decir inerte: sin flag, el fondo no toca el tono de cada turno."""
	from red_pill.utils.tone_analyzer import ToneAnalyzer, get_current_sync_state

	fondo.write("F")
	monkeypatch.setattr("red_pill.config.AFFECT_FROM_QUEUE", False, raising=False)
	monkeypatch.setattr("red_pill.config.DYNAMIC_EMOTION_SYNC", True, raising=False)
	monkeypatch.setattr(ToneAnalyzer, "get_dominant_mood", staticmethod(lambda manager=None: "gray"))
	monkeypatch.setattr("red_pill.config.AFFECT_FONDO_ENABLED", False, raising=False)
	assert get_current_sync_state()["mood"] == "gray"
	monkeypatch.setattr("red_pill.config.AFFECT_FONDO_ENABLED", True, raising=False)
	assert get_current_sync_state()["mood"] == "red"


def test_low_no_lleva_bloque_y_full_medium_si(aislado):
	"""`low` es despertar/subagente: no hay a quién preguntar (criterio del plan)."""
	import importlib.util
	from pathlib import Path as _Path

	fondo.write("C")
	raiz = _Path(__file__).resolve().parents[1]
	spec = importlib.util.spec_from_file_location("wake_up_v6", raiz / "scripts" / "wake_up_v6.py")
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	assert mod._afecto_para_modo("low") == ""
	assert mod._afecto_para_modo("full").startswith("ÁNIMO — fondo: C · cansancio")
	assert mod._afecto_para_modo("medium").startswith("ÁNIMO — fondo: C · cansancio")


def test_letra_invalida_falla_fuerte(aislado):
	with pytest.raises(ValueError):
		fondo.write("Z")
	assert fondo.read() is None


def test_flag_apagado_no_emite_bloque(aislado, monkeypatch):
	fondo.write("C")
	monkeypatch.setattr("red_pill.config.AFFECT_FONDO_ENABLED", False, raising=False)
	assert fondo.enabled() is False
	assert fondo.block() == ""
