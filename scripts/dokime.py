#!/usr/bin/env python3
"""Dokimé — banco de pruebas aislado (RFC-HARNESS-001 · W2).

Subcomandos:

		dokime.py up         crea volúmenes, clona el repo DENTRO del volumen y arranca
		dokime.py down       para los contenedores (conserva volúmenes)
		dokime.py exec …     camino batch: `pi -p "<prompt>"` dentro del contenedor
		dokime.py shell      TUI de depuración (no es el camino medido)
		dokime.py net on|off enciende/apaga la salida a internet EN CALIENTE
		dokime.py preflight  ejecuta la puerta de aislamiento (dentro del contenedor)
		dokime.py status     radiografía: cajas, kernel montado, sha, desk
		dokime.py update     actualiza el kernel del banco y re-siembra (ver abajo)
		dokime.py desk …     intercambio con el alma: `path`, `ls`, `put`, `get`

`update` es el que mantiene el banco al día: sincroniza el **worktree dedicado**
que se monta `:ro` en `/src/red-pill`, recrea el contenedor si sus montajes se
quedaron viejos, y re-siembra la identidad (`red-pill seed` + anclas de pi) para
que el alma no arranque con textos de la versión anterior. `up` re-siembra
también, salvo `--no-seed`: es idempotente y es lo que garantiza que un arranque
nunca mida semillas viejas.

El **desk** (`AGENT_CORE_DIR`) es ahora un directorio del HOST montado en
`/srv/dokime/desk`: lo que el alma escriba se lee desde aquí, y lo que dejes en
`desk/inbox` lo ve dentro. `desk put/get` son atajos de copia; no hace falta.

Decisiones que este script materializa (ver DOKIME.md):

- **Worktree dedicado, no el checkout del Operador.** El kernel que se mide es
	un worktree propio (`~/.local/share/dokime/kernel/<caja>`) que `update`
	sincroniza. Se monta SIEMPRE `:ro`, que es lo que impide reescribir refs del
	repo del Operador: `preflight` verifica que `.git` no sea escribible dentro.
	Sin worktree creado, se sigue montando este checkout (comportamiento legado).
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
import shutil
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

# ── kernel del banco: el árbol que se mide y se actualiza ───────────────────
# Un worktree propio, no el checkout del Operador: así `update` puede moverlo de
# rama sin tocar el despacho, y el montaje `:ro` impide reescribir sus refs
# (preflight lo verifica dentro del contenedor).
KERNEL_WORKTREE = Path(os.path.expanduser(os.getenv("DOKIME_KERNEL_WORKTREE") or f"~/.local/share/dokime/kernel/{BOX}"))
KERNEL_REF = os.getenv("DOKIME_KERNEL_REF", "next")

# ── desk: el despacho del alma, en el HOST (intercambio con el Operador) ────
DESK_HOST = Path(os.path.expanduser(os.getenv("DOKIME_DESK") or f"~/.local/share/dokime/desk/{BOX}"))
DESK_MOUNT = "/srv/dokime/desk"  # == AGENT_CORE_DIR dentro de la caja
# Subdirectorios del intercambio: lo que el Operador deja en `inbox`, el alma lo
# lee; lo que ella produce y quiere devolver, va a `outbox`.
DESK_INBOX = "inbox"
DESK_OUTBOX = "outbox"

# Config con la que se creó cada caja. Recrear con el entorno del momento perdería
# el modelo, la ventana, el alias o los montajes extra; con esto, `update
# --recreate` reconstruye la MISMA caja y el Operador sólo declara lo nuevo.
BOX_STATE = Path(os.path.expanduser(f"~/.local/share/dokime/boxes/{BOX}.json"))

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
	# Sin `run()`: esto se llama en bucles de diagnóstico y el "+ podman…" de cada
	# comprobación convertía `status` en ruido.
	return subprocess.run([RUNTIME, kind, "exists", name], capture_output=True, check=False).returncode == 0


# ── kernel del banco (worktree dedicado, montado :ro) ───────────────────────


def _git(*args: str, cwd: object = None) -> subprocess.CompletedProcess:
	"""`git` silencioso: estas rutas informan por su propio mensaje, no por el ruido."""
	return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)


def _is_kernel_worktree() -> bool:
	return (KERNEL_WORKTREE / ".git").exists() and _git("rev-parse", "--is-inside-work-tree", cwd=KERNEL_WORKTREE).stdout.strip() == "true"


def _kernel_source() -> str:
	"""Árbol que entra en `/src/red-pill`: el worktree del banco si existe, si no este checkout.

	Se mantiene el comportamiento legado (montar el checkout del Operador) para no
	romper una caja ya levantada; `update` es el que crea el worktree dedicado. Un
	`DOKIME_SOURCE_REPO` explícito manda siempre: es una chincheta, no un default.
	"""
	if os.getenv("DOKIME_SOURCE_REPO"):
		return SOURCE_REPO
	if _is_kernel_worktree():
		return str(KERNEL_WORKTREE)
	return SOURCE_REPO


def _kernel_state() -> dict | None:
	"""sha, ref y suciedad del worktree del banco. `None` si aún no existe."""
	if not _is_kernel_worktree():
		return None
	sha = _git("rev-parse", "HEAD", cwd=KERNEL_WORKTREE).stdout.strip()
	ref = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=KERNEL_WORKTREE).stdout.strip()
	dirty = bool(_git("status", "--porcelain", cwd=KERNEL_WORKTREE).stdout.strip())
	return {"sha": sha, "ref": ref, "dirty": dirty}


def _inspect(name: str) -> dict:
	"""`podman inspect` como dict (primer elemento). `{}` si no existe o falla."""
	out = subprocess.run([RUNTIME, "inspect", name], capture_output=True, text=True, check=False)
	if out.returncode != 0:
		return {}
	try:
		data = json.loads(out.stdout or "[]")
		return data[0] if data else {}
	except Exception:  # noqa: BLE001
		return {}


def _mounts_of(name: str) -> dict:
	"""Montajes del contenedor indexados por destino. `{}` si no existe o falla."""
	out = subprocess.run([RUNTIME, "inspect", name, "--format", "{{json .Mounts}}"], capture_output=True, text=True, check=False)
	if out.returncode != 0 or not (out.stdout or "").strip():
		return {}
	try:
		return {m.get("Destination"): m for m in json.loads(out.stdout) if isinstance(m, dict)}
	except Exception:  # noqa: BLE001 — un inspect raro no debe tumbar el diagnóstico
		return {}


def _mounts_need_refresh() -> list[str]:
	"""Motivos por los que la caja vigente NO apunta ya a lo que toca (lista vacía = bien).

	Los montajes se congelan al crear el contenedor: actualizar el worktree o mover
	el desk sin recrear la caja deja al alma leyendo el árbol viejo, y el bench
	mediría una versión que ya no es. Se compara SIEMPRE por ruta real.
	"""
	if not _exists("container", NAME):
		return []
	mounts = _mounts_of(NAME)
	reasons: list[str] = []
	kernel = mounts.get("/src/red-pill")
	if kernel is None:
		reasons.append("/src/red-pill no está montado")
	elif os.path.realpath(kernel.get("Source") or "") != os.path.realpath(_kernel_source()):
		reasons.append(f"/src/red-pill apunta a {kernel.get('Source')} y debería a {_kernel_source()}")
	desk = mounts.get(DESK_MOUNT)
	if desk is None:
		reasons.append(f"{DESK_MOUNT} no está montado (el desk vive dentro del volumen, no en el host)")
	elif os.path.realpath(desk.get("Source") or "") != os.path.realpath(DESK_HOST):
		reasons.append(f"{DESK_MOUNT} apunta a {desk.get('Source')} y debería a {DESK_HOST}")
	return reasons


def _host_uid_in(mappings: dict, uid: int) -> int | None:
	"""Traduce un uid del CONTENEDOR al uid del HOST según el mapa de podman.

	Rootless sin `keep-id`: el root del contenedor es el Operador y el resto cae
	en los subuids (100000+). En la imagen, `dokime` es uid 1001 — no 1000: el
	`node:22-slim` ya gastó el 1000 con el usuario `node`.
	"""
	if uid == 0:
		return os.getuid()
	for entry in mappings.get("uidmap") or []:
		start = int(entry.get("container_id", 0))
		size = int(entry.get("size", 0))
		if start <= uid < start + size:
			return int(entry.get("host_id", 0)) + (uid - start)
	return None


def _agent_uid_on_host() -> int | None:
	"""uid del alma traducido al host. `None` si no hay caja viva o no se puede saber."""
	if not _is_running(NAME):
		return None
	out = subprocess.run([RUNTIME, "exec", NAME, "id", "-u"], capture_output=True, text=True, check=False)
	if out.returncode != 0:
		return None
	try:
		uid = int((out.stdout or "").strip())
	except ValueError:
		return None
	maps = subprocess.run([RUNTIME, "info", "--format", "{{json .Host.IDMappings}}"], capture_output=True, text=True, check=False)
	try:
		return _host_uid_in(json.loads(maps.stdout or "{}"), uid)
	except Exception:  # noqa: BLE001 — sin mapa no se concede nada, no se adivina
		return None


def _grant_desk_acl() -> None:
	"""Que cada lado pueda REESCRIBIR lo que crea el otro, no sólo crear y borrar.

	`0777` en el directorio permite crear/borrar, pero un `>` sobre un fichero
	ajeno exige permiso en el fichero. Las entradas ACL por defecto hacen que lo
	que nazca en el desk —de cualquiera de los dos lados— traiga permiso del otro.
	"""
	uid = _agent_uid_on_host()
	if uid is None or uid == os.getuid():
		return
	for path in (DESK_HOST, DESK_HOST / DESK_INBOX, DESK_HOST / DESK_OUTBOX):
		if not path.is_dir():
			continue
		result = subprocess.run(
			["setfacl", "-m", f"u:{uid}:rwx,d:u:{uid}:rwx,d:u:{os.getuid()}:rwx", str(path)],
			capture_output=True,
			text=True,
			check=False,
		)
		if result.returncode != 0:
			print(
				f"[dokime] aviso: {path} sin ACL ({result.stderr.strip() or 'setfacl no disponible'}); "
				"el alma no podrá reescribir en sitio los ficheros del host",
				file=sys.stderr,
			)
			return


def _ensure_desk() -> None:
	"""Crea el despacho del host con sus dos buzones. Idempotente.

	Permisos: en podman rootless el usuario del alma (uid 1001 en la imagen) mapea
	a OTRO uid del host (`100000 + 1001 - 1`), así que un `0775` del Operador deja
	al alma sin poder escribir. El desk se abre a `0777` a propósito: es un
	directorio de intercambio entre dos identidades que no comparten uid. Los
	ficheros conservan su dueño; cada lado lee todo y crea/borra lo suyo (o lo del
	otro, que es justo lo que pide un buzón). `_grant_desk_acl` añade lo que falta:
	que un fichero nacido de un lado se pueda reescribir desde el otro.
	"""
	for sub in ("", DESK_INBOX, DESK_OUTBOX):
		path = DESK_HOST / sub
		path.mkdir(parents=True, exist_ok=True)
		try:
			os.chmod(path, 0o777)
		except OSError as exc:  # noqa: BLE001 — un chmod imposible se avisa, no se aborta
			print(f"[dokime] aviso: no se pudo abrir {path} al alma: {exc}", file=sys.stderr)


def _box_config() -> dict:
	"""Config resuelta de la caja, tal como se usó para crearla."""
	return {
		"model": LLAMA_MODEL,
		"ctx": LLAMA_CTX,
		"alias": LLAMA_ALIAS,
		"kv_type": LLAMA_KV_TYPE,
		"gpu": LLAMA_GPU,
		"threads": LLAMA_THREADS,
		"reasoning": LLAMA_REASONING,
		"reasoning_budget": LLAMA_REASONING_BUDGET,
		"parallel": LLAMA_PARALLEL,
		"identity_mode": os.getenv("DOKIME_IDENTITY_MODE", "minimal"),
		# `role`: qué reglas/skills se siembran (RFC-HARNESS-001). `none` es la
		# instalación estándar sin rol; Dokimé nace con `worker` y su identidad mínima.
		"role": os.getenv("DOKIME_ROLE", "none"),
		"capability": os.getenv("DOKIME_CAPABILITY", "local-4b-64k"),
		"egress": os.getenv("DOKIME_EGRESS", "none"),
		"agent_name": os.getenv("DOKIME_AGENT_NAME", "Dokimé" if BOX == "dokime" else BOX.capitalize()),
		"embedding_model": os.getenv("DOKIME_EMBEDDING_MODEL") or "",
		"extra_mounts": os.getenv("DOKIME_EXTRA_MOUNTS") or "",
		"embed_cache": _embed_cache(),
		"anchor_mode": os.getenv("DOKIME_ANCHOR_MODE", "auto"),
	}


def _save_box_config() -> None:
	"""Apunta la config con la que quedó la caja (para recrearla igual)."""
	try:
		BOX_STATE.parent.mkdir(parents=True, exist_ok=True)
		BOX_STATE.write_text(json.dumps(_box_config(), ensure_ascii=False, indent=1), encoding="utf-8")
	except Exception as exc:  # noqa: BLE001 — informar nunca debe tumbar el arranque
		print(f"[dokime] aviso: no se pudo guardar la config de la caja: {exc}", file=sys.stderr)


def _adopt_box_config() -> None:
	"""Recupera la config de la caja para reconstruirla igual (`update --recreate`).

	Lo que el Operador haya exportado AHORA manda; lo guardado sólo rellena lo que
	no declaró. Sin esto, recrear Titanium con el entorno vacío la dejaría con el
	modelo de Dokimé y sin sus montajes extra.
	"""
	if not BOX_STATE.is_file():
		return
	try:
		saved = json.loads(BOX_STATE.read_text(encoding="utf-8"))
	except Exception as exc:  # noqa: BLE001
		print(f"[dokime] aviso: config de caja ilegible ({BOX_STATE}): {exc}", file=sys.stderr)
		return
	global LLAMA_MODEL, LLAMA_CTX, LLAMA_ALIAS, LLAMA_KV_TYPE, LLAMA_GPU
	global LLAMA_THREADS, LLAMA_REASONING, LLAMA_REASONING_BUDGET, LLAMA_PARALLEL
	if "DOKIME_MODEL" not in os.environ and saved.get("model"):
		LLAMA_MODEL = saved["model"]
	if "DOKIME_CTX" not in os.environ and saved.get("ctx"):
		LLAMA_CTX = int(saved["ctx"])
	if "DOKIME_LLAMA_ALIAS" not in os.environ and saved.get("alias"):
		LLAMA_ALIAS = saved["alias"]
	if "DOKIME_KV_TYPE" not in os.environ and saved.get("kv_type"):
		LLAMA_KV_TYPE = saved["kv_type"]
	if "DOKIME_GPU" not in os.environ and "gpu" in saved:
		LLAMA_GPU = bool(saved["gpu"])
	if "DOKIME_THREADS" not in os.environ and saved.get("threads"):
		LLAMA_THREADS = int(saved["threads"])
	if "DOKIME_REASONING" not in os.environ and saved.get("reasoning"):
		LLAMA_REASONING = str(saved["reasoning"])
	if "DOKIME_REASONING_BUDGET" not in os.environ and saved.get("reasoning_budget") is not None:
		LLAMA_REASONING_BUDGET = int(saved["reasoning_budget"])
	if "DOKIME_PARALLEL" not in os.environ and saved.get("parallel"):
		LLAMA_PARALLEL = int(saved["parallel"])
	# Variables que se leen con `os.getenv` al montar/crear: se rellenan en el
	# entorno del proceso para que el resto del código no sepa de dónde vienen.
	for key, value in (
		("DOKIME_IDENTITY_MODE", saved.get("identity_mode")),
		("DOKIME_ROLE", saved.get("role")),
		("DOKIME_AGENT_NAME", saved.get("agent_name")),
		("DOKIME_EMBEDDING_MODEL", saved.get("embedding_model") or None),
		("DOKIME_EXTRA_MOUNTS", saved.get("extra_mounts") or None),
		("DOKIME_ANCHOR_MODE", saved.get("anchor_mode")),
	):
		if key not in os.environ and value:
			os.environ[key] = str(value)


def _import_box_config() -> bool:
	"""Deriva la config de una caja creada ANTES de que existiera el snapshot.

	Las cajas de los bancos ya existen (Dokimé con Spark, Titanium con MiMo) y no
	tienen config apuntada: recrearlas con los defaults las cambiaría en silencio.
	Se lee del servidor del modelo (Cmd + montajes) y del entorno del alma.
	Devuelve True si dejó un snapshot utilizable.
	"""
	if BOX_STATE.is_file() or not _exists("container", LLAMA_NAME):
		return BOX_STATE.is_file()
	llama = _inspect(LLAMA_NAME)
	cmd = [str(x) for x in (llama.get("Config") or {}).get("Cmd") or []]

	def flag(name: str, default: object = None) -> object:
		return cmd[cmd.index(name) + 1] if name in cmd and cmd.index(name) + 1 < len(cmd) else default

	model = next((m.get("Source") for m in llama.get("Mounts") or [] if m.get("Destination") == "/models/model.gguf"), "")
	image = str(llama.get("ImageName") or (llama.get("Config") or {}).get("Image") or "")
	alma = _inspect(NAME)
	env = dict(item.split("=", 1) for item in (alma.get("Config") or {}).get("Env") or [] if "=" in item)
	extra = [
		f"{m.get('Source')}:{m.get('Destination')}{'' if m.get('RW') else ':ro'}"
		for m in alma.get("Mounts") or []
		if m.get("Destination") not in ("/srv/dokime", "/src/red-pill", "/models", DESK_MOUNT) and m.get("Source")
	]
	cfg = {
		"model": model or LLAMA_MODEL,
		"ctx": int(flag("-c", LLAMA_CTX) or LLAMA_CTX),
		"alias": str(flag("--alias", LLAMA_ALIAS)),
		"kv_type": str(flag("-ctk", LLAMA_KV_TYPE)),
		"gpu": "cuda" in image.lower(),
		"threads": int(flag("-t", LLAMA_THREADS) or LLAMA_THREADS),
		"reasoning": str(flag("--reasoning", LLAMA_REASONING)),
		"reasoning_budget": int(flag("--reasoning-budget", LLAMA_REASONING_BUDGET) or LLAMA_REASONING_BUDGET),
		"parallel": int(flag("-np", LLAMA_PARALLEL) or LLAMA_PARALLEL),
		"identity_mode": env.get("REDPILL_IDENTITY_MODE", "minimal"),
		"role": env.get("REDPILL_ROLE", "none"),
		"capability": env.get("REDPILL_CAPABILITY", "local-4b-64k"),
		"egress": env.get("REDPILL_EGRESS", "none"),
		"agent_name": env.get("AGENT_NAME", "Dokimé" if BOX == "dokime" else BOX.capitalize()),
		"embedding_model": env.get("EMBEDDING_MODEL", ""),
		"extra_mounts": ",".join(extra),
		"embed_cache": next((m.get("Source") for m in alma.get("Mounts") or [] if m.get("Destination") == "/models"), _embed_cache()),
		"anchor_mode": "auto",
	}
	try:
		BOX_STATE.parent.mkdir(parents=True, exist_ok=True)
		BOX_STATE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
	except Exception as exc:  # noqa: BLE001
		print(f"[dokime] aviso: no se pudo apuntar la config heredada: {exc}", file=sys.stderr)
		return False
	print(f"+ config de la caja importada desde {LLAMA_NAME} → {BOX_STATE}")
	return True


def _sync_kernel(ref: str, fetch: bool, force: bool, dry_run: bool) -> tuple[str | None, str | None]:
	"""Crea o mueve el worktree del banco a `ref`. Devuelve (sha_antes, sha_después)."""
	before = (_kernel_state() or {}).get("sha")
	if dry_run:
		print(f"[dry-run] kernel: {KERNEL_WORKTREE} → {ref} (antes: {before[:8] if before else 'sin worktree'})")
		return before, before
	KERNEL_WORKTREE.parent.mkdir(parents=True, exist_ok=True)
	if fetch:
		run(["git", "fetch", "--all", "--prune"], cwd=SOURCE_REPO)
	if not _is_kernel_worktree():
		# `--detach`: el bench no debe tener ramas checkouteadas (git no deja
		# compartir una rama entre worktrees, y aquí la rama la mueve el Operador).
		r = _git("worktree", "add", "--detach", str(KERNEL_WORKTREE), ref, cwd=SOURCE_REPO)
		if r.returncode != 0:
			raise SystemExit(f"no se pudo crear el worktree del banco: {r.stderr.strip() or r.stdout.strip()}")
	else:
		state = _kernel_state() or {}
		if state.get("dirty") and not force:
			raise SystemExit(
				f"el worktree del banco tiene cambios sin commitear ({KERNEL_WORKTREE}).\nPásalos a un commit, o descártalos con `--force`."
			)
		r = _git("switch", "--detach", ref, cwd=KERNEL_WORKTREE)
		if r.returncode != 0:
			raise SystemExit(f"no se pudo mover el worktree a {ref}: {r.stderr.strip() or r.stdout.strip()}")
	after = (_kernel_state() or {}).get("sha")
	return before, after


def _reseed() -> None:
	"""Re-siembra el alma desde las semillas del kernel: memoria + anclas del arnés.

	Sin esto, actualizar el árbol cambia los textos que la identidad lee pero el
	alma sigue con los engramas viejos en su Qdrant: mediría otra época. Es
	idempotente (`seed_project` garantiza el génesis y no duplica).
	"""
	if not _is_running(NAME):
		print(f"[dokime] aviso: {NAME} está parada; no re-siembro (arranca con `up`)", file=sys.stderr)
		return
	print("+ Búnker: re-sembrando desde las semillas del kernel")
	if run([RUNTIME, "exec", NAME, "red-pill", "seed"]).returncode != 0:
		print("[dokime] aviso: `red-pill seed` falló; el alma puede arrancar con semillas viejas", file=sys.stderr)

	# Identidad: la tarjeta del repo entra en `ID_IDENTITY` y los pactos se borran.
	# Sin este paso, actualizar el árbol no cambia lo que el alma lee de sí misma
	# (pasó con la tarjeta mínima de b159c19: se quedó en el repo, no en su Qdrant).
	print("+ identidad: fijando la tarjeta en ID_IDENTITY")
	if (
		run(
			[
				RUNTIME,
				"exec",
				NAME,
				"/opt/py/bin/python",
				"/src/red-pill/scripts/dokime_boot.py",
				"--workspace",
				"/srv/dokime",
				"--no-card",
			]
		).returncode
		!= 0
	):
		print("[dokime] aviso: no se pudo fijar la identidad; el alma puede presentarse con la tarjeta vieja", file=sys.stderr)

	# Anclas: el rol decide el juego (RFC-HARNESS-001). `identity_mode=minimal`
	# manda por encima del rol —un 4B no sostiene siete protocolos— y `role=none`
	# es la instalación estándar (roster completo). Se siembra una sola vez con
	# `--prune-unlisted`: el rol vigente sustituye al anterior, no se acumula.
	identity_mode = os.getenv("DOKIME_IDENTITY_MODE", "minimal")
	role = os.getenv("DOKIME_ROLE", "none")
	blocks: list[str] | None = ["minimal"] if identity_mode == "minimal" else None
	if blocks is None and role not in ("", "none", "standard"):
		try:
			sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
			from red_pill.harness.profile import resolve  # noqa: PLC0415 — import perezoso a propósito

			bundle = resolve(role, os.getenv("DOKIME_CAPABILITY", "local-4b-64k"), os.getenv("DOKIME_EGRESS", "none"))
			blocks = list(bundle.rules_blocks) or None
			print(f"+ rol: {bundle.role} × {bundle.capability} × {bundle.egress} → anclas: {', '.join(blocks or ['(roster completo)'])}")
		except Exception as exc:  # noqa: BLE001 — un perfil inválido no debe tumbar la caja
			print(f"[dokime] aviso: perfil `{role}` no resuelto ({exc}); se siembra el roster completo", file=sys.stderr)
	print("+ arnés: anclas de pi (AGENTS.override.md + skills)")
	_anchor = [RUNTIME, "exec", NAME, "/opt/py/bin/python", "/src/red-pill/scripts/inject_anchor.py", "--ide", "pi", "--workspace", "/srv/dokime"]
	_cmd = [*_anchor, "--mode", os.getenv("DOKIME_ANCHOR_MODE", "auto"), "--update", "--prune-unlisted"]
	if blocks:
		_cmd += ["--anchor", ",".join(blocks)]
	if run(_cmd).returncode != 0:
		print("[dokime] aviso: la inyección de anclas falló (revisa el log de arriba)", file=sys.stderr)


def up(args: argparse.Namespace) -> int:
	_adopt_box_config()
	_ensure_desk()
	if not _is_kernel_worktree():
		print(
			f"[dokime] aviso: no hay worktree del banco en {KERNEL_WORKTREE}; se monta este checkout.\n"
			"          `dokime.py update` crea uno dedicado y lo mantiene al día.",
			file=sys.stderr,
		)
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
			f"REDPILL_IDENTITY_MODE={os.getenv('DOKIME_IDENTITY_MODE', 'minimal')}",
			"-e",
			# Rol del arnés (RFC-HARNESS-001): qué anclas/skills se siembran. `none`
			# es la instalación estándar sin rol. No particiona la memoria: Dokimé
			# sigue siendo Dokimé con cualquier rol.
			f"REDPILL_ROLE={os.getenv('DOKIME_ROLE', 'none')}",
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
		# El desk del alma, en el HOST: es el intercambio con el Operador. Se monta
		# encima del directorio del volumen (`/srv/dokime/desk`), que queda
		# sombreado; el resto del estado sigue viviendo en el volumen.
		mounts += ["-v", f"{DESK_HOST}:{DESK_MOUNT}"]
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
				f"{_kernel_source()}:/src/red-pill:ro",
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
	# Sólo se apunta la config si la caja se ha creado ahora: si ya existía, la
	# verdad está en el contenedor y `_import_box_config` la leerá de allí.
	if created or BOX_STATE.is_file():
		_save_box_config()
	# El desk ya tiene contenedor vivo: se conceden las ACL cruzadas.
	_grant_desk_acl()

	# Re-siembra: un arranque nunca debe medir semillas de la versión anterior.
	if getattr(args, "seed", True):
		_reseed()
	else:
		print("+ semillas: omitidas (--no-seed)")

	print(f"\nDokimé arriba. Kernel: {_kernel_source()}")
	print(f"Desk del alma (host): {DESK_HOST}")
	print("Siguiente: `dokime.py preflight` (debe salir 0 antes de despertarla).")
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
		# La imagen se resuelve AQUÍ, no en el import: `--recreate` puede adoptar
		# `gpu` de la config guardada de la caja y quedaría una cuda sin --device.
		os.getenv("DOKIME_LLAMA_IMAGE") or ("ghcr.io/ggml-org/llama.cpp:server-cuda" if LLAMA_GPU else "ghcr.io/ggml-org/llama.cpp:server"),
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


def chat(args: argparse.Namespace) -> int:
	"""Sesión interactiva con el alma: la TUI de pi dentro del sandbox.

	`exec` sigue siendo el camino medido (un turno, sin estado); esto es para
	hablar y mirar. La identidad y las tools llegan por el hook, igual que en
	batch: no hay una versión "de verdad" más que otra.
	"""
	extra = list(getattr(args, "args", None) or [])
	print(f"Sesión interactiva con {NAME}. Sal con Ctrl-D." + (" Continuando la última." if "-c" in extra else ""))
	return run([RUNTIME, "exec", "-it", NAME, "pi", *extra]).returncode


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


def update(args: argparse.Namespace) -> int:
	"""Mantiene el banco al día: kernel, montajes y semillas.

	Orden importa. Primero se mueve el árbol (es lo que se va a medir), luego se
	comprueba si la caja vigente sigue apuntando a él (los montajes se congelan al
	crear el contenedor) y sólo entonces se re-siembra: sembrar un alma que lee
	otro árbol sería sembrar la versión equivocada.
	"""
	_ensure_desk()
	_import_box_config()
	_grant_desk_acl()
	print(f"kernel: {KERNEL_WORKTREE} (ref {args.ref})")
	before, after = _sync_kernel(args.ref, args.fetch, args.force, args.dry_run)
	if after:
		cambio = "sin cambios" if before == after else "actualizado"
		print(f"+ kernel: {after[:12]} ({cambio})")

	reasons = _mounts_need_refresh()
	if args.dry_run:
		if reasons:
			print("[dry-run] recrearía la caja: " + "; ".join(reasons))
		else:
			print("[dry-run] montajes al día: no recrearía la caja")
		return 0

	if reasons and not args.recreate:
		# Los montajes se congelan al crear el contenedor. Recrear arranca la caja
		# (y con ella el modelo en GPU), así que no se hace a traición: se dice y
		# el Operador decide. El árbol ya está actualizado, eso sí.
		for reason in reasons:
			print(f"+ montaje obsoleto: {reason}")
		print("  la caja seguiría midiendo el árbol viejo: `dokime.py update --recreate` la recrea (volúmenes intactos)")
		return 0

	if args.recreate:
		if not _exists("container", NAME):
			print(f"+ no hay caja {NAME}: `up` la creará con los montajes nuevos")
			return 0
		for reason in reasons:
			print(f"+ montaje obsoleto: {reason}")
		print(f"+ recreando {NAME} (los volúmenes se conservan)")
		run([RUNTIME, "rm", "-f", NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		return up(argparse.Namespace(seed=args.seed))

	if args.seed:
		_reseed()
	return 0


def status(_: argparse.Namespace) -> int:
	"""Radiografía de la caja: qué corre, qué árbol se mide y dónde está el desk."""
	print(f"caja         {BOX} · runtime {RUNTIME} · imagen {IMAGE}")
	for label, name in (("alma", NAME), ("qdrant", QDRANT), ("modelo", LLAMA_NAME)):
		state = "no existe" if not _exists("container", name) else ("arriba" if _is_running(name) else "parada")
		print(f"{label:13s}{name:18s} {state}")
	state = _kernel_state()
	if state:
		sucio = " · SUCIO" if state["dirty"] else ""
		print(f"{'kernel':13s}{KERNEL_WORKTREE}")
		print(f"{'':13s}{state['ref']} @ {state['sha'][:12]}{sucio}")
	else:
		print(f"{'kernel':13s}sin worktree del banco (se montaría {SOURCE_REPO})")
	mounts = _mounts_of(NAME)
	if mounts:
		kernel = mounts.get("/src/red-pill") or {}
		desk_m = mounts.get(DESK_MOUNT) or {}
		mode = "ro" if kernel.get("RW") is False else "rw"
		print(f"{'montado':13s}/src/red-pill ← {kernel.get('Source', '—')} ({mode})")
		print(f"{'':13s}{DESK_MOUNT} ← {desk_m.get('Source', '—')}")
	reasons = _mounts_need_refresh()
	print(f"{'montajes':13s}{'ok' if not reasons else 'OBSOLETOS · ' + '; '.join(reasons)}")
	inbox = len(list((DESK_HOST / DESK_INBOX).glob("*"))) if (DESK_HOST / DESK_INBOX).is_dir() else 0
	outbox = len(list((DESK_HOST / DESK_OUTBOX).glob("*"))) if (DESK_HOST / DESK_OUTBOX).is_dir() else 0
	print(f"{'desk':13s}{DESK_HOST} (inbox {inbox} · outbox {outbox})")
	if BOX_STATE.is_file():
		try:
			saved = json.loads(BOX_STATE.read_text(encoding="utf-8"))
			print(
				f"{'config':13s}{saved.get('alias', '—')} · ctx {saved.get('ctx', '—')} · "
				f"{'GPU' if saved.get('gpu') else 'CPU'} · {Path(saved.get('model', '—')).name} · {BOX_STATE}"
			)
		except Exception:  # noqa: BLE001 — un snapshot roto no debe romper el diagnóstico
			print(f"{'config':13s}{BOX_STATE} (ilegible)")
	return 0


def desk(args: argparse.Namespace) -> int:
	"""Intercambio con el alma: el desk vive en el HOST y se ve dentro en `/srv/dokime/desk`.

	`inbox` es la dirección Operador → alma y `outbox` la contraria. `put`/`get`
	son azúcar de `cp`; el alma ya ve el directorio montado, no hace falta
	"sincronizar" nada: el mismo inodo en los dos lados.
	"""
	_ensure_desk()
	_grant_desk_acl()
	cmd = args.desk_cmd or "path"
	items = list(args.items or [])

	if cmd == "path":
		print(f"host       {DESK_HOST}")
		print(f"contenedor {DESK_MOUNT}")
		print(f"inbox      {DESK_HOST / DESK_INBOX}  (Operador → alma)")
		print(f"outbox     {DESK_HOST / DESK_OUTBOX}  (alma → Operador)")
		return 0

	if cmd == "ls":
		base = DESK_HOST / (items[0] if items else "")
		if not base.is_dir():
			print(f"no existe el directorio: {base}", file=sys.stderr)
			return 1
		for p in sorted(base.iterdir()):
			size = "dir" if p.is_dir() else f"{p.stat().st_size} B"
			print(f"{size:>10s}  {p.name}")
		return 0

	if cmd == "put":
		if not items:
			print("uso: dokime.py desk put <fichero…> [--to inbox]", file=sys.stderr)
			return 2
		dest = DESK_HOST / (args.to or DESK_INBOX)
		dest.mkdir(parents=True, exist_ok=True)
		rc = 0
		for item in items:
			origin = Path(item).expanduser()
			target = dest / origin.name
			if origin.is_dir():
				shutil.copytree(origin, target, dirs_exist_ok=True)
			elif origin.is_file():
				if target.is_file():
					# El destino puede pertenecer al uid mapeado del alma: no se
					# puede sobrescribir en sitio, pero sí reemplazar (dir 0777).
					target.unlink()
				# `copyfile`, no `copy2`: copiar el modo (644) recalcula la máscara
				# de la ACL heredada y le quita el write al alma — el buzón deja
				# de ser de ida y vuelta.
				shutil.copyfile(origin, target)
			else:
				print(f"no existe: {origin}", file=sys.stderr)
				rc = 1
				continue
			print(f"+ {origin} → {target}")
		return rc

	if cmd == "get":
		src_dir = DESK_HOST / (args.from_dir or DESK_OUTBOX)
		if not src_dir.is_dir():
			print(f"no existe el directorio: {src_dir}", file=sys.stderr)
			return 1
		pattern = items[0] if items else "*"
		hits = sorted(src_dir.glob(pattern))
		if not hits:
			print(f"nada que traer en {src_dir} (patrón {pattern})", file=sys.stderr)
			return 1
		dest = Path(args.to or ".").expanduser()
		dest.mkdir(parents=True, exist_ok=True)
		for hit in hits:
			target = dest / hit.name
			if hit.is_dir():
				shutil.copytree(hit, target, dirs_exist_ok=True)
			else:
				shutil.copyfile(hit, target)
			if args.move:
				shutil.rmtree(hit) if hit.is_dir() else hit.unlink()
			print(f"+ {hit} → {target}")
		return 0

	print(f"subcomando desconocido: {cmd}", file=sys.stderr)
	return 2


def main() -> int:
	ap = argparse.ArgumentParser(description="Dokimé — banco de pruebas aislado")
	sub = ap.add_subparsers(dest="cmd", required=True)
	p_up = sub.add_parser("up")
	p_up.add_argument("--no-seed", dest="seed", action="store_false", default=True, help="no re-sembrar la identidad al arrancar")
	sub.add_parser("down")
	sub.add_parser("shell")
	p = sub.add_parser("exec")
	p.add_argument("prompt", nargs=argparse.REMAINDER)
	c = sub.add_parser("chat", help="sesión interactiva con el alma (TUI de pi)")
	c.add_argument("args", nargs=argparse.REMAINDER, help="pasa flags a pi (p.ej. `-c` para continuar)")
	n = sub.add_parser("net")
	n.add_argument("state", choices=["on", "off"])
	sub.add_parser("preflight")
	sub.add_parser("status")
	u = sub.add_parser("update", help="actualiza el kernel del banco, los montajes y las semillas")
	u.add_argument("--ref", default=KERNEL_REF, help=f"ref a la que sincronizar el worktree del banco (defecto: {KERNEL_REF})")
	u.add_argument("--no-fetch", dest="fetch", action="store_false", default=True, help="no hacer `git fetch` antes de mover")
	u.add_argument("--recreate", action="store_true", help="recrear la caja aunque los montajes ya cuadren")
	u.add_argument("--no-seed", dest="seed", action="store_false", default=True, help="no re-sembrar la identidad")
	u.add_argument("--force", action="store_true", help="descartar cambios sin commitear del worktree del banco")
	u.add_argument("--dry-run", action="store_true", help="decir qué haría, sin tocar nada")
	d = sub.add_parser("desk", help="intercambio con el alma: el desk del host, visible dentro")
	d.add_argument("desk_cmd", nargs="?", default="path", choices=["path", "ls", "put", "get"])
	d.add_argument("items", nargs="*", help="put: orígenes · get: patrón glob · ls: subdirectorio")
	d.add_argument("--to", default=None, help="put: subdirectorio del desk · get: destino en el host")
	d.add_argument("--from-dir", dest="from_dir", default=None, help="get: subdirectorio del desk (defecto: outbox)")
	d.add_argument("--move", action="store_true", help="get: borrar el original tras copiarlo")
	args = ap.parse_args()
	return {
		"up": up,
		"down": down,
		"exec": exec_,
		"shell": shell,
		"chat": chat,
		"net": net,
		"preflight": preflight,
		"status": status,
		"update": update,
		"desk": desk,
	}[args.cmd](args)


if __name__ == "__main__":
	sys.exit(main())
