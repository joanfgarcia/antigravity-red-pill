"""PROMPT-001 F1: composición de prompts — equivalencia, firma y artefactos.

El fixture `fixtures/prompt_goldens_pre_f1.json` se generó con el render anterior
(`str.format`) antes de la migración; aquí se exige equivalencia byte a byte del
render nuevo (`string.Template` + fragmentos del manifiesto).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from red_pill.core import prompts as core

FIXTURE = Path(__file__).parent / "fixtures" / "prompt_goldens_pre_f1.json"
FIX = json.loads(FIXTURE.read_text(encoding="utf-8"))
COMPONENT = "memento/agentic"
STATIC_KEYS = {"identity", "work_scope", "social_scope"}
RUNTIME_KEYS = {"fragment", "notes", "memories", "content", "previous", "candidates", "fragments", "summary", "title"}
# F2 cambia a propósito estos prompts (inyecta la leyenda emocional): ya no
# aplica el oráculo byte-exacto pre-F1; tienen su propio gate más abajo.
CHANGED_IN_F2 = {
	"annotate_work_user",
	"annotate_social_user",
	"annotate_work_user_v2",
	"annotate_social_user_v2",
	"refine_work_user",
	"refine_social_user",
	"refine_multi_user",
	"refine_user",
}


def _inputs(pid: str):
	payload = FIX["prompts"][pid]
	vals = FIX["values"]
	static = {k: vals[k] for k in payload["placeholders"] if k in STATIC_KEYS}
	runtime = {k: vals[k] for k in payload["placeholders"] if k in RUNTIME_KEYS}
	return static, runtime


@pytest.mark.parametrize("pid", sorted(set(FIX["prompts"]) - CHANGED_IN_F2))
def test_render_equivalente_pre_f1(pid):
	static, runtime = _inputs(pid)
	out = core.render(COMPONENT, pid, static=static, **runtime)
	assert out == FIX["prompts"][pid]["rendered"]


def test_emotion_legend_presente_solo_donde_toca():
	for pid in sorted(CHANGED_IN_F2):
		static, runtime = _inputs(pid)
		assert "EMOTION COLORS" in core.render(COMPONENT, pid, static=static, **runtime), pid
	for pid in sorted(set(FIX["prompts"]) - CHANGED_IN_F2):
		static, runtime = _inputs(pid)
		assert "EMOTION COLORS" not in core.render(COMPONENT, pid, static=static, **runtime), pid


def test_emotion_legend_consistente_con_mapa():
	"""Gate: la leyenda cubre exactamente la inversa de EMOTION_CHROMA_MAP."""
	from collections import defaultdict

	from red_pill.utils.emotion import EMOTION_CHROMA_MAP

	text = (core._FRAGMENTS_DIR / "emotion_legend.txt").read_text(encoding="utf-8")
	colors = {}
	for line in text.splitlines():
		if not line.startswith("- "):
			continue
		color, _, rest = line[2:].partition(" — ")
		assert rest.endswith(")"), line
		labels = {part.strip() for part in rest[rest.rindex("(") + 1 : -1].split(",")}
		colors[color.strip()] = labels
	inverse: dict = defaultdict(set)
	for label, color in EMOTION_CHROMA_MAP.items():
		inverse[color].add(label)
	assert set(colors) == set(inverse) == {"gray", "yellow", "orange", "cyan", "blue", "purple", "red", "green"}
	for color, labels in colors.items():
		assert labels == inverse[color], (color, labels, inverse[color])


def test_validate_all_sin_errores():
	assert core.validate_all() == []


def test_firma_determinista_y_sensible_a_config():
	static = {"identity": FIX["values"]["identity"], "work_scope": FIX["values"]["work_scope"]}
	sig1 = core.signature(COMPONENT, "annotate_work_user_v2", static=static)
	sig2 = core.signature(COMPONENT, "annotate_work_user_v2", static=static)
	assert sig1 == sig2
	assert sig1.startswith("p1:")
	other = core.signature(COMPONENT, "annotate_work_user_v2", static={**static, "identity": "OTRA BIO"})
	assert other != sig1
	assert os.getcwd() not in sig1


def test_placeholder_runtime_faltante_es_error():
	with pytest.raises(core.PromptError):
		core.render(COMPONENT, "content_validate_user")


def test_artefacto_materializado_en_xdg():
	ep = core.resolve(COMPONENT, "content_validate_user")
	path = core.artifact_path(ep)
	assert path is not None and path.is_file()
	assert path.read_text(encoding="utf-8") == ep.text
	assert path.stat().st_mode & 0o777 == 0o600


def test_stage_signature_agrega_en_orden_fijo():
	parts = [(COMPONENT, "refine_work_user", None), (COMPONENT, "refine_social_user", None)]
	a = core.stage_signature(parts)
	b = core.stage_signature(list(reversed(parts)))  # el orden importa
	assert a != b
	assert core.stage_signature(parts) == a
