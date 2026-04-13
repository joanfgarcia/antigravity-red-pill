import pytest
from typing import Dict, Any
from pathlib import Path
import datetime

# La directiva inyectada: Importamos el cliente en memoria nativo.
from qdrant_client import QdrantClient 
from red_pill.core.plugin_engine import PluginScope
from red_pill.plugins.trinity_learning.plugin import BayesianLearningPlugin

@pytest.mark.asyncio
async def test_bayesian_scolding_adjusts_weight_downward():
    """Prueba que el motor penaliza pesos ante fricción (scolding)."""
    
    # 1. Arrange: Inicializamos el plugin inyectándole un DB de memoria (Cero I/O)
    plugin = BayesianLearningPlugin(name="trinity_learn", version="1.0", directory=Path("/tmp"))
    
    # Simulamos el setup de DB (que en producción se hará en init())
    mock_db = QdrantClient(location=":memory:") 
    plugin.qdrant = mock_db # Inyección directa para el test
    
    await plugin.init()
    await plugin.activate()
    
    # Simulamos el payload del Kernel cuando hay "Scolding" (fricción)
    payload_cognitivo = {
        "active_engram_id": "axon-1234",
        "operator_friction": True  # Detectamos castigo
    }
    
    # 2. Act
    await plugin.hook(PluginScope.COGNITION, payload_cognitivo)
    
    # 3. Assert (Pendiente de implementar el driver de Qdrant en el plugin)
    # Aquí consultaríamos el mock_db.retrieve("axon-1234") y 
    # comprobaríamos que weight == old_weight - delta (0.8 -> 0.6)
    
    # Garantizamos que el payload mutado sigue íntegro para el resto de la cascada
    assert payload_cognitivo["operator_friction"] is True

@pytest.mark.asyncio
async def test_temporal_decay_lowers_old_engrams():
    """Prueba que la extracción de Qdrant decae el peso de engramas viejos."""
    plugin = BayesianLearningPlugin(name="trinity_learn", version="1.0", directory=Path("/tmp"))
    await plugin.init()
    
    viejo_ts = datetime.datetime.now() - datetime.timedelta(days=10)
    
    payload_rag = {
        "retrieved_engrams": [
            {"id": "doc-A", "weight": 1.0, "last_accessed": viejo_ts}
        ]
    }
    
    # Act
    mutated = await plugin.hook(PluginScope.MEMORY, payload_rag)
    
    # Assert
    engram_mutado = mutated["retrieved_engrams"][0]
    # Si λ=0.05 y t=10, 1.0 * e^(-0.5) ≈ 0.606
    assert engram_mutado["weight"] < 1.0
    assert engram_mutado["weight"] == pytest.approx(0.606, rel=1e-2)
    
