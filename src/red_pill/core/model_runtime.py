"""model_runtime — fuente única de resolución de la inferencia local (RFC-HARNESS-002 v3).

Selector (experimental > custom > model > task > config > env, SIN aliases),
candidatos v2.0, merge por especificidad (cadena completa), modos
custom/experimental, hot reload por mtime, parsers compartidos
(`toolcall` / `extract_thinking`), validación/registro de modelos y presupuesto
de contexto dinámico. Compartido por el daemon (`run_dual_bind.py`) y los
clientes (distiller del sueño, memento, providers) — §8 del RFC.

Separación de responsabilidades (RFC §2):
- `model_profiles.yaml` = calibración HARDWARE + conducta de MODELO
	(vram_tiers, n_ctx, device_fallback, chat_format, minion_chat_format,
	tool_format, thinking, licencia, prompt_file, temperature).
- `task_profiles.yaml` = curación de TAREAS (prompt_file, temperature,
	max_tokens, thinking, candidatos de modelo con `default: true`).
- `model_runtime.yaml` = config en caliente (default_model, fallup, hot_reload).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from red_pill.core.model_license import assert_commercial_ok, normalize_license
from red_pill.core.model_registry import ModelRegistry
from red_pill.core.paths import (
	get_model_runtime_path,
	get_model_validation_path,
	get_task_profiles_path,
)
from red_pill.core.vram_probe import VramProbe

logger = logging.getLogger(__name__)

# ── Modos de razonamiento soportados (v3, RFC §5.3) ────────────────────────
THINKING_MODES = ("off", "on", "low")
TOOL_FORMATS = ("qwen", "gemma", "openai", "auto")

# Env rename (RFC §10): la ÚNICA variable de arranque es MINION_DEFAULT_PROFILE.
# MINION_PROFILE se lee solo como fallback legacy, con warning, y se elimina
# tras la primera migración verificada.
ENV_DEFAULT_PROFILE = "MINION_DEFAULT_PROFILE"
ENV_LEGACY_PROFILE = "MINION_PROFILE"

_GGUF_MAGIC = b"GGUF"


class ModelRuntimeError(Exception):
	"""Error de resolución del selector: 400 con razón, nunca fallo silencioso."""


class ModelRuntimeConfigError(ModelRuntimeError):
	"""Config corrupta / id sin resolver / modo inválido."""


class ModelNotFoundError(ModelRuntimeError):
	"""Modelo no encontrado en perfiles ni inventario."""


@dataclass
class ResolvedModel:
	"""Resolución completa del selector: perfil + conducta + calibración.

	Es el CONTRATO entre daemon y clientes (RFC §8): el daemon deriva lo
	técnico (model_path, chat_format, n_ctx, device_fallback), los clientes
	derivan la conducta (prompt_file, temperature, max_tokens, thinking).
	"""

	profile_name: str
	model_path: str
	chat_format: Optional[str] = None  # None = template nativo del GGUF
	minion_chat_format: Optional[str] = None
	tool_format: str = "auto"
	thinking: str = "off"
	temperature: float = 0.3
	max_tokens: int = 4096
	prompt_file: Optional[str] = None
	n_ctx: int = 8192
	cpu_n_ctx: Optional[int] = None
	device_fallback: List[str] = field(default_factory=lambda: ["gpu", "cpu"])
	n_gpu_layers: int = -1
	license: Dict[str, Any] = field(default_factory=dict)
	mode: str = "curated"  # curated | custom | experimental
	last_mode: str = "curated"  # para /status.last_mode
	extra: Dict[str, Any] = field(default_factory=dict)

	def resolved_n_ctx(self) -> int:
		"""n_ctx efectivo del perfil resuelto (vram_tiers aplicado)."""
		return self.n_ctx

	def prompt_budget(self) -> int:
		"""Presupuesto de chars del prompt según n_ctx y modo thinking.

		RFC §5.3: el razonamiento consume presupuesto de salida. Con thinking
		activo se reserva un margen de salida mayor; sin thinking, el margen
		clásico de ~4096 tokens de salida.
		"""
		salida = 8192 if self.thinking == "on" else 4096
		return max(1024, int(self.n_ctx - salida))


# ── Carga con hot reload (RFC §9: releer por mtime en cada request) ────────

_CACHE: Dict[str, Tuple[float, Any]] = {}


def _mtime(path: Path) -> float:
	try:
		return path.stat().st_mtime
	except OSError:
		return 0.0


def _load_yaml(path: Path, name: str, reload: bool) -> Any:
	"""Carga YAML con cache por mtime; config corrupta → última buena + dolor."""
	key = name
	mtime = _mtime(path)
	cached = _CACHE.get(key)
	if reload and cached is not None and abs(cached[0] - mtime) < 1e-6 and path.exists():
		return cached[1]
	if not path.exists():
		_CACHE[key] = (mtime, {})
		return {}
	try:
		with open(path, "r", encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
		_CACHE[key] = (mtime, data)
		return data
	except Exception as e:
		logger.error(f"[MODEL_RUNTIME] Config '{name}' corrupta: {e} — usando última buena.")
		if cached is not None:
			return cached[1]
		return {}


def _runtime_config() -> Dict[str, Any]:
	return _load_yaml(get_model_runtime_path(), "model_runtime", _hot_reload_enabled()) or {}


def _task_profiles() -> Dict[str, Any]:
	data = _load_yaml(get_task_profiles_path(), "task_profiles", _hot_reload_enabled())
	return data.get("tasks") or {}


def _hot_reload_enabled() -> bool:
	# Sin recursión: lee el flag con reload=False (una vez por request, barato).
	hot = _load_yaml(get_model_runtime_path(), "model_runtime", False)
	return bool(hot.get("hot_reload", True))


def _fallup_enabled() -> bool:
	return bool(_runtime_config().get("fallup", True))


# ── Acceso a perfiles (con hot reload via ModelRegistry.reload) ───────────


def _get_profile(profile_name: str) -> dict:
	"""Perfil de model_profiles, refrescando ModelRegistry si el mtime cambió."""
	ModelRegistry.reload()
	return ModelRegistry.get_profile(profile_name)


def _default_profile_from_env() -> str:
	"""Env rename §10: MINION_DEFAULT_PROFILE con fallback legacy MINION_PROFILE."""
	primary = os.getenv(ENV_DEFAULT_PROFILE)
	if primary:
		return primary.strip()
	legacy = os.getenv(ENV_LEGACY_PROFILE)
	if legacy:
		logger.warning(f"[MODEL_RUNTIME] {ENV_LEGACY_PROFILE} en uso (legacy) — migrar a {ENV_DEFAULT_PROFILE}.")
		return legacy.strip()
	return ""


def _resolve_profile_file(profile: dict, name: str) -> str:
	"""model_path del perfil, resuelto contra el directorio de modelos."""
	mp = profile.get("model_path") or ""
	if not mp:
		return ""
	path = Path(mp)
	if path.is_absolute():
		return str(path)
	from red_pill.core.paths import get_models_dir

	return str(get_models_dir() / mp)


def _merge_tier(profile: dict, name: str) -> dict:
	"""Aplica vram_tiers del perfil → n_ctx/n_gpu_layers resueltos (hardware actual)."""
	hw = ModelRegistry.get_resolved_hardware_affinity(name)
	resolved = dict(hw)
	if not resolved.get("n_ctx"):
		resolved["n_ctx"] = profile.get("hardware_affinity", {}).get("n_ctx") or profile.get("max_tokens") or 4096
	if "n_gpu_layers" not in resolved:
		resolved["n_gpu_layers"] = -1
	return resolved


def _base_from_profile(name: str, profile: dict, tier: dict) -> ResolvedModel:
	"""Construye un ResolvedModel desde un perfil curado de model_profiles."""
	n_ctx = int(tier.get("n_ctx") or profile.get("max_tokens") or 4096)
	thinking = _normalize_thinking(profile.get("thinking", "off"))
	return ResolvedModel(
		profile_name=name,
		model_path=_resolve_profile_file(profile, name),
		chat_format=profile.get("chat_format"),
		minion_chat_format=profile.get("minion_chat_format"),
		tool_format=_normalize_tool_format(profile.get("tool_format", "auto")),
		thinking=thinking,
		temperature=float(profile.get("temperature") or 0.3),
		max_tokens=int(profile.get("max_tokens") or 4096),
		prompt_file=profile.get("prompt_file"),
		n_ctx=n_ctx,
		cpu_n_ctx=int(profile.get("cpu_n_ctx") or 0) or None,
		device_fallback=list(profile.get("device_fallback") or ["gpu", "cpu"]),
		n_gpu_layers=int(tier.get("n_gpu_layers") or -1),
		license=normalize_license(profile.get("license"), name),
		extra={"tier": tier, "thinking_supported": thinking != "off"},
	)


def _normalize_thinking(value: Any) -> str:
	if value is None:
		return "off"
	v = str(value).strip().lower()
	if v in ("off", "false", "0"):
		return "off"
	if v in ("low", "brief"):
		return "low"
	return "on"


def _normalize_tool_format(value: Any) -> str:
	v = str(value or "auto").strip().lower()
	return v if v in TOOL_FORMATS else "auto"


# ── Parsers compartidos (v3, RFC §18) ─────────────────────────────────────

_TOOLCALL_RE = {
	"qwen": re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL),
	"gemma": re.compile(r"<\|tool_call\|>call:(\w+)\{([^}]*)\}", re.DOTALL),
}


def extract_toolcalls(text: str, tool_format: str = "qwen") -> List[dict]:
	"""Extrae tool-calls del texto según el formato nativo del modelo.

	- `qwen`: `<tool_call>{json}</tool_call>` (Granite 3.x/4.x, Qwen).
	- `gemma`: `<|tool_call|>call:NAME{args}`.
	- `openai`: intenta parsear como JSON tool_calls estructurados.
	- `auto`: prueba en orden qwen → gemma → openai.
	Vacío → [] (el caller decide si es tool-call real o prosa).
	"""
	formats = TOOL_FORMATS if tool_format == "auto" else [tool_format]
	for fmt in formats:
		if fmt == "qwen":
			m = _TOOLCALL_RE["qwen"].search(text)
			if m:
				inner = m.group(1).strip()
				try:
					obj = json.loads(inner)
					name = obj.get("function", obj.get("name", ""))
					args = obj.get("arguments", obj.get("parameters", {}))
					return [{"function": {"name": name, "arguments": args if isinstance(args, dict) else {}}}]
				except Exception:
					# Formato "<function=NAME><parameter=k>v</parameter></function>"
					fn = re.search(r"<function=([^>]+)>", inner)
					if fn:
						params = re.findall(r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", inner, re.DOTALL)
						args = {k.strip(): v.strip() for k, v in params}
						return [{"function": {"name": fn.group(1).strip(), "arguments": args}}]
		elif fmt == "gemma":
			m = _TOOLCALL_RE["gemma"].search(text)
			if m:
				try:
					args = json.loads("{" + m.group(2) + "}") if m.group(2).strip() else {}
				except Exception:
					args = {}
				return [{"function": {"name": m.group(1).strip(), "arguments": args}}]
		elif fmt == "openai":
			try:
				obj = json.loads(text)
				if isinstance(obj, list):
					obj = obj[0] if obj else None
				if isinstance(obj, dict) and obj.get("type") == "function":
					fn = obj.get("function", {})
					args = fn.get("arguments")
					if isinstance(args, str):
						try:
							args = json.loads(args)
						except Exception:
							args = {}
					return [{"function": {"name": fn.get("name", ""), "arguments": args}}]
			except Exception:
				pass
	return []


_THINKING_SPLIT = re.compile(r"(?:\s+response\s*|\s*</think>\s*|\s* response\s*)(.*)", re.DOTALL)


def extract_thinking(text: str) -> Tuple[str, str]:
	"""Separa la traza de razonamiento de la respuesta final.

	Granite 4.2 cierra el razonamiento con ` response` (3B) o ` response`
	(8B) antes de la respuesta; algunos GGUF usan `</think>`. Tolerante a los
	tres. Devuelve (thinking, answer); sin marcador → ("", text).
	"""
	m = _THINKING_SPLIT.search(text)
	if m and m.group(1).strip():
		thinking = text[: m.start()].strip()
		return thinking, m.group(1).strip()
	return "", text.strip()


# ── Selector — resolución (RFC §6: sin aliases, 400 explícito) ─────────────


def resolve(body: Optional[dict] = None) -> ResolvedModel:
	"""Resuelve una request al modelo + conducta efectivos.

	Orden de precedencia (RFC §6):
	1. body["experimental"] → modo experimental (§5.2)
	2. body["custom"]       → modo custom (§5.1)
	3. body["model"]        → id de perfil o basename GGUF exacto
	4. body["task"]         → candidato default de la tarea (§4.1)
	5. model_runtime.yaml default_model → fallback GENERAL (sin task)
	6. MINION_DEFAULT_PROFILE (env) [fallback legacy MINION_PROFILE]
	7. nada resuelve → ModelRuntimeConfigError (400)

	Raises:
		ModelRuntimeConfigError — id sin resolver, task+model no candidato (K1),
			custom sin model, custom+experimental juntos, experimental incompleto,
			thinking pedido que el modelo no soporta.
		ModelLicenseError — gate comercial fail-closed (curado/custom).
	"""
	body = body or {}

	has_experimental = "experimental" in body
	has_custom = "custom" in body
	if has_experimental and has_custom:
		raise ModelRuntimeConfigError("custom y experimental son mutuamente excluyentes")

	if has_experimental:
		resolved = _resolve_experimental(body["experimental"], body)
	elif has_custom:
		resolved = _resolve_custom(body["custom"], body)
	elif body.get("model"):
		resolved = _resolve_named_model(str(body["model"]), body)
	elif body.get("task"):
		resolved = _resolve_task(str(body["task"]), body)
	else:
		resolved = _resolve_default(body)

	# RFC §6: task + custom/experimental → la tarea aporta conducta, el modo
	# aporta el modelo. Aplicar la conducta de la tarea (si existe) sobre el
	# resolved del modo.
	if body.get("task") and (has_custom or has_experimental):
		try:
			conduct = resolve_task_conduct(str(body["task"]))
			resolved.prompt_file = conduct.get("prompt_file") or resolved.prompt_file
			resolved.temperature = float(conduct.get("temperature") or resolved.temperature)
			resolved.max_tokens = int(conduct.get("max_tokens") or resolved.max_tokens)
			if conduct.get("thinking"):
				want = _normalize_thinking(conduct["thinking"])
				supported = resolved.extra.get("thinking_supported")
				if want != "off" and supported is not None and not supported:
					want = "off"  # degradación de curado (§4.1)
				resolved.thinking = want
		except ModelRuntimeError:
			pass  # task inexistente → el modo ya resolvió; el daemon no lo rechaza

	# Override de conducta por request (RFC §4.1): thinking.
	# `off` siempre se permite (no razonar nunca está prohibido); solo se
	# bloquea pedir RAZONAMIENTO (on/low) en un modelo que no razona
	# (perfil con thinking_supported=False).
	if "thinking" in body:
		want = _normalize_thinking(body["thinking"])
		supported = resolved.extra.get("thinking_supported")
		if want != "off" and supported is not None and not supported:
			raise ModelRuntimeConfigError(f"thinking '{want}' no soportado por '{resolved.profile_name}'")
		resolved.thinking = want

	# Override técnico explícito (RFC §4.1): chat_format / device_fallback.
	if "chat_format" in body:
		resolved.chat_format = body["chat_format"]
	if "device_fallback" in body:
		resolved.device_fallback = list(body["device_fallback"])

	return resolved


def _resolve_experimental(exp: dict, body: dict) -> ResolvedModel:
	"""Modo experimental — perfil virtual completo (RFC §5.2).

	SE SALTA la comprobación de licencia (gap del operador, registrado en
	last_mode). Datos incompletos → 400. Sin vram_tiers → n_gpu_layers
	explícito o -1.
	"""
	mp = exp.get("model_path") or ""
	if not mp:
		raise ModelRuntimeConfigError("experimental.model_path es obligatorio")
	if not isinstance(exp.get("n_ctx"), int) or not exp.get("device_fallback"):
		raise ModelRuntimeConfigError("experimental requiere n_ctx (int) y device_fallback (lista)")
	path = Path(mp).expanduser()
	if not path.is_absolute():
		from red_pill.core.paths import get_models_dir

		path = get_models_dir() / mp
	if not path.exists():
		raise ModelRuntimeConfigError(f"experimental.model_path no existe: {path}")

	n_ctx = int(exp["n_ctx"])
	thinking = _normalize_thinking(exp.get("thinking", "off"))
	resolved = ResolvedModel(
		profile_name=f"experimental:{path.name}",
		model_path=str(path),
		chat_format=exp.get("chat_format"),
		minion_chat_format=exp.get("minion_chat_format"),
		tool_format=_normalize_tool_format(exp.get("tool_format", "auto")),
		thinking=thinking,
		temperature=float(exp.get("temperature") or 0.3),
		max_tokens=int(exp.get("max_tokens") or 4096),
		prompt_file=exp.get("prompt_file"),
		n_ctx=n_ctx,
		cpu_n_ctx=int(exp.get("cpu_n_ctx") or 0) or None,
		device_fallback=list(exp.get("device_fallback") or ["gpu", "cpu"]),
		n_gpu_layers=int(exp.get("n_gpu_layers") or -1),
		license=normalize_license(exp.get("license"), path.name),
		mode="experimental",
		last_mode="experimental",
		# El experimental es el borrador de un perfil: el operador asume que el
		# modelo razona (no hay perfil que lo restrinja). Los 3 modos son válidos.
		extra={"thinking_supported": True},
	)
	validate_model_file(str(path))
	return resolved


def _resolve_custom(custom: dict, body: dict) -> ResolvedModel:
	"""Modo custom — modelo curado con parámetros modificados (RFC §5.1).

	`model` es id exacto de perfil (sin aliases). Licencia fail-closed normal.
	Permite n_ctx/n_gpu_layers/chat_format/device_fallback/thinking.
	"""
	name = custom.get("model") or ""
	if not name:
		raise ModelRuntimeConfigError("custom.model es obligatorio")
	profile = _get_profile(name)
	if not profile:
		raise ModelRuntimeConfigError(f"custom.model '{name}' no es un perfil curado")
	assert_commercial_ok(profile.get("license"), model_name=name)
	tier = _merge_tier(profile, name)
	resolved = _base_from_profile(name, profile, tier)
	resolved.mode = "custom"
	resolved.last_mode = "custom"

	if "n_ctx" in custom:
		resolved.n_ctx = int(custom["n_ctx"])
	if "n_gpu_layers" in custom:
		resolved.n_gpu_layers = int(custom["n_gpu_layers"])
	if "chat_format" in custom:
		resolved.chat_format = custom["chat_format"]
	if "device_fallback" in custom:
		resolved.device_fallback = list(custom["device_fallback"])
	if "thinking" in custom:
		want = _normalize_thinking(custom["thinking"])
		supported = resolved.extra.get("thinking_supported")
		if want != "off" and supported is not None and not supported:
			raise ModelRuntimeConfigError(f"thinking '{want}' no soportado por '{name}'")
		resolved.thinking = want
	return resolved


def _resolve_named_model(name: str, body: dict) -> ResolvedModel:
	"""body["model"] → id de perfil o basename GGUF exacto (sin aliases)."""
	profile = _get_profile(name)
	if not profile:
		# Basename GGUF exacto: buscar entre los perfiles cuyo model_path coincide.
		for pname, prof in ModelRegistry.get_all_profiles().items():
			mp = Path(_resolve_profile_file(prof, pname))
			if mp.name == name or str(mp) == name:
				profile = prof
				name = pname
				break
	if not profile:
		raise ModelRuntimeConfigError(f"model '{name}' no resuelve a un perfil ni basename GGUF")
	assert_commercial_ok(profile.get("license"), model_name=name)
	tier = _merge_tier(profile, name)
	resolved = _base_from_profile(name, profile, tier)

	# task+model: el model DEBE estar en los candidatos de la tarea (K1).
	# El resultado del merge (conducta de la tarea + candidato) gana al perfil.
	if body.get("task"):
		return _resolve_task(str(body["task"]), body, enforce_model=name)
	return resolved


def _resolve_task(task_id: str, body: dict, enforce_model: Optional[str] = None) -> ResolvedModel:
	"""body["task"] → conducta de tarea + candidato default (§4.1)."""
	tasks = _task_profiles()
	if task_id not in tasks:
		raise ModelRuntimeConfigError(f"task '{task_id}' no existe en task_profiles")
	task = tasks[task_id]
	candidates = task.get("models") or []

	# K1: con task+model, el model DEBE estar en los candidatos de la tarea.
	if enforce_model:
		matching = next((c for c in candidates if (c.get("profile") or "") == enforce_model), None)
		if matching is None:
			raise ModelRuntimeConfigError(f"model '{enforce_model}' no es candidato de la task '{task_id}' (K1) — usa custom")
		# Elegir ESE candidato (su conducta tarea×modelo), no el default.
		chosen = matching
	else:
		chosen = None
		for cand in candidates:
			pid = cand.get("profile") or ""
			if pid and not _get_profile(pid):
				logger.warning(f"[MODEL_RUNTIME] candidato '{pid}' de task '{task_id}' sin perfil → skip (K4)")
				continue
			chosen = cand
			break
	if chosen is None and candidates:
		logger.warning(f"[MODEL_RUNTIME] task '{task_id}' sin candidato resoluble → caer a config/env (K4)")
	if chosen is not None:
		pid = chosen.get("profile")
		profile = _get_profile(pid)
		assert_commercial_ok(profile.get("license"), model_name=pid)
		tier = _merge_tier(profile, pid)
		resolved = _base_from_profile(pid, profile, tier)
		# Merge por especificidad: candidato > tarea (§4.1).
		resolved.prompt_file = chosen.get("prompt_file") or task.get("prompt_file") or resolved.prompt_file
		resolved.temperature = float(chosen.get("temperature") or task.get("temperature") or resolved.temperature)
		resolved.max_tokens = int(chosen.get("max_tokens") or task.get("max_tokens") or resolved.max_tokens)
		resolved.thinking = _normalize_thinking(chosen.get("thinking") or task.get("thinking") or resolved.thinking)
		# Protección de curado: si la tarea pidió un modo de RAZONAMIENTO pero
		# el candidato elegido no razona (thinking_supported=False), degradar al
		# thinking del MODELO (off) en vez de intentar un handler inexistente.
		supported = resolved.extra.get("thinking_supported")
		if resolved.thinking != "off" and supported is not None and not supported:
			logger.warning(f"[MODEL_RUNTIME] task '{task_id}' pidió thinking={resolved.thinking} pero '{pid}' no razona → degradado a off")
			resolved.thinking = "off"

		return resolved

	# Sin candidatos → caer a default (config → env).
	return _resolve_default(body)


def _resolve_default(body: dict) -> ResolvedModel:
	"""model_runtime.yaml default_model → env (RFC §6 pasos 5-6)."""
	cfg = _runtime_config()
	dm = (cfg.get("default_model") or "").strip()
	if dm:
		profile = _get_profile(dm)
		if not profile:
			logger.warning(f"[MODEL_RUNTIME] default_model '{dm}' inexistente → caer a env")
		else:
			assert_commercial_ok(profile.get("license"), model_name=dm)
			tier = _merge_tier(profile, dm)
			return _base_from_profile(dm, profile, tier)
	name = _default_profile_from_env()
	if not name:
		raise ModelRuntimeConfigError("ningún modelo resuelve (default_model vacío y sin env)")
	profile = _get_profile(name)
	if not profile:
		raise ModelRuntimeConfigError(f"env default '{name}' no es un perfil curado")
	assert_commercial_ok(profile.get("license"), model_name=name)
	tier = _merge_tier(profile, name)
	return _base_from_profile(name, profile, tier)


# ── Validación de modelos (RFC §10 K5: una vez por fichero) ───────────────

_MODEL_VALIDATION_CAP = 100


def _model_key(path: str) -> str:
	"""Clave de validación: path+size+mtime+sha256 de los primeros 64 KB."""
	try:
		stat = Path(path).stat()
		with open(path, "rb") as f:
			head = f.read(65536)
		h = hashlib.sha256(head).hexdigest()[:16]
		return f"{path}:{stat.st_size}:{int(stat.st_mtime)}:{h}"
	except OSError as e:
		raise ModelRuntimeConfigError(f"modelo ilegible: {path} ({e})") from e


def _read_validation_registry() -> dict:
	try:
		with open(get_model_validation_path(), "r", encoding="utf-8") as f:
			return json.load(f) or {}
	except Exception:
		return {}


def _write_validation_registry(reg: dict) -> None:
	path = get_model_validation_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(".tmp")
	try:
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(reg, f, ensure_ascii=False, indent=2)
		tmp.replace(path)
	except OSError as e:
		logger.error(f"[MODEL_RUNTIME] no se pudo escribir model_validation.json: {e}")


def validate_model_file(path: str) -> dict:
	"""Valida un fichero de modelo una vez; registra el resultado (K5).

	Chequea magic bytes GGUF + tamaño ≥ 10 MB. Un fichero corrupto que crashee
	llama_cpp sería un DoS local del daemon. Devuelve la entrada del registro.
	"""
	key = _model_key(path)
	reg = _read_validation_registry()
	entry = reg.get(key)
	if entry is not None:
		return entry if entry is not None else {}

	try:
		size = Path(path).stat().st_size
		with open(path, "rb") as f:
			magic = f.read(4)
	except OSError as e:
		raise ModelRuntimeConfigError(f"modelo ilegible: {path} ({e})") from e

	valid = size >= 10 * 1024 * 1024 and magic == _GGUF_MAGIC
	entry = {
		"validado_at": time.time(),
		"magic": magic.decode("ascii", errors="replace") if valid else "",
		"load_verified": False,
	}
	if not valid:
		raise ModelRuntimeConfigError(f"modelo no válido (debe ser GGUF ≥ 10 MB): {path} (magic={magic!r}, size={size})")
	# Eviction por antigüedad (cap 100).
	if len(reg) >= _MODEL_VALIDATION_CAP:
		oldest = sorted(reg.keys(), key=lambda k: reg[k].get("validado_at", 0))[0]
		reg.pop(oldest, None)
	reg[key] = entry
	_write_validation_registry(reg)
	return entry


def mark_load_verified(path: str) -> None:
	"""Marca `load_verified: true` tras la primera carga exitosa (K5)."""
	key = _model_key(path)
	reg = _read_validation_registry()
	entry = reg.get(key)
	if entry is None:
		entry = validate_model_file(path)
	entry["load_verified"] = True
	reg[key] = entry
	_write_validation_registry(reg)


# ── Seed hardware-aware de task_profiles (RFC §10) ─────────────────────────


def seed_task_profiles() -> dict:
	"""Genera el seed de task_profiles.yaml según el hardware detectado.

	NUNCA sobreescribe un fichero existente (el curado manual gana). Verifica
	que cada perfil referenciado exista en model_profiles (ausente → omitido).
	"""
	path = get_task_profiles_path()
	if path.exists():
		return _task_profiles()

	free_gb = VramProbe.get_free_mb() / 1024.0
	all_profiles = set(ModelRegistry.get_all_profiles().keys())

	def pick(candidates):
		# [("id", default: bool)] → lista de perfiles existentes, primero el default.
		existing = [c for c in candidates if c[0] in all_profiles]
		by_default = sorted(existing, key=lambda c: 0 if c[1] else 1)
		return [{"profile": c[0], "default": True} if c[1] else {"profile": c[0]} for c in by_default]

	if free_gb >= 6.5:
		distill = pick([("granite_8b", True), ("tiny_aya_water", False), ("granite_3b", False)])
		refine = pick([("tiny_aya_water", True), ("granite_8b", False)])
		conv = pick([("granite_8b", True)])
		tool = pick([("granite_8b", True)])
		hub = pick([("granite_8b", True)])
	elif free_gb >= 3.5:
		distill = pick([("granite_3b", True), ("llama_32", False)])
		refine = pick([("granite_3b", True), ("llama_32", False)])
		conv = pick([("granite_3b", True)])
		tool = pick([("granite_3b", True)])
		hub = pick([("granite_3b", True)])
	else:
		distill = pick([("llama_32", True), ("granite_3b", False)])
		refine = pick([("llama_32", True), ("granite_3b", False)])
		conv = pick([("llama_32", True)])
		tool = pick([("llama_32", True)])
		hub = pick([("llama_32", True)])

	seed = {
		"tasks": {
			"distill": {"temperature": 0.3, "max_tokens": 512, "thinking": "off", "models": distill},
			"refine": {"temperature": 0.1, "max_tokens": 1024, "thinking": "off", "models": refine},
			"conversation": {"thinking": "low", "models": conv},
			"minion_tool": {"thinking": "off", "models": tool},
			"hub": {"temperature": 0.1, "thinking": "on", "models": hub},
		}
	}
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w", encoding="utf-8") as f:
			yaml.safe_dump(seed, f, allow_unicode=True, sort_keys=False)
		logger.info(f"[MODEL_RUNTIME] task_profiles.yaml sembrado (hardware-aware, {free_gb:.1f} GB libres)")
	except OSError as e:
		logger.error(f"[MODEL_RUNTIME] no se pudo escribir task_profiles.yaml: {e}")
	return seed


def task_conduct(task_id: str) -> dict:
	"""Conducta de una tarea curada (para clientes; resolución in-process)."""
	tasks = _task_profiles()
	task = tasks.get(task_id)
	if not task:
		raise ModelRuntimeConfigError(f"task '{task_id}' no existe en task_profiles")
	return dict(task)


def effective_default() -> ResolvedModel:
	"""Resolución sin request (para doctor/sentinel: default EFECTIVO, RFC §11)."""
	try:
		return _resolve_default({})
	except ModelRuntimeError:
		# Sin env/config → devuelve un stub informativo para que el doctor no falle.
		return ResolvedModel(profile_name="", model_path="", mode="none", last_mode="none")


def apply_thinking_to_template(thinking: str) -> Optional[str]:
	"""Devuelve el chat_format registrado para un modo thinking (v3, §5.3).

	El daemon registra `granite-thinking`/`granite-nothink`/`granite-low` al
	cargar un modelo con template nativo; esta función mapea el modo resuelto
	al nombre del handler. Devuelve None si no aplica (chat_format explícito).
	"""
	if thinking == "on":
		return "granite-thinking"
	if thinking == "low":
		return "granite-low"
	if thinking == "off":
		return "granite-nothink"
	return None


def resolve_task_conduct(task_id: str) -> dict:
	"""Conducta de una tarea con el candidato default resuelto (para clientes).

	Devuelve {prompt_file, temperature, max_tokens, thinking, profile}. El
	cliente usa `prompt_file` para armar el prompt; el daemon ya cargó/le toca
	cargar el modelo resuelto por la request con `task`. Resolución in-process,
	sin HTTP — el sueño no depende del daemon para armar prompts (RFC §8).
	"""
	tasks = _task_profiles()
	task = tasks.get(task_id)
	if not task:
		raise ModelRuntimeConfigError(f"task '{task_id}' no existe en task_profiles")
	candidates = task.get("models") or []
	chosen = None
	for cand in candidates:
		pid = cand.get("profile") or ""
		if pid and not _get_profile(pid):
			continue  # K4: candidato sin perfil → skip
		chosen = cand
		break
	profile_name = ""
	prompt_file = task.get("prompt_file")
	temperature = float(task.get("temperature") or 0.3)
	max_tokens = int(task.get("max_tokens") or 4096)
	thinking = _normalize_thinking(task.get("thinking", "off"))
	if chosen is not None:
		profile_name = chosen.get("profile") or ""
		prompt_file = chosen.get("prompt_file") or prompt_file
		temperature = float(chosen.get("temperature") or temperature)
		max_tokens = int(chosen.get("max_tokens") or max_tokens)
		thinking = _normalize_thinking(chosen.get("thinking") or task.get("thinking") or thinking)
	return {
		"task": task_id,
		"profile": profile_name,
		"prompt_file": prompt_file,
		"temperature": temperature,
		"max_tokens": max_tokens,
		"thinking": thinking,
	}


def refresh_hardware_tier(resolved: ResolvedModel) -> ResolvedModel:
	"""Re-aplica el tier de hardware del perfil (VRAM ya liberada).

	El resolve inicial puede calcular el tier mientras el modelo ANTERIOR aún
	ocupa la VRAM (n_ctx conservador). Tras el unload del daemon, re-evaluar
	permite un tier mayor si hay VRAM libre — el fallup §9 en su forma directa.
	Devuelve el mismo objeto actualizado (o uno nuevo para experimental sin tier).
	"""
	if resolved.mode == "experimental":
		return resolved  # sin vram_tiers: n_ctx explícito del caller
	name = resolved.profile_name
	profile = _get_profile(name)
	if not profile:
		return resolved
	tier = _merge_tier(profile, name)
	resolved.n_ctx = int(tier.get("n_ctx") or resolved.n_ctx)
	resolved.n_gpu_layers = int(tier.get("n_gpu_layers") or resolved.n_gpu_layers)
	return resolved
