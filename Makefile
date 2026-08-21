PYTHON := ./nosql/bin/python
PIP := ./nosql/bin/python -m pip

.PHONY: preflight wheel-test phase0-acceptance phase15-acceptance pip-check test dev replica-test-env paper-env acceptance nosqlbench-smoke safetybench phase43-acceptance phase44-acceptance phase45-acceptance phase46-acceptance phase47-acceptance phase48-acceptance phase49-acceptance phase50-acceptance phase51-acceptance

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
	$(PYTHON) -c 'import sys; assert sys.version_info[:2] == (3, 10)'
	$(PYTHON) -c 'import platform; assert platform.machine() == "x86_64"'

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
	$(PIP) check
	$(MAKE) phase0-acceptance

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
