"""Update Ritual — versioned, launchable engram-migration steps for upgraders.

OPERATOR RULE (2026-07-18): any change that implies updating Bünker engrams
MUST ship here as a versioned ritual step and be documented in
docs/GUIDES/AGENT_UPDATE_GUIDE.md. Agents updating themselves run this script
as part of the update ritual; it is idempotent and dry-run by default.

Usage:
	uv run python scripts/update_ritual.py             # dry-run: report what would change
	uv run python scripts/update_ritual.py --execute   # apply (take a soul backup first)
	uv run python scripts/update_ritual.py --from 7.6  # only steps newer than your version
"""

import argparse
import sys

sys.path.insert(0, "src")

import red_pill.config as cfg  # noqa: E402


def ritual_7_7_0(mm, execute: bool) -> None:
	"""v7.7.0 — Synaptic Axons & Texture Remediation (AD-023 + ADR-AXON-001).

	Engram-affecting changes an upgrader inherits: (1) orphan-chunk promotion —
	hub-less consolidated turns get their newest chunk flipped sequence_chunk ->
	synthesis_hub (payload gains promoted_from, plus hub_rebuild_pending on
	multi-chunk parents), idempotent; (2) recall calibration — Bayesian deletion
	threshold 0.5 -> 0.2 (code-side; the invariant is verified here), no data
	rewrite because rehabilitation is organic via the non-hiding read path;
	(3) revision backlog advisory — legacy engrams lack category_reviewed_at and
	the operator decides how to drain; this ritual NEVER moves engrams itself;
	(4) new payload fields appear organically on engrams consolidated from now on
	(texture, lang, relics, emotional_vector, category_reviewed_at) and typed
	axons inside `associations` — additive, readers retrocompatible, no backfill.
	"""
	from red_pill.affect import get_memory_engine
	from red_pill.metabolism.axons import load_axon_state
	from red_pill.metabolism.maintenance import promote_orphan_chunks
	from red_pill.metabolism.revision import backlog_count

	print("── Ritual 7.7.0 ──")

	# 1. Calibration invariant (AD-023): threshold strictly below the prior mean.
	threshold = get_memory_engine("bayesian").deletion_threshold
	status = "OK" if threshold < 0.5 else "VIOLATION — engrams are born dead, update your checkout"
	print(f"[1/4] Bayesian deletion threshold: {threshold} ({status})")

	# 2. Orphan-chunk promotion (idempotent engram migration).
	report = promote_orphan_chunks(mm, dry_run=not execute)
	for collection, stats in report.items():
		print(
			f"[2/4] {collection}: {stats['hubless_parents_promoted']} hub-less parents "
			f"{'promoted' if execute else 'WOULD be promoted'} ({stats['multi_chunk_flagged']} flagged hub_rebuild_pending)"
		)

	# 3. Revision backlog advisory — operator decides, the ritual only informs.
	counts = backlog_count(mm.client)
	total = sum(c for c in counts.values() if c > 0)
	print(f"[3/4] Revision backlog (engrams without category_reviewed_at): {counts}")
	if total:
		print(
			f"      {total} legacy engrams pending re-classification. Your call:\n"
			"      - do nothing: RevisionPhase drains them in nightly batches once SLEEP_PLUGIN_REVISION=true\n"
			"      - drain now:  uv run red-pill revision --drain            (dry-run report)\n"
			"                    uv run red-pill revision --drain --execute  (moves engrams)"
		)

	# 4. Axon shadow-rollout state.
	state = load_axon_state()
	runs = int(state.get("completed_runs", 0))
	print(f"[4/4] Axon weaver: SLEEP_PLUGIN_AXONS={cfg.SLEEP_PLUGIN_AXONS}, effective runs={runs}, AXON_READ_ENABLED={cfg.AXON_READ_ENABLED}")
	if cfg.SLEEP_PLUGIN_AXONS and not cfg.AXON_READ_ENABLED and runs >= 4:
		print("      Shadow gate reached (>=4 effective runs): review AxonWeaveEvent telemetry and consider AXON_READ_ENABLED=true.")


RITUALS = [
	("7.7.0", ritual_7_7_0),
]


def main() -> None:
	parser = argparse.ArgumentParser(description="Red Pill update ritual (engram migrations, versioned)")
	parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run report)")
	parser.add_argument("--from", dest="from_version", default="0", help="Run only rituals newer than this version")
	args = parser.parse_args()

	from red_pill.memory import MemoryManager

	mm = MemoryManager()

	def as_tuple(v: str):
		return tuple(int(x) for x in v.split(".") if x.isdigit())

	baseline = as_tuple(args.from_version)
	mode = "EXECUTE" if args.execute else "DRY-RUN"
	print(f"=== UPDATE RITUAL ({mode}) ===")
	if args.execute:
		print("Reminder: 'red-pill soul export' BEFORE running rituals is the operator's safety net.\n")

	for version, ritual in RITUALS:
		if as_tuple(version) <= baseline:
			print(f"── Ritual {version} skipped (already at or below --from {args.from_version}) ──")
			continue
		ritual(mm, execute=args.execute)

	if not args.execute:
		print("\nDry-run complete. Re-run with --execute to apply.")


if __name__ == "__main__":
	main()
