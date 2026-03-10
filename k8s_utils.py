"""
Kubernetes SDK wrapper, custom exceptions, and data models.

Wraps kubernetes-client/python so every other module imports only
the clean data classes defined here — never raw k8s API objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)


# ─── Custom Exceptions ────────────────────────────────────────────────────────

class K8sConnectionError(Exception):
    """Raised when we cannot connect to the Kubernetes API server."""


class PodNotFoundError(Exception):
    def __init__(self, pod_name: str, namespace: str = "default"):
        self.pod_name = pod_name
        self.namespace = namespace
        super().__init__(f"Pod '{pod_name}' not found in namespace '{namespace}'")


class DeploymentNotFoundError(Exception):
    def __init__(self, deployment_name: str, namespace: str = "default"):
        self.deployment_name = deployment_name
        self.namespace = namespace
        super().__init__(
            f"Deployment '{deployment_name}' not found in namespace '{namespace}'"
        )


# ─── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class PodInfo:
    name: str
    namespace: str
    status: str
    phase: str
    node: str
    ip: str
    restart_count: int
    containers: List[str]
    labels: Dict[str, str]
    created_at: Optional[str]

    def format_summary(self) -> str:
        icon = "✓" if self.phase == "Running" else "✗"
        lines = [
            f"{icon} Pod: {self.name}",
            f"   Namespace : {self.namespace}",
            f"   Phase     : {self.phase}",
            f"   Status    : {self.status}",
            f"   Node      : {self.node}",
            f"   Pod IP    : {self.ip}",
            f"   Restarts  : {self.restart_count}",
            f"   Containers: {', '.join(self.containers)}",
            f"   Created   : {self.created_at}",
        ]
        return "\n".join(lines)


@dataclass
class DeploymentInfo:
    name: str
    namespace: str
    replicas: int
    ready_replicas: int
    available_replicas: int
    updated_replicas: int
    labels: Dict[str, str]
    image: str

    def format_summary(self) -> str:
        icon = "✓" if self.ready_replicas == self.replicas else "⚠"
        return (
            f"{icon} Deployment: {self.name}\n"
            f"   Namespace  : {self.namespace}\n"
            f"   Replicas   : {self.ready_replicas}/{self.replicas} ready\n"
            f"   Available  : {self.available_replicas}\n"
            f"   Updated    : {self.updated_replicas}\n"
            f"   Image      : {self.image}"
        )


@dataclass
class ServiceInfo:
    name: str
    namespace: str
    type: str
    cluster_ip: str
    external_ip: str
    ports: List[str]

    def format_summary(self) -> str:
        return (
            f"⚡ Service: {self.name}\n"
            f"   Namespace  : {self.namespace}\n"
            f"   Type       : {self.type}\n"
            f"   Cluster IP : {self.cluster_ip}\n"
            f"   External IP: {self.external_ip}\n"
            f"   Ports      : {', '.join(self.ports)}"
        )


@dataclass
class NodeInfo:
    name: str
    status: str
    roles: List[str]
    version: str
    os: str
    cpu: str
    memory: str
    conditions: List[str]

    def format_summary(self) -> str:
        icon = "✓" if self.status == "Ready" else "✗"
        return (
            f"{icon} Node: {self.name}\n"
            f"   Status : {self.status}\n"
            f"   Roles  : {', '.join(self.roles)}\n"
            f"   Version: {self.version}\n"
            f"   OS     : {self.os}\n"
            f"   CPU    : {self.cpu}\n"
            f"   Memory : {self.memory}"
        )


@dataclass
class EventInfo:
    namespace: str
    name: str
    reason: str
    message: str
    type: str         # Normal | Warning
    count: int
    first_time: str
    last_time: str
    involved_object: str

    def format_summary(self) -> str:
        icon = "⚠" if self.type == "Warning" else "ℹ"
        return (
            f"{icon} [{self.type}] {self.involved_object} — {self.reason}\n"
            f"   Message: {self.message}\n"
            f"   Count  : {self.count}  Last: {self.last_time}"
        )


@dataclass
class PodHealthResult:
    pod_name: str
    namespace: str
    is_healthy: bool
    phase: str
    restart_count: int
    conditions: List[str]
    issues: List[str] = field(default_factory=list)

    def format_summary(self) -> str:
        icon = "✓" if self.is_healthy else "✗"
        base = (
            f"{icon} {self.pod_name} ({self.namespace})\n"
            f"   Phase    : {self.phase}\n"
            f"   Restarts : {self.restart_count}\n"
            f"   Conditions: {', '.join(self.conditions)}"
        )
        if self.issues:
            base += "\n   Issues:\n" + "\n".join(f"     • {i}" for i in self.issues)
        return base


# ─── Client Wrapper ───────────────────────────────────────────────────────────

class K8sClientWrapper:
    """
    Thin wrapper around kubernetes-client/python.
    Loads in-cluster config or kubeconfig automatically.
    """

    def __init__(self, in_cluster: bool = False, kubeconfig: Optional[str] = None):
        try:
            if in_cluster:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config")
            else:
                config.load_kube_config(config_file=kubeconfig)
                logger.info("Loaded kubeconfig from %s", kubeconfig or "~/.kube/config")

            self.core_v1   = client.CoreV1Api()
            self.apps_v1   = client.AppsV1Api()
            self.batch_v1  = client.BatchV1Api()
            # quick connectivity check
            self.core_v1.list_namespace(_request_timeout=5)
        except Exception as exc:
            raise K8sConnectionError(f"Cannot connect to Kubernetes: {exc}") from exc

    # ── Pods ──────────────────────────────────────────────────────────────────

    def list_pods(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
        all_namespaces: bool = False,
    ) -> List[PodInfo]:
        try:
            if all_namespaces:
                resp = self.core_v1.list_pod_for_all_namespaces(
                    label_selector=label_selector,
                    field_selector=field_selector,
                )
                pods = resp.items
            else:
                resp = self.core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector,
                    field_selector=field_selector,
                )
                pods = resp.items
            return [self._pod_to_info(p) for p in pods]
        except ApiException as exc:
            raise K8sConnectionError(f"API error listing pods: {exc}") from exc

    def get_pod(self, pod_name: str, namespace: str = "default") -> PodInfo:
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            return self._pod_to_info(pod)
        except ApiException as exc:
            if exc.status == 404:
                raise PodNotFoundError(pod_name, namespace)
            raise K8sConnectionError(str(exc)) from exc

    def get_pod_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        tail_lines: int = 100,
        since_seconds: Optional[int] = None,
        previous: bool = False,
    ) -> str:
        try:
            logs = self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
                since_seconds=since_seconds,
                previous=previous,
            )
            return logs or ""
        except ApiException as exc:
            if exc.status == 404:
                raise PodNotFoundError(pod_name, namespace)
            raise K8sConnectionError(str(exc)) from exc

    def delete_pod(self, pod_name: str, namespace: str = "default") -> bool:
        """Delete (restart) a pod — the controller will recreate it."""
        try:
            self.core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            logger.info("Deleted pod %s/%s (will be recreated by controller)", namespace, pod_name)
            return True
        except ApiException as exc:
            if exc.status == 404:
                raise PodNotFoundError(pod_name, namespace)
            raise K8sConnectionError(str(exc)) from exc

    def check_pod_health(self, pod_name: str, namespace: str = "default") -> PodHealthResult:
        pod = self.get_pod(pod_name, namespace)
        issues: List[str] = []

        if pod.phase not in ("Running", "Succeeded"):
            issues.append(f"Unexpected phase: {pod.phase}")
        if pod.restart_count >= 5:
            issues.append(f"High restart count: {pod.restart_count}")

        # fetch raw to inspect conditions
        raw = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        conditions = []
        if raw.status and raw.status.conditions:
            for cond in raw.status.conditions:
                status_str = "✓" if cond.status == "True" else "✗"
                conditions.append(f"{status_str}{cond.type}")
                if cond.status != "True" and cond.type != "PodScheduled":
                    issues.append(f"Condition {cond.type} is {cond.status}: {cond.message}")

        return PodHealthResult(
            pod_name=pod_name,
            namespace=namespace,
            is_healthy=len(issues) == 0,
            phase=pod.phase,
            restart_count=pod.restart_count,
            conditions=conditions,
            issues=issues,
        )

    # ── Deployments ──────────────────────────────────────────────────────────

    def list_deployments(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None,
        all_namespaces: bool = False,
    ) -> List[DeploymentInfo]:
        try:
            if all_namespaces:
                resp = self.apps_v1.list_deployment_for_all_namespaces(
                    label_selector=label_selector
                )
            else:
                resp = self.apps_v1.list_namespaced_deployment(
                    namespace=namespace,
                    label_selector=label_selector,
                )
            return [self._deploy_to_info(d) for d in resp.items]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str = "default",
    ) -> DeploymentInfo:
        try:
            body = {"spec": {"replicas": replicas}}
            self.apps_v1.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=namespace,
                body=body,
            )
            logger.info("Scaled %s/%s to %d replicas", namespace, deployment_name, replicas)
            return self._deploy_to_info(
                self.apps_v1.read_namespaced_deployment(
                    name=deployment_name, namespace=namespace
                )
            )
        except ApiException as exc:
            if exc.status == 404:
                raise DeploymentNotFoundError(deployment_name, namespace)
            raise K8sConnectionError(str(exc)) from exc

    def restart_deployment(
        self, deployment_name: str, namespace: str = "default"
    ) -> bool:
        """Trigger a rollout restart by patching the pod template annotation."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                        }
                    }
                }
            }
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name, namespace=namespace, body=body
            )
            logger.info("Triggered rollout restart for %s/%s", namespace, deployment_name)
            return True
        except ApiException as exc:
            if exc.status == 404:
                raise DeploymentNotFoundError(deployment_name, namespace)
            raise K8sConnectionError(str(exc)) from exc

    # ── Services ─────────────────────────────────────────────────────────────

    def list_services(
        self, namespace: str = "default", all_namespaces: bool = False
    ) -> List[ServiceInfo]:
        try:
            if all_namespaces:
                resp = self.core_v1.list_service_for_all_namespaces()
            else:
                resp = self.core_v1.list_namespaced_service(namespace=namespace)
            return [self._svc_to_info(s) for s in resp.items]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def list_nodes(self) -> List[NodeInfo]:
        try:
            resp = self.core_v1.list_node()
            return [self._node_to_info(n) for n in resp.items]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    # ── Namespaces ───────────────────────────────────────────────────────────

    def list_namespaces(self) -> List[str]:
        try:
            resp = self.core_v1.list_namespace()
            return [ns.metadata.name for ns in resp.items]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    # ── Events ────────────────────────────────────────────────────────────────

    def get_events(
        self,
        namespace: str = "default",
        field_selector: Optional[str] = None,
        warnings_only: bool = False,
    ) -> List[EventInfo]:
        try:
            fs = field_selector or ""
            if warnings_only:
                fs = (fs + ",type=Warning").lstrip(",")
            resp = self.core_v1.list_namespaced_event(
                namespace=namespace,
                field_selector=fs or None,
            )
            events = sorted(
                resp.items,
                key=lambda e: e.last_timestamp or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            return [self._event_to_info(e) for e in events]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    # ── ConfigMaps ───────────────────────────────────────────────────────────

    def list_configmaps(self, namespace: str = "default") -> List[Dict[str, Any]]:
        try:
            resp = self.core_v1.list_namespaced_config_map(namespace=namespace)
            return [
                {
                    "name": cm.metadata.name,
                    "namespace": cm.metadata.namespace,
                    "keys": list(cm.data.keys()) if cm.data else [],
                }
                for cm in resp.items
            ]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    # ── PersistentVolumeClaims ───────────────────────────────────────────────

    def list_pvcs(self, namespace: str = "default") -> List[Dict[str, Any]]:
        try:
            resp = self.core_v1.list_namespaced_persistent_volume_claim(namespace=namespace)
            return [
                {
                    "name": pvc.metadata.name,
                    "namespace": pvc.metadata.namespace,
                    "status": pvc.status.phase,
                    "capacity": pvc.status.capacity,
                    "storage_class": pvc.spec.storage_class_name,
                }
                for pvc in resp.items
            ]
        except ApiException as exc:
            raise K8sConnectionError(str(exc)) from exc

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _pod_to_info(pod: Any) -> PodInfo:
        containers = [c.name for c in (pod.spec.containers or [])]
        restarts = 0
        if pod.status and pod.status.container_statuses:
            restarts = sum(cs.restart_count for cs in pod.status.container_statuses)
        return PodInfo(
            name=pod.metadata.name,
            namespace=pod.metadata.namespace or "default",
            status=pod.status.phase or "Unknown" if pod.status else "Unknown",
            phase=pod.status.phase or "Unknown" if pod.status else "Unknown",
            node=pod.spec.node_name or "Unscheduled",
            ip=pod.status.pod_ip or "" if pod.status else "",
            restart_count=restarts,
            containers=containers,
            labels=pod.metadata.labels or {},
            created_at=(
                pod.metadata.creation_timestamp.isoformat()
                if pod.metadata.creation_timestamp
                else None
            ),
        )

    @staticmethod
    def _deploy_to_info(dep: Any) -> DeploymentInfo:
        containers = dep.spec.template.spec.containers or []
        image = containers[0].image if containers else "unknown"
        spec = dep.spec
        status = dep.status
        return DeploymentInfo(
            name=dep.metadata.name,
            namespace=dep.metadata.namespace or "default",
            replicas=spec.replicas or 0,
            ready_replicas=status.ready_replicas or 0,
            available_replicas=status.available_replicas or 0,
            updated_replicas=status.updated_replicas or 0,
            labels=dep.metadata.labels or {},
            image=image,
        )

    @staticmethod
    def _svc_to_info(svc: Any) -> ServiceInfo:
        ports = []
        if svc.spec.ports:
            for p in svc.spec.ports:
                entry = f"{p.port}"
                if p.node_port:
                    entry += f":{p.node_port}"
                if p.protocol:
                    entry += f"/{p.protocol}"
                ports.append(entry)
        ext_ip = ""
        if svc.status.load_balancer and svc.status.load_balancer.ingress:
            ing = svc.status.load_balancer.ingress[0]
            ext_ip = ing.ip or ing.hostname or ""
        return ServiceInfo(
            name=svc.metadata.name,
            namespace=svc.metadata.namespace or "default",
            type=svc.spec.type or "ClusterIP",
            cluster_ip=svc.spec.cluster_ip or "",
            external_ip=ext_ip or "<none>",
            ports=ports,
        )

    @staticmethod
    def _node_to_info(node: Any) -> NodeInfo:
        labels = node.metadata.labels or {}
        roles = [
            k.replace("node-role.kubernetes.io/", "")
            for k in labels
            if k.startswith("node-role.kubernetes.io/")
        ] or ["worker"]

        ready_status = "NotReady"
        conditions = []
        if node.status and node.status.conditions:
            for cond in node.status.conditions:
                if cond.type == "Ready":
                    ready_status = "Ready" if cond.status == "True" else "NotReady"
                conditions.append(cond.type)

        info = node.status.node_info if node.status else None
        return NodeInfo(
            name=node.metadata.name,
            status=ready_status,
            roles=roles,
            version=info.kubelet_version if info else "unknown",
            os=f"{info.os_image}" if info else "unknown",
            cpu=node.status.capacity.get("cpu", "?") if node.status else "?",
            memory=node.status.capacity.get("memory", "?") if node.status else "?",
            conditions=conditions,
        )

    @staticmethod
    def _event_to_info(event: Any) -> EventInfo:
        return EventInfo(
            namespace=event.metadata.namespace or "default",
            name=event.metadata.name,
            reason=event.reason or "",
            message=event.message or "",
            type=event.type or "Normal",
            count=event.count or 1,
            first_time=str(event.first_timestamp) if event.first_timestamp else "",
            last_time=str(event.last_timestamp) if event.last_timestamp else "",
            involved_object=(
                f"{event.involved_object.kind}/{event.involved_object.name}"
                if event.involved_object
                else ""
            ),
        )
