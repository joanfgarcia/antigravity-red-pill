#!/usr/bin/env python3
"""compose.py — cadena de música SIMBÓLICA 100% libre (LLM → MIDI → FluidSynth → WAV).

Genera música desde una descripción textual construyendo un **MIDI** (mido) y
renderizándolo con **FluidSynth** + un **soundfont libre** (SF2). No requiere
GPU ni modelos de onda: pesa KB y corre en CPU.

Cadena:
  1. `--llm-prompt "..."`  → pide a un LLM local (endpoint red-pill) un JSON de
     arreglo musical (tempo/clave/progresión/barras).
  2. `--spec spec.json`    → usa un arreglo dado.
  3. `--demo`              → arreglo fijo (para probar el pipeline).
  → `compose_midi(spec)` (mido) → `<out>.mid`
  → `fluidsynth -ni <sf2> <out>.mid -F <out>.wav -r 44100`

Rutas configurables: MUSIC_FORGE_HOME (def ~/opt/music-forge), MUSIC_SF2
(def /usr/share/sounds/sf2/TimGM6mb.sf2), REDPILL_LLM_URL (def http://localhost:8760).

Uso:
  python compose.py --demo --out out/song
  python compose.py --spec arreglo.json --out out/song
  python compose.py --llm-prompt "lofi hip hop relajante en Do mayor" --out out/song
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

# Nota MIDI (C4 = 60) y grados de la escala mayor.
SEMITONES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
	"F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
MAJOR = [0, 2, 4, 5, 7, 9, 11]
_ES = {"do": "C", "re": "D", "mi": "E", "fa": "F", "sol": "G", "la": "A", "si": "B"}


def _norm_key(k: str) -> str:
	"""Normaliza la clave a una nota en letra inglesa (acepta 'La', 'Am', 'C#', 'Sol')."""
	if not k:
		return "C"
	low = k.strip().lower()
	for es, en in _ES.items():
		if low.startswith(es):
			k = en + k[len(es):]
			break
	m = re.match(r"([A-Ga-g])([#b]?)", k)
	root = (m.group(1).upper() + m.group(2)) if m else "C"
	return root if root in SEMITONES else "C"

# Progresiones por grado (0-based) → semitonos de la tríada sobre la tónica.
ROMAN = {"I": (0, 4, 7), "ii": (2, 5, 9), "iii": (4, 7, 11), "IV": (5, 9, 12),
	"V": (7, 11, 14), "vi": (9, 12, 16), "iv": (5, 8, 12), "i": (0, 3, 7), "v": (7, 10, 14)}


def _note(key: str, semi: int, octave: int = 4) -> int:
	return 12 * (octave + 1) + SEMITONES[key] + semi


def _proc(home: Path, sf2: Path, out_base: Path, mid: Path) -> Path:
	out_wav = out_base.with_suffix(".wav")
	cmd = ["fluidsynth", "-ni", str(sf2), str(mid), "-F", str(out_wav), "-r", "44100"]
	subprocess.run(cmd, check=True)
	return out_wav


def _default_sf2() -> str:
	"""Soundfont por defecto: MUSIC_SF2 > MuseScore_General > GeneralUser GS > TimGM6mb."""
	env = os.environ.get("MUSIC_SF2")
	if env:
		return env
	base = Path.home() / ".local" / "share" / "red-pill" / "soundfonts"
	for c in (base / "MuseScore_General.sf2", base / "GeneralUser-GS.sf2", Path("/usr/share/sounds/sf2/TimGM6mb.sf2")):
		if c.exists():
			return str(c)
	return "/usr/share/sounds/sf2/TimGM6mb.sf2"


def compose_midi(spec: dict, mid_path: Path) -> None:
	import mido

	tempo = int(spec.get("tempo", 100))
	key = _norm_key(spec.get("key", "C"))
	prog = spec.get("progression", ["I", "V", "vi", "IV"]) or ["I", "V", "vi", "IV"]
	bars = int(spec.get("bars", 8))
	beats_per_bar = 4

	ticks = 480
	mid = mido.MidiFile(ticks_per_beat=ticks)

	def _track(name, channel, program):
		t = mido.MidiTrack()
		t.append(mido.MetaMessage("track_name", name=name, time=0))
		t.append(mido.Message("program_change", channel=channel, program=program, time=0))
		return t

	# Programas GM: E.Piano (4), Strings pad (48), E.Bass (33), Flute (73).
	chords = _track("chords_epiano", 0, 4)
	pad = _track("pad_strings", 3, 48)
	bass = _track("bass", 1, 33)
	melody = _track("lead_flute", 2, 73)
	drums = _track("drums", 9, 0)
	meta = mido.MidiTrack()
	meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo)))
	meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))

	hh = ticks // 2  # corchea

	for bar in range(bars):
		roman = prog[bar % len(prog)]
		triad = ROMAN.get(roman, (0, 4, 7))
		# Chords (E.Piano): tríada por compás, ligero arpegio en la 2ª mitad.
		for s in triad:
			chords.append(mido.Message("note_on", channel=0, note=_note(key, s, 3), velocity=68, time=0))
		chords.append(mido.Message("note_off", channel=0, note=_note(key, triad[0], 3), time=ticks * 2))
		for s in triad[1:]:
			chords.append(mido.Message("note_off", channel=0, note=_note(key, s, 3), time=0))
		for s in triad:
			chords.append(mido.Message("note_on", channel=0, note=_note(key, s, 3), velocity=60, time=0))
		chords.append(mido.Message("note_off", channel=0, note=_note(key, triad[0], 3), time=ticks * 2))
		for s in triad[1:]:
			chords.append(mido.Message("note_off", channel=0, note=_note(key, s, 3), time=0))
		# Pad (Strings): tríada sostenida todo el compás, octava 4.
		for s in triad:
			pad.append(mido.Message("note_on", channel=3, note=_note(key, s, 4), velocity=45, time=0))
		pad.append(mido.Message("note_off", channel=3, note=_note(key, triad[0], 4), time=ticks * beats_per_bar))
		for s in triad[1:]:
			pad.append(mido.Message("note_off", channel=3, note=_note(key, s, 4), time=0))
		# Bass: raíz + quinta en negras.
		root = _note(key, triad[0], 2)
		fifth = _note(key, triad[0] + 7, 2)
		for b in range(beats_per_bar):
			n = root if b % 2 == 0 else fifth
			bass.append(mido.Message("note_on", channel=1, note=n, velocity=82, time=0))
			bass.append(mido.Message("note_off", channel=1, note=n, time=ticks - 20))
			bass.append(mido.Message("note_on", channel=1, note=root, velocity=40, time=0))
			bass.append(mido.Message("note_off", channel=1, note=root, time=20))
		# Drums GM: bombo 36, caja 38, hi-hat 42, ride 51.
		for b in range(beats_per_bar * 2):
			beat = b // 2
			drums.append(mido.Message("note_on", channel=9, note=42, velocity=58, time=0))
			drums.append(mido.Message("note_off", channel=9, note=42, time=hh - 10))
			if beat in (0, 2):
				drums.append(mido.Message("note_on", channel=9, note=36, velocity=102, time=0))
				drums.append(mido.Message("note_off", channel=9, note=36, time=10))
			if beat in (1, 3):
				drums.append(mido.Message("note_on", channel=9, note=38, velocity=96, time=0))
				drums.append(mido.Message("note_off", channel=9, note=38, time=10))
		# Melody (Flute): escala sobre el acorde.
		scale = [MAJOR[i % 7] + 12 * (i // 7) for i in range(8)]
		for i in range(beats_per_bar):
			s = scale[(bar * 3 + i) % len(scale)]
			n = _note(key, s, 5)
			melody.append(mido.Message("note_on", channel=2, note=n, velocity=78, time=0))
			melody.append(mido.Message("note_off", channel=2, note=n, time=ticks))

	mid.tracks.extend([meta, chords, pad, bass, drums, melody])
	mid_path.parent.mkdir(parents=True, exist_ok=True)
	mid.save(str(mid_path))


def _llm_spec(prompt: str) -> dict:
	"""Pide a un LLM local (endpoint red-pill, OpenAI-compatible) un JSON de arreglo."""
	url = os.environ.get("REDPILL_LLM_URL", "http://localhost:8760").rstrip("/")
	# RULE 5 (PROMPT-001): el system prompt es un RECURSO declarado, no un string inline.
	system = (Path(__file__).resolve().parent / "prompts" / "composer_system.txt").read_text(encoding="utf-8").strip()
	req_body = json.dumps({
		"messages": [
			{"role": "system", "content": system},
			{"role": "user", "content": prompt},
		],
		"temperature": 0.7, "max_tokens": 256,
	}).encode()
	req = urllib.request.Request(f"{url}/v1/chat/completions", data=req_body, headers={"Content-Type": "application/json"})
	with urllib.request.urlopen(req, timeout=120) as r:
		data = json.loads(r.read())
	content = data["choices"][0]["message"]["content"]
	start, end = content.find("{"), content.rfind("}")
	return json.loads(content[start:end + 1])


DEMO = {"tempo": 92, "key": "C", "progression": ["I", "V", "vi", "IV"], "bars": 8}


def main() -> int:
	ap = argparse.ArgumentParser(description="Música simbólica libre: LLM→MIDI→FluidSynth→WAV")
	ap.add_argument("--demo", action="store_true")
	ap.add_argument("--spec")
	ap.add_argument("--llm-prompt")
	ap.add_argument("--out", default="out/song")
	ap.add_argument("--sf2", default=_default_sf2())
	args = ap.parse_args()

	import shutil

	if not shutil.which("fluidsynth"):
		print("[!] fluidsynth no está instalado. Instálalo (requiere sudo): sudo apt install fluidsynth")
		return 3

	if args.llm_prompt:
		spec = _llm_spec(args.llm_prompt)
	elif args.spec:
		spec = json.loads(Path(args.spec).read_text())
	else:
		spec = DEMO

	sf2 = Path(args.sf2)
	if not sf2.exists():
		print(f"[!] soundfont no encontrado: {sf2}")
		return 4

	out_base = Path(args.out)
	mid = out_base.with_suffix(".mid")
	compose_midi(spec, mid)
	wav = _proc(Path(os.environ.get("MUSIC_FORGE_HOME", Path.home() / "opt" / "music-forge")), sf2, out_base, mid)
	print(f"[ok] spec={spec}")
	print(f"[ok] midi={mid}")
	print(f"[ok] wav ={wav}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
