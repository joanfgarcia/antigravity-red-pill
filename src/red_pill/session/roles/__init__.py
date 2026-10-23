"""Políticas de hidratación por rol (el rol es dato, no inferencia)."""

from red_pill.session.roles import orchestrator, spawn, task  # noqa: F401  (registro)
from red_pill.session.roles.base import RolePolicy, policy_for

__all__ = ["RolePolicy", "policy_for"]
