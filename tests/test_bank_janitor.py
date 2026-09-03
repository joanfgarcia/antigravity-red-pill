"""bank_janitor — higiene del memory bank por workspace (convención @refs canónica).

Fija la decisión operador 2026-09-03: el índice `MEMORY.md` se mantiene con
`@fichero.md`. Los enlaces markdown (`[t](./f.md)`, `[t](file://./f.md)`) solo
se diagnostican (`non_canonical_refs`), nunca cuentan como índice.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import bank_janitor as bj

OLD_TS = time.time() - 100 * 86400  # > BANK_ARCHIVE_AGE_DAYS (90)


def _bank(tmp_path: Path, index: str | None, files: dict[str, str] | None = None) -> Path:
	bank = tmp_path / "bank"
	bank.mkdir()
	for name, content in (files or {"keep.md": "# keep\n"}).items():
		p = bank / name
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(content, encoding="utf-8")
	if index is not None:
		(bank / "MEMORY.md").write_text(index, encoding="utf-8")
	return bank


def _age(bank: Path, name: str, old: bool = True) -> None:
	ts = OLD_TS if old else time.time()
	os.utime(bank / name, (ts, ts))


def test_index_refs_counts_at_refs(tmp_path):
	bank = _bank(tmp_path, "# idx\n@keep.md\n@sub/other.md\n")
	refs = bj._index_refs(bank)
	assert refs == {"keep.md", "sub/other.md"}


def test_migrated_index_counts_refs(tmp_path):
	bank = _bank(tmp_path, "# Workspace Memory\n\n## Active Anchors\n- @keep.md — guidelines.\n")
	_age(bank, "keep.md", old=False)
	h = bj.audit_bank(bank, "ws", apply=False)
	assert h["index"]["refs_total"] == 1
	assert h["index"]["non_canonical_refs"] == []
	assert h["index"]["orphans"] == []


def test_non_canonical_links_diagnosed_not_counted(tmp_path):
	idx = "# idx\n- [keep](file://./keep.md) — guidelines.\n- [o](./other.md)\n"
	bank = _bank(tmp_path, idx, {"keep.md": "# k\n", "other.md": "# o\n"})
	_age(bank, "keep.md", old=False)
	_age(bank, "other.md", old=False)
	h = bj.audit_bank(bank, "ws", apply=True)
	assert h["index"]["refs_total"] == 0
	assert h["index"]["non_canonical_refs"] == ["keep.md", "other.md"]
	# Sin @refs no hay base para archivar: el guard suprime aunque haya candidatos viejos
	_age(bank, "other.md", old=True)
	h2 = bj.audit_bank(bank, "ws", apply=True)
	assert h2["archive_suppressed_no_index"] is True
	assert h2["archived"] == []
	assert (bank / "other.md").exists()


def test_guard_no_index_never_archives(tmp_path):
	bank = _bank(tmp_path, None, {"old.md": "# old\n"})
	_age(bank, "old.md", old=True)
	h = bj.audit_bank(bank, "ws", apply=True)
	assert h["archived"] == []
	assert h["archive_suppressed_no_index"] is True
	assert (bank / "old.md").exists()


def test_apply_archives_old_unreferenced_only(tmp_path):
	bank = _bank(tmp_path, "# idx\n@keep.md\n", {"keep.md": "# k\n", "old.md": "# o\n"})
	_age(bank, "keep.md", old=True)  # referenciado: aunque viejo, no se toca
	_age(bank, "old.md", old=True)
	h = bj.audit_bank(bank, "ws", apply=True)
	assert h["archived"] == ["old.md"]
	assert (bank / "archive" / "old.md").exists()
	assert (bank / "keep.md").exists()
	assert h["archive_suppressed_no_index"] is False


def test_dry_run_never_moves(tmp_path):
	bank = _bank(tmp_path, "# idx\n@keep.md\n", {"keep.md": "# k\n", "old.md": "# o\n"})
	_age(bank, "old.md", old=True)
	h = bj.audit_bank(bank, "ws", apply=False)
	assert h["archived"] == []
	assert h["archive_candidates"] == ["old.md"]
	assert (bank / "old.md").exists()


def test_duplicates_exact_reported(tmp_path):
	bank = _bank(tmp_path, "# idx\n@a.md\n", {"a.md": "same\n", "b.md": "same\n", "c.md": "diff\n"})
	_age(bank, "a.md", old=False)
	_age(bank, "b.md", old=False)
	_age(bank, "c.md", old=False)
	h = bj.audit_bank(bank, "ws", apply=False)
	assert sorted(map(sorted, h["duplicates"])) == [["a.md", "b.md"]]
