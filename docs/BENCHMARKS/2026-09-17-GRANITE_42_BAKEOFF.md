# Bake-off Granite 4.2 vs 4.1 — 2026-09-17 15:40

## granite_4_2_8b
- entidades: {"valid": false, "reason": "no JSON"}
- decision: {"valid": false, "reason": "no JSON"}
- filosofico: {"valid": false, "reason": "no JSON"}
- genero: {"valid": false, "reason": "no JSON"}

## granite_8b
- entidades: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": true, "relics": {"got": 3, "verbatim": 3}}
- decision: {"valid": true, "lang": "es", "mode_b": true, "bad_2nd": [], "genero_fem": false, "relics": {"got": 2, "verbatim": 2}}
- filosofico: {"valid": false, "reason": "no JSON"}
- genero: {"valid": false, "reason": "no JSON"}

## granite_4_2_3b
- cenicienta: {"valid": false, "reason": "json: Expecting value: line 1 column 21 (char 20)"}
- abrumada: {"valid": false, "reason": "no JSON"}
- correcto: {"valid": false, "reason": "no JSON"}
- voz3a: {"valid": false, "reason": "json: Expecting value: line 1 column 21 (char 20)"}
- cansada: {"valid": false, "reason": "json: Expecting value: line 1 column 21 (char 20)"}

## granite_3b
- cenicienta: {"valid": true, "acierto": false, "got": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": true}, "esperado": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": true}}
- abrumada: {"valid": true, "acierto": true, "got": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": false}, "esperado": {"genero_femenino": true, "voz_3a": false, "identidad_inestable": false}}
- correcto: {"valid": true, "acierto": false, "got": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}, "esperado": {"genero_femenino": false, "voz_3a": false, "identidad_inestable": false}}
- voz3a: {"valid": true, "acierto": true, "got": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}, "esperado": {"genero_femenino": false, "voz_3a": true, "identidad_inestable": false}}
- cansada: {"valid": true, "acierto": false, "got": {"genero_femenino": true, "voz_3a": true, "identidad_inestable": false}, "esperado": {"genero_femenino": true, "voz_3a": true, "identidad_inestable": true}}
