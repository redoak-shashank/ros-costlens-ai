# AgentCore Billing Intelligence — Architecture Document

## 1. Overview

A multi-agent AWS cost intelligence system built on **Amazon Bedrock AgentCore Runtime**, orchestrated with **LangGraph**, and provisioned with **Terraform**. The system provides proactive cost monitoring, anomaly detection, spend trend analysis, and optimization recommendations — delivered via Slack and a lightweight Streamlit dashboard.

**Key design principles:**
- **100% serverless** — no always-on compute, pay only for what you use
- **AgentCore Runtime at the center** — all agent logic runs inside the Runtime
- **Thin invoker Lambda** — zero business logic, only forwards events to the Runtime
- **Infrastructure as Code** — everything provisioned via Terraform

---

## 2. System Architecture

```
                    ┌──────────────────────────────────────────┐
                    │       Amazon Bedrock AgentCore Runtime     │
                    │  ┌────────────────────────────────────┐   │
                    │  │  LangGraph Supervisor + Specialists │   │
                    │  │  (Cost Analyst, Anomaly Detector,   │   │
                    │  │   Optimizer, Reporter)              │   │
                    │  └────────────────────────────────────┘   │
                    └──────────┬───────────────┬────────────────┘
                               │               │
              ┌────────────────┘               └────────────────┐
              │                                                 │
    ┌─────────▼─────────┐                          ┌────────────▼────────┐
    │  AgentCore Gateway │                          │   Invoker Lambda    │
    │  (MCP Tool Server) │                          │   (thin bridge)     │
    │  → cost_tools λ    │                          └────────────────────┘
    └────────────────────┘                               ▲          ▲
                                                         │          │
                                          ┌──────────────┘          └──────────┐
                                          │                                    │
                                ┌─────────┴──────────┐             ┌───────────┴────────┐
                                │  EventBridge Rules  │             │  API Gateway (HTTP) │
                                │  • Daily report     │             │  /slack/events      │
                                │  • Anomaly check    │             │  (Slack webhook)    │
                                │  • Weekly digest    │             └────────────────────┘
                                └────────────────────┘
```

---

## 3. Agent Architecture (LangGraph Supervisor Pattern)

A **supervisor + specialist** multi-agent pattern. The Supervisor routes incoming requests to the appropriate specialist agent(s), then aggregates outputs via the Reporter.

```
                    ┌─────────────────────────┐
                    │    Supervisor Agent      │
                    │  (Router + Orchestrator) │
                    └────────┬────────────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
   ┌────────▼──────┐  ┌─────▼──────┐  ┌──────▼────────┐
   │  Cost Analyst  │  │  Anomaly   │  │  Optimizer    │
   │    Agent       │  │  Detector  │  │    Agent      │
   │                │  │   Agent    │  │               │
   └────────────────┘  └────────────┘  └───────────────┘
            │                │                │
            └────────────────┼────────────────┘
                             │
                    ┌────────▼────────────────┐
                    │     Reporter Agent       │
                    │  (Slack + Dashboard S3)  │
                    └─────────────────────────┘
```

### Agent Descriptions

| Agent | Role | Key Tools |
|-------|------|-----------|
| **Supervisor** | Routes queries, orchestrates workflows, manages conversation state | LangGraph conditional edges |
| **Cost Analyst** | Queries spend data, computes trends, runs Athena deep-dives for weekly reports | Cost Explorer API, CUR via Athena |
| **Anomaly Detector** | Monitors for cost spikes, compares day-over-day / week-over-week | Cost Explorer API, statistical analysis, threshold configs |
| **Optimizer** | Recommends savings: unused resources, right-sizing, RI/SP coverage gaps | CloudWatch, Trusted Advisor, Compute Optimizer |
| **Reporter** | Formats outputs into Slack messages, persists dashboard JSON to S3 | Slack API, S3 (dashboard data) |

---

## 4. AWS Services Used

All services are **serverless / pay-per-use** — no always-on compute.

### Core Services

| Service | Purpose |
|---------|---------|
| **Bedrock AgentCore Runtime** | Serverless execution of the LangGraph multi-agent graph |
| **Bedrock AgentCore Gateway** | MCP-compatible tool registry exposing cost tools to agents |
| **Bedrock (Claude Sonnet)** | Foundation model for agent reasoning |
| **Lambda** | 1) Thin invoker (EventBridge/API GW → Runtime), 2) cost_tools (Gateway target) |
| **EventBridge** | Scheduling daily reports, anomaly checks, weekly digests |
| **API Gateway (HTTP API)** | Slack webhook endpoint (`/slack/events`) |

