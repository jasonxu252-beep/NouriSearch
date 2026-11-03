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

## Open the app

You need Node 22 or newer, with the API and its data running as above.

```bash
cd frontend
npm install
npm run dev
```

Then open <http://localhost:5173>. Search for bibimbap, select sodium, and use the wrench beside salt to remove it.

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

## Develop the frontend

The typed API client is generated from the backend. After changing the API, regenerate it:

```bash
cd backend && python -m app.export_openapi ../frontend/openapi.json
cd ../frontend && npm run generate:api
```

```bash
npm run lint && npm run format:check
npm run typecheck
npm test                         # component tests, need nothing running
npx playwright install chromium  # once
npm run test:browser             # browser tests, need the API with its data loaded
```

## Troubleshooting

**`CERTIFICATE_VERIFY_FAILED` during a Docker build.** Security software that inspects HTTPS traffic, such as antivirus web shields, presents a certificate that containers do not trust. Follow the steps in [docker-compose.override.example.yml](docker-compose.override.example.yml). Do not disable certificate verification.

**npm or Playwright reports a certificate error.** The same security software affects Node. Point it at the certificate you exported, and keep verification on: `NODE_EXTRA_CA_CERTS=.local/extra-ca.pem npm install`, using the file's full path.

**Browser tests stall with many workers.** On a machine running security software that inspects traffic, several browsers at once can stall for seconds, even against a plain file server. `frontend/playwright.config.ts` runs one at a time outside CI for this reason.

**`DatasetIntegrityError` during an ingest.** A USDA file does not match its pinned hash. USDA may have republished it. Delete the file from `data/raw/`, review the new data, and update the pin in `backend/data/curated/fdc_mappings.yaml`. The regression tests will show whether the figures moved.
