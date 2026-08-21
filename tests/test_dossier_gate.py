"""DossierGateMinion — tabla de transición determinista del loop de ideación
(RFC_DOSSIER_IDEACION §3.4, FASE 3 del plan). Sin LLM, sin I/O real: la lógica
pura (compute_verdict / apply_hallazgo / detect_findings) se testea a fondo."""

import pytest

from red_pill.swarm.agents.dossier_gate import (
	DEFAULT_MAX_PASSES,
	DEFAULT_MAX_SILENT_PASSES,
	apply_hallazgo,
	compute_verdict,
	detect_findings,
)


def _state(**over):
	base = {
		"status": "llama",
		"type": "idea",
		"domain": "agentes autónomos",
		"open_questions": ["¿cómo se ancla el porqué?"],
		"claims": [],
		"contradictions": False,
		"viable": None,
		"pases_ejecutados": 0,
		"pasadas_sin_hallazgos": 0,
	}
	base.update(over)
	return base


# ── Tabla de transición (cada fila de §3.4) ──────────────────────────────────

def test_verdict_germination_when_no_domain():
	"""type: idea sin domain → germinación (expansión a llama)."""
	assert compute_verdict(_state(domain=None)) == {"verdict": "continue", "next_pass": "germination"}


def test_verdict_research_when_open_questions():
	"""open_questions sin evidencia → investigación."""
	v = compute_verdict(_state(open_questions=["¿x?"]))
	assert v["verdict"] == "continue" and v["next_pass"] == "research"


def test_verdict_research_when_claims_lack_evidence():
	"""claims sin evidencia (o vacíos) → investigación."""
	v = compute_verdict(_state(open_questions=[], claims=[{"id": "c1", "evidence": None}]))
	assert v["next_pass"] == "research"


def test_verdict_synthesis_when_viable_undecided():
	"""claims con evidencia, sin contradicciones, viable sin evaluar → síntesis."""
	v = compute_verdict(_state(open_questions=[], claims=[{"id": "c1", "evidence": "shard-1"}]))
	assert v["verdict"] == "continue" and v["next_pass"] == "synthesis"


def test_verdict_hypothesis_when_contradictions():
	"""contradicciones detectadas → prueba de hipótesis."""
	v = compute_verdict(_state(open_questions=[], claims=[{"id": "c1", "evidence": "e"}], contradictions=True, viable=None))
	assert v["next_pass"] == "hypothesis"


def test_verdict_hypothesis_when_not_viable():
	"""viable: false → prueba de hipótesis (antes de descartar)."""
	v = compute_verdict(_state(open_questions=[], claims=[{"id": "c1", "evidence": "e"}], viable=False))
	assert v["next_pass"] == "hypothesis"


def test_verdict_matured():
	"""criterio L4 cumplido → matured (terminal)."""
	v = compute_verdict(_state(open_questions=[], claims=[{"id": "c1", "evidence": "e"}], viable=True))
	assert v["verdict"] == "matured"


def test_verdict_task_never_iterates():
	"""type: task → matured directo (no itera)."""
	assert compute_verdict(_state(type="task"))["verdict"] == "matured"


def test_verdict_respects_declared_terminal():
	"""status terminal declarado por un pase previo se respeta."""
	assert compute_verdict(_state(status="dead"))["verdict"] == "dead"


def test_verdict_respects_declared_pause():
	"""status de pausa declarado se respeta con su razón."""
	v = compute_verdict(_state(status="awaiting_operator", pause_reason="falta juicio"))
	assert v["verdict"] == "awaiting_operator" and v["reason"] == "falta juicio"


# ── Tope fijo (L2) ───────────────────────────────────────────────────────────

def test_fixed_cap_triggers_awaiting_operator():
	"""pases_ejecutados >= max_passes → awaiting_operator, aunque falte poco."""
	v = compute_verdict(_state(pases_ejecutados=DEFAULT_MAX_PASSES))
	assert v["verdict"] == "awaiting_operator"


def test_fixed_cap_parametrizable():
	v = compute_verdict(_state(pases_ejecutados=3), limits={"max_passes": 3})
	assert v["verdict"] == "awaiting_operator"
	# con 2 aún no dispara
	assert compute_verdict(_state(pases_ejecutados=2), limits={"max_passes": 3})["verdict"] != "awaiting_operator"


# ── Tope dinámico (L2): pasadas sin hallazgos ────────────────────────────────

def test_silent_cap_triggers_awaiting_operator():
	"""3 pasadas sin hallazgos y sin criterio L4 → awaiting_operator."""
	state = _state(
		open_questions=[],
		claims=[{"id": "c1", "evidence": "e"}],
		viable=True,
		contradictions=False,
		pasadas_sin_hallazgos=DEFAULT_MAX_SILENT_PASSES,
	)
	# ¡Ojo! con viable=True y sin preguntas el criterio L4 ya da matured antes:
	# el tope dinámico aplica cuando el L4 NO se cumple (p.ej. viable=None).
	state["viable"] = None
	assert compute_verdict(state)["verdict"] == "awaiting_operator"


