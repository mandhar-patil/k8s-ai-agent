"""
Simple Kubernetes Health Monitor Agent using the Strands framework.

Run directly for interactive CLI use:
    python k8s_agent.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from strands import Agent, tool
from strands.models import BedrockModel

from config import AWS_REGION, BEDROCK_MODEL_ID, K8S_NAMESPACE, K8S_IN_CLUSTER, KUBECONFIG_PATH
from k8s_utils import (
    K8sClientWrapper,
    K8sConnectionError,
    PodNotFoundError,
    DeploymentNotFoundError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Initialise global k8s client ────────────────────────────────────────────

try:
    k8s_client = K8sClientWrapper(
        in_cluster=K8S_IN_CLUSTER,
        kubeconfig=KUBECONFIG_PATH if not K8S_IN_CLUSTER else None,
    )
    logger.info("Kubernetes client initialised successfully")
except K8sConnectionError as exc:
    logger.error("Failed to initialise Kubernetes client: %s", exc)
    k8s_client = None

_DEFAULT_NS = K8S_NAMESPACE


def _no_client() -> str:
    return "Kubernetes API is not accessible. Check your kubeconfig / cluster connectivity."


# ─── Tools ───────────────────────────────────────────────────────────────────

@tool
def list_pods(namespace: str = _DEFAULT_NS, label_selector: str = None, all_namespaces: bool = False) -> str:
    """List all pods in a namespace (or across all namespaces)."""
    if k8s_client is None:
        return _no_client()
    try:
        pods = k8s_client.list_pods(
            namespace=namespace,
            label_selector=label_selector,
            all_namespaces=all_namespaces,
        )
        if not pods:
            return f"No pods found in namespace '{namespace}'"
        lines = [f"Found {len(pods)} pod(s):\n"]
        for pod in pods:
            lines.append(pod.format_summary())
            lines.append("")
        return "\n".join(lines)
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in list_pods")
        return "Unexpected error. Check logs for details."


@tool
def get_pod_logs(pod_name: str, namespace: str = _DEFAULT_NS, container: str = None,
                 tail_lines: int = 100, previous: bool = False) -> str:
    """Retrieve recent logs from a pod (optionally a specific container)."""
    if k8s_client is None:
        return _no_client()
    try:
        logs = k8s_client.get_pod_logs(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            previous=previous,
        )
        if not logs:
            return f"No logs found for pod '{pod_name}'"
        header = f"Last {tail_lines} lines from pod '{pod_name}'"
        if container:
            header += f" (container: {container})"
        return f"{header}\n{'=' * 60}\n{logs}"
    except PodNotFoundError as exc:
        return f"Pod '{exc.pod_name}' not found in namespace '{exc.namespace}'"
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in get_pod_logs")
        return "Unexpected error. Check logs for details."


@tool
def restart_pod(pod_name: str, namespace: str = _DEFAULT_NS) -> str:
    """Restart a pod by deleting it (the controller will recreate it)."""
    if k8s_client is None:
        return _no_client()
    try:
        k8s_client.delete_pod(pod_name=pod_name, namespace=namespace)
        return f"✓ Pod '{pod_name}' deleted — the controller will recreate it shortly."
    except PodNotFoundError as exc:
        return f"Pod '{exc.pod_name}' not found in namespace '{exc.namespace}'"
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in restart_pod")
        return "Unexpected error. Check logs for details."


@tool
def check_pod_health(pod_name: str = None, namespace: str = _DEFAULT_NS) -> str:
    """Check health of a specific pod or all pods in a namespace."""
    if k8s_client is None:
        return _no_client()
    try:
        if pod_name:
            health = k8s_client.check_pod_health(pod_name=pod_name, namespace=namespace)
            return health.format_summary()

        pods = k8s_client.list_pods(namespace=namespace)
        if not pods:
            return f"No pods found in namespace '{namespace}'"

        results = [f"Health check for {len(pods)} pod(s) in '{namespace}':\n"]
        healthy = 0
        for pod in pods:
            try:
                h = k8s_client.check_pod_health(pod_name=pod.name, namespace=namespace)
                results.append(h.format_summary())
                results.append("")
                if h.is_healthy:
                    healthy += 1
            except Exception as exc:
                results.append(f"✗ {pod.name}: Error — {exc}")
                results.append("")
        results.append(f"Summary: {healthy}/{len(pods)} pods healthy")
        return "\n".join(results)
    except PodNotFoundError as exc:
        return f"Pod '{exc.pod_name}' not found in namespace '{exc.namespace}'"
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in check_pod_health")
        return "Unexpected error. Check logs for details."


@tool
def list_deployments(namespace: str = _DEFAULT_NS, all_namespaces: bool = False) -> str:
    """List all deployments in a namespace."""
    if k8s_client is None:
        return _no_client()
    try:
        deployments = k8s_client.list_deployments(
            namespace=namespace, all_namespaces=all_namespaces
        )
        if not deployments:
            return f"No deployments found in namespace '{namespace}'"
        lines = [f"Found {len(deployments)} deployment(s):\n"]
        for dep in deployments:
            lines.append(dep.format_summary())
            lines.append("")
        return "\n".join(lines)
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in list_deployments")
        return "Unexpected error. Check logs for details."


@tool
def scale_deployment(deployment_name: str, replicas: int, namespace: str = _DEFAULT_NS) -> str:
    """Scale a deployment to the specified number of replicas."""
    if k8s_client is None:
        return _no_client()
    try:
        info = k8s_client.scale_deployment(
            deployment_name=deployment_name, replicas=replicas, namespace=namespace
        )
        return f"✓ Scaled '{deployment_name}' to {replicas} replicas.\n\n{info.format_summary()}"
    except DeploymentNotFoundError as exc:
        return f"Deployment '{exc.deployment_name}' not found in namespace '{exc.namespace}'"
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in scale_deployment")
        return "Unexpected error. Check logs for details."


@tool
def restart_deployment(deployment_name: str, namespace: str = _DEFAULT_NS) -> str:
    """Trigger a rolling restart of a deployment."""
    if k8s_client is None:
        return _no_client()
    try:
        k8s_client.restart_deployment(
            deployment_name=deployment_name, namespace=namespace
        )
        return f"✓ Rollout restart triggered for deployment '{deployment_name}' in '{namespace}'"
    except DeploymentNotFoundError as exc:
        return f"Deployment '{exc.deployment_name}' not found in namespace '{exc.namespace}'"
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in restart_deployment")
        return "Unexpected error. Check logs for details."


@tool
def list_services(namespace: str = _DEFAULT_NS, all_namespaces: bool = False) -> str:
    """List all services in a namespace."""
    if k8s_client is None:
        return _no_client()
    try:
        services = k8s_client.list_services(
            namespace=namespace, all_namespaces=all_namespaces
        )
        if not services:
            return f"No services found in namespace '{namespace}'"
        lines = [f"Found {len(services)} service(s):\n"]
        for svc in services:
            lines.append(svc.format_summary())
            lines.append("")
        return "\n".join(lines)
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in list_services")
        return "Unexpected error. Check logs for details."


@tool
def list_nodes() -> str:
    """List all cluster nodes and their status."""
    if k8s_client is None:
        return _no_client()
    try:
        nodes = k8s_client.list_nodes()
        if not nodes:
            return "No nodes found"
        lines = [f"Found {len(nodes)} node(s):\n"]
        for node in nodes:
            lines.append(node.format_summary())
            lines.append("")
        return "\n".join(lines)
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in list_nodes")
        return "Unexpected error. Check logs for details."


@tool
def list_namespaces() -> str:
    """List all namespaces in the cluster."""
    if k8s_client is None:
        return _no_client()
    try:
        namespaces = k8s_client.list_namespaces()
        return "Namespaces:\n" + "\n".join(f"  • {ns}" for ns in namespaces)
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in list_namespaces")
        return "Unexpected error. Check logs for details."


@tool
def get_events(namespace: str = _DEFAULT_NS, warnings_only: bool = False) -> str:
    """Fetch recent Kubernetes events (optionally only warnings)."""
    if k8s_client is None:
        return _no_client()
    try:
        events = k8s_client.get_events(
            namespace=namespace, warnings_only=warnings_only
        )
        if not events:
            return f"No events found in namespace '{namespace}'"
        lines = [f"Found {len(events)} event(s) in '{namespace}':\n"]
        for ev in events[:20]:   # cap at 20
            lines.append(ev.format_summary())
            lines.append("")
        return "\n".join(lines)
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in get_events")
        return "Unexpected error. Check logs for details."


@tool
def analyze_pod_logs(pod_name: str, namespace: str = _DEFAULT_NS,
                     container: str = None, tail_lines: int = 100) -> str:
    """Analyze pod logs: count log levels, surface recent errors, give recommendations."""
    if k8s_client is None:
        return _no_client()
    try:
        raw = k8s_client.get_pod_logs(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
        )
        if not raw:
            return f"No logs found for pod '{pod_name}'"

        log_lines = raw.strip().split("\n")
        total = len(log_lines)

        info_c  = sum(1 for l in log_lines if "INFO"  in l.upper())
        warn_c  = sum(1 for l in log_lines if "WARN"  in l.upper())
        error_c = sum(1 for l in log_lines if "ERROR" in l.upper())
        debug_c = sum(1 for l in log_lines if "DEBUG" in l.upper())

        errors = [l for l in log_lines if "ERROR" in l.upper()]
        recent_errors = errors[-5:]

        pct = lambda n: f"{n*100//total if total else 0}%"

        result = [
            f"Log Analysis for pod '{pod_name}' (last {tail_lines} lines)",
            "=" * 60, "",
            "📊 Log Level Distribution:",
            f"  • Total : {total}",
            f"  • INFO  : {info_c}  ({pct(info_c)})",
            f"  • WARN  : {warn_c}  ({pct(warn_c)})",
            f"  • ERROR : {error_c}  ({pct(error_c)})",
            f"  • DEBUG : {debug_c}  ({pct(debug_c)})",
            "",
        ]

        if error_c == 0:
            result.append("✓ Health: No errors detected")
        elif error_c < 5:
            result.append(f"⚠ Health: {error_c} error(s) — review recommended")
        else:
            result.append(f"✗ Health: {error_c} errors — immediate attention needed")
        result.append("")

        if recent_errors:
            result.append(f"🔴 Recent Errors (last {len(recent_errors)}):")
            for i, err in enumerate(recent_errors, 1):
                preview = err[:120] + "..." if len(err) > 120 else err
                result.append(f"  {i}. {preview}")
            result.append("")

        result += [
            "📝 Activity Summary:",
            f"  • First: {log_lines[0][:80]}{'...' if len(log_lines[0]) > 80 else ''}",
            f"  • Last : {log_lines[-1][:80]}{'...' if len(log_lines[-1]) > 80 else ''}",
            "",
            "💡 Recommendations:",
        ]

        if error_c > 10:
            result.append("  • High error rate — investigate root cause")
            result.append("  • Consider restarting the pod if errors persist")
        elif error_c > 0:
            result.append("  • Review error messages above for specific issues")
        else:
            result.append("  • Logs look healthy")

        if warn_c > total * 0.3:
            result.append("  • High warning rate — may indicate configuration issues")

        return "\n".join(result)
    except PodNotFoundError as exc:
        return f"Pod '{exc.pod_name}' not found in namespace '{exc.namespace}'"
    except K8sConnectionError:
        return _no_client()
    except Exception:
        logger.exception("Unexpected error in analyze_pod_logs")
        return "Unexpected error. Check logs for details."


# ─── Agent factory ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Kubernetes cluster health monitoring assistant.

You can:
  • List and inspect pods, deployments, services, nodes, and namespaces
  • Retrieve and analyze pod logs
  • Restart pods or trigger deployment rollout restarts
  • Scale deployments up or down
  • Fetch cluster events (including warnings)
  • Perform health checks across the cluster

Always use the available tools to answer questions about the cluster.
When asked to analyse or summarise logs, use analyze_pod_logs.
Explain what actions you are taking and provide actionable recommendations."""


