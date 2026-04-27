import os

from celery import Celery

broker_url = os.getenv("REDIS_URL", "redis://localhost:8770/0")
backend_url = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:8770/1")

celery_app = Celery("red_pill_tasks", broker=broker_url, backend=backend_url, include=["red_pill.tasks.definitions"])

celery_app.conf.update(
	task_serializer="json",
	accept_content=["json"],
	result_serializer="json",
	timezone="UTC",
	enable_utc=True,
	worker_concurrency=2,
	task_time_limit=300,
)
