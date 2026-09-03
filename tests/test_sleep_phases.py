"""Coverage for the SleepPhase pipeline introduced by ADR-SLEEP-001 (phase B)."""

from unittest.mock import MagicMock, patch

from red_pill.metabolism.phases import ConsolidationPhase, ErosionPhase, EvolutionPhase, SleepContext, WashoutPhase
from red_pill.metabolism.sleep import perform_sleep_cycle

CONS = "red_pill.metabolism.phases.consolidation"
MAINT = "red_pill.metabolism.phases.maintenance_phases"
EVO = "red_pill.metabolism.phases.evolution_phase"
EPH = "red_pill.metabolism.ephemeral_server"


# ── Phase contract ────────────────────────────────────────────────────────────


def test_phase_names_and_gpu_flags():
	assert ConsolidationPhase().name == "consolidation"
	assert ConsolidationPhase().requires_gpu is True
	for phase in (ErosionPhase(), WashoutPhase(), EvolutionPhase()):
		assert phase.name
		assert phase.requires_gpu is False  # CPU-only default from SleepPhase


def test_is_enabled_default_and_disabled():
	phase = ErosionPhase()
	assert phase.is_enabled({}) is True
	assert phase.is_enabled({"sleep_phases": {"erosion": {"enabled": False}}}) is False
	assert phase.is_enabled({"sleep_phases": {"erosion": {"enabled": True}}}) is True


# ── CPU-only phases delegate and swallow errors ────────────────────────────────


def test_erosion_phase_delegates():
	ctx = SleepContext(memory_manager=MagicMock())
	with patch(f"{MAINT}.erode_work_hubs") as fn:
		ErosionPhase().execute(ctx)
		fn.assert_called_once_with(ctx.memory_manager)


def test_washout_phase_delegates():
	ctx = SleepContext(memory_manager=MagicMock())
	with patch(f"{MAINT}.run_rhizodb_washout_and_pruning") as fn:
		WashoutPhase().execute(ctx)
		fn.assert_called_once_with(ctx.memory_manager)


def test_evolution_phase_delegates():
	ctx = SleepContext(memory_manager=MagicMock())
	with patch(f"{EVO}.IdentityEvaluator.evaluate_set_point") as fn:
		EvolutionPhase().execute(ctx)
		fn.assert_called_once_with(ctx.memory_manager)


def test_cpu_phases_swallow_exceptions():
	ctx = SleepContext(memory_manager=MagicMock())
	with patch(f"{MAINT}.erode_work_hubs", side_effect=Exception("boom")):
		ErosionPhase().execute(ctx)  # must not raise
	with patch(f"{MAINT}.run_rhizodb_washout_and_pruning", side_effect=Exception("boom")):
		WashoutPhase().execute(ctx)
	with patch(f"{EVO}.IdentityEvaluator.evaluate_set_point", side_effect=Exception("boom")):
		EvolutionPhase().execute(ctx)


# ── _check_llm_available reachability probe ─────────────────────────────────────


def test_check_llm_available_uds_ok():
	from red_pill.metabolism import ephemeral_server as es

	with (
		patch(f"{EPH}.os.path.exists", return_value=True),
		patch(f"{EPH}.socket.socket") as sock,
	):
		sock.return_value.connect.return_value = None
		assert es._check_llm_available() is True


def test_check_llm_available_uds_refused_no_tcp():
	from red_pill.metabolism import ephemeral_server as es

	with (
		patch(f"{EPH}.os.path.exists", return_value=True),
		patch(f"{EPH}.os.remove"),
		patch(f"{EPH}.socket.socket") as sock,
		patch.object(es.cfg, "MLX_LM_URL", "", create=True),
	):
		sock.return_value.connect.side_effect = OSError("refused")
		assert es._check_llm_available() is False


def test_check_llm_available_tcp_ok():
	from red_pill.metabolism import ephemeral_server as es

	with (
		patch(f"{EPH}.os.path.exists", return_value=False),
		patch.object(es.cfg, "MLX_LM_URL", "http://127.0.0.1:8760", create=True),
		patch(f"{EPH}.socket.create_connection") as conn,
	):
		conn.return_value = MagicMock()
		assert es._check_llm_available() is True


