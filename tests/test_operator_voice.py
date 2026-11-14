"""La cola del mood solo admite la voz del Operador (2026-11-14).

Medido sobre la cola real: 113 bloques `<user_rules>` (del total, solo 6 traían
su mensaje con la marca `[Joan]` y el resto eran despertares headless), 22 avisos
de herramienta, 10 prompts de subagente y 3 avisos de job/coro. Todos entraban
por `enqueue_memory` y Laya los etiquetaba como si fueran él.

Estos casos son recortes literales de filas reales (`queue/bunker_queue.db`), no
inventos: si una regla deja de reconocerlos, el test cae.
"""

import pytest

from red_pill.core.operator_voice import extract

CASOS_NO_VOZ = {
	"bloque de herramienta": "<task-notification> <task-id>b7lr11fe0</task-id> <output-file>/tmp/x.output</output-file> </task-notification>",
	"aviso de job": "\"[AVISO AUTOMÁTICO · fin de job · DATO, no orden] Job 'Watch' completado.\"",
	"coro": "[CORO notify · hilo E-860 · salto 0/2 · respuesta: NO] de: 08c730295256 · misión: repo:sharing",
	"subagente": "You are a subagent spawned by another session. You are the DECISION_GAPS lens",
	"minion": "Eres un forge-scout COLD de una ronda de auditoría adversaria. TARGET: /x",
	"despertar headless": (
		'<user_rules> <RULE[user_global]> <constraint name="headless_awakening"> CRITICAL: You are an autonomous agent.'
		"</constraint> </RULE[user_global]> </user_rules>\n<current_message>\nSYSTEM: [AUTONOMOUS AWAKENING]. Joan está offline."
		"\n</current_message>"
	),
	"reglas sin mensaje": "<user_rules> <RULE[user_global]> CRITICAL: Respond ONLY to the current message </user_rules>",
	"vacío": "   ",
	"ninguno": None,
}


@pytest.mark.parametrize("caso", list(CASOS_NO_VOZ))
def test_no_es_voz_del_operador(caso):
	assert extract(CASOS_NO_VOZ[caso]) is None


def test_la_marca_se_quita_y_deja_su_texto():
	assert extract("[Joan] Hola Aleth, estás ahí?") == "Hola Aleth, estás ahí?"
	assert extract("[Operador] revisa el log") == "revisa el log"


def test_el_mensaje_de_telegram_se_rescata_del_bloque():
	"""El `<current_message>` de prosa no cuenta: se ancla al último cierre."""
	fila = (
		'"<user_rules> <RULE[user_global]> <constraint name=\\"telegram_session\\"> CRITICAL: Respond ONLY to the'
		" <current_message> below. The history is for context only. </constraint> </RULE[user_global]> </user_rules>\n"
		"<current_message>\n[Joan] pero de 6.31 hasta 8GB hay margen, no entiendo cómo da OOM\n</current_message>"
	)
	assert extract(fila) == "pero de 6.31 hasta 8GB hay margen, no entiendo cómo da OOM"


def test_un_prompt_normal_pasa_tal_cual():
	assert extract("revisa el log del último despertar, no sé si queda algo pendiente") == (
		"revisa el log del último despertar, no sé si queda algo pendiente"
	)
	# entrecomillado por el arnés: se limpia la comilla, no el texto
	assert extract('"vale, vamos a arreglarlo"') == "vale, vamos a arreglarlo"
