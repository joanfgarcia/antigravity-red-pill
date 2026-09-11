# Bake-off tool-calling — 2026-09-11

> 6 modelos vía `scripts/model_battle_tool.py` (bindings llama-cpp-python CUDA,
> venv sidecar, template NATIVO del GGUF). Resultados crudos por modelo en
> `TOOL_<modelo>_20260911-185*.jsonl`. Hallazgos que alimentan
> `Aleth_Core/design/RFC_INVENTARIO_MODELOS_HARNESS.md`.

## Matriz

| Modelo | simple | multi_sel | json_args | no_tool | multi_step | score |
|---|---|---|---|---|---|---|
| granite_8b | ✓ | ✓ | ✓ | ✓ | ✓(parcial) | 5/5 |
| qwen3_8b | ✓ | ✓ | ✓ | ✓ | ✓(parcial) | 5/5 |
| gemma4_e4b | ✓ | ✓ | ✗ | ✓ | ✓(parcial) | 4/5 |
| granite_3b | ✓ | ✓ | ✓ | ✓ | ✗ | 4/5 |
| qwen35_9b | ✗ | ✗ | ✗ | ✓ | ✗ | 1/5 |
| smollm3_3b | ✗ | ✗ | ✗ | ✓ | ✗ | 1/5 |

## Peculiaridades por modelo

1. **granite_8b / granite_3b / qwen3_8b** emiten `<tool_call>{json}</tool_call>`
   (formato qwen). Funcionan con `chat_format=None` (template nativo).
   ⚠️ **Forzar `chatml-function-calling` ROMPE granite** (responde en prosa):
   revisar el `minion_chat_format` de producción.
2. **gemma4_e4b** emite `<|tool_call>call:NAME{args}<tool_call|>` (parser
   dedicado). Falla `json_args` por pedir la fecha en vez de emitir ISO.
3. **smollm3_3b / qwen35_9b** entran en *extended thinking* y consumen el
   presupuesto antes de emitir el tool-call (qwen35 razona en prosa sin llegar a
   emitirlo) → requieren `thinking: off` (`/no_think`) o `max_tokens` mayor.

## Notas de método

- El harness de bindings necesita parsear los formatos NATIVOS (antes solo
  entendía OpenAI/JSON → falsos FAIL en gemma4 y granite).
- El run inicial (job `5b700c79`, chat_format forzado) quedó descartado por
  artefacto de harness; los JSONL de 18:53-18:57 son el run válido.
