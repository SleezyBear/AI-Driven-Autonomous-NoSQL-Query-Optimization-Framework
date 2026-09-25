# 🧠🗄️ AI-Driven Autonomous NoSQL Query Optimization Framework

> *An AI that's allowed to watch your database, form an opinion about it, argue that opinion in front of a sandbox, and — only if it wins the argument fair and square — quietly make it faster.*

This is not a chatbot that writes MongoDB queries for you. It's a **control plane**: a service that sits beside a live MongoDB deployment, continuously reasons about its query workload, proposes indexes and query-settings changes, proves those proposals actually help in an isolated copy of the data, and then walks the change through an auditable, reversible, optionally human-gated deployment pipeline. The AI is treated the way you'd treat a very opinionated junior DBA — useful for ideas, never trusted with the keys unsupervised.

---

## 🎭 The elevator pitch

Every optimization the system ever makes travels down the same fixed, seventeen-stage rail. Nothing skips stages, nothing writes to production without earning it, and nothing is undone without leaving a paper trail:

```
CREATED → SNAPSHOTTING → DIAGNOSING → GENERATING_CANDIDATES → RANKING
        → CALIBRATING → EVALUATING → ADMISSION → ADMITTED
        → APPROVAL_PENDING → APPROVED → DEPLOYING → DEPLOYED
        → MONITORING → COMPLETED
                     ↘ ROLLED_BACK / ROLLBACK_BLOCKED / FAILED (at any gate)
```

The AI only ever gets a vote at two of those stages (`DIAGNOSING` and `RANKING`). Everything else — whether a candidate is even *allowed to exist*, whether it measurably helped, whether it's safe to ship — is decided by deterministic code the model has no way to talk its way around.

---

## 🔬 What's actually happening, stage by stage

**1. Snapshot & evidence, not vibes.**
A run starts by taking an immutable snapshot of the target's real query shapes, index layout, and execution stats. That snapshot is converted into a text "evidence" bundle with explicit, hashable evidence references (`evidence_ref`, `query_shape_id`, `SNAPSHOT:<id>`) — the only things the model is permitted to cite.

**2. Diagnosis, on a leash.**
The evidence goes to a local model (the project targets Ollama, running on the host — no data leaves the machine). The diagnosis prompt is blunt about it: *"If you cannot cite exact supplied IDs, return an empty findings list. Do not invent metric values, query-shape IDs, evidence references, findings, MongoDB commands, or executable actions."* A finding the model can't ground in real evidence simply doesn't count.

**3. Candidates are generated, not imagined.**
Actual index candidates come from a **deterministic** generator (`DeterministicIndexGenerator`), not the LLM. It takes a query's equality/sort/range fields and mechanically applies the frozen ESR (Equality → Sort → Range) pattern, producing a stable, hash-identified `CreateIndexAction` — a typed, schema-validated object, never a raw command string. The model's role downstream is narrower still: it may only **rank opaque candidate handles** it's handed ("Return every supplied handle exactly once, with no new, missing, or duplicate handles. Handles ... do not define or modify candidates.").

**4. Experience memory.**
Before ranking, candidates are pre-ordered by an experience-memory component that biases toward patterns that have empirically worked before — a lightweight learned prior sitting in front of the LLM call, not inside it.

**5. Calibration & evaluation in a sandbox, never in production.**
Every surviving candidate is applied to an isolated evaluation copy of the target data (`evaluation/sandbox.py`, `mongodb_copier.py`) and benchmarked under one of three frozen statistical profiles — `SMOKE`, `AUTONOMOUS`, `PUBLICATION` — each specifying warm-up time, minimum sample counts, and required confidence (e.g. the autonomous profile demands ≥10 paired A/A and A/B samples at 95% confidence before a candidate is even eligible).

**6. Admission is arithmetic, not opinion.**
`admission/policy.py` loads a frozen JSON policy of per-metric directions, relative/absolute improvement caps, hard upper boundaries, and "zero-tolerance invariants" (metrics that must never regress, no matter how good everything else looks). A candidate is admitted only if it clears a configured *minimum meaningful improvement* threshold — measured, not asserted.

