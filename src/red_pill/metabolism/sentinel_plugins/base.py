from abc import ABC, abstractmethod
from typing import Any, List


class SentinelPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre legible del plugin de salud (ej: 'Neon-Link Bridge')"""
        pass

    @abstractmethod
    def is_enabled(self, cfg: Any) -> bool:
        """Si devuelve False, el autodescubrimiento se salta este chequeo."""
        pass

    @abstractmethod
    def audit(self, cfg: Any) -> List[Any]:
        """
        Ejecuta la prueba de salud. 
        Debe devolver una lista de objetos AuditFinding (vía importación diferida si es necesario).
        """
        pass

    @abstractmethod
    def heal(self, cfg: Any, finding: Any) -> bool:
        """
        Intento de auto-curación cuando se detecta el problema.
        Devuelve True si la curación parece haber tenido éxito.
        """
        pass
