"""
Temporal Workflows and Activities for the Kubernetes Monitor Agent.

Architecture:
  K8sMonitorWorkflow   ← top-level workflow dispatched by the client
    └─ run_k8s_agent_task  (activity) ← uses Strands Agent with all k8s tools
       └─ individual tool activities  ← called directly for deterministic ops

Each Kubernetes operation is also exposed as its own Temporal Activity so
it can be used standalone in more complex workflow compositions.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# Activities import the synchronous helpers — keep imports inside activity
# functions to avoid issues when the workflow sandbox re-imports this module.

logger = logging.getLogger(__name__)


# ─── Request / Response dataclasses ──────────────────────────────────────────

@dataclass
class K8sAgentRequest:
    """Free-text task sent to the AI orchestrator activity."""
    task: str
    namespace: str = "default"
    context: str = ""          # optional extra context


@dataclass
class K8sAgentResponse:
    """Response returned by the AI orchestrator activity / workflow."""
    success: bool
    result: str
    task: str


@dataclass
class PodLogsRequest:
    pod_name: str
    namespace: str = "default"
    container: Optional[str] = None
    tail_lines: int = 100
    previous: bool = False


@dataclass
class ScaleRequest:
    deployment_name: str
    replicas: int
    namespace: str = "default"


@dataclass
class RestartRequest:
    name: str                  # pod or deployment name
    namespace: str = "default"
    kind: str = "deployment"   # "pod" | "deployment"


@dataclass
class HealthCheckRequest:
    namespace: str = "default"
    pod_name: Optional[str] = None


# ─── Activities ───────────────────────────────────────────────────────────────

@activity.defn(name="list_pods_activity")
async def list_pods_activity(namespace: str, all_namespaces: bool = False) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper, K8sConnectionError

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        pods = client.list_pods(namespace=namespace, all_namespaces=all_namespaces)
        if not pods:
            return f"No pods found in namespace '{namespace}'"
        lines = [f"Found {len(pods)} pod(s):\n"]
        for pod in pods:
            lines.append(pod.format_summary())
            lines.append("")
        return "\n".join(lines)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("list_pods_activity failed")
        return f"Error listing pods: {exc}"


@activity.defn(name="get_pod_logs_activity")
async def get_pod_logs_activity(req: PodLogsRequest) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper, PodNotFoundError

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        logs = client.get_pod_logs(
            pod_name=req.pod_name,
            namespace=req.namespace,
            container=req.container,
            tail_lines=req.tail_lines,
            previous=req.previous,
        )
        if not logs:
            return f"No logs for pod '{req.pod_name}'"
        return f"Logs from '{req.pod_name}':\n{'=' * 60}\n{logs}"

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except PodNotFoundError as exc:
        return f"Pod '{exc.pod_name}' not found in '{exc.namespace}'"
    except Exception as exc:
        logger.exception("get_pod_logs_activity failed")
        return f"Error retrieving logs: {exc}"


@activity.defn(name="restart_pod_activity")
async def restart_pod_activity(req: RestartRequest) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import (
        K8sClientWrapper, PodNotFoundError, DeploymentNotFoundError
    )

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        if req.kind == "pod":
            client.delete_pod(pod_name=req.name, namespace=req.namespace)
            return f"✓ Pod '{req.name}' deleted — controller will recreate it."
        else:
            client.restart_deployment(
                deployment_name=req.name, namespace=req.namespace
            )
            return f"✓ Rollout restart triggered for deployment '{req.name}'"

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except (PodNotFoundError, DeploymentNotFoundError) as exc:
        return f"Resource not found: {exc}"
    except Exception as exc:
        logger.exception("restart_pod_activity failed")
        return f"Error during restart: {exc}"


@activity.defn(name="scale_deployment_activity")
async def scale_deployment_activity(req: ScaleRequest) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper, DeploymentNotFoundError

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        info = client.scale_deployment(
            deployment_name=req.deployment_name,
            replicas=req.replicas,
            namespace=req.namespace,
        )
        return f"✓ Scaled '{req.deployment_name}' to {req.replicas} replicas.\n{info.format_summary()}"

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except DeploymentNotFoundError as exc:
        return f"Deployment '{exc.deployment_name}' not found in '{exc.namespace}'"
    except Exception as exc:
        logger.exception("scale_deployment_activity failed")
        return f"Error scaling deployment: {exc}"


@activity.defn(name="check_pod_health_activity")
async def check_pod_health_activity(req: HealthCheckRequest) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper, PodNotFoundError

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        if req.pod_name:
            h = client.check_pod_health(pod_name=req.pod_name, namespace=req.namespace)
            return h.format_summary()
        pods = client.list_pods(namespace=req.namespace)
        if not pods:
            return f"No pods in namespace '{req.namespace}'"
        results = []
        healthy = 0
        for pod in pods:
            try:
                h = client.check_pod_health(pod_name=pod.name, namespace=req.namespace)
                results.append(h.format_summary())
                results.append("")
                if h.is_healthy:
                    healthy += 1
            except Exception as exc:
                results.append(f"✗ {pod.name}: {exc}")
        results.append(f"\nSummary: {healthy}/{len(pods)} pods healthy")
        return "\n".join(results)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except PodNotFoundError as exc:
        return f"Pod '{exc.pod_name}' not found in '{exc.namespace}'"
    except Exception as exc:
        logger.exception("check_pod_health_activity failed")
        return f"Error checking pod health: {exc}"


@activity.defn(name="list_deployments_activity")
async def list_deployments_activity(namespace: str, all_namespaces: bool = False) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        deps = client.list_deployments(namespace=namespace, all_namespaces=all_namespaces)
        if not deps:
            return f"No deployments in namespace '{namespace}'"
        lines = [f"Found {len(deps)} deployment(s):\n"]
        for dep in deps:
            lines.append(dep.format_summary())
            lines.append("")
        return "\n".join(lines)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("list_deployments_activity failed")
        return f"Error listing deployments: {exc}"


@activity.defn(name="list_services_activity")
async def list_services_activity(namespace: str, all_namespaces: bool = False) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        svcs = client.list_services(namespace=namespace, all_namespaces=all_namespaces)
        if not svcs:
            return f"No services in namespace '{namespace}'"
        lines = [f"Found {len(svcs)} service(s):\n"]
        for svc in svcs:
            lines.append(svc.format_summary())
            lines.append("")
        return "\n".join(lines)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("list_services_activity failed")
        return f"Error listing services: {exc}"


@activity.defn(name="list_nodes_activity")
async def list_nodes_activity() -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        nodes = client.list_nodes()
        if not nodes:
            return "No nodes found"
        lines = [f"Found {len(nodes)} node(s):\n"]
        for node in nodes:
            lines.append(node.format_summary())
            lines.append("")
        return "\n".join(lines)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("list_nodes_activity failed")
        return f"Error listing nodes: {exc}"


@activity.defn(name="get_events_activity")
async def get_events_activity(namespace: str, warnings_only: bool = False) -> str:
    from config import K8S_IN_CLUSTER, KUBECONFIG_PATH
    from k8s_utils import K8sClientWrapper

    def _run():
        client = K8sClientWrapper(in_cluster=K8S_IN_CLUSTER, kubeconfig=KUBECONFIG_PATH)
        events = client.get_events(namespace=namespace, warnings_only=warnings_only)
        if not events:
            return f"No events in namespace '{namespace}'"
        lines = [f"Found {len(events)} event(s):\n"]
        for ev in events[:20]:
            lines.append(ev.format_summary())
            lines.append("")
        return "\n".join(lines)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("get_events_activity failed")
        return f"Error fetching events: {exc}"


@activity.defn(name="run_k8s_agent_task")
async def run_k8s_agent_task(req: K8sAgentRequest) -> K8sAgentResponse:
    """
    Core AI orchestrator activity.
    Runs a Strands Agent with all Kubernetes tools against the user's task.
    This is the single activity the simple workflow delegates to.
    """
    from config import AWS_REGION, BEDROCK_MODEL_ID, K8S_IN_CLUSTER, KUBECONFIG_PATH
    from strands import Agent, tool as strands_tool
    from strands.models import BedrockModel
    from k8s_utils import (
        K8sClientWrapper, K8sConnectionError, PodNotFoundError, DeploymentNotFoundError
    )

    def _run():
        try:
            k8s = K8sClientWrapper(
                in_cluster=K8S_IN_CLUSTER,
                kubeconfig=KUBECONFIG_PATH if not K8S_IN_CLUSTER else None,
            )
        except K8sConnectionError as exc:
            return K8sAgentResponse(success=False, result=str(exc), task=req.task)

        ns = req.namespace

        @strands_tool
        def list_pods_tool(namespace: str = ns, all_namespaces: bool = False) -> str:
            """List pods in a namespace."""
            pods = k8s.list_pods(namespace=namespace, all_namespaces=all_namespaces)
            if not pods:
                return f"No pods in '{namespace}'"
            return "\n".join(p.format_summary() for p in pods)

        @strands_tool
        def get_pod_logs_tool(pod_name: str, namespace: str = ns, container: str = None, tail_lines: int = 100) -> str:
            """Get pod logs."""
            try:
                logs = k8s.get_pod_logs(pod_name, namespace, container, tail_lines)
                return logs or f"No logs for '{pod_name}'"
            except PodNotFoundError as e:
                return f"Pod '{e.pod_name}' not found"

        @strands_tool
        def restart_pod_tool(pod_name: str, namespace: str = ns) -> str:
            """Restart a pod by deleting it."""
            try:
                k8s.delete_pod(pod_name, namespace)
                return f"✓ Pod '{pod_name}' deleted — will be recreated"
            except PodNotFoundError as e:
                return f"Pod '{e.pod_name}' not found"

        @strands_tool
        def check_pod_health_tool(pod_name: str = None, namespace: str = ns) -> str:
            """Check pod health."""
            if pod_name:
                try:
                    return k8s.check_pod_health(pod_name, namespace).format_summary()
                except PodNotFoundError as e:
                    return f"Pod '{e.pod_name}' not found"
            pods = k8s.list_pods(namespace=namespace)
            return "\n".join(k8s.check_pod_health(p.name, namespace).format_summary() for p in pods)

        @strands_tool
        def list_deployments_tool(namespace: str = ns) -> str:
            """List deployments."""
            deps = k8s.list_deployments(namespace=namespace)
            return "\n".join(d.format_summary() for d in deps) if deps else f"No deployments in '{namespace}'"

        @strands_tool
        def scale_deployment_tool(deployment_name: str, replicas: int, namespace: str = ns) -> str:
            """Scale a deployment."""
            try:
                info = k8s.scale_deployment(deployment_name, replicas, namespace)
                return f"✓ Scaled to {replicas}\n{info.format_summary()}"
            except DeploymentNotFoundError as e:
                return f"Deployment '{e.deployment_name}' not found"

        @strands_tool
        def restart_deployment_tool(deployment_name: str, namespace: str = ns) -> str:
            """Restart a deployment."""
            try:
                k8s.restart_deployment(deployment_name, namespace)
                return f"✓ Rollout restart triggered for '{deployment_name}'"
            except DeploymentNotFoundError as e:
                return f"Deployment '{e.deployment_name}' not found"

        @strands_tool
        def list_services_tool(namespace: str = ns) -> str:
            """List services."""
            svcs = k8s.list_services(namespace=namespace)
            return "\n".join(s.format_summary() for s in svcs) if svcs else f"No services in '{namespace}'"

        @strands_tool
        def list_nodes_tool() -> str:
            """List cluster nodes."""
            nodes = k8s.list_nodes()
            return "\n".join(n.format_summary() for n in nodes) if nodes else "No nodes found"

        @strands_tool
        def get_events_tool(namespace: str = ns, warnings_only: bool = False) -> str:
            """Get cluster events."""
            events = k8s.get_events(namespace=namespace, warnings_only=warnings_only)
            return "\n".join(e.format_summary() for e in events[:20]) if events else "No events"

        @strands_tool
        def list_namespaces_tool() -> str:
            """List all namespaces."""
            return "\n".join(f"  • {n}" for n in k8s.list_namespaces())

        task_with_context = req.task
        if req.context:
            task_with_context = f"{req.task}\n\nContext: {req.context}"

        agent = Agent(
            model=BedrockModel(model_id=BEDROCK_MODEL_ID, region_name=AWS_REGION),
            tools=[
                list_pods_tool, get_pod_logs_tool, restart_pod_tool,
                check_pod_health_tool, list_deployments_tool, scale_deployment_tool,
                restart_deployment_tool, list_services_tool, list_nodes_tool,
                get_events_tool, list_namespaces_tool,
            ],
            system_prompt=(
                "You are a Kubernetes cluster assistant. Use the available tools to "
                "answer questions and perform operations. Be concise and accurate."
            ),
        )

        result_str = str(agent(task_with_context))
        return K8sAgentResponse(success=True, result=result_str, task=req.task)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.exception("run_k8s_agent_task failed")
        return K8sAgentResponse(success=False, result=str(exc), task=req.task)


# ─── Workflows ────────────────────────────────────────────────────────────────

_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2))

_SHORT  = timedelta(seconds=30)
_MEDIUM = timedelta(seconds=60)
_LONG   = timedelta(seconds=120)


@workflow.defn(name="K8sMonitorWorkflow")
class K8sMonitorWorkflow:
    """
    General-purpose workflow: delegates the user's free-text task to the
    AI orchestrator activity which uses a Strands Agent internally.
    """

    @workflow.run
    async def run(self, req: K8sAgentRequest) -> K8sAgentResponse:
        workflow.logger.info("K8sMonitorWorkflow started — task: %s", req.task)
        result = await workflow.execute_activity(
            run_k8s_agent_task,
            req,
            start_to_close_timeout=_LONG,
            retry_policy=_RETRY,
        )
        workflow.logger.info("K8sMonitorWorkflow completed — success: %s", result.success)
        return result


@workflow.defn(name="PodLogsWorkflow")
class PodLogsWorkflow:
    """Retrieve pod logs directly (no AI layer)."""

    @workflow.run
    async def run(self, req: PodLogsRequest) -> str:
        return await workflow.execute_activity(
            get_pod_logs_activity,
            req,
            start_to_close_timeout=_MEDIUM,
            retry_policy=_RETRY,
        )


@workflow.defn(name="ScaleDeploymentWorkflow")
class ScaleDeploymentWorkflow:
    """Scale a deployment directly."""

    @workflow.run
    async def run(self, req: ScaleRequest) -> str:
        return await workflow.execute_activity(
            scale_deployment_activity,
            req,
            start_to_close_timeout=_MEDIUM,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn(name="RestartWorkflow")
class RestartWorkflow:
    """Restart a pod or deployment directly."""

    @workflow.run
    async def run(self, req: RestartRequest) -> str:
        return await workflow.execute_activity(
            restart_pod_activity,
            req,
            start_to_close_timeout=_MEDIUM,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn(name="ClusterHealthWorkflow")
class ClusterHealthWorkflow:
    """
    Run a full cluster health check in parallel:
      • pod health in the given namespace
      • recent warning events
      • node status
    Returns a combined report.
    """

    @workflow.run
    async def run(self, namespace: str = "default") -> str:
        workflow.logger.info("ClusterHealthWorkflow — namespace: %s", namespace)

        pod_health_task  = workflow.execute_activity(
            check_pod_health_activity,
            HealthCheckRequest(namespace=namespace),
            start_to_close_timeout=_MEDIUM,
            retry_policy=_RETRY,
        )
        events_task = workflow.execute_activity(
            get_events_activity,
            namespace,
            True,          # warnings_only
            start_to_close_timeout=_SHORT,
            retry_policy=_RETRY,
        )
        nodes_task = workflow.execute_activity(
            list_nodes_activity,
            start_to_close_timeout=_SHORT,
            retry_policy=_RETRY,
        )

        pod_health, events, nodes = await asyncio.gather(
            pod_health_task, events_task, nodes_task
        )

        report = [
            "=" * 60,
            f"Cluster Health Report — namespace: {namespace}",
            "=" * 60,
            "",
            "── Pod Health ──────────────────────────────────────────",
            pod_health,
            "",
            "── Warning Events ──────────────────────────────────────",
            events,
            "",
            "── Node Status ─────────────────────────────────────────",
            nodes,
        ]
        return "\n".join(report)
