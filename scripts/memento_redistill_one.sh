#!/usr/bin/env bash
# Re-procesa UNA sesión Memento para un element_job (UN step = UNA sesión).
#
# El driver pasa el elemento por `RP_ELEMENT` (JSON). Contrato:
#   {"target": "opencode:opencode:ses_...", "phase": "both"}   # las dos fases
#   {"target": "...", "phase": "distill"}                      # solo polaroids
#   {"target": "...", "phase": "annotate"}                     # solo notas
#
# `both` se ejecuta como DOS corridas, cada una con su task: la voz la pone el
# destilador y la nota el juez, que son modelos distintos por diseño (2026-10-30).
# Aquí el coste de los dos cambios de modelo importa poco: es una sesión, lanzada
# a mano, donde lo que se busca es calidad, no throughput.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

read -r TARGET PHASE <<<"$(printf '%s' "${RP_ELEMENT:-}" | .venv/bin/python -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("target", ""), d.get("phase", "") or "both")
')"

if [ -z "${TARGET}" ]; then
	echo "[redistill-one] RP_ELEMENT sin target" >&2
	exit 2
fi

echo "[redistill-one] ${TARGET} fase=${PHASE}" >&2

if [ "${PHASE}" = "both" ]; then
	RP_LLM_TASK=distill .venv/bin/python scripts/memento_agentic.py --force --phase distill --target "${TARGET}"
	RP_LLM_TASK=annotate .venv/bin/python scripts/memento_agentic.py --force --phase annotate --target "${TARGET}"
else
	.venv/bin/python scripts/memento_agentic.py --force --phase "${PHASE}" --target "${TARGET}"
fi

# Libro de sesiones ya reprocesadas (para no repetirlas en bucle): lo escribe
# quien orquesta la cola lenta, no el pase.
if [ -n "${RP_FIX_LEDGER:-}" ]; then
	mkdir -p "$(dirname "${RP_FIX_LEDGER}")"
	printf '{"session":"%s","target":"%s","at":"%s"}\n' "${TARGET}" "${TARGET}" "$(date -Iseconds)" >>"${RP_FIX_LEDGER}"
fi
