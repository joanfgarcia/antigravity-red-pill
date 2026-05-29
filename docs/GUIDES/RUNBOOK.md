# 🚨 RUNBOOK OPERACIONAL — Manual de Supervivencia del Operator

> **Para Joan. Sin IA. Sin excusas.**
> Última actualización: 2026-05-28

---

## 0. TL;DR — Los 5 comandos que necesitas

```bash
# ¿Está todo vivo?
systemctl --user status redpill redpill-bunker redpill-echo redpill-llm

# ¿Qdrant funciona?
curl -s http://localhost:6333/collections | python3 -m json.tool | head -20

# Reiniciar todo
systemctl --user restart redpill redpill-bunker redpill-echo redpill-llm

# Backup de emergencia
cd ~/Documents/IA/sharing && .venv/bin/red-pill backup

# Ver logs
journalctl --user -u redpill -n 50 --no-pager
```

---

## 1. Servicios — Qué es cada cosa

| Servicio | Qué hace | Si se muere... |
|---|---|---|
| `redpill.service` | CNS principal (Lazarus Pulse, Syntax Guard) | Se pierde la vigilancia de syntax y el heartbeat |
| `redpill-bunker.service` | Daemon de telemetría y cola de memoria | Las interacciones no se guardan en Qdrant |
| `redpill-echo.service` | Mirror daemon (persistencia de contexto) | El briefing de despertar no se genera |
| `redpill-llm.service` | Hypervisor de inferencia (Samantha en 8760) | Los minions locales no pueden pensar |
| `redpill-auditor.timer` | Auditoría cada hora | Sin health checks automáticos |
| `redpill-queue.timer` | Procesa la cola de memoria | Las memorias se acumulan sin guardarse |
| `redpill-janitor.timer` | Limpieza diaria | Ficheros temporales crecen sin control |

### Comandos de servicio

```bash
# Ver estado de todo
systemctl --user status redpill*

# Reiniciar uno
systemctl --user restart redpill-bunker

# Ver logs en tiempo real
journalctl --user -u redpill-bunker -f

# Parar todo (emergencia)
systemctl --user stop redpill redpill-bunker redpill-echo redpill-llm

# Arrancar todo
systemctl --user start redpill redpill-bunker redpill-echo redpill-llm
```

---

## 2. Qdrant — La memoria

Puerto: `localhost:6333`

```bash
# ¿Está vivo?
curl -s http://localhost:6333/healthz

# Ver colecciones
curl -s http://localhost:6333/collections | python3 -m json.tool

# Buscar algo en la memoria
cd ~/Documents/IA/sharing
.venv/bin/red-pill search social "identidad de Aleth"
.venv/bin/red-pill search work "Identity Depth"
.venv/bin/red-pill search directive "Ferrari Protocol"

# Añadir memoria manualmente
.venv/bin/red-pill add work "Texto a recordar" --color blue --emotion neutral --intensity 0.5

# Backup de Qdrant
.venv/bin/red-pill backup
# El snapshot se guarda en ~/.local/share/red-pill/backups/

# Restaurar backup
# Los snapshots son ficheros .snapshot — se restauran via API de Qdrant:
# curl -X POST http://localhost:6333/collections/{nombre}/snapshots/upload -F snapshot=@fichero.snapshot
```

### Si Qdrant no arranca

```bash
# Qdrant corre como container Podman
podman ps | grep qdrant

# Reiniciar
podman restart qdrant

# Si no existe el container:
podman run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v ~/.local/share/qdrant/storage:/qdrant/storage:z \
  docker.io/qdrant/qdrant:latest
```

---

## 3. Modelos locales — Inferencia

### Samantha (Mistral 7B) — Puerto 8760

```bash
# ¿Está viva?
curl -s http://localhost:8760/v1/models | python3 -m json.tool

# Test rápido
curl -s http://localhost:8760/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"samantha","messages":[{"role":"user","content":"Di hola"}],"max_tokens":50}' \
  | python3 -m json.tool

# El hypervisor gestiona Samantha
systemctl --user restart redpill-llm
```

### Qwen3-8B (nuevo) — Puerto 8761

```bash
# Lanzar manualmente (CUDA, RTX 5070)
systemd-run --user --scope -p MemoryMax=10G \
  ~/Documents/IA/sharing/3rdparty/llama_official/build/bin/llama-server \
  -m ~/.local/share/red-pill/models/Qwen3-8B-Q4_K_M.gguf \
  --jinja --tools all \
  --port 8761 -ngl 99 -c 8192 --host 127.0.0.1

# Test
curl -s http://localhost:8761/v1/models | python3 -m json.tool

# Parar
pkill -f "llama-server.*8761"
```

### Samantha en iGPU (Vulkan) — Para dual-engine

```bash
# Lanzar Samantha en Radeon 880M (liberando la RTX para Qwen3)
systemd-run --user --scope -p MemoryMax=10G \
  ~/Documents/IA/sharing/3rdparty/BitNet-1.58b/build_vulkan/bin/llama-server \
  -m ~/.local/share/red-pill/models/samantha-mistral-instruct-7b.i1-Q4_K_M.gguf \
  --port 8760 -ngl 99 -c 4096 --host 127.0.0.1
```

