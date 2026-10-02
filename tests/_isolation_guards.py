"""Guardas de aislamiento de la suite: la suite no toca NADA vivo del operador.

conftest las instala ANTES de importar red_pill y las verifica en cada test:

1. Sandbox temporal de la sesión: TMPDIR / ``tempfile.tempdir`` apuntan a un dir
   propio (``/tmp/rpt…``). Todo mkdtemp, tmp_path y XDG_* de los tests vive ahí
   dentro y el proceso que lo creó lo borra al cerrar la sesión (los workers de
   xdist lo heredan por entorno y no lo borran). ``REDPILL_TEST_KEEP_TMP=1`` lo
   conserva para depurar.
2. Red: un ``connect()`` a un AF_UNIX fuera del sandbox (el socket SIP real, el
   bus de sesión...), a los puertos de los servicios locales (Qdrant, LLM,
   neon-link) o a un host que no sea loopback se rechaza (ConnectionRefused) y
   el test FALLA aunque el código se trague la excepción.
3. Comandos de host: systemctl / journalctl / podman / docker / systemd-run
   nunca llegan al sistema. Los verbos de lectura (is-active, status, show,
   ps...) devuelven un "inactive" determinista (no depende de qué corra en la
   máquina); los que mutan (start, stop, reset-failed, daemon-reload...) fallan
   el test: si un test los ejerce, los mockea.

Opt-out explícito por test: ``@pytest.mark.allow_local_services`` (justificarlo).
Límite conocido: no cubre procesos hijos (heredan el entorno redirigido, no los
parches) ni transportes en C (gRPC).
"""

from __future__ import annotations

import errno
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Iterator, List, Optional, Sequence, Tuple

SANDBOX_ENV = "REDPILL_TEST_SANDBOX"
KEEP_ENV = "REDPILL_TEST_KEEP_TMP"

# Qdrant (HTTP/gRPC), LLM local (dual-bind + reserva), neon-link (API/webhook).
GUARDED_TCP_PORTS = frozenset({6333, 6334, 8760, 8761, 8770, 8771})
_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback", "::1", "0.0.0.0", "::"})

_violations: List[str] = []
_reported = 0
_allowed_unix_roots: List[str] = []
_bypass = False


def _record(kind: str, detail: str) -> None:
	test = os.environ.get("PYTEST_CURRENT_TEST", "<fuera de un test>")
	_violations.append(f"{kind}: {detail}  [{test}]")


def take_violations() -> List[str]:
	"""Violaciones nuevas desde la última comprobación (incluye rezagadas de hilos)."""
	global _reported
	new = _violations[_reported:]
	_reported = len(_violations)
	return new


@contextmanager
def bypass(enabled: bool) -> Iterator[None]:
	"""Desactiva las guardas mientras corre un test que lo pide explícitamente."""
	global _bypass
	previous, _bypass = _bypass, enabled
	try:
		yield
	finally:
		_bypass = previous


# ── 1. Sandbox temporal ────────────────────────────────────────────────────────


def setup_sandbox() -> Tuple[str, bool]:
	"""Crea (o hereda, en un worker de xdist) el sandbox temporal. → (ruta, propio)."""
	inherited = os.environ.get(SANDBOX_ENV, "")
	if inherited and os.path.isdir(inherited):
		sandbox, owned = inherited, False
	else:
		# Prefijo corto: los sockets AF_UNIX de los tests cuelgan de aquí (límite 108).
		sandbox, owned = tempfile.mkdtemp(prefix="rpt"), True
	sandbox = os.path.realpath(sandbox)
	os.environ[SANDBOX_ENV] = sandbox
	os.environ["TMPDIR"] = sandbox
	tempfile.tempdir = sandbox
	allow_unix_root(sandbox)
	return sandbox, owned


def allow_unix_root(path: str) -> None:
	root = os.path.realpath(path)
	if root not in _allowed_unix_roots:
		_allowed_unix_roots.append(root)


def remove_sandbox(sandbox: str) -> None:
	if os.environ.get(KEEP_ENV) == "1":
		return
	shutil.rmtree(sandbox, ignore_errors=True)


# ── 2. Red ─────────────────────────────────────────────────────────────────────


def _is_loopback(host: object) -> bool:
	if not isinstance(host, str):
		return False
	h = host.strip("[]").lower()
	return h in _LOOPBACK_NAMES or h.startswith("127.") or h.startswith("::ffff:127.")


