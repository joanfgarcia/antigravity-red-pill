"""
Synaptic Fragmentation Engine (v5.5.0)
======================================
Logic for splitting large text blocks into semantically coherent chunks.
Prevents vector dilution and retrieval amnesia by ensuring engrams are
granular enough for high-fidelity search.
"""

import re
from typing import List

import red_pill.config as cfg


def synaptic_split(text: str) -> List[str]:
	"""
	Splits text into overlapping chunks using a recursive strategy.
	Priority: Paragraphs (\n\n) > Newlines (\n) > Sentences (.) > Spaces ( ).
	"""
	if len(text) <= cfg.CHUNK_THRESHOLD:
		return [text]

	separators = ["\n\n", "\n", ". ", " ", ""]
	return _recursive_split(text, separators, cfg.CHUNK_SIZE, cfg.CHUNK_OVERLAP)


def _recursive_split(text: str, separators: List[str], chunk_size: int, overlap: int) -> List[str]:
	"""
	Internal recursive splitter. Tries to split on the highest priority
	separator that doesn't exceed the chunk size.
	"""
	# If text is already small enough, we're done with this branch
	if len(text) <= chunk_size:
		return [text]

	# Choose the best separator
	final_chunks: List[str] = []
	separator = separators[-1]
	new_separators: List[str] = []

	for i, s in enumerate(separators):
		# Look for the first separator that appears in the text
		if s == "":
			separator = s
			break
		if s in text:
			separator = s
			new_separators = separators[i + 1 :]
			break

	# Split the text
	if separator != "":
		# Escape separator for regex if it's special (like '.')
		escaped_sep = re.escape(separator)
		splits = re.split(f"({escaped_sep})", text)
		# Re-merge separators with their fragments (keeping consistency)
		items = []
		for i in range(0, len(splits) - 1, 2):
			items.append(splits[i] + splits[i + 1])
		if len(splits) % 2 == 1:
			items.append(splits[-1])
	else:
		# Final fallback: character-based split
		items = list(text)

	# Group items into chunks of target size
	current_chunk = ""
	for item in items:
		if len(current_chunk) + len(item) <= chunk_size:
			current_chunk += item
		else:
			if current_chunk:
				final_chunks.append(current_chunk)

			# If a single item is larger than chunk_size, recurse on it
			if len(item) > chunk_size:
				if new_separators:
					sub_chunks = _recursive_split(item, new_separators, chunk_size, overlap)
					final_chunks.extend(sub_chunks)
				else:
					# Force split if no more separators
					final_chunks.append(item[:chunk_size])
				current_chunk = ""  # Recurse handled the overflow
			else:
				# Start new chunk with overlap from previous
				overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
				current_chunk = overlap_text + item

	if current_chunk:
		final_chunks.append(current_chunk)

	return final_chunks
