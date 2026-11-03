# NouriSearch

A multilingual food intelligence platform. It connects foods, ingredients, nutrients, cuisines, allergens, and health considerations in a structured knowledge model, then explains what those relationships mean, with a source for every fact.

NouriSearch is educational. It does not diagnose nutritional deficiencies or give medical advice.

The design and milestones are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run it

You need Docker with Compose.

```bash
docker compose up -d --build --wait
curl http://localhost:8000/health/ready
```

| Service | Address |
| --- | --- |
| API | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| PostgreSQL | `localhost:5433` |

## Develop the backend

You need Python 3.13 or newer, and the database from Docker for integration tests.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate           # Linux and macOS: source .venv/bin/activate
pip install -c requirements.lock -e ".[dev]"

ruff check . && ruff format --check .
mypy
pytest                           # all tests, needs the database
pytest -m "not integration"      # tests that need no database
```

Integration tests create and drop their own database, `nourisearch_test`. They never touch the development database.

`requirements.lock` is generated on Linux, because that is where the app is deployed. On other systems, pip uses it as a set of version constraints and skips packages that do not apply.

## Troubleshooting

**`CERTIFICATE_VERIFY_FAILED` during a Docker build.** Security software that inspects HTTPS traffic, such as antivirus web shields, presents a certificate that containers do not trust. Follow the steps in [docker-compose.override.example.yml](docker-compose.override.example.yml). Do not disable certificate verification.