**7. Approval is bound to the evidence, not the action.**
Every `Approval` is a signed record tied to one specific `evidence_hash`. If the underlying diagnosis or benchmark evidence changes after a human approves it, the approval goes `STALE` and can't be reused — deploying always re-checks that what's about to happen is what was actually approved. Approvals also expire (15-minute default TTL).

**8. Full-autonomous mode is a scoped exception, not a master switch.**
`DeploymentMode.FULL_AUTONOMOUS` doesn't remove human oversight everywhere — it only waives approval for two specific, low-blast-radius action types (`CREATE_INDEX`, `SET_QUERY_SETTINGS_INDEX_HINT`), and even that can be overridden per-action by a `permanent_human_gate` flag that always wins.

**9. Every real-world write is a ledger entry.**
Production-relevant actions are recorded in a SHA-256 hash-chained ledger (`ledger/chain.py`) — genesis hash, before/after state, forward action *and* its inverse action, evidence hash, actor — so the entire deployment history is tamper-evident and every change carries its own rollback recipe.

**10. Rollback is a first-class outcome, not an afterthought.**
`DEPLOYED` and `MONITORING` are the only states that can transition to `ROLLED_BACK` — or to `ROLLBACK_BLOCKED` when a safe reversal genuinely can't be guaranteed, which is a distinct, honestly-reported outcome rather than a silent failure.

---

## 🏗️ Architecture at a glance

| Layer | Tech | Role |
|---|---|---|
| **Control-plane API** | FastAPI + PostgreSQL (asyncpg/SQLAlchemy, Alembic migrations) | Owns runs, approvals, the ledger, auth (JWT + RBAC) — the durable source of truth |
| **Worker** | Async Python service | Executes the diagnosis→admission→deployment pipeline against targets |
| **Target datastore** | MongoDB (replica set) | The database actually being optimized — accessed only through a typed `DatabaseAdapter`, never raw shell commands |
| **AI provider** | Ollama (local LLM + embedding model) | Diagnosis and candidate ranking only, always evidence-grounded |
| **Frontend** | React + TypeScript + Vite, Tailwind | Dashboards for runs, targets, workloads, approvals, and an "expert" view |
| **Everything glued together with** | Docker Compose profiles (`light`, `replica-test`, `paper`) | Reproducible local and benchmark environments |

Safety is enforced at the *interface* level, not just the prompt level: `app/adapters/contracts.py` defines the only operations orchestration code can perform on the target — `list_namespaces`, `list_indexes`, a typed `IndexSpec`, a typed `QuerySettingsIndexHint`. There is no code path from "AI says X" to "arbitrary command runs on your cluster."

---

## 🗂️ Repo layout (the short version)

```
backend/app/
  state_machine/    ← the frozen 17-state lifecycle graph
  pipeline/         ← orchestrates snapshot → evidence → candidates → AI → sandbox → admission
  candidates/        ← deterministic index-candidate generation (ESR pattern)
  ai/               ← Ollama provider + the two locked-down prompts (diagnosis, ranking)
  admission/         ← statistical profiles + zero-tolerance metric policy
  approvals/         ← evidence-bound, expiring human approval flow
  autonomy/          ← the narrow full-autonomous approval-bypass rule
  ledger/            ← SHA-256 hash-chained production action log
  rollback/          ← inverse-action rollback machinery
  adapters/          ← the typed MongoDB adapter (+ fakes for testing)
  monitoring/        ← post-deployment health + workload-shift detection
frontend/src/        ← runs / targets / workloads / expert dashboards
docs/                ← RUNBOOK, THREAT_MODEL, SAFETY_CONTRACT, PLAN_COMPLIANCE_MATRIX, audits
scripts/              ← bootstrap, demo mode, acceptance-gate automation
```

---

## 🚀 How you'd actually go about using it

