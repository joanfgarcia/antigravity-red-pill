"""Tests del resolver de perfiles (RFC-HARNESS-001 · P3b)."""

from __future__ import annotations

import pytest

from red_pill.harness import profile


def test_las_tres_dimensiones_existen():
	names = profile.available()
	assert {"none", "worker", "reviewer", "explorer", "operator"} <= set(names["roles"])
	assert {"local-9b", "cloud-flash", "cloud-frontier"} <= set(names["capabilities"])
	assert {"none", "local", "cloud"} <= set(names["egress"])


def test_local_9b_instala_tres_y_el_resto_va_a_biblioteca():
	b = profile.resolve("worker", "local-9b", "none")
	assert b.window == 16384
	assert b.surface == "codemode"
	assert b.identity_mode == "low"
	assert len(b.skills) == 3
	assert b.skills_library, "lo que no cabe debe seguir accesible, no desaparecer"
	assert b.limits["compact_at"] == 0.65
	assert b.kv == "q8_0"


def test_frontier_instala_casi_todo():
	b = profile.resolve("worker", "cloud-frontier", "cloud")
	assert len(b.skills) >= 7
	assert b.surface == "deferred"
	assert b.identity_mode == "full"


def test_egress_none_bloquea_las_skills_del_mundo_real():
	b = profile.resolve("operator", "cloud-frontier", "none")
	assert "telegram-gateway" not in b.skills
	assert "wake-callback" not in b.skills
	assert "minion-delegation" not in b.skills
	assert b.network == "none"
	assert b.secrets == "none"


def test_egress_cloud_permite_telegram():
	b = profile.resolve("operator", "cloud-frontier", "cloud")
	assert "telegram-gateway" in b.skills
	assert b.network == "egress"


def test_el_rol_manda_en_reglas_y_el_modelo_en_plomeria():
	worker = profile.resolve("worker", "local-9b", "none")
	reviewer = profile.resolve("reviewer", "local-9b", "none")
	assert worker.rules_blocks != reviewer.rules_blocks
	assert worker.surface == reviewer.surface == "codemode"


def test_combinacion_inexistente_falla_ruidosamente():
	with pytest.raises(profile.ProfileError):
		profile.resolve("no-existe", "local-9b", "none")
	with pytest.raises(profile.ProfileError):
		profile.resolve("worker", "no-existe", "none")


def test_describe_es_legible():
	texto = profile.describe(profile.resolve("worker", "local-9b", "none"))
	assert "worker × local-9b × none" in texto
	assert "16,384" in texto


def test_rol_none_es_la_instalacion_estandar():
	"""`none` = despertar normal: identidad full, roster completo y todas las
	skills, sin el presupuesto de un rol acotado."""
	b = profile.resolve("none", "local-9b", "none")
	assert b.all_skills is True
	assert b.identity_mode == "full"
	assert b.rules_blocks == []
