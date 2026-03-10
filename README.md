# Kubernetes Strands Temporal Agent

AI-powered Kubernetes cluster monitoring and management agent using **Strands**, **AWS Bedrock (Qwen3)**, and **Temporal**.

---

## Project Structure

```
k8s_monitor/
├── __init__.py                  # Package exports
├── k8s_utils.py                 # Kubernetes SDK wrapper + data models
├── k8s_agent.py                 # Simple Strands CLI agent (@tool decorators)
├── k8s_temporal_agent.py        # Temporal workflows & activities
├── k8s_worker.py                # Temporal worker process
├── k8s_client.py                # Temporal client (CLI + programmatic)
├── config.py                    # Central configuration
└── requirements.txt
```

---

## What the Agent Can Do

| Capability | Tool / Activity |
|---|---|
| List pods (with filtering) | `list_pods` |
| Get pod logs | `get_pod_logs` |
| Analyze pod logs (AI summary) | `analyze_pod_logs` |
| Check pod / cluster health | `check_pod_health` |
| Restart a pod | `restart_pod` |
| List deployments | `list_deployments` |
| Scale a deployment | `scale_deployment` |
| Rollout-restart a deployment | `restart_deployment` |
| List services | `list_services` |
| List nodes | `list_nodes` |
| List namespaces | `list_namespaces` |
| Fetch cluster events (warnings) | `get_events` |
| Full cluster health report | `ClusterHealthWorkflow` |

---

## Setup

### 1. Install dependencies

```bash
pip install -r k8s_monitor/requirements.txt
```

### 2. Configure AWS credentials

```bash
export AWS_REGION=us-east-2
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
# Or use an IAM role / AWS profile
```

### 3. Configure Kubernetes access

```bash
# Local cluster (default) — uses ~/.kube/config
export KUBECONFIG=~/.kube/config

# Inside a Pod (in-cluster)
export K8S_IN_CLUSTER=true
```

### 4. Start Temporal (local dev)

```bash
# Using Temporal CLI
temporal server start-dev

# Or Docker Compose
docker run --rm -p 7233:7233 temporalio/auto-setup:latest
```

### 5. Start the worker

```bash
python k8s_monitor/k8s_worker.py
```

---

## Usage

### Option A — Simple CLI agent (no Temporal)

```bash
python k8s_monitor/k8s_agent.py
```

Interactive prompts:
```
Enter task: list all pods in kube-system
Enter task: show logs for pod coredns-abc123
Enter task: is the nginx deployment healthy?
Enter task: scale deployment api-server to 5 replicas
```

---

### Option B — Temporal client (production mode)

**Free-text AI query:**
```bash
python k8s_monitor/k8s_client.py "list all pods in the production namespace"
python k8s_monitor/k8s_client.py "are there any warning events in kube-system?"
python k8s_monitor/k8s_client.py "scale my-app deployment to 3 replicas"
```

**Specific workflow shortcuts:**
```bash
# Pod logs
python k8s_monitor/k8s_client.py --workflow logs --pod my-app-abc123
python k8s_monitor/k8s_client.py --workflow logs --pod my-app-abc123 --container sidecar --lines 200

# Scale
python k8s_monitor/k8s_client.py --workflow scale --deployment my-app --replicas 5 -n production

# Restart
python k8s_monitor/k8s_client.py --workflow restart --deployment backend
python k8s_monitor/k8s_client.py --workflow restart --pod my-app-abc123

# Full cluster health check
python k8s_monitor/k8s_client.py --workflow health --namespace production
```

---

### Option C — Programmatic (Python)

```python
import asyncio
from k8s_monitor.k8s_client import K8sTemporalClient

async def main():
    async with K8sTemporalClient() as client:
        # Free-text AI query
        response = await client.ask("list unhealthy pods in production")
        print(response)

        # Get logs
        logs = await client.get_pod_logs("my-pod", namespace="production", tail_lines=200)
        print(logs)

        # Scale
        result = await client.scale_deployment("api-server", replicas=3)
        print(result)

        # Full health report
        report = await client.cluster_health(namespace="default")
        print(report)

asyncio.run(main())
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TEMPORAL_HOST` | `localhost:7233` | Temporal gRPC endpoint |
| `AWS_REGION` | `us-east-2` | AWS region for Bedrock |
| `BEDROCK_MODEL_ID` | `qwen.qwen3-coder-next` | Bedrock model ID |
| `KUBECONFIG` | `~/.kube/config` | Path to kubeconfig |
| `K8S_NAMESPACE` | `default` | Default namespace |
| `K8S_IN_CLUSTER` | `false` | Set `true` when running inside a Pod |
| `K8S_TIMEOUT` | `30` | Kubernetes API timeout (seconds) |

---

## Architecture

```
┌─────────────────────┐
│   k8s_client.py     │  ← CLI or programmatic entry point
│  K8sTemporalClient  │
└────────┬────────────┘
         │  Temporal gRPC
         ▼
┌─────────────────────┐
│   Temporal Server   │
└────────┬────────────┘
         │  Task Queue: k8s-monitor-queue
         ▼
┌─────────────────────┐
│   k8s_worker.py     │  ← Poll & execute
│   Worker process    │
└────────┬────────────┘
         │
    ┌────┴──────────────────────────────────────────┐
    │              Workflows                        │
    │  K8sMonitorWorkflow  (AI orchestrator)        │
    │  PodLogsWorkflow     (direct log fetch)       │
    │  ScaleDeploymentWorkflow                      │
    │  RestartWorkflow                              │
    │  ClusterHealthWorkflow (parallel health check)│
    └────┬──────────────────────────────────────────┘
         │
    ┌────┴──────────────────────────────────────────┐
    │              Activities                       │
    │  run_k8s_agent_task   (Strands + Bedrock)     │
    │  list_pods_activity                           │
    │  get_pod_logs_activity                        │
    │  scale_deployment_activity                    │
    │  restart_pod_activity                         │
    │  check_pod_health_activity                    │
    │  get_events_activity  … etc.                  │
    └────┬──────────────────────────────────────────┘
         │
┌─────────────────────┐
│   k8s_utils.py      │  ← kubernetes-client/python wrapper
│  K8sClientWrapper   │
└─────────────────────┘
```