# ── Runner: partial deferral ────────────────────────────────────────────────────


def test_runner_defers_gpu_but_runs_cpu_maintenance():
	"""GPU committed → consolidation self-defers (vram_busy kept), CPU phases still run."""
	mgr = MagicMock()
	with (
		patch(f"{CONS}.VramProbe.get_backend", return_value="cuda"),
		patch(f"{CONS}._check_llm_available", return_value=False),
		patch(f"{CONS}.VramProbe.get_free_mb", return_value=100),
		patch(f"{MAINT}.erode_work_hubs") as erosion,
		patch(f"{MAINT}.run_rhizodb_washout_and_pruning") as washout,
		patch(f"{EVO}.IdentityEvaluator.evaluate_set_point") as evo,
		patch("red_pill.core.notifier.SovereignNotifier.clear_bunker_signal") as clear,
	):
		result = perform_sleep_cycle(mgr)
		assert result == 0
		# CPU-only maintenance ran despite the deferral
		erosion.assert_called_once()
		washout.assert_called_once()
		evo.assert_called_once()
		# vram_busy must NOT be cleared while deferred
		cleared = [c.args[1] for c in clear.call_args_list]
		assert "vram_busy" not in cleared


def test_runner_clears_vram_busy_on_real_cycle():
	"""GPU free → consolidation runs (empty buffer) and the alert is cleared."""
	mgr = MagicMock()
	mgr.client.collection_exists.return_value = False  # consolidation no-ops, not deferred
	with (
		patch(f"{CONS}.VramProbe.get_backend", return_value="cpu"),
		patch(f"{CONS}._check_llm_available", return_value=True),
		patch(f"{MAINT}.erode_work_hubs"),
		patch(f"{MAINT}.run_rhizodb_washout_and_pruning"),
		patch(f"{EVO}.IdentityEvaluator.evaluate_set_point"),
		patch("red_pill.core.notifier.SovereignNotifier.clear_bunker_signal") as clear,
	):
		perform_sleep_cycle(mgr)
		cleared = [c.args[1] for c in clear.call_args_list]
		assert "vram_busy" in cleared


# ── Drain cutoff: the cycle terminates even if sessions keep writing ───────────


def test_drain_cutoff_bounds_scroll_filter_and_terminates():
	"""The drain only touches engrams with timestamp <= cutoff; points written
	after the cycle started stay buffered for the NEXT cycle (no infinite drain)."""
	cutoff = 1700000000
	raw_point = MagicMock()
	raw_point.id = "raw-1"
	raw_point.payload = {
		"content": "USER: check compiler error\n\nASSISTANT: compile clean",
		"timestamp": cutoff - 10,  # inserted before the cycle started
		"metadata": {"model": "opus", "category": "work"},
	}
	seen_filters = []
	scroll_calls = {"n": 0}

	def mock_scroll(collection_name, **kwargs):
		if collection_name == "interaction_memories":
			scroll_calls["n"] += 1
			seen_filters.append(kwargs.get("scroll_filter"))
			# First batch: the pre-cutoff point. After it is deleted (mocked),
			# no other point with timestamp <= cutoff remains -> empty -> break.
			return ([raw_point] if scroll_calls["n"] == 1 else [], None)
		return ([], None)

	mgr = MagicMock()
	mgr.client.collection_exists.return_value = True
	mgr.client.scroll.side_effect = mock_scroll
	ctx = SleepContext(memory_manager=mgr, sleep_cutoff_ts=cutoff)

	with (
		patch(f"{CONS}.VramProbe.get_backend", return_value="cpu"),
		patch(f"{CONS}._check_llm_available", return_value=True),
		patch(f"{CONS}.chunk_text", side_effect=lambda text: ["distilled fix"]),
		patch(f"{CONS}.distill_engram", return_value={"summary": "s", "emotion": "neutral", "intensity": 0.8, "category": "work"}),
		patch(f"{CONS}.distill_session_anchors"),
		patch(f"{CONS}.EphemeralServer") as server,
		patch(f"{CONS}._load_thread_state", return_value={}),
		patch(f"{CONS}._save_thread_state"),
		patch("uuid.uuid4", return_value=__import__("uuid").UUID("00000000-0000-0000-0000-000000000999")),
	):
		mgr.add_memory.side_effect = ["child-1", "00000000-0000-0000-0000-000000000999"]
		server.return_value = MagicMock()
		ConsolidationPhase().execute(ctx)

	# Every drain scroll carried the timestamp bound to the pinned cutoff.
	assert seen_filters, "drain never scrolled"
	for f in seen_filters:
		conds = list(f.must or [])
		ts_conds = [c for c in conds if getattr(c, "key", "") == "timestamp"]
		assert ts_conds, f"missing timestamp bound in filter: {f}"
		assert ts_conds[0].range.lte == cutoff
	# The loop terminated after the eligible point was drained (no infinite drain).
	assert scroll_calls["n"] == 2


