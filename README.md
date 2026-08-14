# AI-Driven Autonomous NoSQL Query Optimization Framework

This project targets Intel x86_64 macOS using CPython 3.10 and linux/amd64 Docker containers.

## First-time setup

```bash
./scripts/bootstrap.sh
source nosql/bin/activate
```

## Normal development

```bash
make preflight
make dev
```

## Testing

```bash
make test
make acceptance
```

## Docker profiles

```bash
make dev
make replica-test-env
make paper-env
```

Do not install project packages into system Python or use a virtual environment other than `nosql/` for this project.