> ⚠️ Read this before you start: the bootstrap script currently hard-checks for **macOS on Intel x86_64** and pins to `linux/amd64` Docker images. If you're on Apple Silicon or Linux, you'll need to adapt `scripts/bootstrap.sh` yourself — it's a good first PR.

**1. Get the prerequisites in place.**
You'll need Docker, [`uv`](https://github.com/astral-sh/uv) for a project-local Python 3.12 environment, and [Ollama](https://ollama.com) running on the host (the compose setup expects `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBEDDING_MODEL` — defaults are `gemma4:e4b` and `embeddinggemma` per `.env.example`).

**2. Bootstrap the environment.**
```bash
./scripts/bootstrap.sh
source nosql/bin/activate
```
This creates the project's dedicated virtualenv (`nosql/`) — don't install into system Python or any other venv; the project is strict about this on purpose.

**3. Generate your local secrets.**
```bash
mkdir -p .secrets
./nosql/bin/python scripts/generate_master_key.py --output .secrets/control_plane_master_key
./nosql/bin/python scripts/generate_mongodb_keyfile.py --output .secrets/mongodb_replica_keyfile
```
These are development-only secrets Compose mounts into the containers — never commit them, never reuse them in production.

**4. Copy and fill in your environment file.**
```bash
cp .env.example .env
```
At minimum, set a real `JWT_SIGNING_KEY`. Everything else has sane local defaults.

**5. Run preflight, then bring the stack up.**
```bash
make preflight
make dev          # docker compose --profile light up -d
```
This starts PostgreSQL, the two MongoDB targets (`mongo-monitored`, `mongo-evaluation`), the API, the worker, and the frontend.

**6. Kick the tires with demo mode** (the friendliest on-ramp — no real workload required):
```bash
make demo-reset      # clean slate
make demo-start       # bring demo services up
make demo-seed        # load a representative dataset + query shapes
make demo-workload    # generate traffic for the system to diagnose
```

**7. Open the frontend** (default Vite dev port, typically `http://localhost:5173`) and watch a run go through the lifecycle live: snapshot → diagnosis → candidates → ranking → sandbox evaluation → admission.

**8. Or drive it directly against the API:**
```bash
# authenticate
curl -X POST http://localhost:8000/auth/login -d '{"username": "...", "password": "..."}'

# register a target MongoDB deployment
curl -X POST http://localhost:8000/targets -H "Authorization: Bearer $TOKEN" -d '{ ... }'

# kick off an optimization run against it
curl -X POST http://localhost:8000/runs -H "Authorization: Bearer $TOKEN" -d '{ "target_id": "..." }'

# poll it
curl http://localhost:8000/runs/{run_id} -H "Authorization: Bearer $TOKEN"
```

**9. If the run reaches `APPROVAL_PENDING`**, review the evidence and either:
```bash
curl -X POST http://localhost:8000/approvals/{approval_id}/approve -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/approvals/{approval_id}/reject  -H "Authorization: Bearer $TOKEN"
```
(Full-autonomous mode skips this step for `CREATE_INDEX` and query-hint actions only — everything else always stops here.)

**10. Run the test and acceptance suites** to see the safety guarantees exercised directly:
```bash
make test          # unit + integration tests
make acceptance    # broader acceptance gate
```
The `backend/tests/` tree is organized by exactly the same subsystems as `backend/app/` (`rollback/`, `autonomy/`, `ranking/`, `evaluation/`, `auth/`, `safetybench/adversarial.py` for adversarial-prompt tests, etc.) — a good map for exploring *how* each guarantee is actually verified.

**11. Read `docs/RUNBOOK.md` before you get anywhere near a real production MongoDB.** It covers connection-pool capacity math, migration locking, MongoDB TLS requirements, and exactly what the system does (and refuses to do) during a PostgreSQL or MongoDB outage.

---

## 🛡️ Why it's built this way

The throughline across every module here is the same design bet: **language models are good at generating hypotheses and bad at being trusted with side effects.** So the AI never touches the database, never writes an executable command, and never gets the last word — it proposes, deterministic code and measured evidence dispose. That's the whole framework in one sentence; everything above is just how seriously it's taken.
