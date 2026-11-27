"""E-e03edb: una extracción truncada en annotate no debe podar ni sellar.

Con `finish_reason=length` el array de ideas llega sin cerrar. Antes se degradaba
a lista vacía y el pase borraba las notas previas (poda de huérfanas) y sellaba
la sesión con 0 notas, como si la sesión no tuviera nada que anotar.
"""

import pytest

import red_pill.config as cfg
from red_pill.memento.agentic import runtime
from red_pill.memento.agentic.annotate import annotate_session
from red_pill.memento.agentic.runner import run_agentic
from red_pill.memento.registry import MementoRegistry
from red_pill.memento.render import render_session, write_session


def _tree(tmp_path):
	root = tmp_path / "memento"
	registry = MementoRegistry(path=tmp_path / "reg.json")
	msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Mensaje {i} útil.", "timestamp": 1787234592.0 + i * 60} for i in range(5)]
	rendered = render_session("opencode:s1", "opencode", "opencode", msgs)
	write_session(root, rendered)
	registry.upsert(
		"opencode",
		"opencode:s1",
		{
			"dir": rendered.dir_rel,
			"month": rendered.month,
			"created_at": rendered.created_at,
			"message_count": rendered.message_count,
			"memento_hash": rendered.memento_hash,
			"workspace": "-home-joan-Workspace",
		},
	)
	return root, registry, rendered


def _previas(root, rendered):
	annotate_dir = root / rendered.dir_rel / "annotate"
	annotate_dir.mkdir(parents=True, exist_ok=True)
	for i in (1, 2):
		(annotate_dir / f"00{i}-previa.md").write_text(
			f"---\ntitle: previa {i}\nwork_score: 0.9\nsocial_score: 0.1\nascended: true\n---\n\nnota previa {i}\n",
			encoding="utf-8",
		)
	return annotate_dir, {p.name: p.read_bytes() for p in annotate_dir.glob("*.md")}


def _truncado(system, user, max_tokens):
	# Array abierto a mitad: lo que deja finish_reason=length.
	return '```json\n[{"title": "corta", "text": "se cor'


def _vacio(system, user, max_tokens):
	return "[]"


def test_extract_truncado_aborta_sin_podar_ni_sellar(tmp_path, monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", True)
	root, _registry, rendered = _tree(tmp_path)
	annotate_dir, antes = _previas(root, rendered)

	with pytest.raises(runtime.TruncatedResponseError):
		annotate_session(root, rendered.dir_rel, "opencode:s1", "opencode", _truncado)

	despues = {p.name: p.read_bytes() for p in annotate_dir.glob("*.md")}
	assert despues == antes  # las notas previas siguen byte a byte
	assert not (annotate_dir / "_meta.json").exists()  # nada sellado


def test_runner_cuenta_fallo_y_no_sella(tmp_path, monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", True)
	monkeypatch.setattr(cfg, "MEMENTO_STATIC_ASCENSION_ENABLED", False)
	root, registry, rendered = _tree(tmp_path)
	annotate_dir, antes = _previas(root, rendered)
	registry.upsert(
		"opencode",
		"opencode:s1",
		{"agentic": {"distill_hash": rendered.memento_hash, "annotate_pending": True}},
	)
	index = root / rendered.dir_rel / "memento" / "index.md"
	index_antes = index.read_text(encoding="utf-8")

	stats = run_agentic(root, registry, [("opencode", "opencode:s1")], _truncado, phase="annotate")

	assert stats["processed"] == 0 and stats["failed"] == 1
	assert {p.name: p.read_bytes() for p in annotate_dir.glob("*.md")} == antes
	assert index.read_text(encoding="utf-8") == index_antes  # sin sello de significance
	assert registry.get("opencode", "opencode:s1")["agentic"]["annotate_pending"] is True  # sigue pendiente


def test_lista_vacia_valida_si_es_un_resultado(tmp_path, monkeypatch):
	"""Un `[]` bien cerrado no es un corte: la sesión no tiene ideas y se poda."""
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", True)
	root, _registry, rendered = _tree(tmp_path)
	annotate_dir, _antes = _previas(root, rendered)

	annotate_session(root, rendered.dir_rel, "opencode:s1", "opencode", _vacio)

	assert list(annotate_dir.glob("*.md")) == []
	assert (annotate_dir / "_meta.json").exists()


def test_ideas_or_raise_aborta_si_el_transporte_trunco_aunque_el_json_cierre(monkeypatch):
	"""2026-11-27: un corte que cierra el array por casualidad perdía ideas sólo
	con un warning. Si el transporte marcó truncado, se aborta igual."""
	from red_pill.memento.agentic import annotation_phases

	monkeypatch.setattr(runtime, "_LAST_TRUNCATED", True, raising=False)

	# `_extract` llama al transporte y luego a `_ideas_or_raise`; el flag ya está
	# puesto, así que un array cerrado NO debe aceptarse.
	with pytest.raises(runtime.TruncatedResponseError):
		annotation_phases._ideas_or_raise('[{"title": "a", "text": "b"}]', "annotate_work_user_v3")


def test_annotate_max_tokens_crece_con_el_fragmento(monkeypatch):
	from red_pill.core import model_runtime as mr

	class _Resolved:
		max_tokens = 2048
		n_ctx = 10240

	monkeypatch.setattr(mr, "resolve", lambda _selector: _Resolved())

	assert runtime.annotate_max_tokens(chars=8000) == 2048
	small = runtime.annotate_max_tokens(chars=12000)
	big = runtime.annotate_max_tokens(chars=16000)
	assert 2048 < small < big <= 4096
	# Un fragmento enorme no puede pedir más que el hueco del contexto (10.240).
	assert runtime.annotate_max_tokens(chars=20000) <= 4096
	assert runtime.annotate_max_tokens(chars=0) == 2048


def test_prompt_que_no_cabe_falla_antes_de_llamar(monkeypatch):
	"""2026-11-27: el tope de prompt sale del contexto del modelo.

	Si la unidad no cabe, se falla con `PromptTooLongError` ANTES de generar: el
	pase no puede anotar una fracción como si fuera el split entero (lo que hacía
	el recorte silencioso a 20.000 chars), y no se gasta una generación que ya se
	sabe inválida.
	"""
	import requests

	monkeypatch.setattr(runtime, "_prompt_char_cap", lambda _mt: 100)
	monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no debió llamar al LLM"))

	with pytest.raises(runtime.PromptTooLongError):
		runtime.http_transport("system", "x" * 500, max_tokens=2048)


def test_annotate_max_tokens_usa_el_modelo_fijado_por_el_job(monkeypatch):
	"""El presupuesto se calcula con el contexto del modelo que sirve la task.

	Antes resolvía sólo la task: un job que fija otro perfil (A/B de contexto)
	calculaba el hueco con el n_ctx del titular.
	"""
	from red_pill.core import model_runtime as mr

	class _Resolved:
		max_tokens = 2048

		def __init__(self, n_ctx):
			self.n_ctx = n_ctx

	seen = {}

	def _resolve(selector):
		seen.update(selector)
		return _Resolved(16384 if selector.get("model") == "k2_ctx16" else 10240)

	monkeypatch.setattr(mr, "resolve", _resolve)
	monkeypatch.setenv("RP_LLM_MODEL", "k2_ctx16")

	assert runtime.annotate_max_tokens(chars=20000) > 2048
	assert seen.get("model") == "k2_ctx16"
