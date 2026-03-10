"""
Temporal Worker Process for the Kubernetes Monitor Agent.

Start this before sending any workflows:
    python k8s_monitor/k8s_worker.py

The worker connects to Temporal, registers all workflows and activities,
then polls the task queue for work.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Flat layout: all files are siblings in the same directory
sys.path.insert(0, str(Path(__file__).parent))

from temporalio.client import Client
from temporalio.worker import Worker

from config import TEMPORAL_HOST, K8S_MONITOR_TASK_QUEUE

# ── Import all workflows & activities ────────────────────────────────────────
from k8s_temporal_agent import (
    # Activities
    list_pods_activity,
    get_pod_logs_activity,
    restart_pod_activity,
    scale_deployment_activity,
    check_pod_health_activity,
    list_deployments_activity,
    list_services_activity,
    list_nodes_activity,
    get_events_activity,
    run_k8s_agent_task,
    # Workflows
    K8sMonitorWorkflow,
    PodLogsWorkflow,
    ScaleDeploymentWorkflow,
    RestartWorkflow,
    ClusterHealthWorkflow,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

WORKFLOWS = [
    K8sMonitorWorkflow,
    PodLogsWorkflow,
    ScaleDeploymentWorkflow,
    RestartWorkflow,
    ClusterHealthWorkflow,
]

ACTIVITIES = [
    list_pods_activity,
    get_pod_logs_activity,
    restart_pod_activity,
    scale_deployment_activity,
    check_pod_health_activity,
    list_deployments_activity,
    list_services_activity,
    list_nodes_activity,
    get_events_activity,
    run_k8s_agent_task,
]


async def run_worker():
    logger.info("Connecting to Temporal at %s …", TEMPORAL_HOST)
    client = await Client.connect(TEMPORAL_HOST)
    logger.info("Connected to Temporal ✓")

    worker = Worker(
        client,
        task_queue=K8S_MONITOR_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        # Tune concurrency for your hardware
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=5,
    )

    logger.info(
        "Worker started — task queue: '%s'",
        K8S_MONITOR_TASK_QUEUE,
    )
    logger.info(
        "Registered %d workflow(s) and %d activity(s)",
        len(WORKFLOWS),
        len(ACTIVITIES),
    )

    # Graceful shutdown on SIGINT / SIGTERM
    stop_event = asyncio.Event()

    def _shutdown(signum, frame):
        logger.info("Shutdown signal received, stopping worker …")
        stop_event.set()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    async with worker:
        logger.info("Worker is running. Press Ctrl-C to stop.")
        await stop_event.wait()

    logger.info("Worker stopped.")


def main():
    print("=" * 60)
    print("Kubernetes Monitor — Temporal Worker")
    print("=" * 60)
    print(f"  Temporal host : {TEMPORAL_HOST}")
    print(f"  Task queue    : {K8S_MONITOR_TASK_QUEUE}")
    print("=" * 60)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
