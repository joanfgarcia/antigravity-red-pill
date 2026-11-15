"""Afecto del Operador leído de los turnos vivos (AFFECT_FROM_QUEUE).

El chroma que pinta cada turno salía de los engramas de `work_memories` /
`social_memories`, que son lo que **ascendió la noche anterior** (o de hace días
si la ingesta se para). Ese camino no puede decir cómo está el Operador *ahora*:
le estábamos pidiendo el parte de mañana al periódico de ayer.

Aquí el estado sale de lo único que se escribe por turno: la columna `prompt` de
`memory_queue` — las palabras del Operador, no las del agente. Se clasifica con
un léxico (barato, determinista, sin LLM) y se publica en `state/affect.json`
con TTL corto. El LLM local puede refinar más adelante; el contrato de los
interceptores no cambia (siguen leyendo `mood` + `directive`).

Paleta (datos en `data/affect_lexicon.yaml`): anger/fear → red, anxiety →
orange, joy → yellow, calm → cyan, neutral → gray.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import red_pill.config as cfg

_LEXICON_PATH = Path(__file__).resolve().parent.parent / "data" / "affect_lexicon.yaml"


def _normalizar(texto: str) -> str:
	"""Minúsculas y sin acentos: el léxico guarda raíces desnudas."""
	sin_tildes = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
	return sin_tildes.lower()


def _load_lexicon() -> Dict[str, Dict[str, Any]]:
	"""Léxico emoción → {color, peso, palabras}; vacío si el YAML no se puede leer."""
	try:
		import yaml

		with open(_LEXICON_PATH, "r", encoding="utf-8") as fh:
			data = yaml.safe_load(fh) or {}
		return {str(k): dict(v or {}) for k, v in data.items() if isinstance(v, dict)}
	except Exception:
		return {}


def classify(textos: List[str]) -> Dict[str, Any]:
	"""Emoción dominante del conjunto de textos (léxico, determinista).

	Devuelve `{emotion, color, intensity, hits, evidence}`. Sin ninguna pista,
	`neutral`/gray con intensidad 0. El color sale del léxico, así que ampliar la
	paleta no toca código.
	"""
	lexico = _load_lexicon()
	cuenta: Dict[str, int] = {}
	evidencia: Dict[str, List[str]] = {}
	for emocion, datos in lexico.items():
		palabras = [str(p) for p in (datos.get("palabras") or [])]
		for texto in textos:
			norm = _normalizar(texto)
			for palabra in palabras:
				if palabra and palabra in norm:
					cuenta[emocion] = cuenta.get(emocion, 0) + 1
					evidencia.setdefault(emocion, [])
					if palabra not in evidencia[emocion]:
						evidencia[emocion].append(palabra)
	if not cuenta:
		return {"emotion": "neutral", "color": str((lexico.get("neutral") or {}).get("color") or "gray"), "intensity": 0.0, "hits": 0, "evidence": []}
	# Desempate por `peso` (el miedo/la ira ganan a la calma) y luego por hits.
	emocion = max(cuenta, key=lambda e: (int((lexico.get(e) or {}).get("peso") or 0), cuenta[e]))
	hits = cuenta[emocion]
	return {
		"emotion": emocion,
		"color": str((lexico.get(emocion) or {}).get("color") or "gray"),
		"intensity": round(min(1.0, 0.4 + 0.2 * hits), 2),
		"hits": hits,
		"evidence": evidencia.get(emocion, [])[:5],
	}


def _state_path() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "affect.json"


def _read_state() -> Optional[Dict[str, Any]]:
	try:
		path = _state_path()
		if path.is_file():
			data = json.loads(path.read_text(encoding="utf-8"))
			return data if isinstance(data, dict) else None
	except Exception:
		return None
	return None


def _write_state(state: Dict[str, Any]) -> None:
	try:
		path = _state_path()
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(path.suffix + ".tmp")
		tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
		os.replace(tmp, path)
	except Exception:
		pass


def _recent_prompts(limit: int, window_min: int, now: float) -> List[str]:
	"""Los últimos prompts del Operador en la cola viva (`memory_queue.prompt`).

	En `memory_queue` cada fila guarda el par: `prompt` es lo que escribió el
	Operador y `response` lo que respondió el agente. Solo interesa el primero, y
	solo si es su voz: la cola recibe también bloques del arnés (`<user_rules>`),
	avisos de job/coro y encargos de subagente, que metían ruido en el léxico (un
	`calma` de las reglas pintaba el turno de cian). El filtro vive en
	`core.operator_voice`: una sola definición para el léxico, el enqueue y la
	purga.
	"""
	try:
		from red_pill.core.operator_voice import extract
		from red_pill.core.paths import get_queue_dir

		db = Path(get_queue_dir()) / "bunker_queue.db"
		if not db.is_file():
			return []
		since = now - max(1, int(window_min)) * 60
		with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
			rows = conn.execute(
				"SELECT prompt FROM memory_queue WHERE created_at >= ? AND length(trim(prompt)) > 0 ORDER BY created_at DESC LIMIT ?",
				(since, max(1, int(limit))),
			).fetchall()
		voces = [v for r in rows if (v := extract(str(r[0])))]
		return voces[: max(1, int(limit))]
	except Exception:
		return []


def current(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
	"""Estado de afecto vigente: del fichero si está fresco; si no, se recalcula.

	Sin turnos en la ventana devuelve el último estado conocido (o None): un
	silencio no es una emoción nueva.
	"""
	now = float(now if now is not None else time.time())
	ttl_s = max(1, int(getattr(cfg, "AFFECT_TTL_MIN", 15))) * 60
	state = _read_state()
	if state and now - float(state.get("computed_at") or 0) < ttl_s:
		return state
	prompts = _recent_prompts(
		limit=int(getattr(cfg, "AFFECT_TURNS", 8)),
		window_min=int(getattr(cfg, "AFFECT_WINDOW_MIN", 180)),
		now=now,
	)
	if not prompts:
		return state
	resultado = classify(prompts)
	resultado["computed_at"] = now
	resultado["turns"] = len(prompts)
	_write_state(resultado)
	return resultado
