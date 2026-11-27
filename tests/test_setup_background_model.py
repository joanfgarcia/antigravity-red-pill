"""Guard del generador del daemon dual-bind (setup_background_model.sh).

El daemon `run_dual_bind.py` se GENERA desde el heredoc del script. Un deploy a
medias puede dejarlo sin la clase `ModelManager` (NameError en cada request →
sleep/Memento sin distilar, falso positivo). Estos tests validan el artefacto
generado directamente desde la fuente de verdad, sin desplegarlo."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_background_model.sh"


def _generated_daemon() -> str:
	source = SCRIPT.read_text(encoding="utf-8")
	lines = source.splitlines()
	start = next(i for i, ln in enumerate(lines) if ln.startswith("cat << 'DUAL_BIND_EOF'"))
	end = next(i for i, ln in enumerate(lines) if ln == "DUAL_BIND_EOF" and i > start)
	return "\n".join(lines[start + 1 : end])


def test_generated_daemon_compiles():
	compile(_generated_daemon(), "run_dual_bind.py", "exec")


def test_generated_daemon_define_manager():
	source = _generated_daemon()
	assert "class ModelManager:" in source
	assert "manager = ModelManager()" in source


def test_generated_daemon_importa_handlers_de_runtime():
	# Única verdad del renderizado thinking: red_pill.inference.runtime.
	source = _generated_daemon()
	assert "from red_pill.inference.runtime import" in source
	assert "def _apply_chat_handler" not in source
	assert "def _register_thinking_handlers" not in source


def test_generated_daemon_pasa_la_decision_de_dispositivo_al_backend():
	# Regresión de 8d78450: el daemon calculaba n_ctx/n_gpu_layers/flash_attn por
	# dispositivo y `build_local_backend(resolved)` cargaba con los del perfil.
	source = _generated_daemon()
	assert "build_local_backend(resolved, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, flash_attn=flash_attn)" in source


def test_generated_daemon_paraleliza_solo_http_con_slots():
	"""AD-150: generación fuera del lock solo para backend HTTP con np>1.

	El lock se mantiene para modelos en proceso (llama_cpp.Llama) y para el
	camino de carga/cambio; `in_flight` impide que el reaper o un switch
	descarguen el modelo a mitad de una generación.
	"""
	src = _generated_daemon()
	assert "self.in_flight = 0" in src
	assert "def can_parallel_current" in src
	assert "async def ensure_parallel" in src
	assert "async def release" in src
	assert 'getattr(self.model, "http_backend", False)' in src
	assert "await manager.release()" in src
	assert "if manager.in_flight > 0:" in src
