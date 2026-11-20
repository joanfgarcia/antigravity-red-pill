"""MEM-012 · F3 — tasa de abstención y registro de demanda.

Lo que se prueba aquí es que el registro dice la verdad (tasa y demanda), que no
se lleva secretos, que se puede apagar y que un fallo de escritura no rompe nada.
"""

from __future__ import annotations

from red_pill.recall_demand import abstention_rate, load_demand, load_stats, record_recall


def test_registra_la_tasa_y_la_demanda(tmp_path):
	record_recall(
		query="receta de paella con api_key=SECRET123",
		collection="work_memories",
		confidence="insuficiente",
		no_recall=True,
		max_similarity=0.19,
		below_floor_count=3,
		caller="test",
		state_dir=tmp_path,
	)
	record_recall(
		query="checkpoint híbrido",
		collection="work_memories",
		confidence="alta",
		no_recall=False,
		max_similarity=0.78,
		caller="test",
		state_dir=tmp_path,
	)

	stats = load_stats(tmp_path)
	assert stats["total"] == 2
	assert stats["no_recall"] == 1
	assert abstention_rate(stats) == 0.5
	assert stats["by_collection"]["work_memories"] == {"total": 2, "no_recall": 1}
	assert stats["by_confidence"]["insuficiente"] == 1
	assert stats["by_confidence"]["alta"] == 1
	assert stats["below_floor_total"] == 3

	demand = load_demand(state_dir=tmp_path)
	assert len(demand) == 1, "solo se guarda lo que no estaba"
	assert demand[0]["collection"] == "work_memories"
	assert demand[0]["below_floor_count"] == 3
	assert "SECRET123" not in demand[0]["query"], "el registro no colecciona credenciales"


def test_apagado_no_escribe_nada(tmp_path):
	wrote = record_recall(
		query="paella",
		collection="work_memories",
		confidence="insuficiente",
		no_recall=True,
		enabled=False,
		state_dir=tmp_path,
	)

	assert wrote is False
	assert not (tmp_path / "recall_abstention_stats.json").exists()
	assert not (tmp_path / "recall_demand.jsonl").exists()


def test_la_consulta_se_recorta(tmp_path):
	record_recall(
		query="x" * 1000,
		collection="work_memories",
		confidence="insuficiente",
		no_recall=True,
		max_chars=50,
		state_dir=tmp_path,
	)

	assert len(load_demand(state_dir=tmp_path)[0]["query"]) <= 50


def test_sin_muestra_no_hay_tasa():
	assert abstention_rate({}) is None
	assert abstention_rate({"total": 0, "no_recall": 0}) is None
