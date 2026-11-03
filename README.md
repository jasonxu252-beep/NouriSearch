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

## Load the food data

The database starts empty. This loads the curated reference data and three USDA FoodData Central datasets, about 13,600 foods, in under a minute. It downloads about 18 MB the first time, into `data/raw/`, and refuses any file that does not match the hash pinned in `backend/data/curated/fdc_mappings.yaml`. Running it again changes nothing.

Run it from the backend environment described below, not from a container, with the database from Docker running:

```bash
cd backend
python -m app.ingest all --data-dir ../data/raw
python -m app.ingest benchmark    # compares rebuilt dishes with USDA's published values
```

Then try the API:

```bash
curl "http://localhost:8000/v1/foods/search?q=broccoli&type=whole_foods"
curl "http://localhost:8000/v1/foods/1"
```

A food lists every tracked nutrient. A value nobody knows is `null` with the status `unknown`, never zero.

## Develop the backend

You need Python 3.13 or newer, and the database from Docker for integration tests.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate           # Linux and macOS: source .venv/bin/activate
pip install -c requirements.lock -e ".[dev]"

ruff check . && ruff format --check .
mypy
pytest                           # all tests, needs the database and the USDA files
pytest -m "not usda"             # skips the full USDA load, which takes about 2 minutes
pytest -m "not integration"      # tests that need no database
```

Integration tests create and drop their own databases, named `nourisearch_test` and variations on it. They never touch the development database. The USDA tests download the datasets on their first run.

`requirements.lock` is generated on Linux, because that is where the app is deployed. On other systems, pip uses it as a set of version constraints and skips packages that do not apply.

## Troubleshooting

**`CERTIFICATE_VERIFY_FAILED` during a Docker build.** Security software that inspects HTTPS traffic, such as antivirus web shields, presents a certificate that containers do not trust. Follow the steps in [docker-compose.override.example.yml](docker-compose.override.example.yml). Do not disable certificate verification.

**`DatasetIntegrityError` during an ingest.** A USDA file does not match its pinned hash. USDA may have republished it. Delete the file from `data/raw/`, review the new data, and update the pin in `backend/data/curated/fdc_mappings.yaml`. The regression tests will show whether the figures moved.
