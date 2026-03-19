import logging
import os
from typing import Any, Dict, List, Optional

# Force CPU to avoid CUDA library mismatch in BERT
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

logger = logging.getLogger(__name__)

# Singleton for the emotion classifier to avoid reloading
_classifier = None
_model_failed = False


def get_emotions(text: str, top_k: int = 3, threshold: float = 0.2) -> List[Dict[str, Any]]:
	"""
	Detect multiple emotions in text.
	Returns a list of {label, score}.
	"""
	global _classifier, _model_failed
	
	if _model_failed:
		return []
		
	try:
		if _classifier is None:
			from transformers import pipeline

			logger.info("Loading BERT-Emotion model (boltuix/bert-emotion) on CPU...")  # pragma: no cover
			_classifier = pipeline("text-classification", model="boltuix/bert-emotion", device="cpu", top_k=top_k)  # pragma: no cover

		results = _classifier(text)
		if isinstance(results, dict):
			results = [results]

		# Flatten if nested
		if results and isinstance(results[0], list):
			results = results[0]

		filtered = [{"label": str(r["label"]).lower(), "score": float(r["score"])} for r in results if float(r["score"]) >= threshold]
		return filtered
	except Exception as e:
		_model_failed = True
		logger.warning(f"Multi-emotion model missing/failed (disabling module): {e}")
		return []


def get_emotion(text: str) -> Optional[str]:
	"""Legacy single-emotion detector."""
	emotions = get_emotions(text, top_k=1)
	if emotions:
		return str(emotions[0]["label"])
	return None


EMOTION_CHROMA_MAP = {
	"happiness": "yellow",
	"love": "orange",
	"surprise": "cyan",
	"neutral": "gray",
	"sadness": "blue",
	"fear": "purple",
	"anger": "red",
	"disgust": "green",
	"shame": "purple",
	"guilt": "blue",
	"confusion": "cyan",
	"desire": "orange",
	"sarcasm": "yellow",
}


def get_chroma_for_emotion(emotion: str) -> str:
	return EMOTION_CHROMA_MAP.get(emotion.lower(), "gray")
