#!/usr/bin/env bash
# Re-destila UNA sesión Memento para un element_job (UN step = UNA sesión).
#
# El driver pasa el elemento por `RP_ELEMENT` (JSON). Contrato esperado:
#   {"target": "opencode:opencode:ses_..."}
#
# Lo usa `configs/jobs/memento_redistill_bonsai.yaml`. El modelo NO se decide
# aquí: lo resuelve la task `distill` de task_profiles.yaml, y el driver la
# propaga por RP_LLM_TASK (llm.task en la receta). Este satélite no sabe —ni
# debe saber— qué modelo pone la voz.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TARGET="$(printf '%s' "${RP_ELEMENT:-}" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["target"])')"
if [ -z "${TARGET}" ]; then
	echo "[redistill-one] RP_ELEMENT sin target" >&2
	exit 2
fi

echo "[redistill-one] ${TARGET} (task=${RP_LLM_TASK:-<default daemon>})" >&2
exec .venv/bin/python scripts/memento_agentic.py --force --target "${TARGET}"
