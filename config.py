"""Central configuration for Kubernetes Strands Temporal Agent."""

import os

# ─── Temporal ────────────────────────────────────────────────────────────────
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = "strands-temporal-agent-queue"
K8S_MONITOR_TASK_QUEUE = "k8s-monitor-queue"

# ─── AWS Bedrock ─────────────────────────────────────────────────────────────
AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")

# ─── Kubernetes ──────────────────────────────────────────────────────────────
KUBECONFIG_PATH = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "default")          # default namespace
K8S_IN_CLUSTER = os.getenv("K8S_IN_CLUSTER", "false").lower() == "true"
K8S_TIMEOUT = int(os.getenv("K8S_TIMEOUT", "30"))

# ─── Operation timeouts (seconds) ────────────────────────────────────────────
POD_LIST_TIMEOUT        = 10
POD_LOG_TIMEOUT         = 15
POD_RESTART_TIMEOUT     = 30
SCALE_TIMEOUT           = 30
DESCRIBE_TIMEOUT        = 10
EXEC_TIMEOUT            = 20
EVENT_FETCH_TIMEOUT     = 10
RESOURCE_USAGE_TIMEOUT  = 15
AI_ORCHESTRATOR_TIMEOUT = 60

# ─── Health / resource thresholds ────────────────────────────────────────────
CPU_THRESHOLD_PERCENT    = 90.0
MEMORY_THRESHOLD_PERCENT = 90.0
RESTART_COUNT_THRESHOLD  = 5

# ─── Log defaults ────────────────────────────────────────────────────────────
DEFAULT_LOG_LINES        = 100
DEFAULT_LOG_SINCE        = "1h"       # passed to kubectl-style since param
