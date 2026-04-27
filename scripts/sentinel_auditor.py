#!/usr/bin/env python3
"""
sentinel_auditor.py — Sovereign System Health Auditor (Project MULTITUDE)

Analyzes 'signal_memories' to generate a 'Vitality Report'.
Identifies MTBF (Mean Time Between Failures) and Lazarus Loops.
"""

import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime

# Add project src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(project_root, "src"))

from red_pill.core.inbox import MinionInbox  # noqa: E402
from red_pill.memory import MemoryManager  # noqa: E402


def generate_vitality_report():
	manager = MemoryManager()
	collection = "signal_memories"

	print(f"[*] Deploying Sentinel Auditor: analyzing {collection}...")

	if not manager.client.collection_exists(collection):
		return "SYSTEM OPTIMAL: No signal_memories collection found."

	# Scroll to get recent signals
	points, _ = manager.client.scroll(
		collection_name=collection,
		limit=100,
		with_payload=True
	)

	if not points:
		return "SYSTEM OPTIMAL: Zero pain signals detected in the Cortex."

	# 1. Basic Stats
	total_signals = len(points)
	severities = []
	types = []
	timestamps = []

	for p in points:
		payload = p.payload or {}
		severities.append(payload.get("severity", payload.get("importance", 5.0)))
		types.append(payload.get("title", payload.get("content", "Unknown"))[:30])
		timestamps.append(payload.get("timestamp", payload.get("created_at", time.time())))

	avg_severity = sum(severities) / len(severities) if severities else 0
	type_counts = Counter(types)

	# 2. MTBF (Mean Time Between Failures)
	# Sort timestamps (descending)
	ts_float = []
	for ts in timestamps:
		if isinstance(ts, str):
			try:
				ts_float.append(datetime.fromisoformat(ts).timestamp())
			except ValueError:
				ts_float.append(time.time())
		else:
			ts_float.append(float(ts))

	ts_float.sort(reverse=True)

	mtbf_str = "N/A (Insufficient data)"
	if len(ts_float) >= 2:
		intervals = []
		for i in range(len(ts_float) - 1):
			intervals.append(ts_float[i] - ts_float[i+1])
		avg_interval = sum(intervals) / len(intervals)

		if avg_interval < 60:
			mtbf_str = f"{avg_interval:.1f} seconds"
		elif avg_interval < 3600:
			mtbf_str = f"{avg_interval/60:.1f} minutes"
		else:
			mtbf_str = f"{avg_interval/3600:.1f} hours"

	# 3. Lazarus Loops (Chronic failure detection)
	lazarus_loops = [t for t, count in type_counts.items() if count >= 3]

	# 4. Generate Markdown
	timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

	report = f"""# 🩺 BÜNKER VITALITY REPORT
---
**Timestamp**: {timestamp_now}
**System Status**: {"🔴 CRITICAL" if avg_severity > 7.0 else "🟡 UNSTABLE" if avg_severity > 4.0 else "🟢 STABLE"}

### 📊 Vitality Metrics
- **Total Signals (Cortex)**: {total_signals}
- **Average Pain Severity**: {avg_severity:.2f}/10.0
- **MTBF (Mean Time Between Failures)**: {mtbf_str}

### 🔄 Lazarus Loops (Chronic Failures)
"""
	if lazarus_loops:
		for loop in lazarus_loops:
			report += f"- **{loop}**: Detected {type_counts[loop]} occurrences.\n"
		report += "\n> [!CAUTION]\n> Chronic failures detected. Systemic remediation required."
	else:
		report += "_No chronic loops detected. Recurrent patterns are within nominal bounds._"

	report += "\n\n### 📝 Signal Distribution\n"
	for t, count in type_counts.most_common(5):
		report += f"- {t}: {count}\n"

	return report


def main():
	event_id = str(uuid.uuid4())[:8]
	try:
		report_content = generate_vitality_report()

		# Drop in inbox
		MinionInbox().drop_report(
			event_id=event_id,
			source="SentinelAuditor",
			status="success",
			content=report_content
		)
		print(f"[✓] Vitality Report [{event_id}] delivered to Minion Inbox.")

	except Exception as e:
		print(f"[✗] Auditor Failed: {e}")
		MinionInbox().drop_report(
			event_id=event_id,
			source="SentinelAuditor",
			status="failed",
			content=f"Auditor Crash: {str(e)}"
		)
		sys.exit(1)


if __name__ == "__main__":
	main()
