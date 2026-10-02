"""Celery application. Transport is RabbitMQ; execution is Celery.

No result backend (no Redis): tasks are fire-and-forget, durability lives in
the outbox, and the beat drain re-dispatches whatever is still pending.
"""

from __future__ import annotations

from celery import Celery

from app.core.settings import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "ecommerce", broker=settings.rabbitmq_url, include=["app.workers.tasks"]
    )
    app.conf.update(
        task_acks_late=True,
        task_ignore_result=True,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "drain-outbox": {
                "task": "app.workers.tasks.drain_outbox",
                "schedule": 15.0,
            },
        },
    )
    return app


celery_app = make_celery()
