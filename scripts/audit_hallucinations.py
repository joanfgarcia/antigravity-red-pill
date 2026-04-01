#!/usr/bin/env python3
import json
import logging
from pathlib import Path
from red_pill.core.storage import StorageEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auditor")

db = StorageEngine()
client = db.client

def audit_collection(collection_name: str, md_file):
    try:
        points, _ = client.scroll(collection_name=collection_name, limit=100, with_payload=True)
        if not points:
            md_file.write(f"### Colección: `{collection_name}` está vacía o inactiva.\n\n")
            return
            
        md_file.write(f"### Colección: `{collection_name}` ({len(points)} engramas recuperados)\n\n")
        
        for p in points:
            payload = p.payload or {}
            content = payload.get("refined_content") or payload.get("raw_content") or payload.get("content", "SIN CONTENIDO")
            date = payload.get("created_at") or payload.get("date", "SIN FECHA")
            
            # Formateo visual para el usuario
            md_file.write(f"**ID:** `{p.id}` | **Fecha:** `{date}` \\ \n")
            
            # Marcar sospechosos de Qwen
            is_suspicious = any(word in content.lower() for word in ['cenicienta', 'david', 'qwen', 'hallucinated'])
            
            if is_suspicious:
                md_file.write(f"> [!WARNING] ALARMA - Posible Alucinación de Qwen detectada\n")
            else:
                md_file.write(f"> [!TIP] Aparentemente limpio/normal\n")
                
            md_file.write(f"> {content[:500]}...\n\n---\n\n")
            
    except Exception as e:
        logger.error(f"Error scrolleando {collection_name}: {e}")

def main():
    out_path = Path("/home/joan/.gemini/antigravity/artifacts/audit_results.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Auditoría de Alucinaciones Qwen\n")
        f.write("A continuación se listan los engramas activos en tus colecciones nobles. Revisa los IDs marcados como `WARNING` por contexto sospechoso:\n\n")
        audit_collection("social_memories", f)
        audit_collection("work_memories", f)
        
    logger.info(f"Auditoría generada en: {out_path}")

if __name__ == "__main__":
    main()
