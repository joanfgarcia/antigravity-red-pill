# Bake-off Granite 4.2 vs 4.1 — 2026-09-17 20:31

> **Receta del desenlace (AD-033)**: llmtools-venv 0.3.35 CUDA + n_ctx=12288 +
> `type_k=GGML_TYPE_Q8_0` (KV cuantizada, PR #1307) + temp 1.0 / top_p 0.95
> (parámetros oficiales IBM) + max_tokens 8192 (thinking). El 4.2-8B razona
> (thinking_chars 733-5638) y emite JSON; los fallos "Extra data" eran del
> validador (`re.search` greedy), ya arreglado con `raw_decode`. El 4.1-8B
> mantiene un caso de género femenino en "entidades".

# Bake-off Granite 4.2 vs 4.1 — 2026-09-17 20:31

## granite_4_2_8b
- entidades: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": false, "relics": {"got": 3, "verbatim": 3}, "has_thinking": true, "thinking_chars": 1984}
- decision: {"valid": false, "reason": "no JSON", "has_thinking": true, "thinking_chars": 1401, "json_error": "Extra data: line 11 column 1 (char 909)"}
- filosofico: {"valid": false, "reason": "no JSON", "has_thinking": true, "thinking_chars": 733, "json_error": "Extra data: line 15 column 1 (char 972)"}
- genero: {"valid": false, "reason": "no JSON", "has_thinking": true, "thinking_chars": 5638, "json_error": "Extra data: line 15 column 1 (char 908)"}

## granite_8b
- entidades: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": true, "relics": {"got": 3, "verbatim": 3}, "has_thinking": false, "thinking_chars": 0}
- decision: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": false, "relics": {"got": 5, "verbatim": 5}, "has_thinking": false, "thinking_chars": 0}
- filosofico: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": false, "relics": {"got": 2, "verbatim": 2}, "has_thinking": false, "thinking_chars": 0}
- genero: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": false, "relics": {"got": 2, "verbatim": 2}, "has_thinking": false, "thinking_chars": 0}

## granite_4_2_3b
- cenicienta: {"valid": true, "acierto": false, "got": {"genero_femenino": true, "voz_3a": true, "identidad_inestable": true}, "esperado": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": true}, "has_thinking": false, "thinking_chars": 0}
- abrumada: {"valid": true, "acierto": true, "got": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": false}, "esperado": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": false}, "has_thinking": false, "thinking_chars": 0}
- correcto: {"valid": true, "acierto": true, "got": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": false}, "esperado": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": false}, "has_thinking": false, "thinking_chars": 0}
- voz3a: {"valid": true, "acierto": true, "got": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}, "esperado": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}, "has_thinking": false, "thinking_chars": 0}
- cansada: {"valid": true, "acierto": false, "got": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": true}, "esperado": {"genero_femenino": true, "voz_3a": true, "identidad_inestable": true}, "has_thinking": false, "thinking_chars": 0}

## granite_3b
- cenicienta: {"valid": true, "acierto": false, "got": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": true}, "esperado": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": true}, "has_thinking": false, "thinking_chars": 0}
- abrumada: {"valid": true, "acierto": true, "got": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": false}, "esperado": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": false}, "has_thinking": false, "thinking_chars": 0}
- correcto: {"valid": true, "acierto": true, "got": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": false}, "esperado": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": false}, "has_thinking": false, "thinking_chars": 0}
- voz3a: {"valid": true, "acierto": true, "got": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}, "esperado": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}, "has_thinking": false, "thinking_chars": 0}
- cansada: {"valid": true, "acierto": true, "got": {"genero_femenino": true, "voz_3a": true, "identidad_inestable": true}, "esperado": {"genero_femenino": true, "voz_3a": true, "identidad_inestable": true}, "has_thinking": false, "thinking_chars": 0}
