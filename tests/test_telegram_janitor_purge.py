"""Purga de Telegram Memento-consciente (infra de staging retirada).

El janitor purga del disco las sesiones `pending_purge` ya renderizadas en Memento
(acotado a la fuente `telegram`); fail-safe si no puede verificar.
"""

from __future__ import annotations

import pytest

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


# ── _is_archived (siempre Memento) ─────────────────────────────────────────

def test_archived_usa_memento(xdg):
	reg = MementoRegistry()
	reg.upsert("telegram", "s1", {"dir": "d"})
	reg.save()
	mgr = TelegramSessionManager()
	assert mgr._is_archived(session_id="s1") is True
	assert mgr._is_archived(session_id="no-existe") is False


def test_archived_registry_roto_no_purga(xdg, monkeypatch):
	"""Fail-safe: si no se puede verificar, se retiene (no se borra)."""
	monkeypatch.setattr(MementoRegistry, "is_rendered", lambda self, sid, sources=None: (_ for _ in ()).throw(RuntimeError("boom")))
	mgr = TelegramSessionManager()
	assert mgr._is_archived(session_id="s1") is False


def test_archived_no_falso_positivo_cross_source(xdg):
	"""UUID presente en OTRA fuente (antigravity) NO debe purgar un pendiente de Telegram."""
	reg = MementoRegistry()
	reg.state["registry"] = {"antigravity": {"s1": {"dir": "d"}}}
	reg.save()
	mgr = TelegramSessionManager()
	assert mgr._is_archived(session_id="s1") is False


def test_run_janitor_purga_solo_renderizadas(xdg):
	mgr = TelegramSessionManager()
	s1 = mgr.create_session("u")
	s2 = mgr.create_session("u")
	mgr.mark_for_deletion(s1["id"])
	mgr.mark_for_deletion(s2["id"])
	reg = MementoRegistry()
	reg.upsert("telegram", s1["id"], {"dir": "d"})
	reg.save()
	n = mgr.run_janitor_sweep()
	assert n == 1
	assert not mgr._get_path(s1["id"]).exists()
	assert mgr._get_path(s2["id"]).exists()
