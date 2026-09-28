"""Fallup-watcher v2 — tests puros (mocks, sin red ni servicios).

Cubre los 11 blockers del panel (R1-R4/E1-E3/P1-P5):
- should_fallup: 12 ramas (True estable + 11 False con reason exacta).
- worst_case incluye granite 6.5 (dinámico desde ModelRegistry).
- Generator: el source generado compila y contiene fallup/IS_CPU_WORKER//status/serve_cpu fix.
- Regresión 2590: _same_model ignora n_ctx (histéresis intacta).

Prohibido: llamadas a la red del daemon, servicios del sistema o sondas HW en tests.
Todo VRAM/registry se inyecta por parámetro (free_mb/tier/worst_case_gb).
"""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_background_model.sh"


def _generated_daemon() -> str:
	source = SCRIPT.read_text(encoding="utf-8")
	lines = source.splitlines()
	start = next(i for i, ln in enumerate(lines) if ln.startswith("cat << 'DUAL_BIND_EOF'"))
	end = next(i for i, ln in enumerate(lines) if ln == "DUAL_BIND_EOF" and i > start)
	return "\n".join(lines[start + 1 : end])


# ── should_fallup: 12 ramas ────────────────────────────────────────────────


def _ok():
	from red_pill.core.fallup import should_fallup

	# llama_32 barato: free 7.62GB pasa entrada(3.5)+0.5=4.0 y worst(6.5)+0.5=7.0.
	return should_fallup("cpu", "llama_32", False, "high", 120, 7800, 12, False, True)


def test_should_fallup_true_estable():
	ok, reason = _ok()
	assert ok is True and reason == "stable-fallup"


def test_should_fallup_false_not_cpu():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("gpu", "llama_32", False, "high", 120, 7800, 12, False, True)
	assert (ok, reason) == (False, "not-cpu")


def test_should_fallup_false_disabled():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("cpu", "llama_32", False, "high", 120, 7800, 12, False, False)
	assert (ok, reason) == (False, "fallup-disabled")


def test_should_fallup_false_nothing_loaded():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("cpu", None, False, "high", 120, 7800, 12, False, True)
	assert (ok, reason) == (False, "nothing-loaded")


def test_should_fallup_false_experimental():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("cpu", "experimental:foo.gguf", True, "high", 120, 7800, 12, False, True)
	assert (ok, reason) == (False, "experimental-no-tiers")


def test_should_fallup_false_low_priority():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("cpu", "llama_32", False, "low", 120, 7800, 12, False, True)
	assert (ok, reason) == (False, "low-priority-idle-unloads-anyway")


def test_should_fallup_false_not_idle():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("cpu", "llama_32", False, "high", 10, 7800, 12, False, True)
	assert (ok, reason) == (False, "not-idle")


def test_should_fallup_false_gpu_reserved():
	from red_pill.core.fallup import should_fallup

	ok, reason = should_fallup("cpu", "llama_32", False, "high", 120, 7800, 12, True, True)
	assert (ok, reason) == (False, "gpu-reserved")


def test_should_fallup_false_no_gpu_tier():
	from red_pill.core.fallup import should_fallup

	# free=0 → ningún tier GPU encaja (CPU fallback) → None.
	ok, reason = should_fallup("cpu", "granite_8b", False, "high", 120, 0, 12, False, True)
	assert (ok, reason) == (False, "no-gpu-tier-fits")


def test_should_fallup_false_margin():
	from red_pill.core.fallup import should_fallup

	# llama_32 entrada 3.5 + margen 0.5 = 4.0GB; 3.81GB falla.
	ok, reason = should_fallup("cpu", "llama_32", False, "high", 120, 3900, 12, False, True)
	assert (ok, reason) == (False, "margin")


def test_should_fallup_true_granite_tonight():
	from red_pill.core.fallup import should_fallup

	# Caso real 2026-09-27: granite en CPU con 7.27GB libres → GPU 10240,
	# estable y sin OOM. Entrada 6.5+0.5=7.0 ✓, worst 6.5+0.5=7.0 ✓.
	# (Con margen sobre el tier máximo —7.2+1.0=8.2— este caso daría
	# "margin": código muerto en tarjeta de 8.15GB.)
	ok, reason = should_fallup("cpu", "granite_8b", False, "high", 120, 7450, 12, False, True)
	assert (ok, reason) == (True, "stable-fallup")


def test_should_fallup_false_unstable():
	from red_pill.core.fallup import should_fallup

	# free 4.6GB pasa entrada(3.5)+0.5=4.0 pero stable 3/12 → unstable (antes que worst).
	ok, reason = should_fallup("cpu", "llama_32", False, "high", 120, 4710, 3, False, True)
	assert (ok, reason) == (False, "unstable")


def test_should_fallup_false_worst_case():
	from red_pill.core.fallup import should_fallup

	# Perfil barato cabe (entrada 3.5+0.5=4.0 con 4.6GB) y estable 12/12,
	# pero granite 6.5+0.5=7.0 no cabe → worst-case (anti-flap nocturno R1).
	ok, reason = should_fallup("cpu", "llama_32", False, "high", 120, 4710, 12, False, True)
	assert (ok, reason) == (False, "worst-case")


