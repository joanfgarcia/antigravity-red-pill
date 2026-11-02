import asyncio
import logging
import os
import sys
import time

from red_pill.core.paths import get_workspace_root

# Fix path for local imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from red_pill.metabolism.auditor import SEGMENT_SIGNAL_NAMES, SentinelAuditor
from red_pill.metabolism.reconcile import VERDICT_ERROR, VERDICT_OK, AuditRound, reconcile


async def main():
	logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
	logger = logging.getLogger("redpill.auditor_runner")

	logger.info("Sentinel Auditor: Commencing scheduled infrastructure audit...")

	repos = [str(get_workspace_root() / "pure-mls"), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

	auditor = SentinelAuditor(target_repos=repos)

	# RFC-OBS-005: la ronda es el único sitio que ve las cuatro fases. Cada fase
	# informa de lo que emitió y de lo que no pudo evaluar; al cerrar, se reconcilia.
	round_ = AuditRound(round_id=time.strftime("%Y%m%dT%H%M%S", time.localtime()))

	def run_segment(segment: str, audit_fn, declared: frozenset) -> None:
		try:
			report = audit_fn()
			auditor.sync_to_thalamus(report)
			round_.record(segment, VERDICT_OK, report.emitted_signals, report.preserved_signals)
		except Exception as e:
			logger.error(f"Failed to audit {segment}: {e}")
			# Sin veredicto no hay borrado: se preserva todo lo que el segmento podía emitir.
			round_.record(segment, VERDICT_ERROR, set(), declared)

	for repo in repos:
		run_segment(f"repo:{os.path.basename(repo)}", lambda r=repo: auditor.audit_repo(r), SEGMENT_SIGNAL_NAMES["repo"])

	run_segment("runtime", auditor.audit_runtime, SEGMENT_SIGNAL_NAMES["runtime"])
	run_segment("vitals", auditor.audit_vitals, SEGMENT_SIGNAL_NAMES["vitals"])

	round_.complete = True
	try:
		report = reconcile(round_)
		logger.info(
			f"Sentinel Auditor: reconcile {report.get('skipped') or 'ok'}"
			f" · candidatas {len(report.get('candidates') or [])}"
			f" · report_only={report.get('report_only')}"
			f" · evaporaría {report.get('would_evaporate')}"
		)
	except Exception as e:
		logger.error(f"Reconciliación falló (no borra nada: P0 es report-only): {e}")

	logger.info("Sentinel Auditor: Audit cycle complete.")


if __name__ == "__main__":
	asyncio.run(main())
