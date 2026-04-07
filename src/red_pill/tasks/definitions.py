import time

from red_pill.tasks.celery_app import celery_app


@celery_app.task(bind=True)
def dummy_audit_task(self, path: str):
	"""
	Simula una tarea pesada como la que hará Keymaker o Smith.
	"""
	time.sleep(5)  # Simulamos 5 segundos de auditoría
	return {"status": "success", "audited_path": path, "issues_found": 0}

@celery_app.task(bind=True)
def extract_knowledge(self, text: str):
	time.sleep(2)
	return {"status": "completed", "entities": ["Podman", "Celery", "Redis"]}
