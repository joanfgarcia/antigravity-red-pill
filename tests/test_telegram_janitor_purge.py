"""SHARD-13 — purga de Telegram Memento-consciente bajo SW_INGEST_RETIRED.

Con la ingesta retirada, `metadata.source_buffer_id` (drenaje legacy) ya no se
escribe: el janitor debe verificar la archivación en Memento, o las sesiones
`pending_purge` nunca se purgarían.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import red_pill.config as cfg
from red_pill.memento.registry import MementoRegistry
from red_pill.telegram.session import TelegramSessionManager


@pytest.fixture
def xdg(tmp_path, monkeypatch):
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
	return tmp_path


# ── registry.is_rendered ───────────────────────────────────────────────────

def test_is_rendered_falso_sin_registro(tmp_path):
	reg = MementoRegistry(path=tmp_path / "r.json")
	assert reg.is_rendered("abc") is False
	assert reg.is_rendered("") is False


def test_is_rendered_por_sesion_exacta(tmp_path):
	reg = MementoRegistry(path=tmp_path / "r.json")
	reg.upsert("telegram", "uuid-1", {"dir": "x"})
	assert reg.is_rendered("uuid-1") is True


def test_is_rendered_por_variante_source_colon(tmp_path):
	reg = MementoRegistry(path=tmp_path / "r.json")
	reg.state["registry"] = {"pi": {"pi:zzz": {"dir": "d"}}}
	assert reg.is_rendered("zzz") is True
	assert reg.is_rendered("otro") is False


def test_is_rendered_scoped_a_fuente(tmp_path):
	reg = MementoRegistry(path=tmp_path / "r.json")
	reg.state["registry"] = {"antigravity": {"u1": {"dir": "d"}}}
	assert reg.is_rendered("u1") is True  # sin scoping, cualquier fuente
	assert reg.is_rendered("u1", sources=["telegram"]) is False  # acotado: no está en telegram


def test_is_rendered_tolera_registro_malformado(tmp_path):
	reg = MementoRegistry(path=tmp_path / "r.json")
	reg.state["registry"] = {"src": "no-es-dict"}  # type: ignore[assignment]
	assert reg.is_rendered("x") is False


# ── _is_archived con SW_INGEST_RETIRED ON ──────────────────────────────────

def test_archived_retired_usa_memento(xdg, monkeypatch):
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", True)
	reg = MementoRegistry()
	reg.upsert("telegram", "s1", {"dir": "d"})
	reg.save()
	mgr = TelegramSessionManager()
	# sin cliente: en modo retirado NO se usa Qdrant
	assert mgr._is_archived(client=None, session_id="s1") is True
	assert mgr._is_archived(client=None, session_id="no-existe") is False


def test_archived_retired_registry_roto_no_purga(xdg, monkeypatch):
	"""Fail-safe: si no se puede verificar, se retiene (no se borra)."""
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", True)
	monkeypatch.setattr(MementoRegistry, "is_rendered", lambda self, sid, sources=None: (_ for _ in ()).throw(RuntimeError("boom")))
	mgr = TelegramSessionManager()
	assert mgr._is_archived(client=None, session_id="s1") is False


def test_archived_retired_no_falso_positivo_cross_source(xdg, monkeypatch):
	"""UUID presente en OTRA fuente (antigravity) NO debe purgar un pendiente de Telegram."""
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", True)
	reg = MementoRegistry()
	reg.state["registry"] = {"antigravity": {"s1": {"dir": "d"}}}
	reg.save()
	mgr = TelegramSessionManager()
	assert mgr._is_archived(client=None, session_id="s1") is False


def test_run_janitor_retired_purga_solo_renderizadas(xdg, monkeypatch):
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", True)
	mgr = TelegramSessionManager()
	s1 = mgr.create_session("u")
	s2 = mgr.create_session("u")
	mgr.mark_for_deletion(s1["id"])
	mgr.mark_for_deletion(s2["id"])
	reg = MementoRegistry()
	reg.upsert("telegram", s1["id"], {"dir": "d"})
	reg.save()
	n = mgr.run_janitor_sweep()  # sin Qdrant: la vía Memento no lo necesita
	assert n == 1
	assert not mgr._get_path(s1["id"]).exists()
	assert mgr._get_path(s2["id"]).exists()


# ── _is_archived con SW_INGEST_RETIRED OFF (legacy) ────────────────────────

def test_archived_legacy_usa_source_buffer_id(xdg, monkeypatch):
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", False)
	mgr = TelegramSessionManager()
	client = MagicMock()
	client.scroll.return_value = ([object()], None)
	assert mgr._is_archived(client=client, session_id="s1") is True
	# el filtro consulta source_buffer_id en work/social
	key = client.scroll.call_args.kwargs["scroll_filter"].must[0].key
	assert key == "metadata.source_buffer_id"


def test_archived_legacy_sin_hit_no_purga(xdg, monkeypatch):
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", False)
	mgr = TelegramSessionManager()
	client = MagicMock()
	client.scroll.return_value = ([], None)
	assert mgr._is_archived(client=client, session_id="s1") is False


def test_archived_legacy_no_consulta_memento(xdg, monkeypatch):
	"""Con RETIRED OFF, el path Memento no se toca (comportamiento intacto)."""
	monkeypatch.setattr(cfg, "SW_INGEST_RETIRED", False)
	monkeypatch.setattr(MementoRegistry, "is_rendered", lambda self, sid: (_ for _ in ()).throw(AssertionError("no debe llamarse")))
	mgr = TelegramSessionManager()
	client = MagicMock()
	client.scroll.return_value = ([], None)
	assert mgr._is_archived(client=client, session_id="s1") is False
