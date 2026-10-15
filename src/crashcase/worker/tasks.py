"""Celery worker.

Run with the threads pool so one process holds the models and the Prometheus metrics:
    celery -A crashcase.worker.tasks worker --pool=threads --concurrency=2 --loglevel=info
Scale out by adding worker containers/tasks, not processes.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready
from prometheus_client import start_http_server

from crashcase.config import get_settings

settings = get_settings()

app = Celery("crashcase", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_acks_late=True,  # don't lose a claim if the worker dies mid-task
    worker_prefetch_multiplier=1,  # one heavy inference task at a time per thread
    task_track_started=True,
)


@worker_ready.connect
def _on_ready(**_):
    start_http_server(settings.worker_metrics_port)
    # Load models once at startup instead of on the first claim.
    from crashcase.pipeline.run import get_pipeline

    get_pipeline()


@app.task(name="crashcase.process_claim")
def process_claim_task(claim_id: str) -> str:
    from crashcase.pipeline.run import process_claim

    process_claim(claim_id)
    return claim_id
