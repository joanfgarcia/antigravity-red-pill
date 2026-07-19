"""synaptic_split never emits empty/whitespace fragments (immune-shrapnel source fix)."""

import red_pill.config as cfg
from red_pill.utils.fragmentation import synaptic_split


def test_separator_heavy_text_yields_no_empty_fragments(monkeypatch):
	monkeypatch.setattr(cfg, "CHUNK_THRESHOLD", 100)
	monkeypatch.setattr(cfg, "CHUNK_SIZE", 50)
	monkeypatch.setattr(cfg, "CHUNK_OVERLAP", 10)
	text = "bloque real de contenido. " * 5 + "\n\n" * 40 + " " * 60 + "\n\n" + "otro bloque real. " * 5
	fragments = synaptic_split(text)
	assert fragments, "el contenido real debe sobrevivir"
	assert all(f.strip() for f in fragments), "ningún fragmento vacío/whitespace"


def test_small_text_untouched():
	assert synaptic_split("pequeño") == ["pequeño"]