# ── Hallazgos (definición L2) ────────────────────────────────────────────────

def test_apply_hallazgo_resets_silent():
	state = apply_hallazgo(_state(pasadas_sin_hallazgos=2), had_findings=True)
	assert state["pasadas_sin_hallazgos"] == 0
	assert state["pases_ejecutados"] == 1


def test_apply_hallazgo_increments_silent():
	state = apply_hallazgo(_state(pasadas_sin_hallazgos=2), had_findings=False)
	assert state["pasadas_sin_hallazgos"] == 3


def test_detect_findings_new_question():
	assert detect_findings(_state(open_questions=["a"]), _state(open_questions=["a", "b"])) is True


def test_detect_findings_new_claim():
	assert detect_findings(_state(claims=[]), _state(claims=[{"id": "c1"}])) is True


def test_detect_findings_new_contradiction():
	assert detect_findings(_state(), _state(contradictions=True)) is True


def test_detect_findings_no_finding_on_answered_question():
	"""Responder una pregunta YA listada (sin añadir nada) NO es hallazgo."""
	before = _state(open_questions=["a", "b"])
	after = _state(open_questions=["a", "b"], claims=[{"id": "c1", "evidence": "e"}])
	assert detect_findings(before, after) is True  # el claim SÍ es hallazgo
	before2 = _state(open_questions=["a"])
	after2 = _state(open_questions=[])  # solo se respondió: sin claim nuevo
	assert detect_findings(before2, after2) is False


# ── Params del gate ──────────────────────────────────────────────────────────

def test_inject_gate_params_appends_dossier_and_mission():
	from red_pill.swarm.agents.dossier_gate import _inject_gate_params

	stages = [
		{"id": "research", "type": "agent", "minion": "agent", "model": "m", "prompt": "x"},
		{"id": "gate", "type": "command", "minion": "dossier_gate", "params": {}},
	]
	out = _inject_gate_params(stages, "/dossier", "mission-1")
	assert out[-1]["params"] == {"dossier_dir": "/dossier", "mission_id": "mission-1"}
	assert out[0]["id"] == "research"  # el pase no se toca


# ── Integración del minion (I/O real sobre dossier temporal) ─────────────────

def _write_state(tmp_path, **over):
	import yaml

	state = {
		"status": "llama",
		"type": "idea",
		"domain": "agentes autónomos",
		"open_questions": ["¿cómo se ancla el porqué?"],
		"claims": [],
		"contradictions": False,
		"viable": None,
		"pases_ejecutados": 0,
		"pasadas_sin_hallazgos": 0,
	}
	state.update(over)
	path = tmp_path / "state.yaml"
	path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
	return path


def test_gate_matured_does_not_reenqueue(tmp_path, monkeypatch):
	"""Veredicto terminal (matured) NO re-encola: el job del pase completa."""
	from red_pill.swarm.agents.dossier_gate import DossierGateMinion

	_write_state(
		tmp_path,
		open_questions=[],
		claims=[{"id": "c1", "evidence": "shard-1"}],
		viable=True,
		contradictions=False,
	)
	called = []
	monkeypatch.setattr(DossierGateMinion, "_enqueue_next_pass", lambda self, kwargs, np, st: called.append(np))
	m = DossierGateMinion()
	res = asyncio_run(m.execute("", dossier_dir=str(tmp_path), mission_id="m1"))
	assert res["status"] == "success"
	assert res["verdict"] == "matured"
	assert called == [], "un veredicto terminal NO debe re-encolar"


def test_gate_continue_reenqueues_with_same_mission(tmp_path, monkeypatch):
	"""Veredicto continue re-encola el pase siguiente (mismo mission_id)."""
	from red_pill.swarm.agents.dossier_gate import DossierGateMinion

	_write_state(tmp_path)
	recorded = {}

	def _fake_enqueue(self, kwargs, next_pass, state):
		recorded["next_pass"] = next_pass
		recorded["mission_id"] = kwargs.get("mission_id")
		return "job-id-123"

	monkeypatch.setattr(DossierGateMinion, "_enqueue_next_pass", _fake_enqueue)
	m = DossierGateMinion()
	res = asyncio_run(m.execute("", dossier_dir=str(tmp_path), mission_id="m1"))
	assert res["status"] == "success"
	assert res["verdict"] == "continue"
	assert recorded == {"next_pass": "research", "mission_id": "m1"}


def test_gate_pause_states_raise_job_pause(tmp_path):
	"""awaiting_operator/parked/superseded → JobPauseRequested (PAUSED, cero intentos)."""
	from red_pill.jobs.drivers.base import JobPauseRequested
	from red_pill.swarm.agents.dossier_gate import DossierGateMinion

	_write_state(tmp_path, status="awaiting_operator", pause_reason="juicio del operador")
	m = DossierGateMinion()
	with pytest.raises(JobPauseRequested, match="juicio del operador"):
		asyncio_run(m.execute("", dossier_dir=str(tmp_path), mission_id="m1"))


def asyncio_run(coro):
	import asyncio

	return asyncio.run(coro)


