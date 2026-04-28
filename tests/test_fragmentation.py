import red_pill.config as cfg
from red_pill.utils.fragmentation import synaptic_split


def test_synaptic_split_no_split():
	"""Text smaller than threshold should not be split."""
	text = "Short memory."
	chunks = synaptic_split(text)
	assert len(chunks) == 1
	assert chunks[0] == text


def test_synaptic_split_simple_split():
	"""Text larger than threshold should be split."""
	original_threshold = cfg.CHUNK_THRESHOLD
	original_size = cfg.CHUNK_SIZE
	cfg.CHUNK_THRESHOLD = 20
	cfg.CHUNK_SIZE = 15
	cfg.CHUNK_OVERLAP = 5
	try:
		text = "This is a long sentence that should be split."
		chunks = synaptic_split(text)
		assert len(chunks) > 1
		for i in range(len(chunks) - 1):
			assert chunks[i][-5:] == chunks[i + 1][:5]
	finally:
		cfg.CHUNK_THRESHOLD = original_threshold
		cfg.CHUNK_SIZE = original_size


def test_synaptic_split_recursive():
	"""Verify recursive splitting on different separators."""
	original_threshold = cfg.CHUNK_THRESHOLD
	original_size = cfg.CHUNK_SIZE
	cfg.CHUNK_THRESHOLD = 50
	cfg.CHUNK_SIZE = 40
	try:
		text = "Paragraph one with some text.\n\nParagraph two with more text that is quite long indeed."
		chunks = synaptic_split(text)
		assert len(chunks) >= 2
		assert any(("Paragraph one" in c for c in chunks))
		assert any(("Paragraph two" in c for c in chunks))
	finally:
		cfg.CHUNK_THRESHOLD = original_threshold
		cfg.CHUNK_SIZE = original_size