def _within(path: str, root: str) -> bool:
	return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _blocked_reason(sock: socket.socket, address: object) -> Optional[str]:
	if _bypass:
		return None
	family = sock.family
	if family == socket.AF_UNIX:
		raw = os.fsdecode(address) if isinstance(address, (str, bytes, os.PathLike)) else str(address)
		if not raw or raw.startswith("\0"):
			return f"AF_UNIX abstracto {raw!r}"
		path = os.path.realpath(raw)
		if any(_within(path, root) for root in _allowed_unix_roots):
			return None
		return f"AF_UNIX fuera del sandbox ({raw})"
	if family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and len(address) >= 2:
		host, port = address[0], address[1]
		if not _is_loopback(host):
			return f"host no-loopback {host}:{port}"
		if port in GUARDED_TCP_PORTS:
			return f"servicio local real {host}:{port}"
	return None


_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex


def _guarded_connect(self: socket.socket, address: object) -> None:
	reason = _blocked_reason(self, address)
	if reason:
		_record("red", reason)
		raise ConnectionRefusedError(errno.ECONNREFUSED, f"[TEST ISOLATION] conexión bloqueada: {reason}")
	return _orig_connect(self, address)  # type: ignore[arg-type]


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
	reason = _blocked_reason(self, address)
	if reason:
		_record("red", reason)
		return errno.ECONNREFUSED
	return _orig_connect_ex(self, address)  # type: ignore[arg-type]


# ── 3. Comandos de host ────────────────────────────────────────────────────────

_HOST_TOOLS = frozenset({"systemctl", "journalctl", "podman", "docker", "systemd-run"})
_SHELLS = frozenset({"sh", "bash", "dash", "zsh"})
# Opciones que consumen el token siguiente (para no confundir su valor con el verbo).
_VALUE_OPTIONS = frozenset(
	{
		"-p",
		"--property",
		"-t",
		"--type",
		"--state",
		"-H",
		"--host",
		"-M",
		"--machine",
		"-n",
		"--lines",
		"-o",
		"--output",
		"--root",
		"-s",
		"--signal",
		"--kill-whom",
		"--job-mode",
		"--what",
		"-f",
		"--format",
		"--filter",
		"--url",
		"--connection",
		"--log-level",
	}
)
_SYSTEMCTL_READ = frozenset(
	{
		"is-active",
		"is-enabled",
		"is-failed",
		"is-system-running",
		"status",
		"show",
		"cat",
		"list-units",
		"list-timers",
		"list-unit-files",
		"list-dependencies",
		"list-sockets",
		"list-jobs",
	}
)
# Lo que devolvería una unidad parada: determinista, no depende de la máquina.
_SYSTEMCTL_FIXED = {
	"is-active": ("inactive", 3),
	"is-enabled": ("disabled", 1),
	"is-failed": ("inactive", 1),
	"is-system-running": ("offline", 1),
	"status": ("", 3),
}
_SHOW_DEFAULTS = {"ActiveState": "inactive", "SubState": "dead", "LoadState": "not-found", "MainPID": "0", "MemoryCurrent": "[not set]"}
_JOURNALCTL_MUTATING = ("--vacuum", "--rotate", "--flush", "--sync", "--relinquish-var", "--smart-relinquish-var", "--setup-keys", "--update-catalog")
_CONTAINER_READ = frozenset({"ps", "inspect", "images", "info", "version", "logs", "stats", "top", "port", "exists"})
_CONTAINER_GROUPS = frozenset({"container", "image", "volume", "network", "pod", "system"})
_CONTAINER_GROUP_READ = frozenset({"ls", "list", "ps", "inspect", "exists", "df", "info"})


def _argv(args: object, shell: bool) -> List[str]:
	if isinstance(args, (str, bytes, os.PathLike)):
		text = os.fsdecode(args)
		if not shell:
			return [text]
		try:
			return shlex.split(text)
		except ValueError:
			return text.split()
	try:
		return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in args]  # type: ignore[union-attr]
	except TypeError:
		return []


def _verbs(rest: Sequence[str]) -> List[str]:
	"""Argumentos posicionales (verbo, unidad...) saltando opciones y sus valores."""
	out: List[str] = []
	skip = False
	for tok in rest:
		if skip:
			skip = False
			continue
		if tok.startswith("-"):
			skip = tok in _VALUE_OPTIONS
			continue
		out.append(tok)
	return out


