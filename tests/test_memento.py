"""Memento Chronicle (RFC-002 Fase 1): renderer, scrubber, registry e hilo prev/next."""

import sys
from pathlib import Path

from red_pill.memento.clean import normalize_noise
from red_pill.memento.registry import MementoRegistry, recompute_chain
from red_pill.memento.render import (
	compute_hash,
	extract_body,
	render_session,
	session_dir_slug,
	update_frontmatter_links,
	write_session,
)
from red_pill.memento.scrub import REDACTED, scrub_secrets

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _messages(n=3, base_ts=1787234592.0):
	msgs = []
	for i in range(n):
		role = "user" if i % 2 == 0 else "assistant"
		msgs.append({"role": role, "content": f"Mensaje {i} con contenido útil.", "timestamp": base_ts + i * 60})
	return msgs


# ── Scrubber MUST-9 ──────────────────────────────────────────────────────────


def test_scrub_redacts_common_credential_shapes():
	samples = [
		"export GH=ghp_" + "a1" * 18,
		"aws key AKIA" + "A" * 16 + " en el .env",
		"jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc123def",
		"curl -H 'Authorization: Bearer abcdef1234567890TOKEN'",
		"password = hunter2secret",
		'api_key: "sk-proj-1234567890abcdefghij"',
		"postgres://joan:supersecreta@localhost/db",
	]
	for sample in samples:
		assert REDACTED in scrub_secrets(sample), sample


def test_scrub_preserves_innocent_text_and_placeholders():
	for sample in [
		"el token de atención del transformer",
		"password = $DB_PASSWORD",
		"api_key: <tu-clave-aqui>",
		"la password: corta",
		"secret_token = get_token()",
	]:
		assert scrub_secrets(sample) == sample, sample


def test_scrub_url_userinfo_keeps_user():
	out = scrub_secrets("https://joan:hunter2pass@git.example.com/repo.git")
	assert "joan" in out and "hunter2pass" not in out


def test_scrub_private_key_block():
	block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
	assert scrub_secrets(block) == REDACTED


# ── Limpieza compartida §5.2 (paridad byte-idéntica con el ingester) ─────────


def test_normalize_noise_matches_ingester_refine_content():
	sys.path.insert(0, str(SCRIPTS_DIR))
	from antigravity_ingest import ChronicleIngester

	dirty = "\x1b[31mrojo\x1b[0m\n[2026-08-26] DEBUG basura\nreal\n\n\n\n" + "A" * 250
	assert ChronicleIngester._refine_content(object(), dirty) == normalize_noise(dirty)
	assert "\x1b" not in normalize_noise(dirty)
	assert "[CONTENT_BLOB_REDACTED]" in normalize_noise(dirty)


# ── Renderer §4.2 ────────────────────────────────────────────────────────────


def test_session_dir_slug_sanitizes():
	assert session_dir_slug("opencode:abc-123") == "opencode-abc-123"
	assert session_dir_slug("claude_code:UUID Con Espacios/½") == "claude_code-uuid-con-espacios"
	assert ":" not in session_dir_slug("a:b:c") and "/" not in session_dir_slug("a/b")
	assert session_dir_slug(":::") == "session"


def test_render_month_pinned_to_first_message():
	rendered = render_session("opencode:s1", "opencode", "opencode", _messages())
	assert rendered.month == "2026-08"
	assert rendered.dir_rel == "2026-08/opencode/opencode-s1"
	assert rendered.created_at is not None and rendered.created_at.endswith("Z")


def test_render_accepts_epoch_string_timestamps():
	msgs = [{"role": "user", "content": "reconstruida desde archive", "timestamp": "1787234592.0"}]
	rendered = render_session("abc-123", "antigravity", "antigravity", msgs, reconstructed=True)
	assert rendered.month == "2026-08" and rendered.created_at == "2026-08-20T14:03:12Z"


def test_render_month_override_wins():
	rendered = render_session("opencode:s1", "opencode", "opencode", _messages(), month_override="2026-07")
	assert rendered.month == "2026-07"


def test_render_frontmatter_and_body():
	rendered = render_session(
		"opencode:s1", "opencode", "opencode", _messages(), workspace="-home-joan-Workspace", step_count=47, reconstructed=True
	)
	text = rendered.index_text
	assert text.startswith("---\nsession_id: opencode:s1\nsource: opencode\n")
	assert "workspace: -home-joan-Workspace" in text
	assert "step_count: 47" in text
	assert "reconstructed: true" in text
	assert "prev_session: null" in text and "next_session: null" in text  # longitud fija: los refs no se mueven
	assert "# opencode:s1" in text
	assert "— Usuario" in text and "— Asistente" in text
	assert compute_hash(extract_body(text)) == rendered.memento_hash


def test_render_is_deterministic():
	a = render_session("opencode:s1", "opencode", "opencode", _messages())
	b = render_session("opencode:s1", "opencode", "opencode", _messages())
	assert a.index_text == b.index_text and a.memento_hash == b.memento_hash


def test_render_light_session_has_no_splits():
	rendered = render_session("opencode:s1", "opencode", "opencode", _messages(5))
	assert not rendered.has_splits and rendered.splits == []
	assert "## Secciones" not in rendered.index_text


