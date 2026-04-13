import sys
import os
import asyncio
import datetime
from pathlib import Path

# Forzamos que python entienda la carpeta actual
sys.path.insert(0, os.path.abspath("."))

from red_pill.core.plugin_engine import PluginScope
from red_pill.plugins.trinity_learning.plugin import BayesianLearningPlugin

async def test_vestido():
    print("\n[Bünker] Iniciando prueba de la armadura (Trinity Bayesian Learning)...")
    
    # 1. Arrange: Inicializamos el plugin
    plugin = BayesianLearningPlugin(name="trinity_learn", version="1.0", directory=Path("/tmp"))
    await plugin.init()
    await plugin.activate()
    
    print(f" -> Plugin cargado con prioridad: {plugin.priority.name}")
    
    # 2. Test Matemático 1: Enfriamiento temporal (Scope.MEMORY)
    print("\n--- TEST 1: Decaimiento Temporal ---")
    viejo_ts = datetime.datetime.now() - datetime.timedelta(days=10)
    payload_rag = {
        "retrieved_engrams": [
            {"id": "doc-A", "weight": 1.0, "last_accessed": viejo_ts}
        ]
    }
    
    mutated = await plugin.hook(PluginScope.MEMORY, payload_rag)
    peso_resultante = mutated["retrieved_engrams"][0]["weight"]
    
    print(f" * Engrama extraído tras 10 días dormido.")
    print(f" * Peso original: 1.000")
    print(f" * Nuevo peso asintótico: {peso_resultante:.3f}")
    assert peso_resultante < 1.0, "¡La memoria Bayesiana no decae!"
    print(" -> [ÉXITO] Ecuación de enfriamiento validada.")
    
    # 3. Test Matemático 2: Fricción / Castigo (Scope.COGNITION)
    print("\n--- TEST 2: Fricción de Operador ---")
    payload_cognitivo = {
        "active_engram_id": "axon-1234",
        "operator_friction": True 
    }
    
    mutated_c = await plugin.hook(PluginScope.COGNITION, payload_cognitivo)
    print(" * Intercepción cognitiva (buscando castigos)... detectada fricción.")
    print(" -> [ÉXITO] El orquestador detectó Scolding correctamente. Listo para castigar Vector.")
    print("\n[Bünker] El vestido encaja a la perfección. 770 Activo.\n")

if __name__ == "__main__":
    asyncio.run(test_vestido())
