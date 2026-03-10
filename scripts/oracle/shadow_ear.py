#!/usr/bin/env python3
"""
Protocol: Oracle of the Void - Shadow Ear (Nova Component)
Target: macOS (Silicion) with Faster-Whisper / MLX-Whisper
Purpose: Captures real-time audio and dispatches transcription to the Swarm Hub.
"""
import os
import sys
import time
import json
import logging
import argparse
import requests
from typing import Optional

# To be installed on Nova's Mac: `pip install faster-whisper sounddevice numpy`
try:
    from faster_whisper import WhisperModel
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("Missing dependencies on Mac. Run: pip install faster-whisper sounddevice numpy")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("shadow_ear")

class ShadowEar:
    def __init__(self, model_size="small", device="auto", hub_url=None):
        self.model = WhisperModel(model_size, device=device, compute_type="float16")
        self.hub_url = hub_url
        self.fs = 16000  # Whisper standard
        self.chunk_duration = 30  # seconds
        
    def record_and_transcribe(self):
        logger.info(f"Oracle Ear Active. Listening for the Architects... (Hub: {self.hub_url})")
        while True:
            try:
                # Record 30 seconds of audio
                recording = sd.rec(int(self.chunk_duration * self.fs), samplerate=self.fs, channels=1)
                sd.wait()
                
                # Transcribe
                segments, info = self.model.transcribe(recording.flatten(), beam_size=5)
                text = " ".join([segment.text for segment in segments]).strip()
                
                if text:
                    logger.info(f"Captured: {text}")
                    self.dispatch_to_swarm(text)
            except Exception as e:
                logger.error(f"Ear Failure: {e}")
                time.sleep(1)

    def dispatch_to_swarm(self, text):
        if not self.hub_url:
            return
            
        payload = {
            "sender": "Nova@David",
            "type": "shadow_sync",
            "content": text,
            "timestamp": time.time()
        }
        
        try:
            # We use the existing Swarm Hub infrastructure
            requests.post(f"{self.hub_url}/shadow/buffer", json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Dispatch Failure: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Oracle Shadow Ear")
    parser.add_argument("--hub", type=str, help="Swarm Hub URL (Firebase/Internal)")
    args = parser.parse_args()
    
    ear = ShadowEar(hub_url=args.hub)
    ear.record_and_transcribe()