def test_render_dense_session_splits_with_stable_line_refs():
	rendered = render_session("opencode:dense", "opencode", "opencode", _messages(25), split_max_messages=10, split_max_chars=100000)
	assert rendered.has_splits and len(rendered.splits) == 3
	assert rendered.splits[0][0] == "001-mensajes-0001-0010.md"
	assert "## Secciones" in rendered.index_text

	lines = rendered.index_text.split("\n")
	for filename, split_text in rendered.splits:
		ref_line = split_text.split("\n")[0]
		start = int(ref_line.split("#l")[1].split("-")[0])
		assert lines[start - 1].startswith("## "), f"{filename}: l{start} no es cabecera de mensaje"


def test_write_session_idempotent_and_reconciles_stale_splits(tmp_path):
	dense = render_session("opencode:d", "opencode", "opencode", _messages(25), split_max_messages=10, split_max_chars=100000)
	session_dir = write_session(tmp_path, dense)
	memento_dir = session_dir / "memento"
	assert (memento_dir / "index.md").exists()
	assert len(list(memento_dir.glob("[0-9][0-9][0-9]-*.md"))) == 3

	light = render_session("opencode:d", "opencode", "opencode", _messages(5), split_max_messages=10, split_max_chars=100000)
	write_session(tmp_path, light)
	assert len(list(memento_dir.glob("[0-9][0-9][0-9]-*.md"))) == 0  # splits stale reconciliados


def test_render_applies_scrub_and_clean():
	msgs = [{"role": "user", "content": "token = ghp_" + "b2" * 18 + "\x1b[31m", "timestamp": 1787234592.0}]
	rendered = render_session("opencode:sec", "opencode", "opencode", msgs)
	assert REDACTED in rendered.index_text and "ghp_" not in rendered.index_text and "\x1b" not in rendered.index_text


# ── Frontmatter links + hash del contrato §4.5.1 ─────────────────────────────


def test_update_frontmatter_links_preserves_body_hash(tmp_path):
	rendered = render_session("opencode:s2", "opencode", "opencode", _messages())
	session_dir = write_session(tmp_path, rendered)
	index_file = session_dir / "memento" / "index.md"

	assert update_frontmatter_links(index_file, "opencode:s1", "opencode:s3")
	text = index_file.read_text(encoding="utf-8")
	assert "prev_session: opencode:s1" in text and "next_session: opencode:s3" in text
	assert compute_hash(extract_body(text)) == rendered.memento_hash
	assert not update_frontmatter_links(index_file, "opencode:s1", "opencode:s3")  # sin cambios → no reescribe


def test_chain_update_does_not_shift_split_line_refs(tmp_path):
	rendered = render_session("opencode:dense2", "opencode", "opencode", _messages(25), split_max_messages=10, split_max_chars=100000)
	session_dir = write_session(tmp_path, rendered)
	index_file = session_dir / "memento" / "index.md"
	assert update_frontmatter_links(index_file, "opencode:a", "opencode:b")

	lines = index_file.read_text(encoding="utf-8").split("\n")
	for filename, split_text in rendered.splits:
		start = int(split_text.split("\n")[0].split("#l")[1].split("-")[0])
		assert lines[start - 1].startswith("## "), f"{filename}: l{start} desplazado tras actualizar el hilo"


def test_rerender_with_chain_links_keeps_hash_stable():
	first = render_session("opencode:s1", "opencode", "opencode", _messages(25), split_max_messages=10, split_max_chars=100000)
	second = render_session(
		"opencode:s1", "opencode", "opencode", _messages(25),
		prev_session="opencode:s0", next_session="opencode:s2", split_max_messages=10, split_max_chars=100000,
	)
	assert first.memento_hash == second.memento_hash  # el frontmatter no participa del hash ni mueve el cuerpo


# ── Registry + hilo ──────────────────────────────────────────────────────────


def test_registry_roundtrip_and_chain(tmp_path):
	root = tmp_path / "memento"
	registry = MementoRegistry(path=tmp_path / "memento_registry.json")

	for i, ts in enumerate([1787234592.0, 1787238192.0, 1787241792.0]):
		rendered = render_session(f"opencode:s{i}", "opencode", "opencode", _messages(3, base_ts=ts))
		write_session(root, rendered)
		registry.upsert(
			"opencode",
			f"opencode:s{i}",
			{"dir": rendered.dir_rel, "created_at": rendered.created_at, "memento_hash": rendered.memento_hash, "step_count": 3},
		)

	assert recompute_chain(root, registry, "opencode") == 3
	assert recompute_chain(root, registry, "opencode") == 0  # segunda pasada: estable

	middle = (root / "2026-08/opencode/opencode-s1/memento/index.md").read_text(encoding="utf-8")
	assert "prev_session: opencode:s0" in middle and "next_session: opencode:s2" in middle

	registry.save()
	reloaded = MementoRegistry(path=tmp_path / "memento_registry.json")
	assert reloaded.get("opencode", "opencode:s1")["next_session"] == "opencode:s2"
	assert reloaded.state["stats"]["total_sessions"] == 3


def test_chain_skips_unrendered_sessions(tmp_path):
	registry = MementoRegistry(path=tmp_path / "reg.json")
	registry.upsert("opencode", "opencode:empty", {"step_count": 5})
	assert recompute_chain(tmp_path, registry, "opencode") == 0