def _show_properties(rest: Sequence[str]) -> List[str]:
	props: List[str] = []
	for i, tok in enumerate(rest):
		if tok.startswith("--property="):
			props += tok.split("=", 1)[1].split(",")
		elif tok.startswith("-p") and len(tok) > 2:
			props += tok[2:].split(",")
		elif tok in ("-p", "--property") and i + 1 < len(rest):
			props += rest[i + 1].split(",")
	return [p for p in props if p]


def _emulate(tool: str, rest: Sequence[str]) -> Tuple[str, str, int, bool]:
	"""→ (stdout, stderr, returncode, muta). Nunca ejecuta la herramienta real."""
	verbs = _verbs(rest)
	verb = verbs[0] if verbs else ""
	blocked = (f"[TEST ISOLATION] {tool} {verb} bloqueado en tests: mockéalo", 1)
	if tool == "systemctl":
		if verb not in _SYSTEMCTL_READ:
			return "", blocked[0], blocked[1], True
		if verb == "show":
			props = _show_properties(rest) or list(_SHOW_DEFAULTS)
			value_only = "--value" in rest
			out = "\n".join(_SHOW_DEFAULTS.get(p, "") if value_only else f"{p}={_SHOW_DEFAULTS.get(p, '')}" for p in props)
			rc = 0
		else:
			out, rc = _SYSTEMCTL_FIXED.get(verb, ("", 0))
		if "--quiet" in rest or "-q" in rest:
			out = ""
		return out, "", rc, False
	if tool == "journalctl":
		if any(tok.startswith(_JOURNALCTL_MUTATING) for tok in rest):
			return "", blocked[0], blocked[1], True
		return "", "", 0, False
	if tool in ("podman", "docker"):
		sub = verbs[1] if len(verbs) > 1 else ""
		read = verb in _CONTAINER_READ or (verb in _CONTAINER_GROUPS and sub in _CONTAINER_GROUP_READ)
		if not read:
			return "", blocked[0], blocked[1], True
		if "inspect" in (verb, sub):
			return "[]", "Error: no such object", 125, False
		if "exists" in (verb, sub):
			return "", "", 1, False
		return "", "", 0, False
	# systemd-run crea unidades transitorias: siempre muta.
	return "", blocked[0], blocked[1], True


_FAKE_SCRIPT = '[ -n "$1" ] && printf "%s\\n" "$1"; [ -n "$2" ] && printf "%s\\n" "$2" >&2; exit "$3"'


def host_command_substitute(args: object, shell: bool) -> Optional[List[str]]:
	"""argv sustituto (un sh que imita la respuesta) si `args` invoca una herramienta de host."""
	if _bypass:
		return None
	argv = _argv(args, shell)
	if not argv:
		return None
	tool, rest = os.path.basename(argv[0]), argv[1:]
	if tool in _SHELLS and "-c" in rest:
		idx = rest.index("-c")
		inner = _argv(rest[idx + 1], True) if idx + 1 < len(rest) else []
		if inner:
			tool, rest = os.path.basename(inner[0]), inner[1:]
	if tool not in _HOST_TOOLS:
		return None
	out, err, rc, mutating = _emulate(tool, rest)
	if mutating:
		_record("host", " ".join([tool, *rest]))
	return ["/bin/sh", "-c", _FAKE_SCRIPT, "rp-host-guard", out, err, str(rc)]


_orig_popen_init = subprocess.Popen.__init__


def _guarded_popen_init(self: subprocess.Popen, args: object, *a: object, **kw: object) -> None:
	shell = bool(kw.get("shell", False) or (len(a) > 7 and a[7]))
	substitute = host_command_substitute(args, shell)
	if substitute is not None:
		args = substitute
		kw.pop("shell", None)
		kw.pop("executable", None)
		if a:
			pos = list(a)
			if len(pos) > 1:
				pos[1] = None  # executable
			if len(pos) > 7:
				pos[7] = False  # shell
			a = tuple(pos)
	_orig_popen_init(self, args, *a, **kw)  # type: ignore[arg-type]


def install() -> None:
	"""Instala los parches de red y de comandos de host (idempotente)."""
	socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
	socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
	subprocess.Popen.__init__ = _guarded_popen_init  # type: ignore[method-assign]
