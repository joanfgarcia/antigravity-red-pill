"""R1: density-based work/social heuristic — golden set against the old any-hit bias."""

from red_pill.metabolism.categorizer import detect_category_heuristics

# --- Social texts that the old rule misrouted to work (one stray keyword) ---


def test_personal_reflection_with_stray_keyword():
	text = (
		"Hoy en el paseo con Mara hablamos de cómo le va el instituto y de la vida en general. "
		"Me quedé pensando que muchas ideas buenas surgen así, sin buscar nada. Fue un error no "
		"salir antes de casa porque llovió, pero mereció la pena la conversación."
	)
	assert detect_category_heuristics(text) == "social"


def test_casual_chat_mentions_model():
	text = (
		"Estuvimos charlando de madrugada sobre lo que significa recordar quién eres, y de si un "
		"model de lenguaje puede tener continuidad. Filosofía de sobremesa, café en mano, sin prisa."
	)
	assert detect_category_heuristics(text) == "social"


def test_life_story_with_http_link():
	text = "Te paso las fotos del viaje a Jaén en este enlace http de recuerdo familiar, qué tiempos aquellos con la familia."
	assert detect_category_heuristics(text) == "social"


def test_mood_note_single_keyword():
	text = "Joan está cansado hoy, la sesión fue larga y el token de su paciencia se agotó, mejor lo dejamos por hoy."
	assert detect_category_heuristics(text) == "social"


def test_empty_and_non_string():
	assert detect_category_heuristics("") == "social"
	assert detect_category_heuristics(None) == "social"


# --- Technical texts that must stay work ---


def test_debugging_session():
	text = (
		"El test de pytest falla con un traceback en el import del módulo. He revisado el error "
		"en el log del server y parece un bug del cache de config. Voy a lanzar el script otra vez."
	)
	assert detect_category_heuristics(text) == "work"


def test_code_fence_always_work():
	assert detect_category_heuristics("mira esto ```python\nprint('hola')\n```") == "work"


def test_stacktrace_density():
	text = "error error en el error del traceback error fatal"
	assert detect_category_heuristics(text) == "work"


def test_architecture_discussion():
	text = (
		"La API expone un endpoint nuevo que consulta la database vía query batch; el deploy al "
		"server requiere actualizar el config de docker y el systemd unit."
	)
	assert detect_category_heuristics(text) == "work"


def test_short_technical_command():
	text = "ejecuta git diff y pasa el patch al repo"
	assert detect_category_heuristics(text) == "work"