### Data & Storage

| Service | Purpose |
|---------|---------|
| **S3** | CUR data, agent code packages, pre-computed dashboard JSON |
| **DynamoDB** | API response cache (5-min TTL), LangGraph state checkpoints |
| **Athena** | SQL queries against CUR data (weekly deep-dives, tag breakdowns) |
| **Glue** | Crawler for CUR schema discovery |
| **Secrets Manager** | Slack bot token storage |

### Monitoring & Cost Management

| Service | Purpose |
|---------|---------|
| **Cost Explorer** | Real-time spend queries, forecasts, anomaly detection |
| **Cost & Usage Reports (CUR)** | Granular line-item billing data (Parquet → S3) |
| **CloudWatch** | Metrics, alarms, agent execution logs |
| **Trusted Advisor** | Cost optimization checks |
| **Compute Optimizer** | EC2/EBS right-sizing recommendations |
| **AWS Budgets** | Monthly spend alerts |
| **SNS** | Budget and system alert notifications |

### IAM & Security

| Service | Purpose |
|---------|---------|
| **IAM** | Least-privilege roles for Runtime, Gateway, Lambda |
| **EC2 (read-only)** | `DescribeInstances` for idle resource detection |
| **Support API** | Trusted Advisor check results |

---

## 5. Request Flow

### 5.1 Scheduled Reports (EventBridge → Runtime)

```
EventBridge Cron Rule
    │
    ▼
Invoker Lambda (thin bridge — zero business logic)
    │  payload: {"source": "aws.events", "detail": {"report_type": "daily"}}
    ▼
AgentCore Runtime (invoke_agent_runtime API)
    │
    ▼
app.py (HTTP server / BedrockAgentCoreApp entry point)
    │
    ▼
src/app.py → handler() dispatches based on event type
    │
    ▼
LangGraph: Supervisor → Cost Analyst → Anomaly Detector → Optimizer → Reporter
    │
    ▼
Reporter sends Slack message + writes dashboard JSON to S3
```

### 5.2 Slack Interactive Q&A

```
Slack User Message
    │
    ▼
API Gateway (HTTP API) → POST /slack/events
    │
    ▼
Invoker Lambda → AgentCore Runtime
    │
    ▼
src/app.py → handle_slack_message()
    │
    ▼
LangGraph: Supervisor → appropriate specialist(s) → Reporter
    │
    ▼
Response sent back to Slack thread
```

### 5.3 AgentCore Gateway (MCP Tools)

```
Agent (inside Runtime) needs cost data
    │
    ▼
AgentCore Gateway (MCP protocol)
    │  tool: get_cost_and_usage / get_cost_forecast / etc.
    ▼
cost_tools Lambda (executes the actual AWS API call)
    │
    ▼
Response returned to agent via MCP
```

---

## 6. Data Pipeline

### 6.1 Cost & Usage Reports (CUR)

```
AWS Billing ──► CUR export to S3 ──► Glue Crawler ──► Athena Table
                  (Parquet format)      (auto-schema)     (SQL queries)
```

- **Frequency**: Hourly CUR exports (Parquet, compressed)
- **Retention**: 13 months rolling in S3 (lifecycle policy)
- **Query Engine**: Athena (serverless, pay-per-query)
- **Use Cases**: Weekly deep-dives, service-level breakdowns, tag-based cost allocation

### 6.2 Cost Explorer API — Quick Queries

- **Use Cases**: Daily/monthly totals, forecasts, service-level summaries
- **Advantages**: No setup required, real-time data, built-in forecasting
- **Caching**: Results cached in DynamoDB (5-min TTL for dashboards, 1-hour for trends)

---

## 7. Scheduled Workflows

| Schedule | EventBridge Rule | Report Type |
|----------|-----------------|-------------|
| **Daily** | `cron(0 8 * * ? *)` — 8 AM UTC | MTD spend, yesterday's costs, anomaly check, savings tips |
| **Anomaly Check** | `rate(4 hours)` | Cost spike detection against configurable thresholds |
| **Weekly Digest** | `cron(0 10 ? * SUN *)` — Sundays 10 AM UTC | Full CUR-based Athena analysis, tag breakdowns, week-over-week trends |