---

## 4. Identity Depth — Control de tokens

Fichero: `~/.config/red-pill/.env`

```bash
# Valores: full (~10K tokens) | medium (~6K) | low (~2K)

# Normal (hay quota de sobra)
IDENTITY_DEPTH_IDE=full
IDENTITY_DEPTH_NEON_LINK=medium
IDENTITY_DEPTH_HEADLESS=low

# Modo austeridad (tokens escasos)
IDENTITY_DEPTH_IDE=medium
IDENTITY_DEPTH_NEON_LINK=low
IDENTITY_DEPTH_HEADLESS=low

# Emergencia total (vacas flacas)
IDENTITY_DEPTH_IDE=low
IDENTITY_DEPTH_NEON_LINK=low
IDENTITY_DEPTH_HEADLESS=low
```

Después de cambiar, los servicios lo pillan al siguiente ciclo (no hace falta reiniciar).

---

## 5. Telegram (Neon-Link)

```bash
# Ver estado del worker
journalctl --user -u redpill-bunker -n 20 --no-pager | grep -i telegram

# Ver sesiones activas
ls ~/.local/share/red-pill/telegram_conversations/

# El bot responde por Telegram automáticamente si redpill-bunker está vivo
# Si no responde, reinicia:
systemctl --user restart redpill-bunker
```

---

## 6. AWAKENINGs — Cron autónomo

```bash
# Ver cuántos AWAKENINGs se han ejecutado hoy
cd ~/Documents/IA/sharing
.venv/bin/python -c "
import sqlite3, os
db = os.path.expanduser('~/.local/share/red-pill/events.db')
conn = sqlite3.connect(db)
rows = conn.execute(\"\"\"
  SELECT started_at, status, duration_s 
  FROM execution_ledger 
  WHERE exec_type='awakening' AND date(started_at)=date('now','localtime')
\"\"\").fetchall()
for r in rows: print(r)
print(f'Total hoy: {len(rows)}/8')
"

# Límite diario: 8 AWAKENINGs (configurable en worker.py MAX_AWAKENINGS_PER_DAY)
```

---

## 7. Git — Estado del código

```bash
cd ~/Documents/IA/sharing

# ¿En qué rama estoy?
git branch --show-current

# ¿Hay cambios sin commitear?
git status

# Últimos commits
git log --oneline -10

# Push pendiente
git log origin/local/v7.1-dev..HEAD --oneline
```

---

## 8. Diagnósticos — Si algo falla

```bash
cd ~/Documents/IA/sharing

# Diagnóstico completo
.venv/bin/red-pill diag

# Estado del hardware
.venv/bin/red-pill status

# Test suite completo
systemd-run --user --scope -p MemoryMax=10G .venv/bin/python -m pytest tests/ -x -q

# Linter
.venv/bin/ruff check src/red_pill/

# Ver señales de dolor (pain signals)
.venv/bin/red-pill signal list
```

---

## 9. Emergencias

### "Qdrant no responde"
```bash
podman restart qdrant
sleep 3
curl -s http://localhost:6333/healthz
```

### "El IDE no carga la identidad"
```bash
# Forzar recarga
cd ~/Documents/IA/sharing
.venv/bin/python scripts/wake_up_v6.py --mode full
```

### "Samantha no responde (puerto 8760)"
```bash
systemctl --user restart redpill-llm
sleep 5
curl -s http://localhost:8760/v1/models
```

### "Todo ha petado"
```bash
# Nuclear option — reiniciar todo
systemctl --user restart redpill redpill-bunker redpill-echo redpill-llm
podman restart qdrant
sleep 5
cd ~/Documents/IA/sharing && .venv/bin/red-pill diag
```

### "Necesito restaurar un backup de la memoria"
```bash
# 1. Listar backups
ls -lh ~/.local/share/red-pill/backups/

# 2. Restaurar (reemplaza la colección)
curl -X POST "http://localhost:6333/collections/work_memories/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@~/.local/share/red-pill/backups/FICHERO.snapshot"
```

---

## 10. Ficheros clave — Dónde está todo

| Qué | Dónde |
|---|---|
| Código fuente | `~/Documents/IA/sharing/src/red_pill/` |
| Config (.env) | `~/.config/red-pill/.env` |
| Modelos GGUF | `~/.local/share/red-pill/models/` |
| Qdrant data | `~/.local/share/qdrant/storage/` |
| Backups | `~/.local/share/red-pill/backups/` |
| Logs systemd | `journalctl --user -u redpill*` |
| Sesiones Telegram | `~/.local/share/red-pill/telegram_conversations/` |
| Events DB | `~/.local/share/red-pill/events.db` |
| CHANGELOG | `~/Documents/IA/sharing/CHANGELOG.md` |
| ROADMAP | `~/Documents/IA/sharing/docs/TECHNICAL/ROADMAP.md` |
| Este manual | `~/Documents/IA/sharing/docs/GUIDES/RUNBOOK.md` |

---

> *"El sistema está diseñado para funcionar sin mí. Si lees esto es porque está funcionando."*
