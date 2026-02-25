import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Singleton for the emotion classifier to avoid reloading
_classifier = None

def get_emotion(text: str) -> Optional[str]:
	"""
	Detect emotion in text using boltuix/bert-emotion model.
	Optimized for edge performance.
	"""
	global _classifier
	try:
		if _classifier is None:
			from transformers import pipeline
			logger.info("Loading BERT-Emotion model (boltuix/bert-emotion)...")
			_classifier = pipeline("text-classification", model="boltuix/bert-emotion")
		
		result = _classifier(text)[0]
		label = result["label"].lower()
		score = result["score"]
		
		# Only return if confidence is decent
		if score > 0.4:
			return label
		return None
	except Exception as e:
		logger.warning(f"Emotion detection failed: {e}")
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
	"sarcasm": "yellow"
}

def get_chroma_for_emotion(emotion: str) -> str:
	return EMOTION_CHROMA_MAP.get(emotion.lower(), "gray")
