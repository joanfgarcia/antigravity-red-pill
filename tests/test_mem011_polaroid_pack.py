"""MEM-011 · F0 — el empaquetado de polaroids es determinista y no reparte nada.

Estos tests fijan los bordes del contrato: la polaroid no se parte, la que excede
el presupuesto va entera, `k <= N` por construcción y una sola parte no se
materializa.
"""

from red_pill.memento.polaroid_pack import (
	PackedPart,
	needs_parts,
	oversized_polaroids,
	pack_polaroids,
	part_index_for,
)


def test_fusiona_adyacentes_hasta_el_presupuesto():
	# 3 polaroids de 4 chars, presupuesto 10 -> [0-1] + [2]
	assert pack_polaroids([4, 4, 4], 10) == [PackedPart(0, 1), PackedPart(2, 2)]


def test_no_fusiona_si_no_cabe():
	# 6+6 = 12 > 10 -> cada una sola (y k == N, el techo se cumple solo)
	assert pack_polaroids([6, 6, 6], 10) == [PackedPart(0, 0), PackedPart(1, 1), PackedPart(2, 2)]


def test_polaroid_que_excede_va_entera_y_sola():
	chars = [3, 12, 4]
	parts = pack_polaroids(chars, 10)
	assert parts == [PackedPart(0, 0), PackedPart(1, 1), PackedPart(2, 2)]
	# Y se reporta como oversized: no se trocea, se sintetiza con map-reduce.
	assert oversized_polaroids(chars, 10) == [1]


def test_polaroid_vacia_se_adhieren_a_la_adyacente():
	# Una polaroid sin hojas no abre parte: los rangos siguen contiguos y k baja.
	assert pack_polaroids([0, 5, 0], 10) == [PackedPart(0, 2)]
	assert needs_parts([PackedPart(0, 2)]) is False


def test_sesion_que_cabe_en_una_parte_no_genera_partes():
	parts = pack_polaroids([4, 3, 2], 8000)
	assert parts == [PackedPart(0, 2)]
	assert needs_parts(parts) is False


def test_k_nunca_supera_el_numero_de_polaroids():
	chars = [6, 6, 6, 6, 6, 6]
	parts = pack_polaroids(chars, 10)
	assert len(parts) <= len(chars)
	assert parts[0].start == 0 and parts[-1].end == len(chars) - 1


def test_presupuesto_cero_es_una_sola_parte():
	assert pack_polaroids([5, 5, 5], 0) == [PackedPart(0, 2)]


def test_mapeo_engrama_polaroid_parte():
	parts = pack_polaroids([5, 5, 5], 10)  # [0-1] (10) + [2]
	assert parts == [PackedPart(0, 1), PackedPart(2, 2)]
	assert [part_index_for(i, parts) for i in range(3)] == [0, 0, 1]
	assert part_index_for(9, parts) is None