# ── Remediación auditoría 2026-08-21 ─────────────────────────────────────────

def test_pass_recipes_gate_depends_on_pass():
	"""El gate jamás corre si su pase no completó: depends_on obligatorio."""
	from pathlib import Path

	import yaml

	repo = Path(__file__).resolve().parents[1]
	for name in ("germination", "research", "synthesis", "hypothesis"):
		data = yaml.safe_load((repo / "configs" / "jobs" / f"dossier-{name}.yaml").read_text(encoding="utf-8"))
		stages = data["manifest"]["stages"]
		assert stages[-1]["minion"] == "dossier_gate"
		assert stages[-1].get("depends_on") == [stages[0]["id"]], f"dossier-{name}: gate sin depends_on del pase"


def test_enqueue_pass_renders_validates_and_expands(monkeypatch):
	"""enqueue_pass interpola {dossier_dir}, pisa el mission_id de fábrica y
	aplica validate+expand antes de encolar."""
	from red_pill.swarm.agents.dossier_gate import enqueue_pass

	recipe_payload = {
		"mission_id": "dossier-loop",
		"manifest": {"workdir": "/tmp", "stages": [
			{"id": "research", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "Lee {dossier_dir}/README.md"},
			{"id": "gate", "type": "command", "minion": "dossier_gate", "params": {}, "depends_on": ["research"]},
		]},
	}
	monkeypatch.setattr("red_pill.jobs.recipes.load_recipe", lambda ref, base_dir=None: ("dag_job", recipe_payload, 5, None, False))
	monkeypatch.setattr("red_pill.jobs.drivers.dag._resolve_minion_kind", lambda mid: "agent" if mid == "agent" else "logic")
	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager.list_tasks", lambda self, statuses=None, limit=50, mission_id=None: [])
	captured = {}

	def _fake_enqueue(self, source, payload, priority=5, mission_id=None, **kw):
		captured.update(payload=payload, mission_id=mission_id)
		return "job-xyz"

	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager.enqueue_task", _fake_enqueue)
	job_id = enqueue_pass("research", "/ideas/i-1", "mission-i-1")
	assert job_id == "job-xyz"
	assert captured["mission_id"] == "mission-i-1"
	assert captured["payload"]["mission_id"] == "mission-i-1"          # pisado, no setdefault
	stage = captured["payload"]["manifest"]["stages"][0]
	assert "{dossier_dir}" not in stage["prompt"] and "/ideas/i-1" in stage["prompt"]
	gate = captured["payload"]["manifest"]["stages"][-1]
	assert gate["params"] == {"dossier_dir": "/ideas/i-1", "mission_id": "mission-i-1"}


def test_enqueue_pass_failsafe_blocks_flash(monkeypatch):
	from red_pill.swarm.agents.dossier_gate import enqueue_pass

	recipe_payload = {
		"mission_id": "dossier-loop",
		"manifest": {"workdir": "/tmp", "stages": [
			{"id": "research", "type": "agent", "minion": "agent", "model": "flash", "prompt": "x {dossier_dir}"},
		]},
	}
	monkeypatch.setattr("red_pill.jobs.recipes.load_recipe", lambda ref, base_dir=None: ("dag_job", recipe_payload, 5, None, False))
	monkeypatch.setattr("red_pill.jobs.drivers.dag._resolve_minion_kind", lambda mid: "agent")
	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager.list_tasks", lambda self, statuses=None, limit=50, mission_id=None: [])
	with pytest.raises(ValueError):
		enqueue_pass("research", "/ideas/i-1", "m-1")


def test_enqueue_pass_rejects_seed(monkeypatch):
	from red_pill.swarm.agents.dossier_gate import enqueue_pass

	monkeypatch.setattr("red_pill.jobs.recipes.load_recipe", lambda ref, base_dir=None: ("dag_job", {}, 5, None, True))
	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager.list_tasks", lambda self, statuses=None, limit=50, mission_id=None: [])
	with pytest.raises(RuntimeError, match="seed"):
		enqueue_pass("research", "/ideas/i-1", "m-1")


def test_enqueue_pass_skips_when_mission_has_live_job(monkeypatch):
	"""Guard de idempotencia por misión: con un job vivo de la misma misión
	(distinto del actual) NO se encola un duplicado — se devuelve el existente.
	Cubre el re-run del gate (at-least-once) y el crash post-persist/pre-enqueue."""
	from red_pill.swarm.agents.dossier_gate import enqueue_pass

	monkeypatch.setattr(
		"red_pill.cognitive.queue_manager.CognitiveQueueManager.list_tasks",
		lambda self, statuses=None, limit=50, mission_id=None: [{"id": "job-vivo", "status": "PENDING", "mission_id": mission_id}],
	)

	def _boom(self, *a, **kw):
		raise AssertionError("enqueue_task no debe llamarse con un job vivo en la misión")

	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager.enqueue_task", _boom)
	assert enqueue_pass("research", "/ideas/i-1", "m-1", current_job_id="job-actual") == "job-vivo"
