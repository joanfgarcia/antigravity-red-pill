from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from red_pill.tasks.celery_app import celery_app
from red_pill.tasks.definitions import dummy_audit_task, extract_knowledge

app = FastAPI(title="Red Pill Background Task Gateway")

class TaskRequest(BaseModel):
	task_name: str
	kwargs: Dict[str, Any] = {}

@app.post("/api/tasks/enqueue")
def enqueue_task(request: TaskRequest):
	if request.task_name == "dummy_audit":
		task = dummy_audit_task.delay(**request.kwargs)
	elif request.task_name == "extract_knowledge":
		task = extract_knowledge.delay(**request.kwargs)
	else:
		raise HTTPException(status_code=400, detail="Unknown task_name.")

	return {"task_id": task.id, "status": "enqueued"}

@app.get("/api/tasks/{task_id}")
def get_task_status(task_id: str):
	res = celery_app.AsyncResult(task_id)
	if res.state == "PENDING":
		return {"task_id": task_id, "state": res.state}
	elif res.state != "FAILURE":
		return {"task_id": task_id, "state": res.state, "result": res.result}
	else:
		# Tarea falló
		return {"task_id": task_id, "state": res.state, "error": str(res.info)}
