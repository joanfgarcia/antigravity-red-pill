#!/usr/bin/env python3
"""Dokimé — banco de pruebas aislado (RFC-HARNESS-001 · W2).

Subcomandos:

		dokime.py up         crea volúmenes, clona el repo DENTRO del volumen y arranca
		dokime.py down       para los contenedores (conserva volúmenes)
		dokime.py exec …     camino batch: `pi -p "<prompt>"` dentro del contenedor
		dokime.py shell      TUI de depuración (no es el camino medido)
		dokime.py net on|off enciende/apaga la salida a internet EN CALIENTE
		dokime.py preflight  ejecuta la puerta de aislamiento (dentro del contenedor)

Decisiones que este script materializa (ver DOKIME.md):

- **Clon, no worktree.** Un worktree comparte `.git` con el repo del Operador y
	permite reescribir sus refs (probado). Aquí se clona dentro del volumen y se
	comprueba que `--git-common-dir` cae dentro.
- **Sin compose.** El toggle de red en caliente (`network connect/disconnect`) no
	es expresable en compose, y la red es parte del contrato de aislamiento.
- **El modelo NO vive aquí.** `llama-server` corre en el host con GPU; el
	contenedor lo alcanza por una red interna (sin internet) en la IP del puente.
- **Sin secretos en la imagen.** Las claves se montan sólo con la red encendida.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUNTIME = os.getenv("DOKIME_RUNTIME", "podman")
IMAGE = os.getenv("DOKIME_IMAGE", "localhost/dokime:latest")
# Caja: cada alma vive en la suya (contenedores, volúmenes y red propios). El
# defecto sigue siendo Dokimé; `DOKIME_BOX=titanium` levanta otra casa igual.
BOX = os.getenv("DOKIME_BOX", "dokime").strip().lower()
NAME = BOX
QDRANT = f"{BOX}-qdrant"
VOLUME = f"{BOX}-state"
QDRANT_VOLUME = f"{BOX}-qdrant"
NET_INTERNAL = f"{BOX}-net"  # --internal: sin internet, sí host
NET_EGRESS = f"{BOX}-egress"  # sólo se conecta con `net on`


def _repo_root() -> str:
	"""Repositorio que se monta :ro: el de ESTE checkout (worktree incluido)."""
	explicit = os.getenv("DOKIME_SOURCE_REPO")
	if explicit:
		return explicit
	try:
		out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
		if out.returncode == 0 and out.stdout.strip():
			return out.stdout.strip()
	except Exception:  # noqa: BLE001
		pass
	# Último recurso: este checkout. Un literal `/home/<user>/...` ataba el
	# sandbox a la máquina del Operador y rompía en cualquier otro clon.
	return str(Path(__file__).resolve().parents[1])


SOURCE_REPO = _repo_root()
HOST_LLAMA_PORT = os.getenv("DOKIME_LLAMA_PORT", "11435")
# Clave del Qdrant del sandbox: NO es un secreto del Operador, es el token con el
# que SEC-CR-02 exige auth fuera de localhost. Vive sólo en `dokime-net`.
QDRANT_KEY = os.getenv("DOKIME_QDRANT_KEY", "dokime-local-only")

# ── modelo del banco ────────────────────────────────────────────────────────
# El servidor NO puede vivir en el host: la red del sandbox es `--internal` y no
# tiene ruta hacia él (comprobado: `host.containers.internal` da "Network is
# unreachable"). Corre como contenedor hermano en `dokime-net`.
LLAMA_NAME = f"{BOX}-llama"
LLAMA_MODEL = os.getenv("DOKIME_MODEL", os.path.expanduser("~/.local/share/red-pill/models/MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf"))
LLAMA_CTX = int(os.getenv("DOKIME_CTX", "16384"))
# CPU: hilos a usar. En GPU no manda (el trabajo va a las tarjetas) y se deja bajo
# para no robarle núcleos al Operador.
LLAMA_THREADS = int(os.getenv("DOKIME_THREADS", "8"))
# Cuantización del KV cache. q8_0 es el compromiso medido: en MiMo, q8_0 y q4_0
# dan la MISMA perplejidad que f16 (ratio 1.0002, +0.00%) y ahorran VRAM, que es
# lo que decide la ventana. f16 queda para comparar.
LLAMA_KV_TYPE = os.getenv("DOKIME_KV_TYPE", "q8_0")
LLAMA_GPU = os.getenv("DOKIME_GPU", "1") == "1"
LLAMA_IMAGE = os.getenv("DOKIME_LLAMA_IMAGE", "ghcr.io/ggml-org/llama.cpp:server-cuda" if LLAMA_GPU else "ghcr.io/ggml-org/llama.cpp:server")
LLAMA_ALIAS = os.getenv("DOKIME_LLAMA_ALIAS", "mimo")
# Spark (y otros con plantilla de razonamiento) gastan `max_tokens` pensando: el
# pase agéntico recibía respuestas truncadas y descartaba las notas. Con off, las
# notas salen completas (medido: 0 notas → 20 en la misma sesión).
# Spark razona por plantilla: sin algo de presupuesto habla peor. La ficha del modelo
# pide budget 256 (no más: con 2k se pasa el turno pensando).
LLAMA_REASONING = os.getenv("DOKIME_REASONING", "on").lower()
LLAMA_REASONING_BUDGET = int(os.getenv("DOKIME_REASONING_BUDGET", "256"))
# Un solo slot: el banco sirve a UN agente. Con 4 slots, llama.cpp reparte la KV y
# un Spark de 64k en 8 GB se queda sin margen (visto: segfault 139 al servir).
LLAMA_PARALLEL = int(os.getenv("DOKIME_PARALLEL", "1"))

# Compactación de pi: los defaults (reserveTokens 16384, keepRecentTokens 20000) son
# para ventanas enormes. Con 16k, el umbral queda en 0: no compacta, el prompt se pasa
# y cada reintento arrastra otro mensaje de usuario hasta el bucle.

MODELS_JSON = (
	"{\n"
	'  "$schema": "https://pi.dev/schemas/models.schema.json",\n'
	'  "providers": {\n'
	'    "local": {\n'
	'      "baseUrl": "http://llama:8080/v1",\n'
	'      "api": "openai-completions",\n'
	'      "apiKey": "dokime",\n'
	'      "models": [{ "id": "%s", "name": "sandbox %s" }]\n'
	"    }\n"
	"  }\n"
	"}\n"
) % (LLAMA_ALIAS, LLAMA_ALIAS)


def _embed_cache() -> str:
	"""Cache de embeddings del host (sólo pesos, `:ro`).

	Sin esto su `red-pill seed` no puede vectorizar y Dokimé se queda sin
	identidad: fastembed se bajaría el modelo de la red, que está cerrada. Se
	montan **pesos**, no estado: nada escribible, nada del Búnker del Operador.
	"""
	return os.getenv("DOKIME_EMBED_CACHE", os.path.expanduser("~/.local/share/red-pill/models"))


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
	print("+", " ".join(cmd))
	return subprocess.run(cmd, check=False, **kw)


def _is_running(name: str) -> bool:
	"""¿Está el contenedor ARRANCADO? `exists` no lo dice, y confundirlos cuesta caro.

	El 20-11 `up` dio "Dokimé arriba" con los contenedores en `Exited`: sólo miraba
	si existían, arrancaba el backend contra un contenedor muerto y devolvía éxito.
	"""
	out = subprocess.run([RUNTIME, "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
	return name in (out.stdout or "").split()


def _exists(kind: str, name: str) -> bool:
	return run([RUNTIME, kind, "exists", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def up(args: argparse.Namespace) -> int:
	if not _exists("network", NET_INTERNAL):
		run([RUNTIME, "network", "create", "--internal", NET_INTERNAL])
	if not _exists("network", NET_EGRESS):
		run([RUNTIME, "network", "create", NET_EGRESS])

	created = False
	if not _exists("container", NAME):
		created = True
		env = [
			"-e",
			"HOME=/srv/dokime/home",
			"-e",
			"IA_DIR=/srv/dokime/bunker",
			"-e",
			"XDG_DATA_HOME=/srv/dokime/xdg/data",
			"-e",
			"XDG_CONFIG_HOME=/srv/dokime/xdg/config",
			"-e",
			"XDG_STATE_HOME=/srv/dokime/xdg/state",
			"-e",
			"XDG_RUNTIME_DIR=/srv/dokime/xdg/run",
			"-e",
			"AGENT_CORE_DIR=/srv/dokime/desk",
			"-e",
			"RED_PILL_BACKUP_DIR=/srv/dokime/backups",
			"-e",
			"RP_TMP_DIR=/srv/dokime/tmp",
			"-e",
			"WORKTREES_ROOT=/srv/dokime/worktrees",
			"-e",
			"QDRANT_HOST=qdrant",
			"-e",
			"QDRANT_PORT=6333",
			"-e",
			f"QDRANT_API_KEY={QDRANT_KEY}",
			"-e",
			# La red es interna (sin egress): http es aquí el transporte correcto.
			# Sin esto, el cliente deriva https para un host no-local y Qdrant (sin TLS)
			# devuelve WRONG_VERSION_NUMBER.
			"QDRANT_SCHEME=http",
			"-e",
			# Embeddings sin red: pesos del host, sólo lectura. La imagen no trae el
			# modelo y el sandbox no tiene egress para bajarlo.
			"FASTEMBED_CACHE_PATH=/models",
			"-e",
			"EMBEDDING_LOCAL_FILES_ONLY=1",
			# El espacio vectorial es del alma, no del arnés: si su memoria se
			# escribió con otro modelo, hay que correr con ESE modelo o los
			# recuerdos existen y no significan.
			*(["-e", f"EMBEDDING_MODEL={os.getenv('DOKIME_EMBEDDING_MODEL')}"] if os.getenv("DOKIME_EMBEDDING_MODEL") else []),
			"-e",
			# Perfil local-9b: identidad mínima (tarjeta + reglas duras). `full`
			# mete ~4,2k chars de plantilla heredada que un 9B no necesita.
			f"REDPILL_IDENTITY_MODE={os.getenv('DOKIME_IDENTITY_MODE', 'low')}",
			"-e",
			# El distiller del memento (y cualquier consumidor de llm_endpoint) apunta
			# al modelo del sandbox, no al de 127.0.0.1:8760 del Operador.
			"MLX_LM_URL=http://llama:8080",
			"-e",
			# Memento: sus turnos de cola son la fuente. `pi` viene en
			# CHRONICLE_ARCHIVE_SOURCES (tiene chronicle propio, que aquí no existe)
			# y la fuente filtra por PREFIJO de provider: sin quitarlo, cero filas.
			'MEMENTO_SOURCES=["memory_queue"]',
			"-e",
			'CHRONICLE_ARCHIVE_SOURCES=["opencode","claude_code","antigravity"]',
			"-e",
			# Sin esto, la PERSONA del wake dice "Name: Agente" (default genérico) y el
			# modelo no se reconoce: el nombre de la instancia es configuración, no código.
			f"AGENT_NAME={os.getenv('DOKIME_AGENT_NAME', 'Dokimé' if BOX == 'dokime' else BOX.capitalize())}",
			"-e",
			"REDPILL_HARNESS=pi",
			"-e",
			"REDPILL_TESTING=1",
		]
		mounts = []
		cache = _embed_cache()
		if os.path.isdir(cache):
			mounts = ["-v", f"{cache}:/models:ro"]
		# Volúmenes extra por caja (DOKIME_EXTRA_MOUNTS="origen:destino[:ro],…").
		# Sirven para que un alma vea el árbol del proyecto (sin esconder que es
		# un worktree) y para un directorio compartido entre dos despachos.
		for spec in (os.getenv("DOKIME_EXTRA_MOUNTS") or "").split(","):
			spec = spec.strip()
			if spec:
				mounts += ["-v", spec]
		else:
			print(f"[dokime] aviso: no hay cache de embeddings en {cache}; el seed fallará (rc=3)", file=sys.stderr)
		run(
			[
				RUNTIME,
				"run",
				"-d",
				"--name",
				NAME,
				"--network-alias",
				NAME,
				# Directamente en la red interna: `none` + `connect` deja el
				# /etc/resolv.conf apuntando al DNS público y `qdrant` no resuelve.
				"--network",
				NET_INTERNAL,
				"-v",
				f"{VOLUME}:/srv/dokime",
				"-v",
				f"{SOURCE_REPO}:/src/red-pill:ro",
				*mounts,
				*env,
				IMAGE,
				# El backend es el proceso del CONTENEDOR, no un `podman exec`: lanzado
				# con exec -d moría a los minutos (la extensión hacía fail-open y el
				# agente se quedaba sin identidad). Con supervisor, si cae, vuelve.
				"sh",
				"-lc",
				"cd /src/red-pill && "
				"( while true; do PYTHONPATH=src /opt/py/bin/python -m red_pill.mcp_backend "
				"--socket /srv/dokime/xdg/data/red-pill/state/mcp.sock "
				">> /srv/dokime/tmp/backend.log 2>&1; sleep 2; done ) & wait",
			]
		)
		# estructura de estado (el volumen nace vacío)
		run(
			[
				RUNTIME,
				"exec",
				NAME,
				"sh",
				"-lc",
				# Sin llaves: `sh` es dash y NO expande `{a,b}` (creaba un directorio
				# literal `{home,xdg` y dejaba `tmp` sin existir).
				"mkdir -p /srv/dokime/home /srv/dokime/xdg/data /srv/dokime/xdg/config "
				"/srv/dokime/xdg/state /srv/dokime/xdg/run /srv/dokime/bunker "
				"/srv/dokime/backups /srv/dokime/tmp /srv/dokime/worktrees /srv/dokime/desk",
			]
		)

	qdrant_created = False
	if not _exists("container", QDRANT):
		qdrant_created = True
		run(
			[
				RUNTIME,
				"run",
				"-d",
				"--name",
				QDRANT,
				"--network",
				NET_INTERNAL,
				"--network-alias",
				"qdrant",
				"-v",
				f"{QDRANT_VOLUME}:/qdrant/storage",
				"-e",
				f"QDRANT__SERVICE__API_KEY={QDRANT_KEY}",
				"docker.io/qdrant/qdrant:v1.19.0",
			]
		)

	# Reanudar lo que ya existía pero está parado (un `down` deja `Exited`).
	if not created and not _is_running(NAME):
		run([RUNTIME, "start", NAME])
	if not qdrant_created and not _is_running(QDRANT):
		run([RUNTIME, "start", QDRANT])

	# Modelo: contenedor hermano en la red interna, pesos del host `:ro`.
	_start_llama()
	_write_models_json()
	_write_pi_settings()
	_start_backend()
	_write_mcp_json()

	print("\nDokimé arriba. Siguiente: `dokime.py preflight` (debe salir 0 antes de despertarla).")
	return 0


def _start_llama() -> None:
	"""Arranca (o reanuda) el servidor del modelo en `dokime-net`."""
	if _exists("container", LLAMA_NAME):
		run([RUNTIME, "start", LLAMA_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		print(f"+ modelo: {LLAMA_NAME} ya existe (reanudado)")
		return
	if not os.path.isfile(LLAMA_MODEL):
		print(f"[dokime] aviso: no existe el modelo {LLAMA_MODEL}; el bench no podrá correr", file=sys.stderr)
		return
	cmd = [
		RUNTIME,
		"run",
		"-d",
		"--name",
		LLAMA_NAME,
		"--network",
		NET_INTERNAL,
		"--network-alias",
		"llama",
		"-v",
		f"{LLAMA_MODEL}:/models/model.gguf:ro",
	]
	if LLAMA_GPU:
		# CDI (nvidia-container-toolkit). Sin él, el runtime falla y se ve en el log.
		cmd += ["--device", "nvidia.com/gpu=all"]
	cmd += [
		LLAMA_IMAGE,
		"-m",
		"/models/model.gguf",
		"--alias",
		LLAMA_ALIAS,
		"--host",
		"0.0.0.0",
		"--port",
		"8080",
		"-c",
		str(LLAMA_CTX),
		"-ctk",
		LLAMA_KV_TYPE,
		"-ctv",
		LLAMA_KV_TYPE,
		"-fa",
		"on",
		"-t",
		str(LLAMA_THREADS),
		"--jinja",
		"-np",
		str(LLAMA_PARALLEL),
		# Sin esto, el template conserva el razonamiento y se come `max_tokens`:
		# la respuesta llega con stopReason=length y contenido vacío.
		"--no-reasoning-preserve",
		*(
			["--reasoning", "on", "--reasoning-budget", str(LLAMA_REASONING_BUDGET)]
			if LLAMA_REASONING != "off"
			else ["--reasoning", "off", "--reasoning-budget", "0"]
		),
	]
	if LLAMA_GPU:
		cmd += ["-ngl", "99"]
	run(cmd)
	print(f"+ modelo: {LLAMA_ALIAS} ({'GPU' if LLAMA_GPU else 'CPU'}) en http://llama:8080/v1")


def _start_backend() -> None:
	"""Arranca el backend del hook dentro del sandbox (identidad por `/hook/context`).

	Sin él, la extensión hace *fail-open*: el turno sigue, pero **sin identidad**, y el
	agente acaba buscándose en ficheros (pasó el 19-11 con Joan). `setsid nohup` para
	que sobreviva al `exec` que lo lanza.
	"""
	socket = "/srv/dokime/xdg/data/red-pill/state/mcp.sock"
	# Se comprueba CONECTANDO al socket, no con `ps`: el grep por args fallaba y
	# reiniciaba el backend en cada `up`, tirando la identidad de una sesión viva.
	# Con el supervisor del contenedor hay carrera al arrancar: se le da margen antes
	# de lanzar un segundo backend.
	alive = None
	for _ in range(12):
		alive = run(
			[
				RUNTIME,
				"exec",
				NAME,
				"/opt/py/bin/python",
				"-c",
				f"import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect({socket!r})",
			],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
		if alive.returncode == 0:
			print("+ backend del hook: ya estaba vivo")
			return
		time.sleep(0.7)
	run(
		[
			RUNTIME,
			"exec",
			"-d",
			NAME,
			"sh",
			"-lc",
			f"rm -f {socket}; cd /src/red-pill && PYTHONPATH=src "
			f"setsid nohup /opt/py/bin/python -m red_pill.mcp_backend --socket {socket} "
			"> /srv/dokime/tmp/backend.log 2>&1 < /dev/null &",
		],
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)
	# No basta con lanzarlo: si el contenedor no está sano, el proceso muere y el
	# `up` devolvía éxito con el arnés sin identidad. Se confirma el socket.
	for _ in range(20):
		alive = run(
			[
				RUNTIME,
				"exec",
				NAME,
				"/opt/py/bin/python",
				"-c",
				f"import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect({socket!r})",
			],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
		if alive.returncode == 0:
			print("+ backend del hook: arrancado (identidad por /hook/context)")
			return
		time.sleep(0.5)
	print(
		"+ backend del hook: NO responde. Mira /srv/dokime/tmp/backend.log dentro del contenedor.",
		file=sys.stderr,
	)


def _effective_alias() -> str:
	"""(Alias REAL del servidor vivo). Si el contenedor ya existía, su `--alias` manda.

	Antes se escribía `models.json` con el alias del entorno y, si no se pasaba, caía al
	default (`mimo`) aunque el servidor sirviera `spark`: `pi` avisaba "model not found
	... using custom model id". Funcionaba igual, pero avisaba por una config mentirosa.
	"""
	out = subprocess.run([RUNTIME, "inspect", LLAMA_NAME, "--format", "{{json .Config.Cmd}}"], capture_output=True, text=True)
	if out.returncode == 0:
		try:
			cmd = json.loads(out.stdout or "[]")
			if "--alias" in cmd:
				i = cmd.index("--alias")
				if i + 1 < len(cmd):
					return str(cmd[i + 1])
		except Exception:  # noqa: BLE001 — cualquier fallo cae al env
			pass
	return LLAMA_ALIAS


def _write_models_json() -> None:
	"""`models.json` de pi con el alias REAL del servidor (idempotente)."""
	alias = _effective_alias()
	payload = {
		"$schema": "https://pi.dev/schemas/models.schema.json",
		"providers": {
			"local": {
				"baseUrl": "http://llama:8080/v1",
				"api": "openai-completions",
				"apiKey": "dokime",
				"models": [{"id": alias, "name": f"sandbox {alias}"}],
			}
		},
	}
	script = (
		"mkdir -p /srv/dokime/home/.pi/agent && cat > /srv/dokime/home/.pi/agent/models.json <<'JSON'\n"
		+ json.dumps(payload, ensure_ascii=False, indent=1)
		+ "\nJSON"
	)
	subprocess.run([RUNTIME, "exec", NAME, "sh", "-lc", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	print(f"+ pi: models.json → local/{alias} (http://llama:8080/v1)")


def _write_mcp_json() -> None:
	"""Conecta `pi` al backend MCP por el proxy (UDS).

	La exposición por defecto de `pi` es **codemode**: las tools no se declaran al
	modelo, se descubren desde script (`searchTools()`/`describeTool()`). Así el
	autodescubrimiento es real y no cuesta esquemas en el prompt.
	"""
	payload = {
		"mcpServers": {
			"redpill": {
				"command": "/opt/py/bin/python",
				"args": [
					"-m",
					"red_pill.mcp_proxy",
					"--socket",
					"/srv/dokime/xdg/data/red-pill/state/mcp.sock",
				],
				"env": {"PYTHONPATH": "/src/red-pill/src"},
				"description": "Memoria, sesiones, trabajos y coro del Búnker",
				# El resto va por codemode (no se declara); la pareja de puerta se declara
				# porque un 4B no escribe scripts para descubrir herramientas.
				"exposure": "codemode",
				"toolExposure": {"redpill_search": "direct", "redpill_call": "direct"},
			}
		}
	}
	script = "cat > /srv/dokime/home/.pi/agent/mcp.json <<'JSON'\n" + json.dumps(payload, ensure_ascii=False, indent=1) + "\nJSON"
	subprocess.run([RUNTIME, "exec", NAME, "sh", "-lc", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	print("+ pi: mcp.json → redpill (proxy UDS, exposición codemode)")


def _pi_settings() -> str:
	"""Compactación dimensionada a la ventana servida (no a los defaults de pi).

	Con 16k: reserve 2k / keep ~5k. Con 64k: 8k / ~21k. Regla explícita:
	reserve = ctx/8, keep = ctx/3.
	"""
	reserve = max(2048, LLAMA_CTX // 8)
	keep = max(4000, LLAMA_CTX // 3)
	return f'{{\n  "compaction": {{\n    "enabled": true,\n    "reserveTokens": {reserve},\n    "keepRecentTokens": {keep}\n  }}\n}}\n'


def _write_pi_settings() -> None:
	"""Compactación dimensionada a la ventana servida (16k), no a los defaults de pi."""
	script = "cat > /srv/dokime/home/.pi/agent/settings.json <<'JSON'\n" + _pi_settings() + "JSON"
	subprocess.run([RUNTIME, "exec", NAME, "sh", "-lc", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	print(f"+ pi: settings.json (compactación {LLAMA_CTX}: reserve {max(2048, LLAMA_CTX // 8)}, keep {max(4000, LLAMA_CTX // 3)})")


def down(_: argparse.Namespace) -> int:
	for c in (NAME, QDRANT, LLAMA_NAME):
		run([RUNTIME, "stop", c], stdout=subprocess.DEVNULL)
	print(f"parados; volúmenes conservados (borra con: podman volume rm {VOLUME} {QDRANT_VOLUME})")
	return 0


def exec_(args: argparse.Namespace) -> int:
	prompt = " ".join(args.prompt)
	cmd = [RUNTIME, "exec", "-i", NAME, "pi", "-p", prompt]
	return run(cmd).returncode


def shell(_: argparse.Namespace) -> int:
	print("TUI de depuración — NO es el camino medido (usa `exec`)")
	return run([RUNTIME, "exec", "-it", NAME, "bash"]).returncode


def net(args: argparse.Namespace) -> int:
	if args.state == "on":
		run([RUNTIME, "network", "connect", NET_EGRESS, NAME])
		print("egress ON (claves cloud: montar a mano si se necesitan)")
	else:
		run([RUNTIME, "network", "disconnect", NET_EGRESS, NAME], stdout=subprocess.DEVNULL)
		print("egress OFF")
	return 0


def preflight(_: argparse.Namespace) -> int:
	return run([RUNTIME, "exec", "-i", NAME, "/opt/py/bin/python", "/src/red-pill/deploy/dokime/preflight.py"]).returncode


def main() -> int:
	ap = argparse.ArgumentParser(description="Dokimé — banco de pruebas aislado")
	sub = ap.add_subparsers(dest="cmd", required=True)
	sub.add_parser("up")
	sub.add_parser("down")
	sub.add_parser("shell")
	p = sub.add_parser("exec")
	p.add_argument("prompt", nargs=argparse.REMAINDER)
	n = sub.add_parser("net")
	n.add_argument("state", choices=["on", "off"])
	sub.add_parser("preflight")
	args = ap.parse_args()
	return {"up": up, "down": down, "exec": exec_, "shell": shell, "net": net, "preflight": preflight}[args.cmd](args)


if __name__ == "__main__":
	sys.exit(main())