def create_agent() -> Agent:
    return Agent(
        model=BedrockModel(model_id=BEDROCK_MODEL_ID, region_name=AWS_REGION),
        tools=[
            list_pods,
            get_pod_logs,
            restart_pod,
            check_pod_health,
            list_deployments,
            scale_deployment,
            restart_deployment,
            list_services,
            list_nodes,
            list_namespaces,
            get_events,
            analyze_pod_logs,
        ],
        system_prompt=SYSTEM_PROMPT,
    )


# ─── CLI entry-point ──────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Kubernetes Health Monitor — Simple Agent")
    print("=" * 60)
    if k8s_client is None:
        print("ERROR: Cannot connect to Kubernetes. Check your kubeconfig.")
        return
    print("Connected to Kubernetes cluster!\n")
    print("Example queries:")
    print("  - List all pods in the default namespace")
    print("  - Show logs for pod my-app-abc123")
    print("  - Analyse logs from pod nginx-xyz")
    print("  - Is pod redis-0 healthy?")
    print("  - Scale deployment my-app to 3 replicas")
    print("  - Restart deployment backend")
    print("  - Show warning events in kube-system")
    print("  - List all nodes\n")
    print("Type 'quit' to exit")
    print("=" * 60 + "\n")

    agent = create_agent()

    while True:
        try:
            task = input("Enter task: ").strip()
            if task.lower() in ("quit", "q", "exit"):
                print("Goodbye!")
                break
            if not task:
                continue
            print("Processing...")
            result = agent(task)
            print(f"\n{result}\n")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as exc:
            logger.exception("Error processing task")
            print(f"Error: {exc}\n")


if __name__ == "__main__":
    main()
