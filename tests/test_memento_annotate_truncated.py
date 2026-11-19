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
