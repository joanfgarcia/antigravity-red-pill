"""Fase 5 (C3): política de wake por rol (D-07) y controles de entrada.

Contrato que se prueba, en el orden del módulo:
- **Matriz de roles como dato**: `WAKE_POLICY` (`from:relation`, CSV) decide quién
	puede empujar a quién; la primera regla que casa permite y ninguna → pull.
- **Fail-closed de verdad**: política vacía, mal formada, con relación
	desconocida o config inaccesible ⇒ **no se despierta a nadie** (nunca un
	default permisivo).
- **Controles de entrada** (`accept`/`hold`/`refuse`): el destinatario manda.
	`refuse` es terminal; `hold` difiere; un estado ilegible o desconocido se
	trata como `hold`.
- **Precedencia**: entrada del destinatario > matriz de roles; `refuse` gana a
	cualquier regla (incluida `*:any`).

Los tests usan una BD temporal (`db_path`) y una config falsa inyectada con
`monkeypatch`: nunca leen el `.env` del Operador.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from red_pill.session import wake_policy as wp


@pytest.fixture
def db(tmp_path):
	return str(tmp_path / "session.db")


def _config(monkeypatch, policy: object) -> None:
	"""Sustituye la config por un objeto con `WAKE_POLICY` (o sin él, si `None`)."""
	import red_pill.config as cfg

	if policy is None:
		stub = SimpleNamespace()
	else:
		stub = SimpleNamespace(WAKE_POLICY=policy)
	monkeypatch.setattr(cfg, "get_config", lambda: stub)


def _actor(**kw) -> wp.Actor:
	return wp.Actor(**kw)


def _sender(role: str = "orchestrator", mission: str = "repo:next") -> wp.Actor:
	return _actor(continuity_id="snd", originator="opencode:snd", role=role, mission_id=mission)


def _recipient(mission: str = "repo:next") -> wp.Actor:
	return _actor(continuity_id="rcv", originator="opencode:rcv", role="task", mission_id=mission)


class TestParsePolicy:
	def test_politica_valida(self):
		rules, error = wp.parse_policy("*:self,orchestrator:chain")
		assert error == ""
		assert rules == (("*", "self"), ("orchestrator", "chain"))

	def test_espacios_y_mayusculas_no_rompen(self):
		rules, error = wp.parse_policy(" * : SELF , Orchestrator : Chain ")
		assert error == ""
		assert rules == (("*", "self"), ("orchestrator", "chain"))

	def test_vacia_es_error_no_permiso(self):
		rules, error = wp.parse_policy("")
		assert rules == ()
		assert error

	def test_relacion_desconocida_invalida_toda_la_politica(self):
		"""Fail-closed: un token raro no deja las demás reglas medio aplicadas."""
		rules, error = wp.parse_policy("orchestrator:chain, alguien:universo")
		assert rules == ()
		assert "universo" in error

	def test_token_vacio_invalida(self):
		rules, error = wp.parse_policy("orchestrator:chain,,*:self")
		assert rules == ()
		assert error

	def test_sin_separador_invalida(self):
		rules, error = wp.parse_policy("orchestrator")
		assert rules == ()
		assert error

	def test_rol_con_caracteres_raros_invalida(self):
		rules, error = wp.parse_policy("orch estrador:chain")
		assert rules == ()
		assert error


class TestLoadPolicy:
	def test_sin_clave_en_config_cae_al_default_de_fabrica(self, monkeypatch):
		_config(monkeypatch, None)
		rules, error = wp.load_policy()
		assert error == ""
		assert rules == wp.parse_policy(wp.DEFAULT_POLICY)[0]

	def test_clave_vacia_cae_al_default_de_fabrica(self, monkeypatch):
		_config(monkeypatch, "")
		rules, error = wp.load_policy()
		assert error == ""
		assert rules == wp.parse_policy(wp.DEFAULT_POLICY)[0]

	def test_solo_espacios_cae_al_default_de_fabrica(self, monkeypatch):
		_config(monkeypatch, "   ")
		rules, error = wp.load_policy()
		assert error == ""
		assert rules == wp.parse_policy(wp.DEFAULT_POLICY)[0]

	def test_politica_del_operador_se_respeta(self, monkeypatch):
		_config(monkeypatch, "*:any")
		rules, error = wp.load_policy()
		assert error == ""
		assert rules == (("*", "any"),)

	def test_politica_invalida_no_despierta_a_nadie(self, monkeypatch):
		_config(monkeypatch, "orchestrator:chain,*:inventada")
		rules, error = wp.load_policy()
		assert rules == ()
		assert error

	def test_config_inaccesible_fail_closed(self, monkeypatch):
		import red_pill.config as cfg

		def boom():
			raise RuntimeError("sin .env")

		monkeypatch.setattr(cfg, "get_config", boom)
		rules, error = wp.load_policy()
		assert rules == ()
		assert error


class TestRelations:
	def test_misma_continuidad_es_self(self):
		a = _actor(continuity_id="x", originator="opencode:a")
		b = _actor(continuity_id="x", originator="opencode:b")
		assert wp.REL_SELF in wp.relations_of(a, b)

	def test_mismo_cuerpo_es_self(self):
		a = _actor(originator="opencode:a")
		b = _actor(originator="opencode:a")
		assert wp.REL_SELF in wp.relations_of(a, b)

	def test_orquestrador_a_su_mision_es_chain(self):
		assert wp.REL_CHAIN in wp.relations_of(_sender(), _recipient())

	def test_tarea_a_compañera_no_es_chain(self):
		assert wp.REL_CHAIN not in wp.relations_of(_sender(role="task"), _recipient())

	def test_misma_campana_y_linaje_cuentan_para_la_cadena(self):
		a = _actor(role="orchestrator", lineage_id="lin")
		b = _actor(lineage_id="lin", continuity_id="otro")
		assert wp.REL_CHAIN in wp.relations_of(a, b)


class TestCanWake:
	def test_default_permite_orquestrador_a_su_cadena(self, monkeypatch):
		_config(monkeypatch, None)
		d = wp.can_wake(_sender(), _recipient())
		assert d.allow is True
		assert d.rule

	def test_default_deniega_par_de_otra_mision(self, monkeypatch):
		_config(monkeypatch, None)
		d = wp.can_wake(_sender(role="task", mission="repo:otro"), _recipient())
		assert d.allow is False
		assert d.reason == wp.REASON_NO_RULE

	def test_sin_destinatario_no_hay_wake(self, monkeypatch):
		_config(monkeypatch, None)
		d = wp.can_wake(_sender(), _actor())
		assert d.allow is False
		assert d.reason == wp.REASON_NO_RECIPIENT

	def test_politica_invalida_deniega(self, monkeypatch):
		_config(monkeypatch, "orchestrator:inventada")
		d = wp.can_wake(_sender(), _recipient())
		assert d.allow is False
		assert d.reason.startswith(wp.REASON_RULES_INVALID)

	def test_any_es_opt_in_explicito(self, monkeypatch):
		_config(monkeypatch, "*:any")
		d = wp.can_wake(_sender(role="task", mission="otra"), _recipient())
		assert d.allow is True
		assert d.rule == "*:any"

	def test_reglas_se_pueden_pasar_ya_cargadas(self):
		"""El llamante puede cargar la matriz una vez por tanda y no releer config."""
		d = wp.can_wake(_sender(), _recipient(), rules=(("*", "self"),))
		assert d.allow is False


class TestInbound:
	def test_roundtrip_por_cuerpo(self, db):
		assert wp.set_inbound("alma", "hold", originator="opencode:s1", db_path=db) is True
		assert wp.get_inbound("alma", originator="opencode:s1", db_path=db) == "hold"

	def test_el_alma_hereda_lo_declarado_sin_cuerpo(self, db):
		assert wp.set_inbound("alma", "refuse", db_path=db) is True
		assert wp.get_inbound("alma", originator="opencode:otro", db_path=db) == "refuse"

	def test_lo_declarado_por_cuerpo_gana_sobre_lo_del_alma(self, db):
		wp.set_inbound("alma", "refuse", db_path=db)
		wp.set_inbound("alma", "accept", originator="opencode:s1", db_path=db)
		assert wp.get_inbound("alma", originator="opencode:s1", db_path=db) == "accept"
		assert wp.get_inbound("alma", originator="opencode:s2", db_path=db) == "refuse"

	def test_estado_invalido_no_se_guarda(self, db):
		assert wp.set_inbound("alma", "quizas", db_path=db) is False
		assert wp.set_inbound("", "accept", db_path=db) is False

	def test_sin_alma_es_hold(self, db):
		assert wp.get_inbound("", db_path=db) == wp.INBOUND_HOLD

	def test_sin_declaracion_es_accept(self, db):
		assert wp.get_inbound("nueva", db_path=db) == wp.INBOUND_ACCEPT

	def test_listado(self, db):
		wp.set_inbound("alma", "hold", reason="reunion", db_path=db)
		rows = wp.list_inbound(continuity_id="alma", db_path=db)
		assert len(rows) == 1
		assert rows[0]["state"] == "hold"
		assert rows[0]["reason"] == "reunion"


class TestDecideWake:
	def test_accept_deja_decidir_a_la_matriz(self, monkeypatch, db):
		_config(monkeypatch, None)
		d = wp.decide_wake(sender=_sender(), recipient=_recipient(), db_path=db)
		assert d.allow is True

	def test_refuse_es_terminal_y_gana_a_la_matriz(self, monkeypatch, db):
		_config(monkeypatch, "*:any")
		assert wp.set_inbound("rcv", "refuse", db_path=db) is True
		d = wp.decide_wake(sender=_sender(), recipient=_recipient(), db_path=db)
		assert d.allow is False
		assert d.reason == wp.REASON_INBOUND_REFUSE
		assert d.terminal is True

	def test_hold_difiere(self, monkeypatch, db):
		_config(monkeypatch, "*:any")
		wp.set_inbound("rcv", "hold", db_path=db)
		d = wp.decide_wake(sender=_sender(), recipient=_recipient(), db_path=db)
		assert d.allow is False
		assert d.reason == wp.REASON_INBOUND_HOLD
		assert d.terminal is False
		assert d.inbound is True

	def test_inbound_blocked_atajo(self, db):
		assert wp.inbound_blocked("libre", db_path=db) is None
		wp.set_inbound("alma", "hold", db_path=db)
		assert wp.inbound_blocked("alma", db_path=db) == wp.REASON_INBOUND_HOLD


class TestDescribe:
	def test_retrato_fail_closed(self, monkeypatch):
		_config(monkeypatch, "orchestrator:inventada")
		snap = wp.describe()
		assert snap["fail_closed"] is True
		assert snap["rules"] == []
		assert snap["config_key"] == wp.CONFIG_KEY

	def test_retrato_vigente(self, monkeypatch):
		_config(monkeypatch, "*:self")
		snap = wp.describe()
		assert snap["fail_closed"] is False
		assert snap["rules"] == ["*:self"]
