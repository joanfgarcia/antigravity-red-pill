"""Unit tests for chunker.py turn-aware splitting and runt absorption."""

import pytest
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
