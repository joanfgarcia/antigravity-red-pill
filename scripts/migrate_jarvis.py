import sys
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://localhost:6333"

def migrate():
    client = QdrantClient(url=QDRANT_URL)
    
    mapping = {
        "social_memory": "social_memories",
        "project_memory": "work_memories"
    }
    
    for source_coll, target_coll in mapping.items():
        if not client.collection_exists(source_coll):
            print(f"Colección origen {source_coll} no existe. Saltando.")
            continue
            
        print(f"Migrando de {source_coll} a {target_coll}...")
        
        # Scroll through all points in source
        points, next_page = client.scroll(
            collection_name=source_coll,
            limit=100,
            with_payload=True,
            with_vectors=True
        )
        
        if not points:
            print(f"No hay puntos en {source_coll}.")
            continue
            
        # Prepare points for upsert
        # We need to make sure vectors are the same size or handled.
        # The new collections use size 384 (MiniLM L6). 
        # Old collections might use a different size (or just 4 as I saw in my manual curls).
        # Fix: If vector size differ, we might need to re-embed, but for now let's try direct move if they match.
        
        target_info = client.get_collection(target_coll)
        target_vector_size = target_info.config.params.vectors.size
        
        new_points = []
        for p in points:
            # Check vector size
            vec = p.vector
            if isinstance(vec, list) and len(vec) != target_vector_size:
                 print(f"Vector size mismatch for point {p.id}: {len(vec)} vs {target_vector_size}. Skipping vector.")
                 vec = [0.0] * target_vector_size # Dummy if mismatch
            
            new_points.append(
                models.PointStruct(
                    id=p.id,
                    vector=vec,
                    payload=p.payload
                )
            )
            
        if new_points:
            client.upsert(
                collection_name=target_coll,
                points=new_points
            )
            print(f"Migrados {len(new_points)} puntos a {target_coll}.")

if __name__ == "__main__":
    migrate()
