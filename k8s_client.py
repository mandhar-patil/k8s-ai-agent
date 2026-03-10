"""
Temporal Client Interface for the Kubernetes Monitor Agent.

Send any natural-language task to the cluster agent:

    python k8s_monitor/k8s_client.py "list all pods in the kube-system namespace"
    python k8s_monitor/k8s_client.py --workflow logs  --pod my-pod
    python k8s_monitor/k8s_client.py --workflow scale --deployment my-app --replicas 3
    python k8s_monitor/k8s_client.py --workflow restart --deployment backend
    python k8s_monitor/k8s_client.py --workflow health --namespace production

Or import K8sTemporalClient and use it programmatically.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from temporalio.client import Client

from config import TEMPORAL_HOST, K8S_MONITOR_TASK_QUEUE, K8S_NAMESPACE
from k8s_temporal_agent import (
    K8sAgentRequest,
    K8sAgentResponse,
    PodLogsRequest,
    ScaleRequest,
    RestartRequest,
    HealthCheckRequest,
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


def _wf_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class K8sTemporalClient:
    """
    High-level async client for the Kubernetes Monitor Temporal workflows.

    Usage (programmatic):
        async with K8sTemporalClient() as c:
            result = await c.ask("show me logs for pod nginx-abc")
            print(result)
    """

    def __init__(self, temporal_host: str = TEMPORAL_HOST, task_queue: str = K8S_MONITOR_TASK_QUEUE):
        self._host = temporal_host
        self._queue = task_queue
        self._client: Client | None = None

    async def __aenter__(self):
        self._client = await Client.connect(self._host)
        logger.info("Connected to Temporal at %s", self._host)
        return self

    async def __aexit__(self, *_):
        # temporalio Client has no explicit close method
        self._client = None

    # ── General AI task ──────────────────────────────────────────────────────

    async def ask(
        self,
        task: str,
        namespace: str = K8S_NAMESPACE,
        context: str = "",
        workflow_id: str | None = None,
    ) -> str:
        """
        Send a free-text task to the AI orchestrator workflow.
        Returns the agent's response as a string.
        """
        wid = workflow_id or _wf_id("k8s-monitor")
        req = K8sAgentRequest(task=task, namespace=namespace, context=context)

        logger.info("Starting K8sMonitorWorkflow (id=%s) — task: %s", wid, task)
        handle = await self._client.start_workflow(
            K8sMonitorWorkflow.run,
            req,
            id=wid,
            task_queue=self._queue,
        )
        result: K8sAgentResponse = await handle.result()
        return result.result

    # ── Pod logs ─────────────────────────────────────────────────────────────

    async def get_pod_logs(
        self,
        pod_name: str,
        namespace: str = K8S_NAMESPACE,
        container: str | None = None,
        tail_lines: int = 100,
        previous: bool = False,
    ) -> str:
        wid = _wf_id("k8s-logs")
        req = PodLogsRequest(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            previous=previous,
        )
        handle = await self._client.start_workflow(
            PodLogsWorkflow.run,
            req,
            id=wid,
            task_queue=self._queue,
        )
        return await handle.result()

    # ── Scale deployment ─────────────────────────────────────────────────────

    async def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str = K8S_NAMESPACE,
    ) -> str:
        wid = _wf_id("k8s-scale")
        req = ScaleRequest(
            deployment_name=deployment_name,
            replicas=replicas,
            namespace=namespace,
        )
        handle = await self._client.start_workflow(
            ScaleDeploymentWorkflow.run,
            req,
            id=wid,
            task_queue=self._queue,
        )
        return await handle.result()

    # ── Restart pod / deployment ─────────────────────────────────────────────

    async def restart(
        self,
        name: str,
        namespace: str = K8S_NAMESPACE,
        kind: str = "deployment",
    ) -> str:
        wid = _wf_id("k8s-restart")
        req = RestartRequest(name=name, namespace=namespace, kind=kind)
        handle = await self._client.start_workflow(
            RestartWorkflow.run,
            req,
            id=wid,
            task_queue=self._queue,
        )
        return await handle.result()

    # ── Full cluster health check ─────────────────────────────────────────────

    async def cluster_health(self, namespace: str = K8S_NAMESPACE) -> str:
        wid = _wf_id("k8s-health")
        handle = await self._client.start_workflow(
            ClusterHealthWorkflow.run,
            namespace,
            id=wid,
            task_queue=self._queue,
        )
        return await handle.result()


# ─── Interactive Shell ────────────────────────────────────────────────────────

HELP_TEXT = """
Commands you can type:
  Any natural language    → AI agent answers (e.g. "list pods", "show logs for pod xyz")

  Special shortcuts:
    :ns <namespace>       → switch default namespace  (e.g. :ns kube-system)
    :logs <pod>           → get logs for a pod
    :scale <deploy> <n>   → scale deployment to n replicas
    :restart <deploy>     → rollout restart a deployment
    :restartpod <pod>     → delete/restart a pod
    :health               → full cluster health report
    :help                 → show this message
    :quit  /  exit        → exit