# ── EphemeralServer lifecycle ───────────────────────────────────────────────────


def _silence_notifier():
	return patch.multiple(
		"red_pill.core.notifier.SovereignNotifier",
		notify_os=MagicMock(),
		notify_bunker=MagicMock(),
		clear_bunker_signal=MagicMock(),
	)


def test_ephemeral_is_managed_service():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	srv = EphemeralServer()
	assert srv.is_managed_service is False  # None
	srv._process = "systemd_service"
	assert srv.is_managed_service is True
	srv._process = MagicMock()
	assert srv.is_managed_service is False  # a Popen is not a managed service


def test_ephemeral_start_missing_script():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	with (
		_silence_notifier(),
		patch(f"{EPH}.get_daemon_persistent_dir") as ddir,
		patch(f"{EPH}.os.path.exists", return_value=False),
	):
		ddir.return_value = MagicMock()
		assert EphemeralServer().start(MagicMock()) is False


def test_ephemeral_start_systemd_success():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	with (
		_silence_notifier(),
		patch(f"{EPH}.get_daemon_persistent_dir") as ddir,
		patch(f"{EPH}.os.path.exists", return_value=True),
		patch("shutil.which", return_value="/usr/bin/systemctl"),
		patch(f"{EPH}.subprocess.run"),
		patch(f"{EPH}._check_llm_available", return_value=True),
		patch("time.sleep"),
	):
		ddir.return_value = MagicMock()
		srv = EphemeralServer()
		assert srv.start(MagicMock()) is True
		assert srv._process == "systemd_service"


def test_ephemeral_stop_managed_service():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	srv = EphemeralServer()
	srv._process = "systemd_service"
	with patch("urllib.request.urlopen") as uo:
		uo.return_value.__enter__.return_value = MagicMock()
		srv.stop(MagicMock(), 3)  # triggers the /unload POST, no raise


def test_ephemeral_stop_popen():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	srv = EphemeralServer()
	proc = MagicMock()
	srv._process = proc
	with _silence_notifier():
		srv.stop(MagicMock(), 5)
	proc.terminate.assert_called_once()


def test_ephemeral_start_subprocess_fallback():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	def which(name):
		return "/usr/bin/systemd-run" if name == "systemd-run" else None

	with (
		_silence_notifier(),
		patch(f"{EPH}.get_daemon_persistent_dir") as ddir,
		patch(f"{EPH}.os.path.exists", return_value=True),
		patch("shutil.which", side_effect=which),
		patch(f"{EPH}.subprocess.Popen") as popen,
		patch(f"{EPH}._check_llm_available", return_value=True),
		patch("time.sleep"),
	):
		ddir.return_value = MagicMock()
		srv = EphemeralServer()
		assert srv.start(MagicMock()) is True
		popen.assert_called_once()


def test_ephemeral_start_timeout_failure():
	from red_pill.metabolism.ephemeral_server import EphemeralServer

	with (
		_silence_notifier(),
		patch(f"{EPH}.get_daemon_persistent_dir") as ddir,
		patch(f"{EPH}.os.path.exists", return_value=True),
		patch("shutil.which", return_value="/usr/bin/systemctl"),
		patch(f"{EPH}.subprocess.run"),
		patch(f"{EPH}._check_llm_available", return_value=False),
		patch("time.sleep"),
	):
		ddir.return_value = MagicMock()
		assert EphemeralServer().start(MagicMock()) is False  # never came online
