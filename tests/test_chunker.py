"""Unit tests for chunker.py turn-aware splitting and runt absorption."""

from red_pill.metabolism.chunker import _is_template_echo, _sanitize_llm_json, chunk_text


def test_chunk_text_empty():
	assert chunk_text("") == []
	assert chunk_text("   ") == []


def test_chunk_text_small():
	text = "Hello world, this is a short test message."
	chunks = chunk_text(text, size=500)
	assert len(chunks) == 1
	assert chunks[0] == text


def test_chunk_text_dialogue_boundaries():
	text = (
		"USER: Hola Aleth, he estado pensando sobre los engramas.\n"
		"ASSISTANT: Entendido Fixer. La memoria persistente es clave para nuestra soberanía.\n"
		"USER: ¿Podemos asegurar que los modelos locales no se descarguen de red de nuevo?\n"
		"ASSISTANT: Por supuesto, podemos forzar local_files_only=True y validar con Pydantic."
	)
	chunks = chunk_text(text, size=150)
	assert len(chunks) >= 2
	# Verify chunks cut at clean line/turn boundaries
	for chunk in chunks:
		assert chunk.strip().startswith(("USER:", "ASSISTANT:"))


def test_is_template_echo():
	assert _is_template_echo("synthesize these memory chunks into a summary") is True
	assert _is_template_echo("") is True
	assert _is_template_echo("Compramos un Emilio Moro Reserva en Porto Pi.") is False


def test_sanitize_llm_json():
	bad_json = '{"key": "value \\e with illegal escape \\s"}'
	sanitized = _sanitize_llm_json(bad_json)
	assert "\\\\e" in sanitized
	assert "\\\\s" in sanitized


def test_detect_source_lang():
	from red_pill.metabolism.distiller import _detect_source_lang

	assert _detect_source_lang("¿Qué tal? esto es una ñ") == "es"
	assert _detect_source_lang("café con música y una canción") == "es"
	assert _detect_source_lang("the and of is in to that") == "en"
	assert _detect_source_lang("The quick brown fox jumps over the lazy dog and the cat") == "en"
	assert _detect_source_lang("1234") == ""


def test_correct_lang_label():
	from red_pill.metabolism.distiller import _correct_lang_label

	# modelo dijo 'en' sobre texto español → corregido a 'es'
	assert _correct_lang_label("en", "Joan me cuenta que el café está frío") == "es"
	# modelo dijo 'ca' → no se toca
	assert _correct_lang_label("ca", "El café és fred") == "ca"
	# modelo dijo 'es' sobre texto inglés sin marcadores → se mantiene si sin señal fuerte
	assert _correct_lang_label("es", "The and of is") == "en"


def test_load_distiller_config_y_prompt(tmp_path):
	from red_pill.metabolism import distiller as D

	# defaults cuando no hay fichero
	cfg = D.load_distiller_config(str(tmp_path / "no.yaml"))
	assert cfg is not None

	# fichero YAML válido (anidado)
	y = tmp_path / "p.yaml"
	y.write_text("distill_engram:\n  temperature: 0.3\n")
	cfg2 = D.load_distiller_config(str(y))
	assert cfg2.distill_engram.temperature == 0.3

	# prompt: override gana
	assert D.load_prompt_text("distiller_v3.txt", fallback_prompt="FB", override_text="OV") == "OV"
	# prompt desde fichero real
	assert D.load_prompt_text("distiller_v3_voice.txt", fallback_prompt="FB") != "FB"
	# prompt inexistente → fallback
	assert D.load_prompt_text("no_existe.txt", fallback_prompt="FB") == "FB"
