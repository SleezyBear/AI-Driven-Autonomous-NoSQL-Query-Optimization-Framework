# 🧠🗄️ AI-Driven Autonomous NoSQL Query Optimization Framework

> An AI that's allowed to *look* at your MongoDB, form an opinion, argue that opinion in a sandboxed copy of your data — and only gets to actually touch production if it wins the argument with numbers, not vibes.

This isn't "ask an LLM to write you an index." It's a control plane that sits next to a live MongoDB, continuously diagnoses its query workload, proposes fixes, proves they work in isolation, and then walks the change through an audited, reversible pipeline before it's allowed anywhere near your real data. Think of the model as a very confident junior DBA who is never, ever handed the production credentials directly.

---

## 🎭 The pitch, minus the marketing

Every optimization travels down the same fixed 17-stage rail, every single time:

```
CREATED → SNAPSHOTTING → DIAGNOSING → GENERATING_CANDIDATES → RANKING
        → CALIBRATING → EVALUATING → ADMISSION → ADMITTED
        → APPROVAL_PENDING → APPROVED → DEPLOYING → DEPLOYED
        → MONITORING → COMPLETED
                     ↘ ROLLED_BACK / ROLLBACK_BLOCKED / FAILED (any gate)
```

The AI gets a say at exactly two of those stages — `DIAGNOSING` and `RANKING`. It doesn't get a vote on whether a candidate is *allowed to exist*, whether it *actually helped*, or whether it's *safe to ship*. That's all deterministic code with no vibes to appeal to.

---

## 🔬 What's actually going on under the hood

- **Snapshot first, opinions second.** A run starts by freezing the target's real query shapes and index stats into an immutable snapshot, turned into an evidence bundle with hashable IDs (`evidence_ref`, `query_shape_id`, `SNAPSHOT:<id>`). That's the *only* thing the model is allowed to cite.

- **Diagnosis on a short leash.** The evidence goes to a local model (this project is built around Ollama — nothing leaves the host). The system prompt is not subtle about it: *"If you cannot cite exact supplied IDs, return an empty findings list. Do not invent metric values, query-shape IDs, evidence references, findings, MongoDB commands, or executable actions."* No citation, no finding.

- **Candidates come from math, not imagination.** Index candidates are produced by a deterministic generator (`DeterministicIndexGenerator`) applying the classic Equality → Sort → Range pattern to a query shape's fields, yielding a typed, hash-identified `CreateIndexAction` — never a raw string the model could smuggle a command into. The LLM's downstream job is narrower still: rank *opaque handles* it's handed. It can't rename them, invent new ones, or drop any ("Handles are not database identities and do not define or modify candidates.").

- **Experience memory nudges the order.** A lightweight learned prior re-sorts candidates toward patterns that have empirically worked before, sitting in front of the LLM call rather than inside it.

- **Everything gets benchmarked in a sandbox, never in prod.** Surviving candidates run against an isolated evaluation copy of the data under one of three frozen statistical profiles (`SMOKE`, `AUTONOMOUS`, `PUBLICATION`), each with its own warm-up time, sample-size floor, and confidence requirement.

- **Admission is arithmetic.** A frozen JSON policy defines per-metric directions, improvement caps, and "zero-tolerance invariants" — metrics that are never allowed to regress, no matter how good everything else looks. A candidate is admitted only if the *measured* improvement clears a configured threshold.

- **Approval is glued to the evidence, not the action.** Every human approval is bound to a specific `evidence_hash`. If the underlying diagnosis changes after someone approves it, the approval goes `STALE` and can't be reused. It also expires (15 minutes by default) — no rubber-stamping something from last week.

- **"Full autonomous" is a narrow exception, not a master switch.** It waives human approval only for two low-blast-radius action types (`CREATE_INDEX`, a query-settings index hint) — and even those can be force-gated back to human review with a flag that always wins.

- **Every real write gets chained into a ledger.** SHA-256 hash-chained entries capture before/after state, the forward action *and* its inverse, and the evidence hash — a tamper-evident history where every change already carries its own undo button.

- **Rollback is an outcome, not a hope.** Deployed changes can transition to `ROLLED_BACK` — or honestly to `ROLLBACK_BLOCKED` when a safe reversal can't be guaranteed, instead of quietly pretending everything's fine.

---

## 🏗️ Architecture, the 30-second version

| Layer | Tech | Job |
|---|---|---|
| **Control-plane API** | FastAPI + PostgreSQL (async SQLAlchemy, Alembic) | Source of truth for runs, approvals, the ledger, auth |
| **Worker** | Async Python | Actually runs the diagnosis→admission→deploy pipeline |
| **Target datastore** | MongoDB replica set | What's being optimized — touched only through a typed adapter, never a shell command |
| **AI provider** | Ollama (chat + embedding model) | Diagnosis and ranking, always evidence-grounded |
| **Frontend** | React + TypeScript + Vite + Tailwind | Dashboards for runs, targets, workloads, approvals |
| **Glue** | Docker Compose profiles (`light`, `replica-test`, `paper`) | Reproducible environments |

The safety story isn't just prompt-level pleading — `app/adapters/contracts.py` defines the *entire* set of operations orchestration code can perform against the target: list namespaces, list indexes, a typed `IndexSpec`, a typed query-settings hint. There is no code path from "the model said so" to "arbitrary command runs on your cluster."

---

## 🗂️ Repo layout, skimmed

