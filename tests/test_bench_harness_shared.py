"""El banco de pruebas no reimplementa lo que ya hace producción (2026-11-16).

Motivo: medir un modelo con un parser propio, un registro de modelos propio o
una coerción propia es medir el banco, no el runtime. Ya pasó tres veces (parser
de tool-calls, tabla de GGUF copiada en cuatro scripts, `thinking: off` sin
aplicar). Estas pruebas son la guardia contra la cuarta.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


class TestNoDuplicateRegistries:
	def test_ningun_harness_declara_su_tabla_de_gguf(self):
		# La tabla vive en model_battle_lib (perfiles ⊕ LEGACY_GGUF) y se importa.
		for name in ("model_battle_lib.py", "model_battle_tool_gpu.py", "distiller_fidelity.py", "distiller_bakeoff.py"):
			src = (SCRIPTS / name).read_text(encoding="utf-8")
			assert "_KNOWN_GGUF = {" not in src, f"{name} vuelve a declarar la tabla"
			assert "MODELS: dict[str, str] = {" not in src, f"{name} vuelve a declarar la tabla"

	def test_los_harness_importan_la_tabla_compartida(self):
		for name in ("distiller_fidelity.py", "distiller_bakeoff.py", "model_battle_tool_gpu.py"):
			src = (SCRIPTS / name).read_text(encoding="utf-8")
			assert "from model_battle_lib import" in src, name


class TestNoDuplicateToolParsing:
	def test_el_banco_usa_el_parser_de_produccion(self):
		src = (SCRIPTS / "model_battle_tool.py").read_text(encoding="utf-8")
		assert "extract_toolcalls" in src
		# Los tres parsers locales que había antes.
		assert "def _gemma_args" not in src
		assert "def _extract_native_tool_call" not in src

	def test_la_coercion_de_argumentos_es_la_del_runtime(self):
		src = (SCRIPTS / "model_battle_tool.py").read_text(encoding="utf-8")
		assert "coerce_by_schema" in src
		assert "def _coerce_text_arg" not in src


class TestCoerceBySchema:
	def test_convierte_segun_el_esquema(self):
		from red_pill.core.model_runtime import coerce_by_schema

		schema = {
			"properties": {
				"attendees": {"type": "array", "items": {"type": "string"}},
				"duration_min": {"type": "integer"},
				"title": {"type": "string"},
			}
		}
		out = coerce_by_schema({"attendees": '["Ana", "Beti"]', "duration_min": "30", "title": "Reunión"}, schema)
		assert out == {"attendees": ["Ana", "Beti"], "duration_min": 30, "title": "Reunión"}

	def test_no_toca_strings_que_el_esquema_declara_string(self):
		from red_pill.core.model_runtime import coerce_by_schema

		# Un patrón de búsqueda "300" NO debe volverse 300.
		schema = {"properties": {"pattern": {"type": "string"}}}
		assert coerce_by_schema({"pattern": "300"}, schema) == {"pattern": "300"}

	def test_sin_esquema_devuelve_el_mapping(self):
		from red_pill.core.model_runtime import coerce_by_schema

		assert coerce_by_schema({"a": "1"}, None) == {"a": "1"}
		assert coerce_by_schema("", None) == {}


class TestGgufProfiles:
	def test_deriva_basenames_de_los_perfiles(self, monkeypatch):
		from red_pill.core import model_registry as mr

		monkeypatch.setattr(
			mr.ModelRegistry,
			"get_all_profiles",
			classmethod(
				lambda cls: {
					"a": {"binary_type": "gguf", "model_path": "/x/A-Q4.gguf"},
					"b": {"binary_type": "fastflowlm", "model_path": "/x/B"},
					"c": {"binary_type": "gguf"},
				}
			),
		)
		assert mr.gguf_profiles() == {"a": "A-Q4.gguf"}

	def test_la_tabla_legacy_no_pisa_al_perfil(self, monkeypatch):
		import sys

		sys.path.insert(0, str(SCRIPTS))
		try:
			import model_battle_lib as lib
		finally:
			sys.path.pop(0)

		from red_pill.core import model_registry as mr

		monkeypatch.setattr(mr, "gguf_profiles", lambda: {"beck_8b": "DESDE-PERFIL.gguf"})
		merged = lib.known_gguf()
		assert merged["beck_8b"] == "DESDE-PERFIL.gguf"  # el perfil manda
		assert merged["r1_distill"] == "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf"  # legacy intacto
