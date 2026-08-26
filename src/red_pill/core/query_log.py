"""Query-log persistido de recall semántico (RFC-002 §4.6, prerequisito de la Fase 3.5).

El `ACTION_START` del registry ya emite la query, pero solo como línea de log
efímera del provider sentinel. Aquí se eleva a un sink persistente (JSONL junto
al resto del estado del kernel) para que el shadow-gate pueda replayar queries
reales contra corpus gateado vs no gateado.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

QUERY_LOG_FILENAME = "search_query_log.jsonl"
_LOGGED_ACTIONS = {"search_memory_research"}


def record_query(action: str, payload: Optional[Dict[str, Any]]) -> None:
	"""Persiste la query si la acción es de recall; best-effort, jamás rompe la llamada."""
	if action not in _LOGGED_ACTIONS:
		return
	query = (payload or {}).get("query")
	if not query:
		return
	from red_pill.core.paths import get_data_dir

	line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "action": action, "query": query}, ensure_ascii=False)
	with open(get_data_dir() / QUERY_LOG_FILENAME, "a", encoding="utf-8") as f:
		f.write(line + "\n")
