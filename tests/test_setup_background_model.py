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