```
backend/app/
  state_machine/    ← the frozen 17-state lifecycle
  pipeline/         ← snapshot → evidence → candidates → AI → sandbox → admission
  candidates/        ← deterministic ESR index generation
  ai/               ← Ollama provider + the two locked-down prompts
  admission/         ← statistical profiles + zero-tolerance metric policy
  approvals/         ← evidence-bound, expiring approval flow
  autonomy/          ← the narrow full-autonomous bypass rule
  ledger/            ← hash-chained production action log
  rollback/          ← inverse-action rollback machinery
  adapters/          ← the typed MongoDB adapter (+ fakes for tests)
  monitoring/        ← post-deployment health + workload-shift detection
frontend/src/        ← runs / targets / workloads / expert dashboards
docs/                ← RUNBOOK, THREAT_MODEL, SAFETY_CONTRACT, audits
scripts/              ← bootstrap, demo mode, acceptance automation
```

---

## 🚀 Getting it running

Heads up: the repo's own `bootstrap.sh` is written for **macOS on Intel**, and it hard-fails on anything else. The good news is that everything past "get a Python interpreter and Docker" is just Docker Compose — so here's the honest setup path per platform.

### Everyone, first — grab these

- Docker Desktop (or Docker Engine + Compose on Linux)
- Python 3.12 (any interpreter — the secret-generation scripts are pure stdlib, no venv required just to get going)
- [Ollama](https://ollama.com), running locally, with a chat model and an embedding model pulled (defaults in `.env.example` are `gemma4:e4b` and `embeddinggemma`)

Then, from the repo root, the shared steps are the same everywhere:

```bash
cp .env.example .env                # set a real JWT_SIGNING_KEY in here
mkdir -p .secrets
python3 scripts/generate_master_key.py --output .secrets/control_plane_master_key
python3 scripts/generate_mongodb_keyfile.py --output .secrets/mongodb_replica_keyfile
docker compose --profile light up -d
```

That's it — API, worker, Postgres, two Mongo targets, and the frontend all come up. What differs per platform is just *how you get there*:

<details>
<summary><b>🍎 Intel Mac</b></summary>

You're the officially supported path. You can use the repo's own bootstrap for the extras (a project-local `uv`-managed Python 3.12 venv, useful if you want to run the test suite or scripts outside Docker):

```bash
./scripts/bootstrap.sh
source nosql/bin/activate
```
Then run the shared steps above. `make dev` is shorthand for the same `docker compose --profile light up -d`.
</details>

<details>
<summary><b>🍏 Apple Silicon (M-series) Mac</b></summary>

`bootstrap.sh` will refuse to run (it checks `uname -m` for `x86_64`). Skip it and just run the shared steps above directly — Docker Desktop on Apple Silicon happily runs `linux/amd64` images under emulation, which is exactly what this compose file targets, so it works, just a bit slower on first pull/build. If you want the local dev venv too, drop the CPU-arch guard at the top of `scripts/bootstrap.sh` or set up `uv` and a Python 3.12 venv by hand.
</details>

<details>
<summary><b>🐧 Linux</b></summary>

Also not what `bootstrap.sh` expects, also not a real obstacle. Install Docker Engine + the Compose plugin, install Python 3.12 (or use `uv`) if you want the dev venv, and run the shared steps above. Everything's already `linux/amd64` native here, so this is arguably the smoothest path.
</details>

<details>
<summary><b>🪟 Windows</b></summary>

Use **WSL2** — run everything (Docker Desktop with the WSL2 backend, Python, Ollama or a `localhost` bridge to Windows-side Ollama) from inside a WSL2 Ubuntu shell and follow the Linux steps above. Running the Bash scripts and Compose directly from PowerShell isn't a supported path here.
</details>

### Take it for a spin (no real workload needed)

```bash
make demo-reset      # clean slate
make demo-start       # bring demo services up
make demo-seed        # load sample data + query shapes
make demo-workload    # generate traffic for the system to diagnose
```
Open the frontend (Vite default is `http://localhost:5173`) and watch a run crawl through the lifecycle in real time.

### Or drive it straight from the API

```bash
# log in
curl -X POST http://localhost:8000/auth/login -d '{"username": "...", "password": "..."}'

# register a target
curl -X POST http://localhost:8000/targets -H "Authorization: Bearer $TOKEN" -d '{ ... }'

# start an optimization run against it
curl -X POST http://localhost:8000/runs -H "Authorization: Bearer $TOKEN" -d '{ "target_id": "..." }'

# check on it
curl http://localhost:8000/runs/{run_id} -H "Authorization: Bearer $TOKEN"
```

If a run lands on `APPROVAL_PENDING`, review the evidence and:
```bash
curl -X POST http://localhost:8000/approvals/{approval_id}/approve -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/approvals/{approval_id}/reject  -H "Authorization: Bearer $TOKEN"
```
(Full-autonomous mode skips this only for index creation / query-hint actions — everything else always stops here.)

### Run the tests

```bash
make test          # unit + integration
make acceptance    # the broader gate
```
`backend/tests/` mirrors `backend/app/` module-for-module, so it doubles as a map of *how* each safety guarantee above is actually checked (`safetybench/adversarial.py` is worth a look if you want to see the adversarial-prompt tests).

Before pointing any of this at a real production MongoDB: read `docs/RUNBOOK.md`. It's blunt about connection-pool math, migration locking, TLS requirements, and exactly what the system refuses to do during a Postgres or Mongo outage.

---

## 🛡️ The one-sentence version of why it's built this way

Language models are great at hypotheses and bad at being trusted with side effects — so this one never touches the database, never emits a raw command, and never gets the last word. It proposes; deterministic code and measured evidence dispose.
