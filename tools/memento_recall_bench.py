#!/usr/bin/env python3
"""memento_recall_bench.py — banco de recall de la memoria curada (solo lectura).

Nace del feedback de recall del 2026-09-25: medir antes de encender. Para cada
consulta del banco comprueba si el top-k de work+social contiene una nota que
**trate el hecho** (patrones del hecho sobre el `content`, no las palabras de la
consulta), bajo varias configuraciones de recuperación:

	A plano · B plano+MMR · C plano+híbrido+MMR · D enriquecido · E enriq+MMR · F enriq+híbrido+MMR

Todo en memoria (numpy): no escribe en Qdrant ni refuerza recuerdos (el recall
real refuerza lo que recupera y ensuciaría la medida). `--model` re-embebe el
corpus en memoria con otro embedder de fastembed para compararlo con el vigente
(bake-off; la primera vez fastembed DESCARGA el modelo).

Banco de consultas: `~/.config/red-pill/recall_probes.yaml` (config del operador:
contiene hechos personales, jamás en el repo público) o `--probes`. Plantilla:
`examples/recall_probes.yaml.example`.

Uso:
	uv run python tools/memento_recall_bench.py
	uv run python tools/memento_recall_bench.py --lambda 0.7
	uv run python tools/memento_recall_bench.py --model jinaai/jina-embeddings-v2-base-es --configs A,C
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import yaml

CONFIGS = {
	"A": ("plano", "P", False, False),
	"B": ("plano+MMR", "P", True, False),
	"C": ("plano+híbrido+MMR", "P", True, True),
	"D": ("enriquecido", "E", False, False),
	"E": ("enriq+MMR", "E", True, False),
	"F": ("enriq+híbrido+MMR", "E", True, True),
}
KS = (3, 5)


def load_probes(path: Path) -> List[Dict[str, Any]]:
	data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
	probes = data.get("probes") or []
	for p in probes:
		if not p.get("id") or not p.get("query") or not p.get("patterns"):
			raise SystemExit(f"[bench] consulta mal formada en {path}: {p}")
	return probes


def relevant(text: str, patterns: Sequence[str]) -> bool:
	"""Todas las expresiones del hecho aparecen en la nota (AND de patrones, sin mayúsculas)."""
	return all(re.search(p, text, re.IGNORECASE) for p in patterns)


def _normalize(m: np.ndarray) -> np.ndarray:
	n = np.linalg.norm(m, axis=1, keepdims=True)
	n[n == 0] = 1.0
	return m / n


def rank(
	qv: np.ndarray, matrix: np.ndarray, ids: List[str], idx: Dict[str, int], query: str, use_mmr: bool, use_kw: bool, k: int, lam: float, root: Path
) -> List[str]:
	from red_pill.memento import hybrid as hy

	top = list(np.argsort(-(matrix @ qv))[: k * 4])
	rankings = [[ids[i] for i in top]]
	if use_kw:
		rankings.append([pid for pid, _ in hy.memento_keyword_hits(query, "", root=root, limit=k * 4) if pid in idx])
	fused = hy.rrf_scores(rankings)
	cand = [pid for pid, _ in fused]
	if use_mmr:
		return hy.mmr_select(qv, cand, [matrix[idx[c]] for c in cand], k, lam=lam, relevance=[sc for _, sc in fused])
	return cand[:k]


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--probes", type=Path, default=None, help="YAML del banco (default: ~/.config/red-pill/recall_probes.yaml).")
	parser.add_argument("--lambda", dest="lam", type=float, default=None, help="λ del MMR (default: MEMORY_RECALL_MMR_LAMBDA).")
	parser.add_argument("--configs", default="A,B,C,D,E,F", help="Configuraciones a medir (letras separadas por comas).")
	parser.add_argument("--model", default=None, help="Otro embedder de fastembed para el bake-off (re-embebe en memoria).")
	args = parser.parse_args()

	from qdrant_client import QdrantClient

	import red_pill.config as cfg
	from red_pill.core.paths import get_config_dir
	from red_pill.memento import get_memento_root
	from red_pill.memento.embed_text import engram_embed_text

	probes_path = args.probes or Path(get_config_dir()) / "recall_probes.yaml"
	if not probes_path.exists():
		sys.exit(f"[bench] no hay banco en {probes_path} — copia examples/recall_probes.yaml.example y rellénalo")
	probes = load_probes(probes_path)
	lam = float(args.lam if args.lam is not None else getattr(cfg, "MEMORY_RECALL_MMR_LAMBDA", 0.85))
	wanted = [c.strip().upper() for c in args.configs.split(",") if c.strip().upper() in CONFIGS]
	root = Path(get_memento_root())

	client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
	points: List[Tuple[str, Any]] = []
	for col in ("work_memories", "social_memories"):
		offset = None
		while True:
			batch, offset = client.scroll(
				col, limit=1000, offset=offset, with_vectors=args.model is None, with_payload=["content", "theme", "relics"]
			)
			points += [(col, p) for p in batch]
			if offset is None:
				break
	ids = [str(p.id) for _, p in points]
	idx = {pid: i for i, pid in enumerate(ids)}
	content = [str((p.payload or {}).get("content") or "") for _, p in points]
	enriched = [engram_embed_text(content[i], (p.payload or {}).get("theme"), (p.payload or {}).get("relics")) for i, (_, p) in enumerate(points)]

	if args.model:
		from fastembed import TextEmbedding

		encoder = TextEmbedding(model_name=args.model)
		embed = lambda texts: np.array(list(encoder.embed(list(texts), batch_size=64)), dtype=float)  # noqa: E731
		print(f"[bench] re-embebiendo {len(ids)} notas con {args.model} (en memoria)…")
		plain = _normalize(embed(content))
	else:
		from red_pill.core.embeddings import EmbeddingEngine

		engine = EmbeddingEngine()
		engine.get_vector("warmup")
		encoder = engine.encoder
		embed = lambda texts: np.array(list(encoder.embed(list(texts), batch_size=64)), dtype=float)  # noqa: E731
		plain = _normalize(np.array([p.vector for _, p in points], dtype=float))
	needs_e = any(CONFIGS[c][1] == "E" for c in wanted)
	enr = _normalize(embed(enriched)) if needs_e else None

	hits = {c: {k: 0 for k in KS} for c in wanted}
	first: Dict[str, Dict[str, Any]] = {}
	for probe in probes:
		qv = _normalize(embed([probe["query"]]))[0]
		for c in wanted:
			_, mat, use_mmr, use_kw = CONFIGS[c]
			matrix = plain if mat == "P" else enr
			assert matrix is not None
			sel = rank(qv, matrix, ids, idx, probe["query"], use_mmr, use_kw, max(KS), lam, root)
			for k in KS:
				if any(relevant(content[idx[s]], probe["patterns"]) for s in sel[:k]):
					hits[c][k] += 1
			first.setdefault(probe["id"], {})[c] = next((r + 1 for r, s in enumerate(sel) if relevant(content[idx[s]], probe["patterns"])), None)

	n = len(probes)
	print(f"\nmodelo: {args.model or cfg.EMBEDDING_MODEL} · λ={lam} · {n} consultas · {len(ids)} notas")
	print(f"{'config':26s}  hit@3   hit@5")
	for c in wanted:
		print(f"{c} {CONFIGS[c][0]:24s}  {hits[c][3]:2d}/{n}   {hits[c][5]:2d}/{n}")
	print("\nrango del primer acierto (— = fuera del top-5):")
	print(f"{'':16s}" + "".join(f"{c:>4s}" for c in wanted))
	for pid, row in first.items():
		print(f"{pid:16s}" + "".join(f"{(str(row[c]) if row[c] else '—'):>4s}" for c in wanted))


if __name__ == "__main__":
	main()
