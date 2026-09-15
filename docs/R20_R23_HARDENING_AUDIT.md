# R20–R23 production-hardening audit

## Baseline

| Area | Classification | Finding |
| --- | --- | --- |
| API JWT, CORS, trusted hosts | NEEDS_HARDENING | JWT is explicit, but runtime configuration is split and readiness is not dependency-backed. |
| Encryption master key | NEEDS_HARDENING | AES-256-GCM key loading is strict, but production startup does not validate the mounted key centrally. |
| Docker runtime images | NEEDS_HARDENING | Minimal images and pinned platforms exist; API, worker, and frontend run as root. |
| Compose profiles/secrets | DEV_ONLY | Profiles and Docker secrets exist, with clearly fake local credentials and host-facing development ports. |
| PostgreSQL runtime | NEEDS_HARDENING | A single factory exists but has only `pool_pre_ping`; pool, timeout, and production URL policy are absent. |
| Alembic | PARTIAL | One linear migration chain and transactional PostgreSQL DDL exist; operational locking/backup verification are not yet exposed. |
| Mongo connections | NEEDS_HARDENING | Capability discovery is bounded, but evaluation copying constructs independent clients with partial timeout settings. |
| Health/readiness | NEEDS_HARDENING | Liveness is truthful; API readiness returns ready without checking PostgreSQL. Worker readiness checks PostgreSQL. |
| Logging/correlation | PARTIAL | Structured request logging and request IDs exist; no metrics endpoint or complete safe operational context. |
| Python dependencies | PARTIAL | Pinned `requirements.txt` is the canonical contract; no SBOM or vulnerability/secret scan automation. |
| Node dependencies | PRODUCTION_READY | Node 22 is pinned, `package-lock.json` is used by the production Docker build. |
| Frontend runtime | NEEDS_HARDENING | Production static image is minimal, but API base defaults to localhost and security headers are absent. |

## Scope boundary

R20–R23 will harden runtime/configuration, dependency inventory, PostgreSQL
operations, and Mongo connection handling. It does not claim qualification;
R24 remains the separate adversarial/no-mock qualification gate.
