"""NB-001 P6 (F4-banco): `scripts/bench_annotate.py` reproducible y medible.

Contrato (PLAN-NB-001 §3 F4 / D-NB-04):
- P6.1 `--dry-run` sale 0 y escribe JSONL con el esquema documentado (v1).
- P6.2 el fixture es estable: mismo hash entre corridas (congelado).
- P6.3 el banco imprime el baseline (2 llamadas por split, work + social).

El dry-run usa un transporte falso (sin LLM): valida el arnés y el fixture, y ya
imprime el baseline porque es una propiedad del pipeline, no del modelo.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "bench_annotate.py"

# Hash canónico del fixture FIJO — si el fixture cambia, este test lo detecta
# (hay que recongelar a propósito, no en silencio).
FROZEN_FIXTURE_HASH = "sha256:2a10110542b6d012fc4bd3876a583b634b6adcdf676d3e547025bdc710d8798e"

SCHEMA_KEYS = {
	"bench",
	"schema_version",
	"ts",
	"dry_run",
	"fixture_hash",
	"fixture_fragments",
	"repetition",
	"llamadas",
	"llamadas_extract",
	"llamadas_score",
	"llamadas_rewrite",
	"llamadas_por_fragmento",
	"extract_por_fragmento",
	"notas_total",
	"notas_por_fragmento",
	"rutas",
	"truncados",
	"json_invalido",
	"segundos_total",
	"segundos_por_fragmento",
}


def _run_bench(out_dir: Path, *extra: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		[sys.executable, str(SCRIPT), "--out", str(out_dir), *extra],
		capture_output=True,
		text=True,
		timeout=120,
	)


def _records(out_dir: Path) -> list[dict]:
	path = out_dir / "ANNOTATE_BENCH.jsonl"
	assert path.exists(), f"falta {path}"
	records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
	assert records, "JSONL vacío"
	return records


# ── P6.1 dry-run sale 0 y escribe JSONL con el esquema documentado ──


def test_dry_run_exits_zero_and_writes_documented_schema(tmp_path):
	proc = _run_bench(tmp_path, "--dry-run", "--repetitions", "2")
	assert proc.returncode == 0, proc.stderr

	records = _records(tmp_path)
	assert len(records) == 2
	for record in records:
		assert SCHEMA_KEYS <= set(record), f"claves faltantes: {SCHEMA_KEYS - set(record)}"
		assert record["bench"] == "annotate"
		assert record["schema_version"] == 1
		assert record["dry_run"] is True
		assert record["fixture_fragments"] == len(record["notas_por_fragmento"]) == len(record["segundos_por_fragmento"])
		assert set(record["rutas"]) == {"work", "social", "none"}
		assert isinstance(record["llamadas"], int) and record["llamadas"] > 0
		assert isinstance(record["truncados"], int) and isinstance(record["json_invalido"], int)


# ── P6.2 el fixture es estable (mismo hash entre corridas) ──


def test_fixture_is_stable_between_runs(tmp_path):
	first = tmp_path / "a"
	second = tmp_path / "b"
	assert _run_bench(first, "--dry-run").returncode == 0
	assert _run_bench(second, "--dry-run").returncode == 0

	hash_a = _records(first)[0]["fixture_hash"]
	hash_b = _records(second)[0]["fixture_hash"]
	assert hash_a == hash_b == FROZEN_FIXTURE_HASH


# ── P6.3 el banco imprime el baseline (2 llamadas por split) ──


def test_bench_prints_two_calls_per_split_baseline(tmp_path):
	proc = _run_bench(tmp_path, "--dry-run")
	assert proc.returncode == 0, proc.stderr
	assert "2 llamadas por split" in proc.stdout

	record = _records(tmp_path)[0]
	assert record["extract_por_fragmento"] == 2.0
	assert record["llamadas_extract"] == record["fixture_fragments"] * 2


# ── P7 (F4-fusión): --single-call mide UNA llamada combinada por split ──


def test_bench_single_call_one_extract_per_split(tmp_path):
	proc = _run_bench(tmp_path, "--dry-run", "--single-call")
	assert proc.returncode == 0, proc.stderr
	assert "1 llamada por split" in proc.stdout

	record = _records(tmp_path)[0]
	assert record["extract_por_fragmento"] == 1.0
	assert record["llamadas_extract"] == record["fixture_fragments"]
	# El dry-run combinado materializa la MISMA idea por fragmento (con scope work):
	# mismas notas, mismas rutas y sin truncados ni JSON inválido.
	assert record["notas_total"] == record["fixture_fragments"]
	assert record["truncados"] == 0
	assert record["json_invalido"] == 0
