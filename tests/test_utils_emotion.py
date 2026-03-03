"""Tests for utils/emotion.py — targeting uncovered lines 20-32, 42, 64."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_classifier():
    """Reset the emotion classifier singleton before/after each test."""
    import red_pill.utils.emotion as em
    em._classifier = None
    yield
    em._classifier = None


class TestGetEmotions:
    def test_classifier_invoked_on_call(self):
        """Lines 17-23: classifier is set externally → invoked directly."""
        import red_pill.utils.emotion as em
        mock_clf = MagicMock(return_value=[{"label": "JOY", "score": 0.9}])
        em._classifier = mock_clf
        result = em.get_emotions("I am happy")
        mock_clf.assert_called_once_with("I am happy")
        assert isinstance(result, list)

    def test_returns_filtered_results(self):
        """Lines 23-32: classifier returns list, filtered by threshold."""
        import red_pill.utils.emotion as em
        mock_clf = MagicMock()
        mock_clf.return_value = [
            {"label": "JOY", "score": 0.95},
            {"label": "FEAR", "score": 0.05},  # below threshold=0.2
        ]
        em._classifier = mock_clf
        result = em.get_emotions("test", threshold=0.2)
        assert len(result) == 1
        assert result[0]["label"] == "joy"
        assert result[0]["score"] == pytest.approx(0.95)

    def test_handles_nested_list_results(self):
        """Lines 28-29: classifier returns nested list → flattened."""
        import red_pill.utils.emotion as em
        mock_clf = MagicMock()
        mock_clf.return_value = [[{"label": "anger", "score": 0.8}]]
        em._classifier = mock_clf
        result = em.get_emotions("rage")
        assert result[0]["label"] == "anger"

    def test_handles_dict_result(self):
        """Lines 24-25: classifier returns single dict → wrapped in list."""
        import red_pill.utils.emotion as em
        mock_clf = MagicMock()
        mock_clf.return_value = {"label": "sadness", "score": 0.7}
        em._classifier = mock_clf
        result = em.get_emotions("sad text")
        assert result[0]["label"] == "sadness"

    def test_exception_returns_empty(self):
        """Lines 33-35: any exception → returns []."""
        import red_pill.utils.emotion as em
        mock_clf = MagicMock(side_effect=RuntimeError("model crash"))
        em._classifier = mock_clf
        result = em.get_emotions("text")
        assert result == []


class TestGetEmotion:
    def test_returns_label_when_detected(self):
        """Line 42: emotions found → returns first label."""
        import red_pill.utils.emotion as em
        with patch.object(em, "get_emotions", return_value=[{"label": "joy", "score": 0.9}]):
            assert em.get_emotion("happy text") == "joy"

    def test_returns_none_when_no_emotions(self):
        """Lines 40-43: no emotions → returns None."""
        import red_pill.utils.emotion as em
        with patch.object(em, "get_emotions", return_value=[]):
            assert em.get_emotion("empty") is None


class TestGetChromaForEmotion:
    def test_known_emotion_returns_color(self):
        """Line 64: known emotion key → correct color."""
        from red_pill.utils.emotion import get_chroma_for_emotion
        assert get_chroma_for_emotion("anger") == "red"
        assert get_chroma_for_emotion("sadness") == "blue"
        assert get_chroma_for_emotion("HAPPINESS") == "yellow"  # case-insensitive

    def test_unknown_emotion_returns_gray(self):
        """Line 64: unknown emotion → default 'gray'."""
        from red_pill.utils.emotion import get_chroma_for_emotion
        assert get_chroma_for_emotion("unknown_emotion") == "gray"
