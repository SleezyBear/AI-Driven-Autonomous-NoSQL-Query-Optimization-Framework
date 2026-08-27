PYTHON := ./nosql/bin/python
PIP := ./nosql/bin/python -m pip

.PHONY: preflight wheel-test phase0-acceptance phase-r0-acceptance phase-r1-acceptance phase-r2-acceptance phase-r3-acceptance phase-r4-acceptance phase-r5-acceptance phase-r6-acceptance phase-r7-acceptance phase-r8-acceptance phase-r9-acceptance phase-r10-acceptance phase-r11-acceptance phase-r12-acceptance phase15-acceptance pip-check test dev replica-test-env paper-env acceptance nosqlbench-smoke safetybench phase43-acceptance phase44-acceptance phase45-acceptance phase46-acceptance phase47-acceptance phase48-acceptance phase49-acceptance phase50-acceptance phase51-acceptance phase52-acceptance phase53-acceptance phase54-acceptance phase55-acceptance demo-reset demo-start demo-seed demo-workload

preflight:
	$(PIP) check
	$(PYTHON) scripts/verify_requirements.py
	$(PYTHON) scripts/check_python_dependencies.py
	$(PYTHON) scripts/verify_environment.py

wheel-test:
	rm -rf .dependency-wheel-test
	mkdir -p .dependency-wheel-test
	$(PYTHON) -m pip download --quiet --only-binary=:all: --dest .dependency-wheel-test -r requirements.txt

phase0-acceptance: wheel-test preflight
	$(PYTHON) -c 'import sys; assert sys.version_info[:2] == (3, 12)'
	$(PYTHON) -c 'import platform; assert platform.machine() == "x86_64"'

phase-r0-acceptance:
	$(PYTHON) scripts/check_system_pass_registry.py
	$(PYTHON) -m pytest backend/tests/tooling/test_system_pass_registry.py

phase-r1-acceptance:
	$(PIP) check
	$(PYTHON) scripts/check_python_dependencies.py
	$(PYTHON) scripts/verify_requirements.py
	$(PYTHON) scripts/verify_environment.py
	$(PYTHON) -m pytest backend/tests
	$(PYTHON) -m ruff check backend
	$(PYTHON) -m mypy backend/app
	$(PYTHON) -c 'import platform, sys; assert sys.version_info[:2] == (3, 12); assert platform.machine() == "x86_64"'

phase-r2-acceptance:
	$(PYTHON) -m pytest backend/tests/schema
	$(PYTHON) scripts/check_control_plane_schema.py

phase-r3-acceptance:
	$(PYTHON) -m pytest backend/tests/repositories backend/tests/worker/test_durable.py
	$(PYTHON) scripts/check_repository_restart.py write --state-file .r3-restart-state.json
	docker compose --profile light up -d --build api worker
	docker compose --profile light restart api worker
	docker compose --profile light up -d --wait api worker
	curl --fail --silent http://localhost:8000/health/ready > /dev/null
	$(PYTHON) scripts/check_repository_restart.py verify --state-file .r3-restart-state.json

phase-r4-acceptance:
	JWT_SIGNING_KEY='r4-test-signing-key-that-is-long-enough' docker compose --profile light up -d --wait postgres
	$(PYTHON) -m alembic -c backend/alembic.ini upgrade head
	JWT_SIGNING_KEY='r4-test-signing-key-that-is-long-enough' $(PYTHON) -m pytest backend/tests/auth/test_production_auth.py

phase-r5-acceptance:
	docker compose --profile light up -d --wait postgres
	$(PYTHON) -m alembic -c backend/alembic.ini upgrade head
	$(PYTHON) -m pytest backend/tests/approvals/test_durable_distributed.py
	docker compose --profile light up -d --build api worker
	docker compose --profile light restart api worker
	docker compose --profile light up -d --wait api worker

phase-r6-acceptance:
	docker compose --profile light up -d --wait postgres
	$(PYTHON) -m pytest backend/tests/production/test_distributed_target_lock.py

phase-r7-acceptance:
	docker compose --profile light up -d --wait postgres
	$(PYTHON) -m alembic -c backend/alembic.ini upgrade head
	$(PYTHON) -m pytest backend/tests/ledger/test_postgres_ledger.py

phase-r8-acceptance:
	docker compose --profile light up -d --wait postgres
	$(PYTHON) -m alembic -c backend/alembic.ini upgrade head
	$(PYTHON) -m pytest backend/tests/recovery/test_durable_idempotency.py

