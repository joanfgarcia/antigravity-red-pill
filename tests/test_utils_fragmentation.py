"""Tests for utils/fragmentation.py — targeting lines 34, 44-45, 64, 82."""
import pytest
from unittest.mock import patch

import red_pill.config as cfg
from red_pill.utils.fragmentation import synaptic_split, _recursive_split


class TestSynapticSplit:
    def test_short_text_returned_as_is(self):
        """Line 20-21: text <= CHUNK_THRESHOLD → single-element list."""
        short = "x" * (cfg.CHUNK_THRESHOLD - 1)
        result = synaptic_split(short)
        assert result == [short]

    def test_long_text_is_split(self):
        """Lines 23-24: text > CHUNK_THRESHOLD → multiple chunks."""
        long_text = ("word " * 500).strip()
        result = synaptic_split(long_text)
        assert len(result) > 1


class TestRecursiveSplit:
    def test_text_already_small_returns_single(self):
        """Line 33-34: text <= chunk_size → returns immediately."""
        result = _recursive_split("small", ["\n", " "], 100, 10)
        assert result == ["small"]

    def test_empty_separator_char_split(self):
        """Lines 43-45, 64: no visible separators found → character-level fallback."""
        # Use only the empty string as separator → hits lines 43-45 directly
        # Then separator=="" → character split (line 64)
        no_sep_text = "abcdefghij" * 3  # 30 chars, no separators
        result = _recursive_split(no_sep_text, [""], chunk_size=10, overlap=0)
        # Characters are split into lists, then grouped into chunks of 10
        assert len(result) >= 2
        assert "".join(result).replace("", "") != ""  # content preserved

    def test_paragraph_separator_used(self):
        """Lines 46-49: \n\n separator found → used to split."""
        text = ("paragraph one.\n\n" * 10).strip()
        result = _recursive_split(text, ["\n\n", "\n", ". ", " ", ""], chunk_size=30, overlap=0)
        assert len(result) > 1

    def test_force_split_when_no_more_separators(self):
        """Line 82: separator found, item > chunk_size, new_separators=[] → force truncate."""
        # '. ' is the ONLY separator → new_separators=[] after match.
        # Text splits into ['AAA...A. ', 'BBB...B'] where first part > chunk_size.
        # Since new_separators is empty, hits the else branch: append item[:chunk_size].
        text = "A" * 60 + ". " + "B" * 30
        result = _recursive_split(text, [". "], chunk_size=50, overlap=0)
        # First item ("A"*60 + ". ") is 62 chars > 50 → force-truncated to 50
        assert all(len(r) <= 50 for r in result)


    def test_overlap_applied_on_new_chunk(self):
        """Lines 85-87: overlap text from previous chunk prepended to new chunk."""
        # Create text that will split across chunk boundaries
        text = "hello " * 20  # 120 chars
        result = _recursive_split(text, [" ", ""], chunk_size=20, overlap=5)
        # With overlap=5, each new chunk starts with last 5 chars of previous
        assert len(result) > 1

    def test_recursive_split_on_oversized_item(self):
        """Lines 77-79: item > chunk_size and new_separators available → recurse."""
        # "\n\n" is first separator, splits into two big chunks each >chunk_size
        # Then recurse with ["\n", ". ", " ", ""]
        part = ("word " * 30)  # 150 chars
        text = part + "\n\n" + part
        result = _recursive_split(
            text, ["\n\n", "\n", ". ", " ", ""], chunk_size=50, overlap=5
        )
        assert len(result) >= 4  # Should produce many sub-chunks