Current namespace is shown in the prompt.
"""


async def _interactive_loop():
    """Connect once, then loop asking for input until the user quits."""
    async with K8sTemporalClient() as client:
        namespace = K8S_NAMESPACE

        print()
        print("Connected! Type a task or :help for commands.")
        print(f"Default namespace: {namespace}")
        print()

        while True:
            try:
                raw = input(f"k8s [{namespace}] > ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break

            if not raw:
                continue

            # ── Built-in commands (:prefix) ──────────────────────────────
            if raw.lower() in ("exit", "quit", ":quit", ":exit", "q"):
                print("Goodbye!")
                break

            if raw.lower() in (":help", "help", "?"):
                print(HELP_TEXT)
                continue

            if raw.startswith(":ns "):
                namespace = raw.split(None, 1)[1].strip()
                print(f"  ✓ Namespace switched to '{namespace}'\n")
                continue

            if raw.startswith(":logs "):
                parts = raw.split()
                pod = parts[1]
                lines = int(parts[2]) if len(parts) > 2 else 100
                print(f"  Fetching logs for pod '{pod}' in '{namespace}' …\n")
                try:
                    result = await client.get_pod_logs(pod_name=pod, namespace=namespace, tail_lines=lines)
                    _print_result(result)
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                continue

            if raw.startswith(":scale "):
                parts = raw.split()
                if len(parts) < 3:
                    print("  Usage: :scale <deployment> <replicas>\n")
                    continue
                deploy, replicas = parts[1], int(parts[2])
                print(f"  Scaling '{deploy}' to {replicas} replicas in '{namespace}' …\n")
                try:
                    result = await client.scale_deployment(deploy, replicas, namespace)
                    _print_result(result)
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                continue

            if raw.startswith(":restart "):
                deploy = raw.split(None, 1)[1].strip()
                print(f"  Restarting deployment '{deploy}' in '{namespace}' …\n")
                try:
                    result = await client.restart(name=deploy, namespace=namespace, kind="deployment")
                    _print_result(result)
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                continue

            if raw.startswith(":restartpod "):
                pod = raw.split(None, 1)[1].strip()
                print(f"  Restarting pod '{pod}' in '{namespace}' …\n")
                try:
                    result = await client.restart(name=pod, namespace=namespace, kind="pod")
                    _print_result(result)
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                continue

            if raw in (":health", "health"):
                print(f"  Running cluster health check for namespace '{namespace}' …\n")
                try:
                    result = await client.cluster_health(namespace=namespace)
                    _print_result(result)
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                continue

            # ── Free-text AI query (default) ─────────────────────────────
            print("  Processing …\n")
            try:
                result = await client.ask(task=raw, namespace=namespace)
                _print_result(result)
            except Exception as exc:
                print(f"  Error: {exc}\n")


def _print_result(result: str):
    print("─" * 60)
    print(result)
    print("─" * 60)
    print()


def main():
    print("=" * 60)
    print("  Kubernetes Monitor — Interactive Shell")
    print(f"  Temporal : {TEMPORAL_HOST}")
    print(f"  Queue    : {K8S_MONITOR_TASK_QUEUE}")
    print("=" * 60)
    print("  Type :help for available commands")
    print("  Type exit or quit to stop")
    print("=" * 60)

    # Silence the INFO logs so they don't clutter the interactive prompt
    logging.getLogger().setLevel(logging.WARNING)

    asyncio.run(_interactive_loop())


if __name__ == "__main__":
    main()