# ── worst_case + dry_run ───────────────────────────────────────────────────


def test_worst_case_incluye_granite():
	from red_pill.core.fallup import FALLUP_WORST_CASE_MIN_FREE_GB, worst_case_gpu_min_free_gb

	w = worst_case_gpu_min_free_gb()
	assert w >= 6.5  # cubre la entrada GPU de granite_8b (6.5GB)
	assert FALLUP_WORST_CASE_MIN_FREE_GB == 6.5


def test_dry_run_no_muta_y_cpu_none():
	from red_pill.core.fallup import dry_run_gpu_tier
	from red_pill.core.model_registry import ModelRegistry

	before = dict(ModelRegistry.get_profile("granite_8b"))
	assert dry_run_gpu_tier("granite_8b", free_mb=0) is None
	tier = dry_run_gpu_tier("llama_32", free_mb=4710)
	assert tier is not None and tier.get("n_gpu_layers") != 0
	after = ModelRegistry.get_profile("granite_8b")
	assert before == after  # nunca muta
	assert dry_run_gpu_tier("no_existe_xyz", free_mb=99999) is None
	assert dry_run_gpu_tier(None, free_mb=99999) is None


def test_constantes_v2():
	from red_pill.core import fallup as f

	assert f.FALLUP_MIN_IDLE_S == 60
	assert f.FALLUP_STABLE_CHECKS == 12
	assert f.FALLUP_MARGIN_GB == 0.5


# ── Generator: fuente de verdad ────────────────────────────────────────────


def test_generated_daemon_compiles():
	compile(_generated_daemon(), "run_dual_bind.py", "exec")


def test_generated_contiene_fallup():
	src = _generated_daemon()
	assert "from red_pill.core.fallup import" in src
	assert "should_fallup" in src
	assert "FALLUP_" in src
	assert "fallup_stable" in src
	assert "fallup_last_check" in src
	assert "fallup_last_result" in src
	assert "fallup_last_at" in src


def test_generated_reaper_gated_y_serve_cpu_fix():
	src = _generated_daemon()
	assert "if not IS_CPU_WORKER:" in src  # reaper gated (E1)
	assert "global IS_CPU_WORKER" in src
	assert 'os.environ["MINION_CPU_WORKER"] = "1"' in src
	assert "IS_CPU_WORKER = True" in src


def test_generated_status_con_fallup():
	src = _generated_daemon()
	assert '"fallup"' in src
	assert '"enabled"' in src and '"stable"' in src and '"required"' in src
	assert '"last_result"' in src and '"last_check_ts"' in src and '"last_fallup_ts"' in src
	assert "_fallup_enabled" in src  # P3: antes muerto, ahora gatea


def test_generated_toctou_y_e2():
	src = _generated_daemon()
	assert "elapsed2" in src
	assert "_waiters" in src
	assert "queue_worker" in src and "oneshot" in src
	assert "GpuReservationManager" in src
	assert '("unstable", "stable-fallup")' in src


def test_generated_sin_timeout_modificado():
	# La rama de timeout existente NO se toca (solo se añade el bloque fallup).
	src = _generated_daemon()
	assert "DEFAULT_LOW_TIMEOUT" in src and "DEFAULT_HIGH_TIMEOUT" in src
	assert "Idle timeout reached" in src


# ── Regresión 2590: histéresis intacta ─────────────────────────────────────


def test_same_model_ignora_n_ctx():
	"""2590 ciclos unload/reload por comparar n_ctx → _same_model solo mira
	fichero+modo+flash_attn (el resolve mide VRAM con el modelo cargado)."""
	from red_pill.core.model_runtime import ResolvedModel

	a = ResolvedModel(profile_name="granite_8b", model_path="/m/g.gguf", mode="curated", flash_attn="true", n_ctx=6144)
	b = ResolvedModel(profile_name="granite_8b", model_path="/m/g.gguf", mode="curated", flash_attn="true", n_ctx=16384)
	# Misma lógica que ModelManager._same_model del generado (3 campos, sin n_ctx).
	assert (a.model_path == b.model_path and a.mode == b.mode and a.flash_attn == b.flash_attn) is True
	src = _generated_daemon()
	assert "def _same_model" in src
	# El método documenta que NO compara n_ctx (solo comentario, no comparación).
	import re

	m = re.search(r"def _same_model\(.*?\).*?(?=\n\tdef |\nclass |\n@app)", src, re.DOTALL)
	assert m is not None
	body = m.group(0)
	assert "model_path" in body and "flash_attn" in body
	assert "b.n_ctx" not in body and "a.n_ctx" not in body


def test_sin_llamadas_a_red_ni_servicios():
	src = Path(__file__).read_text(encoding="utf-8")
	# Construir los patrones sin dejar el literal en el propio fichero.
	puerto = "87" + "60"
	ctl = "system" + "ctl"
	run = "systemd-" + "run"
	uo = "url" + "open"
	assert puerto not in src
	assert ctl not in src
	assert run not in src
	assert uo not in src