All three EventBridge rules target the **invoker Lambda**, which forwards to the **AgentCore Runtime**.

---

## 8. Web Dashboard (Streamlit Community Cloud)

Deployed on **Streamlit Community Cloud** (free tier) — no AWS infrastructure needed for the dashboard itself. Reads pre-computed data from S3.

### Dashboard Pages

| Page | Content |
|------|---------|
| **Overview** | MTD spend metric cards, daily trend chart (Plotly), budget progress bar, forecast gauge |
| **Service Breakdown** | Spend by service (treemap + data table), date range selector |
| **Anomalies** | Timeline of detected anomalies with severity badges |
| **Recommendations** | Active optimization cards with estimated savings |
| **Tag Analysis** | Cost allocation by tags (team, project, env) |
| **Ask a Question** | Chat interface → invokes AgentCore Runtime for live Q&A |

### Dashboard Data Flow

```
Scheduled Agent Run → Reporter → S3 (dashboard/latest.json)
                                        │
                         Streamlit App ◄─┘  (reads from S3 via boto3)
                         (Community Cloud)
                                               │
                                          User Browser
```

- AWS credentials configured via `st.secrets` (Streamlit's native secrets management)
- Data cached with `@st.cache_data(ttl=300)`

---

## 9. Infrastructure (Terraform)

### 9.1 Module Structure

```
terraform/
├── main.tf                    # Root module (all phases)
├── variables.tf               # Global variables
├── outputs.tf                 # Stack outputs
├── backend.tf                 # Local state (configurable for S3)
├── terraform.tfvars           # Deployment config
├── terraform.tfvars.example
│
└── modules/
    ├── agentcore/             # AgentCore Runtime, Gateway, Memory, Secrets
    │   ├── main.tf            # Variables & data sources
    │   ├── runtime.tf         # Runtime, Endpoint, Invoker Lambda, IAM
    │   ├── gateway.tf         # MCP Gateway + cost_tools Lambda target
    │   ├── memory.tf          # DynamoDB (checkpoints + long-term)
    │   └── secrets.tf         # Slack bot token in Secrets Manager
    │
    ├── data-pipeline/         # CUR → S3 → Glue → Athena
    │   ├── s3.tf              # CUR bucket + lifecycle
    │   ├── cur.tf             # CUR export config
    │   ├── glue.tf            # Crawler + catalog
    │   └── athena.tf          # Workgroup + named queries
    │
    ├── scheduling/            # EventBridge rules → invoker Lambda
    │   ├── main.tf
    │   ├── daily_report.tf
    │   ├── anomaly_check.tf
    │   └── weekly_digest.tf
    │
    ├── slack-integration/     # API Gateway for Slack webhooks
    │   ├── main.tf
    │   └── api_gateway.tf     # HTTP API → invoker Lambda
    │
    ├── dashboard/             # S3 bucket for dashboard data
    │   └── main.tf
    │
    ├── caching/               # DynamoDB for API response caching
    │   └── main.tf
    │
    └── monitoring/            # CloudWatch dashboards + alarms (Phase 2)
        ├── main.tf
        ├── dashboards.tf
        └── alarms.tf
```

### 9.2 Deploy Phases

| Phase | What's Deployed | Status |
|-------|----------------|--------|
| **Phase 1** | Data pipeline, AgentCore (Runtime + Gateway + Memory), Scheduling, Slack integration, Dashboard S3, Caching | **Deployed** |
| **Phase 2** | CloudWatch alarms, dashboards, AWS Budgets | Pending (set `deploy_phase = 2`) |

### 9.3 Key Resources Created (Phase 1)

| Resource | Name / ID |
|----------|-----------|
| AgentCore Runtime | `agentcore_billing_dev_billing_runtime` |
| AgentCore Endpoint | `agentcore_billing_dev_billing_endpoint` |
| AgentCore Gateway | `agentcore-billing-dev-billing-gateway` |
| Invoker Lambda | `agentcore-billing-dev-runtime-invoker` |
| cost_tools Lambda | `agentcore-billing-dev-cost-tools` |
| API Gateway | `https://ibdquhfl24.execute-api.us-east-1.amazonaws.com/slack/events` |
| CUR S3 Bucket | `agentcore-billing-dev-cur-{account_id}` |
| Agent Code S3 | `agentcore-billing-dev-agent-code-{account_id}` |
| Dashboard S3 | `agentcore-billing-dev-dashboard-data-{account_id}` |
| DynamoDB Cache | `agentcore-billing-dev-api-cache` |
| DynamoDB Checkpoints | `agentcore-billing-dev-memory-checkpoints` |
| Secrets Manager | `agentcore-billing-dev/slack-bot-tokens` |

---

## 10. Agent Code Structure

```
agents/
├── pyproject.toml              # Dependencies: langgraph, langchain-aws, boto3
└── src/
    ├── __init__.py
    ├── app.py                  # Request dispatcher (handler function)
    ├── graph.py                # LangGraph StateGraph definition
    ├── state.py                # BillingState shared state TypedDict
    ├── checkpointer.py         # Custom DynamoDB-backed LangGraph checkpointer
    │
    ├── agents/
    │   ├── supervisor.py       # Supervisor node — routes to specialists
    │   ├── cost_analyst.py     # Cost Explorer + Athena queries
    │   ├── anomaly_detector.py # Spike detection logic
    │   ├── optimizer.py        # Resource optimization recommendations
    │   └── reporter.py         # Slack formatting + S3 dashboard data
    │
    ├── tools/
    │   ├── cost_explorer.py    # CE API wrappers
    │   ├── athena_query.py     # Athena query execution + result parsing
    │   ├── cloudwatch.py       # EC2 utilization metrics
    │   ├── trusted_advisor.py  # TA cost optimization checks
    │   ├── compute_optimizer.py # Right-sizing recommendations
    │   └── slack.py            # Slack message sending
    │
    ├── prompts/                # System prompts for each agent (Markdown)
    │   ├── supervisor.md
    │   ├── cost_analyst.md
    │   ├── anomaly_detector.md
    │   ├── optimizer.md
    │   └── reporter.md
    │
    └── config/
        ├── thresholds.py       # Anomaly detection thresholds
        ├── budgets.py          # Budget targets
        └── settings.py         # General configuration (env vars)
```

### Deployment Package

The agent code is packaged as a `.zip` (39MB) and uploaded to S3. All dependencies are **pre-bundled as ARM64 Linux wheels** — the Runtime does NOT install anything at startup.

**What's inside the zip:**
- **Root-level `app.py`** — Raw `http.server` entry point (stdlib only, no SDK). Implements `/ping` (health) and `/invocations` (agent logic) endpoints. Lazy-loads `src.app.handler` on first invocation.
- **`src/` package** — all agent logic (graph, agents, tools, prompts, config)
- **39 Python packages** (ARM64 manylinux wheels for Python 3.12) — `langgraph`, `langchain-core`, `langchain-aws`, `boto3`, `pydantic`, `httpx`, `zstandard`, `numpy`, etc.

**Why raw HTTP instead of `bedrock-agentcore` SDK:**
The `bedrock-agentcore` SDK (+ `starlette`, `uvicorn`, etc.) exceeded the 30-second Runtime initialization timeout. The stdlib `http.server` starts instantly (~0ms) and implements the same `/ping` + `/invocations` HTTP protocol that AgentCore expects.

**Build command** (from `agents/` directory):
```bash
uv pip install \
  --python-platform manylinux_2_17_aarch64 \
  --python-version 3.12 \
  --target=deployment_package \
  --only-binary=:all: \
  -r /tmp/runtime-requirements.txt
```

---

## 11. LangGraph State & Flow

### Shared State

```python
class BillingState(MessagesState):
    next_agent: str
    request_type: Literal["report", "query", "alert"]
    iteration_count: int

    # Cost data (Cost Analyst)
    daily_spend: dict | None
    mtd_spend: dict | None
    forecast: dict | None
    trend_data: list[dict] | None

    # Anomaly data (Anomaly Detector)
    anomalies: list[dict] | None
    severity: Literal["low", "medium", "high", "critical"] | None

    # Optimization data (Optimizer)
    recommendations: list[dict] | None
    total_potential_savings: float | None

    # Output
    slack_message: str | None
    dashboard_data: dict | None
```

### Graph Flow

```python
graph = StateGraph(BillingState)

graph.add_node("supervisor", supervisor_node)
graph.add_node("cost_analyst", cost_analyst_node)
graph.add_node("anomaly_detector", anomaly_detector_node)
graph.add_node("optimizer", optimizer_node)
graph.add_node("reporter", reporter_node)

graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route_to_agent, {...})

# Specialists route back to supervisor for multi-step workflows
for agent in ["cost_analyst", "anomaly_detector", "optimizer"]:
    graph.add_edge(agent, "supervisor")

graph.add_edge("reporter", END)

# Checkpointing: DynamoDB-backed (DynamoDBSaver) or MemorySaver fallback
app = graph.compile(checkpointer=get_checkpointer())
```

---

## 12. Configuration

```hcl
# terraform.tfvars
aws_region       = "us-east-1"
project_name     = "agentcore-billing"
environment      = "dev"
deploy_phase     = 1              # 1 = core infra, 2 = + monitoring

monthly_budget   = 1000
slack_channel_id = ""             # Set when Slack bot is configured

bedrock_model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
```

---

## 13. Security

- **Secrets**: Slack tokens stored in AWS Secrets Manager — accessed at runtime
- **IAM**: Per-service roles with least-privilege policies
- **Encryption**: S3 buckets use SSE, DynamoDB uses AWS-managed encryption
- **Network**: AgentCore Runtime runs in isolated microVMs — PUBLIC network mode
- **Logging**: All agent invocations logged via CloudWatch
- **Data Retention**: CUR data 13 months, DynamoDB cache 24-hour TTL

---

## 14. Cost Estimate (This System)

| Component | Estimated Monthly Cost |
|-----------|----------------------|
| AgentCore Runtime | ~$50-150 (depends on invocation volume) |
| Bedrock Claude (Sonnet) | ~$30-100 (depends on query volume) |
| CUR S3 Storage | ~$5-15 |
| Athena Queries | ~$5-20 |
| DynamoDB (Cache + Checkpoints) | ~$5 (on-demand) |
| Lambda (invoker + cost_tools) | ~$1-3 |
| EventBridge | ~$0.01 |
| API Gateway | ~$1-3 |
| Secrets Manager | ~$2 |
| Dashboard (Streamlit Community Cloud) | **Free** |
| **Total Estimated** | **~$100-300/month** |

---

## 15. Current Status

### What's Deployed & Working ✅

- **Terraform Phase 1**: All infrastructure successfully provisioned (35+ AWS resources)
- **AgentCore Runtime**: **RUNNING** — raw HTTP server starts, responds to `/ping` and `/invocations`
- **All imports load successfully**: LangGraph, LangChain, boto3, pydantic, etc. — all 39 packages bundled as ARM64 wheels
- **Handler dispatching works**: Payloads are routed correctly to `handle_scheduled_report()` and `handle_slack_message()`
- **AgentCore Gateway**: MCP tool registry with 5 tools targeting the `cost_tools` Lambda
- **Invoker Lambda**: Deployed and able to call `invoke_agent_runtime` API
- **EventBridge Rules**: 3 schedules configured (daily, anomaly, weekly)
- **API Gateway**: Slack webhook endpoint live at `https://ibdquhfl24.execute-api.us-east-1.amazonaws.com/slack/events`
- **Data Pipeline**: CUR export, Glue crawler, Athena workgroup provisioned
- **DynamoDB Tables**: Cache + checkpoints tables created
- **Dashboard**: Streamlit app code ready for Community Cloud deployment

### Testing Status

**Direct invocation** (via `invoke_agent_runtime` API):

```python
# Health check — ✅ WORKS
payload = {"action": "health_check"}
# → {"status": "ok", "message": "Billing Intelligence System is running"}

# Direct query — routes to LangGraph (next to test end-to-end)
payload = {"prompt": "What is my AWS spend this month?"}

# Scheduled report trigger
payload = {"action": "scheduled_report", "report_type": "daily"}

# Slack message
payload = {"action": "slack_message", "message": "Show me cost anomalies", "thread_id": "123"}
```

### What Needs Testing Next

- **End-to-end agent execution**: Send a `prompt` and verify LangGraph runs Supervisor → Cost Analyst → Reporter
- **Bedrock model access**: Confirm the Runtime's IAM role can invoke `anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Cost Explorer API calls**: Verify the agent can query real AWS spend data
- **Slack message delivery**: Test Reporter sending results to Slack
- **Dashboard data persistence**: Verify Reporter writes JSON to S3

---

## 16. Resolved Issues Log

### Issue 1: Runtime Initialization Timeout (30s limit)

**Error**: `RuntimeClientError: Runtime initialization time exceeded. Please make sure that initialization completes in 30s.`

**Approaches tried (in order):**

| # | Approach | Zip Size | Result |
|---|----------|----------|--------|
| 1 | `bedrock-agentcore` SDK + `requirements.txt` (no bundled deps) | 40KB | ❌ pip install at cold start exceeds 30s |
| 2 | `bedrock-agentcore` SDK bundled as ARM64 wheels | 42MB | ❌ SDK + starlette + uvicorn too heavy to load in 30s |
| 3 | Slimmed bundle (removed boto3/botocore) | 19MB | ❌ Still timeout — SDK imports too slow |
| 4 | Minimal `bedrock-agentcore` only (no app deps) | 5MB | ❌ SDK itself + transitive deps exceed init window |
| 5 | **Raw `http.server` + ALL deps bundled as ARM64 wheels** | **39MB** | ✅ **Instant startup** — stdlib server needs 0 heavy imports at boot |

**Solution**: Replace the `bedrock-agentcore` SDK entry point with a raw `http.server.HTTPServer` that implements the same `/ping` + `/invocations` protocol. The stdlib server starts in <1ms. Agent dependencies (`langgraph`, `langchain`, etc.) are **lazy-loaded** on first invocation, not at startup.

### Issue 2: Missing Dependencies (iterative discovery)

The AgentCore Runtime has **only bare Python stdlib** — unlike Lambda, it does NOT pre-install `boto3`, `urllib3`, `certifi`, etc.

**Packages we incorrectly assumed were pre-installed:**
- `boto3`, `botocore`, `s3transfer` — NOT pre-installed (unlike Lambda)
- `urllib3`, `certifi` — NOT pre-installed
- `httpx`, `zstandard` — required by `langchain-core` / `langsmith`
- `numpy` — required by `langchain-aws`

**Fix**: Bundle ALL 39 transitive dependencies. Remove nothing.

### Issue 3: ARM64 Platform Targeting

AgentCore Runtime runs on ARM64 (`aarch64`). If wheels are built for x86_64, native extensions (like `pydantic-core`, `orjson`, `numpy`) fail silently or crash.

**Fix**: Use `uv pip install --python-platform manylinux_2_17_aarch64 --python-version 3.12 --only-binary=:all:` to ensure correct platform wheels.

---

## 17. Deployment Commands

### Build & Deploy Agent Code to S3

```bash
cd agents/

# 1. Clean previous build
rm -rf deployment_package deployment_package.zip

# 2. Install ALL dependencies as ARM64 wheels for Python 3.12
mkdir -p deployment_package
cat > /tmp/runtime-requirements.txt << 'EOF'
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-aws>=0.2.0
requests>=2.28.0
boto3>=1.35.0
botocore>=1.35.0
EOF

uv pip install \
  --python-platform manylinux_2_17_aarch64 \
  --python-version 3.12 \
  --target=deployment_package \
  --only-binary=:all: \
  -r /tmp/runtime-requirements.txt

# 3. Strip __pycache__ for size
find deployment_package -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 4. Create zip (deps first, then app code on top)
cd deployment_package && zip -r -q ../deployment_package.zip . && cd ..
zip deployment_package.zip app.py
zip -r -q deployment_package.zip src/ -x "*.pyc" -x "*__pycache__*"

# 5. Upload to S3
aws s3 cp deployment_package.zip \
  s3://agentcore-billing-dev-agent-code-088130860316/agent-code/billing-agents.zip \
  --region us-east-1

# 6. Copy as placeholder for Terraform
cp deployment_package.zip ../terraform/modules/agentcore/placeholder.zip
```

### Taint & Recreate Runtime (Terraform)

```bash
cd terraform/

terraform taint module.agentcore.aws_bedrockagentcore_agent_runtime.billing
terraform taint module.agentcore.aws_bedrockagentcore_agent_runtime_endpoint.billing
terraform apply -auto-approve
```

### Test Runtime Invocation

```python
import boto3, json

client = boto3.client("bedrock-agentcore", region_name="us-east-1")

# Get the runtime ARN from terraform output
# terraform output agentcore_runtime_arn

response = client.invoke_agent_runtime(
    agentRuntimeArn="<RUNTIME_ARN>",
    qualifier="agentcore_billing_dev_billing_endpoint",
    payload=json.dumps({"action": "health_check"}).encode("utf-8"),
    contentType="application/json",
    accept="application/json",
)

print("Status:", response.get("statusCode"))
resp = response.get("response")
if hasattr(resp, "read"):
    print("Body:", resp.read().decode("utf-8"))
```

logs in /aws/lambda/agentcore-billing-dev-runtime-invoker