phase-r9-acceptance:
	JWT_SIGNING_KEY='r9-test-signing-key-that-is-long-enough' $(PYTHON) -m pytest backend/tests/api/test_real_routes.py

phase-r10-acceptance:
	$(PYTHON) -m pytest backend/tests/metrics/test_canonical_semantics.py

phase-r11-acceptance:
	$(PYTHON) -m pytest backend/tests/telemetry backend/tests/security/test_privacy.py

phase-r12-acceptance:
	$(PYTHON) -m pytest backend/tests/commercebench
	$(PYTHON) scripts/reset_commercebench.py --profile smoke

phase15-acceptance:
	$(PYTHON) scripts/phase15_acceptance.py

pip-check:
	$(PIP) check

test:
	$(PYTHON) -m pytest backend/tests

dev:
	docker compose --profile light up -d

replica-test-env:
	docker compose --profile replica-test up -d

paper-env:
	docker compose -f docker-compose.yml -f docker-compose.paper.yml --profile paper up -d

acceptance:
	$(PYTHON) scripts/verify_environment.py
	$(PIP) check
	$(PYTHON) scripts/check_python_dependencies.py
	$(PYTHON) scripts/check_makefile_python.py
	$(PYTHON) -m pytest backend/tests
	$(PYTHON) -m ruff check backend benchmarks scripts
	MYPYPATH=backend $(PYTHON) -m mypy backend/app benchmarks scripts/collect_hardware_manifest.py scripts/demo_mode.py scripts/check_makefile_python.py
	$(PYTHON) -m alembic -c backend/alembic.ini upgrade head
	$(PYTHON) -m pytest backend/tests/adapters
	$(PYTHON) -m pytest backend/tests/auth backend/tests/mongodb/test_executor_permissions.py backend/tests/production
	$(PYTHON) -m pytest backend/tests/unit/admission
	$(PYTHON) -m pytest backend/tests/ledger
	$(PYTHON) -m pytest backend/tests/security
	docker run --rm --platform linux/amd64 -v "$(CURDIR)/frontend:/app" -w /app node:22.14.0-alpine npm test
	docker compose --profile light up -d --build frontend
	docker run --rm --platform linux/amd64 --add-host host.docker.internal:host-gateway -v "$(CURDIR)/frontend:/app" -w /app mcr.microsoft.com/playwright:v1.47.1-jammy npx playwright test
	$(PYTHON) -m pytest backend/tests/commercebench
	$(MAKE) nosqlbench-smoke
	$(PYTHON) -m pytest backend/tests/safetybench
	$(PYTHON) -m pytest backend/tests/rollback backend/tests/reversion
	$(PYTHON) -m pytest backend/tests/ai
	$(MAKE) phase47-acceptance
	git diff --check

nosqlbench-smoke:
	docker compose --profile bench run --rm nosqlbench-smoke

safetybench:
	$(PYTHON) -m pytest backend/tests/safetybench

phase43-acceptance:
	$(PYTHON) -m pytest backend/tests/ablations

phase44-acceptance:
	$(PYTHON) -m pytest backend/tests/api
	$(PYTHON) scripts/generate_openapi_types.py --check

phase45-acceptance:
	docker run --rm --platform linux/amd64 -v "$(CURDIR)/frontend:/app" -w /app node:22.14.0-alpine npm test

phase46-acceptance:
	$(PYTHON) -m pytest backend/tests/ai

phase47-acceptance:
	$(PYTHON) scripts/check_database_portability.py
	$(PYTHON) -m pytest backend/tests/portability

phase48-acceptance:
	$(PYTHON) -m pytest backend/tests/security

phase49-acceptance:
	$(PYTHON) -m pytest backend/tests/recovery

phase50-acceptance:
	$(PYTHON) -m pytest backend/tests/resources

phase51-acceptance:
	$(PYTHON) scripts/collect_hardware_manifest.py
	$(PYTHON) -m pytest backend/tests/benchmarks/test_hardware.py backend/tests/benchmarks/test_runner.py

phase52-acceptance:
	$(PYTHON) -m pytest backend/tests/exports

demo-reset:
	$(PYTHON) scripts/demo_mode.py reset

demo-start:
	$(PYTHON) scripts/demo_mode.py start

demo-seed:
	$(PYTHON) scripts/demo_mode.py seed

demo-workload:
	$(PYTHON) scripts/demo_mode.py workload

phase53-acceptance:
	$(PYTHON) -m pytest backend/tests/demo

phase54-acceptance:
	$(PYTHON) -m pytest backend/tests/autonomy backend/tests/production

phase55-acceptance:
	$(PYTHON) -m pytest backend/tests/reversion
