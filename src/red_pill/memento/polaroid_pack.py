"""Empaquetado de polaroids en hubs (MEM-011, Ola 0).

Regla del contrato (determinista, sin interpretación):

1. La **unidad** es la polaroid (una unidad renderizada de Memento).
2. Se **fusionan polaroids adyacentes** mientras la suma del cuerpo de sus hojas
	quepa en el presupuesto.
3. Una polaroid **nunca se reparte** entre dos partes: si sola excede el
	presupuesto, forma su propia parte (`oversized`) y se sintetiza con el
	map-reduce existente.
4. `k <= N` por construcción (cada parte consume >=1 polaroid), así que no hace
	falta ninguna fusión correctiva posterior.
5. Si sale una sola parte, no hay partes: la raíz es el único nodo.

Este módulo es puro (sin Qdrant, sin LLM): lo usa el censo de F0 y, en F1, la
síntesis. Las polaroids de tamaño 0 (sin hojas ascendidas) no abren parte: se
adhieren a la adyacente para que los rangos sigan siendo contiguos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PackedPart:
	"""Una parte: rango **inclusivo** de índices de polaroid."""

	start: int
	end: int

	@property
	def width(self) -> int:
		return self.end - self.start + 1

	def contains(self, polaroid_index: int) -> bool:
		return self.start <= polaroid_index <= self.end


def pack_polaroids(polaroid_chars: Sequence[int], budget: int) -> list[PackedPart]:
	"""Agrupa polaroids contiguas respetando el presupuesto.

	- `polaroid_chars`: cuerpo agregado (chars) de las hojas de cada polaroid, en
		orden de mensaje.
	- `budget`: presupuesto de síntesis por parte (chars). <=0 se trata como
		"sin presupuesto": todo cabe en una parte.
	"""
	if budget <= 0:
		return [PackedPart(0, max(0, len(polaroid_chars) - 1))] if polaroid_chars else []

	parts: list[PackedPart] = []
	start = 0
	acc = 0
	for idx, chars in enumerate(polaroid_chars):
		size = max(0, int(chars))
		oversized = size > budget
		if oversized:
			# Cierra lo acumulado y esta polaroid va sola.
			if idx > start:
				parts.append(PackedPart(start, idx - 1))
			parts.append(PackedPart(idx, idx))
			start = idx + 1
			acc = 0
			continue
		if acc and acc + size > budget:
			parts.append(PackedPart(start, idx - 1))
			start = idx
			acc = 0
		acc += size
	if start < len(polaroid_chars):
		parts.append(PackedPart(start, len(polaroid_chars) - 1))
	return parts


def oversized_polaroids(polaroid_chars: Sequence[int], budget: int) -> list[int]:
	"""Índices de polaroids que, solas, exceden el presupuesto (van enteras)."""
	if budget <= 0:
		return []
	return [idx for idx, chars in enumerate(polaroid_chars) if int(chars) > budget]


def needs_parts(parts: Sequence[PackedPart]) -> bool:
	"""Una sola parte no se materializa: la raíz es el único nodo (punto 5)."""
	return len(parts) > 1


def part_index_for(polaroid_index: int, parts: Sequence[PackedPart]) -> int | None:
	"""Parte que contiene una polaroid (`engrama -> polaroid -> parte`)."""
	for idx, part in enumerate(parts):
		if part.contains(polaroid_index):
			return idx
	return None
