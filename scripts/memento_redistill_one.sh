#!/usr/bin/env bash
# Re-procesa UNA sesión Memento para un element_job (UN step = UNA sesión).
#
# El driver pasa el elemento por `RP_ELEMENT` (JSON). Contrato:
#   {"target": "opencode:opencode:ses_..."}                  # pase completo
#   {"target": "...", "phase": "distill"}                    # solo polaroids
#   {"target": "...", "phase": "annotate"}                   # solo notas
#
# Lo usan las recetas de ronda (`memento_redistill_bonsai.yaml`). El modelo NO
# se decide aquí: lo resuelve la task de `task_profiles.yaml` (distill /
# annotate) y el driver la propaga por RP_LLM_TASK (`llm.task` en la receta).
# Este satélite no sabe —ni debe saber— qué modelo pone la voz ni quién juzga.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

read -r TARGET PHASE <<<"$(printf '%s' "${RP_ELEMENT:-}" | .venv/bin/python -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("target", ""), d.get("phase", "") or "-")
')"

if [ -z "${TARGET}" ]; then
	echo "[redistill-one] RP_ELEMENT sin target" >&2
	exit 2
fi

FASE=()
if [ "${PHASE}" != "-" ]; then
	FASE=(--phase "${PHASE}")
fi

echo "[redistill-one] ${TARGET} fase=${PHASE} task=${RP_LLM_TASK:-<default daemon>}" >&2
exec .venv/bin/python scripts/memento_agentic.py --force "${FASE[@]}" --target "${TARGET}"
