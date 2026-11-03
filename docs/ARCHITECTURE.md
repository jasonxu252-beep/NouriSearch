# NouriSearch: Architecture and Implementation Plan

**Status:** Approved by the owner on 2026-11-02. Implementation is in progress. The owner accepted the sketch changes in section 6 on 2026-11-02 and will review them in the built interface.
**Date:** 2026-11-02

NouriSearch is a multilingual food intelligence platform. Its core asset is a structured knowledge model that connects foods, ingredients, nutrients, cuisines, allergens, and health considerations, with a source attached to every fact. It is not a calorie tracker.

## 1. Starting point

The project started from an empty repository, so there was nothing to preserve. It lives at `C:\dev\NouriSearch`, outside OneDrive, because file syncing tends to conflict with dependency folders and database files. The owner's sketches are in `docs/design/`.

| Tool | State on the development machine |
| --- | --- |
| Python | 3.14.7 |
| Node and npm | 26.13.0 and 11.20.0 |
| Docker | Engine 29.9.2 with Compose 5.6.1 |
| WSL2 Ubuntu 26.04 | Present but not needed, since Docker hosts the database. |
| API keys | None set. Translation and vision need keys in milestones 7 and 9. |

## 2. What the data supports

These numbers were measured from USDA FoodData Central (FDC) bulk files. Reproduce them with the scripts in `scripts/feasibility/`. The files used were FNDDS (the survey food database) 2024-10-31, SR Legacy 2018-04, and Foundation Foods 2026-10-29, all from <https://fdc.nal.usda.gov/download-datasets>.

### Dish structure exists, but only for about half of FNDDS

| Measure | Result |
| --- | --- |
| FNDDS foods | 5,432 |
| Foods with at least 3 ingredient rows | 2,790 |
| Ingredient rows with a positive weight | 18,584 of 18,584 |
| Ingredient rows resolving to SR Legacy | 68.4% |
| Ingredient rows resolving to another FNDDS food | 22.7% |
| Ingredient rows resolving to Foundation Foods | 7.7% |
| Ingredient rows that do not resolve | 217 (1.2%) |
| Foods whose ingredient is a restaurant record | 149 |

Foundation Foods and SR Legacy share 212 NDB numbers, and each pair describes the same food, with water never more than 5.6 g per 100 g apart. USDA's ingredient name shows which record a recipe used, so the loader follows the name. An earlier measurement ignored Foundation and reported 75.8% for SR Legacy and 291 unresolved rows. The rows that still do not resolve are mostly fortificants such as "Iron as ingredient".

Three consequences follow:

- Composition must be recursive, because many ingredients are themselves FNDDS recipes.
- Some dishes are opaque. "Kung pao chicken" has one ingredient, the restaurant record for the same dish. It has real nutrient values but no breakdown.
- A USDA recipe is a survey composite, not an authentic recipe. "Bibimbap, Korean" lists 11 weighted ingredients but no gochujang or egg. The product must label this as a "USDA survey recipe" and must not imply authenticity.

### Dish nutrients can be rebuilt from ingredients

The benchmark rebuilds each dish from its ingredients and compares the result with the published FNDDS value. It covers foods with at least 3 ingredients where every ingredient has a quantity and a value. Nested FNDDS ingredients use their published values. `python -m app.ingest benchmark` reproduces it from a loaded database, and `backend/tests/test_usda_ingest.py` runs it as a regression test.

| Nutrient | Dishes | Within 10%, raw weight | Within 10%, cooked weight | Within 25%, cooked weight | Median error, cooked weight |
| --- | --- | --- | --- | --- | --- |
| Sodium | 2,732 | 83.2% | 94.7% | 96.8% | 0.21% |
| Protein | 2,728 | 85.0% | 99.7% | 99.9% | 0.12% |
| Total fat | 2,728 | 83.5% | 98.3% | 99.0% | 0.12% |
| Saturated fat | 2,696 | 84.8% | 98.3% | 99.9% | 0.13% |
| Vitamin C | 1,946 | 75.0% | 70.7% | 90.1% | 2.26% |
| Fiber | 2,356 | 77.0% | 90.5% | 98.9% | 1.92% |
| Energy | 2,734 | 85.3% | 99.7% | 100% | 0.22% |
| Water | 2,733 | 90.7% | 100% | 100% | 0.04% |

This result validates the data joins and the arithmetic. It does not validate real-world accuracy, because USDA derived these values from the same recipes.

- **Moisture explains most of the tail.** FNDDS states a moisture change for each recipe, and 976 of 5,431 are not zero. A recipe that loses water concentrates what remains, so a value per 100 g must divide by the cooked weight. Water itself is the sharpest check, and it rebuilds to 100%.
- **Retention explains the vitamins.** Dividing by cooked weight does not help vitamin C. Its median ratio of published to rebuilt value is 0.90 where USDA applied a retention factor and 1.00 where it did not, while protein and sodium stay near 1.00 either way. The factors are in a separate USDA table that is not loaded yet, so each recipe ingredient keeps its retention code for later.
- **Choosing the right record matters.** Following USDA's ingredient name instead of always preferring SR Legacy moved protein from 97.7% to 99.7% within 10%, and saturated fat from 95.9% to 98.3%.
- **The recursion holds up.** With published values removed from nested ingredients, leaf ingredients alone bring protein to 99.6% within 10% and sodium to 93.6%. This covers fewer dishes, 1,428 and 1,432, because some leaves have no value for that nutrient, mainly Foundation oils.
- **The rest is unexplained.** About 5% of dishes are still more than 10% away on sodium, and the cause has not been investigated.

Worked example, using USDA values only: salt supplies about 91% of bibimbap's calculated sodium. Halving the salt moves the dish from 435 mg to about 238 mg of sodium per 100 g.

### Missing data is common and zeros are ambiguous

Share of foods with a value, by primary FDC nutrient number:

| Nutrient | FNDDS | SR Legacy | Foundation |
| --- | --- | --- | --- |
| Sodium | 100% | 99% | 89% |
| Vitamin C | 100% | 94% | 28% |
| Vitamin D | 100% | 67% | 18% |
| Vitamin K | 100% | 65% | 20% |
| Saturated fat | 100% | 96% | 41% |

- **Absence must mean unknown.** Foundation Foods alone would show most vitamins as blank, and USDA publishes nothing at all for "Milk, human" after withdrawing that profile.
- **A shared number can fill gaps honestly.** Where a Foundation record has no value, the same food's SR Legacy value fills in through `nutrient_proxy` and is labeled as an estimate.
- **Negative values mean unknown too.** USDA calculates carbohydrate by difference, which comes out slightly negative for 10 Foundation meats and fish. Those rows are not stored.
- **Zero needs a provenance label.** 55% of FNDDS vitamin D values are zero and FNDDS supplies no derivation label. SR Legacy marks some values as "Assumed zero", and that label must be kept.
- **Nutrient codes need normalizing.** Foundation stores total sugars mostly under a second code, 269.3 at 38% coverage, against 1% under code 269.
- **Added sugars are not a nutrient in these datasets.** Added sugar must be modeled through ingredient classification, not displayed as a number.

### Culturally specific coverage is thin

| Requirement example | What USDA has |
| --- | --- |
| Salted fish | No FNDDS match. SR Legacy has "Fish, mackerel, salted", which is a different product from Chinese-style salted fish. |
| Salted duck egg | Only raw and cooked duck egg. |
| Preserved vegetables | Scattered pickled items. Coverage of Chinese preserved vegetables was not established. |
| Mapo tofu | No match. |
| Reduced-sodium soy sauce | Present, which makes it a good first substitution. |

USDA alone cannot satisfy the "salt plus Chinese cuisine" example. A curated dataset is therefore required, and a nutrient estimate borrowed from a similar food must be labeled as an estimate.

### Other sources

| Source | Finding | Design consequence |
| --- | --- | --- |
| FDC API | Limit of 1,000 requests per hour per IP. Data is CC0. The demo key returned HTTP 429 after about 10 calls. | Bulk ingest. No runtime dependency on the API. |
| Wikidata | Four of five tested dishes resolved, each with labels in 5 or 6 of the tested languages and an image. Ingredient claims number 1 to 6 per dish, without quantities. "Mole sauce" found no entity under that name. | Use for names, images, and typical-ingredient edges only. |
| Open Food Facts | Product lookup works. The two official documentation pages disagree on read limits, 15 and 100 per minute. Search is limited to 10 per minute. Data is ODbL, with share-alike terms. | Barcode lookup with caching only. Keep the data in separate tables. Never search as the user types. |
| NIH ODS | The fact sheet API returned XML in one test. Other automated requests were blocked. Reuse terms were not confirmed. | Hand-curate structured rows with citations. No runtime scraping. |
| FDA | 5% Daily Value (DV) or less per serving is low and 20% or more is high. Sodium DV is 2,300 mg. There are nine major allergens. | Basis for warning thresholds and the allergen list. |
| IARC Vol. 56 | Chinese-style salted fish is Group 1, specifically that product. Vol. 100E has not been read yet. | Attach the fact to that food only, and read Vol. 100E before seeding. |

Wikidata's Chinese label for kimchi is 泡菜, which also commonly names other pickled vegetables. This belongs in the search test set.

## 3. Architecture

A modular monolith is the right size. Microservices and a graph database would add operational cost without solving a current problem, since recursive SQL can traverse the relationships.

```text
React + TypeScript (Vite)
        |   typed client generated from OpenAPI
FastAPI routers: validation, rate limits, error mapping
        |
Application services: use cases and transactions
   |                  |                     |
Domain core        Repositories          Integration adapters
(pure Python)      SQLAlchemy 2          FDC, Open Food Facts, Wikidata,
nutrition, rules,  PostgreSQL            translation, vision
substitution,
ranking, insights

Ingestion pipelines run separately:
source file -> adapter -> normalizer -> validation -> upsert with provenance
```

The domain core imports nothing from the database, HTTP, or adapter layers. That lets the rules, ranking, and calculations be tested without any infrastructure. External response shapes stop at the adapters.

```text
backend/app/{api,services,domain,repositories,db,integrations,ingest}
backend/data/curated/      reviewed YAML facts, each with a source
backend/tests/             pytest markers separate tests needing a database or the USDA files
data/raw/                  downloaded USDA files, pinned by hash and not committed
frontend/src/
docs/
scripts/
```

**Deferred until measured:** Redis, because bulk loading removes most external calls and a Postgres table can cache translations at first. Also pgvector, which is adopted only if the search evaluation shows a gain, and learned ranking, which has no training data.

## 4. Knowledge model

**Principles**

1. **Ingredient is a role, not a type.** Salted fish is both a food and an ingredient, so all of them share one `food` table. This avoids duplicating nutrients, allergens, and translations.
2. **Absence means unknown.** `amount` is `NOT NULL` with no default, and a missing row means unknown. The API returns `null` with an `unknown` status.
3. **Every fact has a source.** Knowledge tables have a required `source_id`, so an uncited fact cannot be stored. A processing level is this project's judgment and not USDA's, so it cites the project through `classification_source_id`, and the database rejects one with no citation.
4. **Two separate labels.** `verification` describes how we know a fact: `source_documented`, `typical`, `estimated`, or `user_reported`. `evidence_level` describes the strength of a health claim.
5. **Predictions are not facts.** Image model output and user corrections never write directly to knowledge tables.

| Area | Tables | Relationship expressed |
| --- | --- | --- |
| Catalog | `food`, `food_group`, `food_portion`, `food_image`, `food_external_ref` | Identity, processing level, servings, images, source IDs |
| Language | `food_alias`, `nutrient_translation`, `text_translation` | Names by language, type, and provenance |
| Cuisine | `cuisine` (hierarchical), `food_cuisine` | BELONGS_TO |
| Composition | `recipe`, `recipe_component`, `ingredient_role` | CONTAINS, with optional weight and several recipes per dish |
| Corrections | `ingredient_correction` | User proposals, held for review |
| Nutrition | `nutrient`, `nutrient_source_code`, `food_nutrient`, `nutrient_proxy` | Values per 100 g with value kind, source codes, and labeled borrowed estimates |
| Preparation | `preparation_method`, `recipe_preparation`, `preparation_effect` | MODIFIES |
| References | `nutrient_reference_value` | RDA, AI, UL, CDRR, AMDR, and DV by life stage |
| Education | `health_function`, `nutrient_function`, `health_effect`, `nutrient_health_effect` | HAS_HEALTH_FUNCTION, and effects from inadequacy or excess |
| Safety | `allergen`, `food_allergen`, `health_consideration`, `food_health_consideration`, `food_classification` | CONTAINS, MAY_CONTAIN, FREE_OF, added-sugar source, contextual concerns |
| Substitution | `substitution_option`, `substitution_component`, `sensory_attribute`, `food_sensory` | CAN_SUBSTITUTE_FOR, including one-to-many replacements |
| Provenance | `source` | Publisher, URL, version, retrieval date, license, tier |
| Users | `app_user`, `user_preference`, `user_allergen`, `food_event`, `user_selected_food`, `search_history` | Explored and ate events, chosen foods, profile basis, recent searches |
| Search | `search_document` | Rebuilt read model, not a source of truth |

Tables are created by the milestone that first needs them. `text_translation`, `ingredient_correction`, `search_document`, and the Users tables do not exist yet.

The sodium trace is the model's acceptance test. Given a dish and sodium, one service call must return the contributing ingredients ranked by quantity where known, other dishes sharing those ingredients, substitutions that lower sodium, and the sources for each step.

## 5. Calculations

- **Dish value.** Use the published value when one exists. Otherwise use the recursive recipe sum.
- **Contribution.** An ingredient's contribution is its weight times its value per 100 g. Its share is that amount over the known total.
- **Cooked weight.** A recipe's value per 100 g divides by its cooked weight, which is its raw weight times one plus its moisture change. Water alone also gains or loses the changed amount. A source that states no change is treated as no change.
- **Partial data.** If any ingredient lacks a value, the result is a lower bound, shown as "at least X", and names the ingredients with no data. It is never reported as a plain total. A partial total of zero stays unknown, because "at least 0" would read as a zero.
- **Edited dish.** Apply changes as a delta to the published value, which keeps USDA's cooking adjustments. The published value is per 100 g cooked, so the batch total uses the cooked weight:

  ```text
  adjusted_per_100g = (published_per_100g * C0/100 + sum(edit_deltas)) / C1 * 100
  C0, C1 = cooked recipe weight in grams before and after the edit
  cooked weight = raw weight * (1 + moisture change / 100)
  ```

- **Confidence.** Each recipe's own rebuild error is stored per nutrient, starting with simulations in milestone 5. Above a tested threshold, simulated values display as approximate.
- **No quantities.** Dishes without weights get qualitative comparisons only, and no calculated numbers.

## 6. Interface from the owner's sketches

The sketches set the layout. This table records what is kept and what changes, and why. The owner accepted these changes on 2026-11-02 and will review them in the built interface.

| Sketch element | Decision |
| --- | --- |
| Search and Profile tabs, cuisine selector | Keep. The cuisine selector defaults to "All cuisines" and persists across pages. |
| "Shou Search" title | Becomes NouriSearch, at the owner's direction. |
| Search bar with submit and camera buttons | Keep. Add suggestions and a filter row underneath. |
| Image carousel and description | Keep as the overview column. |
| Similar panel with its Explore tab | Keep. Move it under the description on desktop, so the Ingredients and Nutrients panels get the width they need and sit side by side. Opening a card records an explored event. |
| Ingredient checkboxes | The checkbox includes or excludes the ingredient and recalculates the dish. Clicking the name selects it, which highlights nutrients and opens replacements. |
| Red 40 with a warning icon | Additives are foods of kind `additive`, with sourced, contextual considerations. USDA's generic foods do not list them, so they appear through packaged product ingredient text. |
| "Your nutrient profile" and "Add to profile" | Two clear actions: "I ate this" logs a dated event, and "Add to my foods" adds to the chosen list. |
| Nutrient bars | Bars show percent Daily Value per serving, with a tick at the 20% "high" line. The serving is stated above the panel. |
| Sugar bar | Change. It shows total sugars in grams, with no Daily Value comparison, because the FDA sets none for total sugars. Added sugars compare with the 50 g Daily Value when a label states them, and otherwise show as unknown, because USDA has no added-sugar values. |
| Translate tabs on panels | Keep. A default language also lives in settings. |
| Profile "based on your last 20 searches" | Change. Searching for a food does not mean eating it, so searches only feed Recent Searches. The profile uses foods the user chose or foods marked as eaten. |
| Profile sodium bar labeled "High" | Change. Without portions, the app cannot measure intake, and the requirements forbid implying it. The bar shows the share of the user's foods that are high in sodium. |
| "?" on Vitamin C | Keep as the grey mark for unknown or limited data. |
| Allergens on the profile | Split into allergens the user avoids, set in settings, and allergens found in their foods. |
| Profile filter button | Controls the basis and the period: 7 days, 30 days, or last 20 foods. |

### Additions requested with the sketches

- **Food-type filters.** Search offers All, Whole foods, Fruits, Vegetables, Proteins, Grains, Dishes, and Ingredients. A filter excludes everything else.
- **Whole foods first.** A preference ranks whole foods above dishes in suggestions and results without hiding dishes. It is a ranking feature, separate from the filters.
- **Whole-food classification.** USDA has no "whole food" field, and its fruit category includes juices. Ingest assigns a `processing_level` through a tested, rule-based classifier that records `unknown` when no rule applies. The Whole foods filter includes whole and minimally processed foods, so a plain cooked vegetable counts and a food the rules cannot judge does not.
- **Profile basis setting.** A setting chooses between foods the user selects by hand and foods marked "I ate this". Selecting foods needs no history at all.

## 7. Food detail interaction

One endpoint supplies everything the page needs to respond instantly:

```text
GET  /v1/foods/{id}/composition
     ingredients, nutrients, contribution matrix, conclusions, sources

POST /v1/foods/{id}/simulations
     body: list of edits (replace, scale, remove, add)
     returns the same shape, plus deltas. Writes nothing.
```

**Nutrient marks.** The owner specified two states. This plan adds a third, because a green mark on missing data would falsely reassure, and the requirements say missing values must not be read as zero.

| Mark | Condition | Clicking shows |
| --- | --- | --- |
| Exclamation | A nutrient to limit is at 20% DV or more per serving, or a value is above an established upper limit | Effects of excess, top contributing ingredients, relevant swaps, sources |
| Green | Value is known and no concern rule fired | Benefits and functions, plus a note that this serving was not flagged |
| Grey question mark | Value is unknown, or a lower bound that cannot decide the rule | What is missing and which ingredients lack data |

The exclamation mark can still appear with partial data when the known lower bound alone crosses the threshold.

Nutrients to limit start as sodium, saturated fat, and added sugars, following FDA guidance. Because no added-sugar values exist in these datasets, added sugars will show unknown unless a label value exists, along with any ingredients classified as added-sugar sources.

The serving choice changes the result. FNDDS gives bibimbap 162 g per cup and 121 g for "quantity not specified". The mark uses a named household portion, states it next to the mark, and lets the user switch. If no portion exists, the page labels the value per 100 g.

**Two-way highlighting**

- Clicking a nutrient highlights its contributing ingredients, with strength based on share of the known total.
- Clicking an ingredient highlights the nutrients it contributes to and opens its replacement panel.
- The starting highlight threshold is 5% of the known total, to be tuned during review.
- Ingredients with no quantity use a dashed outline when documented as a source. Ingredients with no data are marked as unknown.
- Selection works from the keyboard, and color is never the only signal.

**Substitution flow**

1. The user clicks an ingredient and picks a goal.
2. The panel lists ranked replacements with reasons and uncertainty.
3. Choosing one calls the simulation endpoint, which updates ingredients, nutrient values, deltas, and marks.
4. The page shows that it is a modified version and offers a reset.

Edits can change more than one ingredient. Some replacements are one-to-many, and sometimes the best change is simply using less, as with the salt in bibimbap.

## 8. Rules engine

Rules are versioned, pure Python functions over a typed set of facts, with no database access. Thresholds carry citations. Every result has this shape:

```text
Conclusion
  code, severity, subject
  message_key      translated template, not generated text
  supporting_facts references to specific rows
  rules_triggered  rule ID and version
  sources
  uncertainty      verification level, inferred or verified
  missing          facts that could not be evaluated
```

Each rule has tests for firing, not firing, and missing data. A rule facing missing data returns "could not evaluate". It never returns "no concern".

## 9. Substitution ranking

1. **Generate candidates.** Curated substitution options first, then same-role foods within the food group.
2. **Filter by hard constraints.** Allergens, diet, and required role. A violating candidate is removed.
3. **Evaluate the dish.** Run each candidate through the simulation and rules, so the score reflects the resulting dish.
4. **Score by goal.** Combine nutrition change, flavor, texture, culinary fit, and user preference, with weights set per goal.
5. **Keep unknowns honest.** Missing sensory data lowers a completeness score and is not treated as 0.

Results expose each score component so the ordering can be explained. Flavor, texture, and role data is not available from USDA and must be curated, so coverage will be limited at first.

## 10. Search and recommendations

```text
query
 -> normalize (Unicode, case, script variants)
 -> understand (nutrient terms, cuisine, "without X", health phrases)
 -> retrieve candidates (full-text, trigram, aliases, ingredients, nutrients)
 -> apply hard filters (excluded allergens, cuisine when required)
 -> rank by weighted, explainable features
 -> return results with reasons
```

- **"Vitamin C"** ranks by value per serving, not by text match.
- **Food-type filters and whole foods first** follow section 6. Suggestions use the same ranking features.
- **"Foods without peanuts"** returns three groups: no peanut in known ingredients, contains peanut (excluded), and incomplete ingredient data. The product never claims a food is peanut-free.
- **Cuisine** is a culinary classification from data and user choice, never tied to a person's ethnicity.
- **CJK text** is not segmented by PostgreSQL's default full-text search, so milestone 7 tests trigram and alias matching on real queries.

**Baseline.** Milestone 3 ships `GET /v1/foods/search`, which matches names by exact, prefix, word prefix, all words in any order, and trigram similarity, and applies the food-type filters. Each result states why it matched. Because each USDA dataset has its own record, 186 names appear more than once, including three entries for "Broccoli, raw". Milestone 7 decides how to merge them, using the evaluation below.

**Evaluation.** A hand-labeled query set, including several languages and the examples in this document, reports nDCG@10, recall@20, and a constraint violation rate that must be zero. Each ranking feature, and pgvector, is kept only if it shows a measured gain.

## 11. History, images, and translation

- **History.** Explore and "I ate this" are separate events, with no grams or calories. Insights use the share of the user's foods that are known sources of a nutrient, over 7 days, 30 days, or the last 20 foods, or over the list of foods they chose. Foods with unknown values are excluded and counted. Wording is tested so that no output asserts intake or deficiency.
- **Images.** A vision adapter returns candidate foods, which the search pipeline matches to catalog entries. The user confirms, and only then is nutrition data fetched from the database. Images are not retained by default. Confidence bands are measured on a labeled photo set, since raw model confidence may not be calibrated.
- **Translation.** Food names come from aliases, interface text from translation files, and conclusions from translated templates. Free text uses machine translation behind an adapter. It is cached, labeled as machine translated, and the original stays available. The provider has not been evaluated and is chosen in milestone 7.
- **Privacy.** Food history can reveal health information, so a delete-my-data endpoint ships with history.

## 12. Milestones

The owner's order is kept. One addition: milestone 4 introduces the rules engine skeleton with one rule, because the nutrient marks need it. Milestone 6 completes the engine.

| # | Milestone | Done when |
| --- | --- | --- |
| 1 | Foundation: repository, Compose, FastAPI, CI | A clean checkout starts Postgres and passes a database health check. CI is green. |
| 2 | Knowledge model: migrations, curated loader, small vertical slice | Constraint tests prove uncited facts and default zeros cannot exist. The sodium trace works on seed data. |
| 3 | Discovery: FDC ingest, recursive calculations, baseline search API | Ingest is idempotent. The rebuild benchmark runs as a regression test. Unknown values stay unknown through the API. |
| 4 | Food detail UI: three panels, marks, two-way highlighting | Component and browser tests pass. Layout is reviewed against the owner's sketches. |
| 5 | Substitution: goals, constraints, ranking, simulation, panel | A swap updates values and ingredients. Hand-computed fixtures match. Excluded allergens never appear. |
| 6 | Rules engine: full rule set and explanations | Every conclusion carries facts, rule version, and sources. Substitutions re-run through the rules. |
| 7 | Search: multilingual, cuisine-aware, whole foods first, evaluated | Metrics are reported per feature. The pgvector decision is made from measurements. |
| 8 | History and insights, including the chosen-foods basis | Period logic and wording tests pass. Data deletion works. |
| 9 | Image recognition | Tests use recorded responses. Accuracy on a labeled set is reported. Predictions cannot reach knowledge tables. |
| 10 | Hardening: rate limits, logging, deployment, documentation | A clean machine reproduces the app from the docs. Published performance numbers are measured. |

Each milestone reports what was implemented, the decisions made, which tests passed and failed, and what still needs manual checking.

## 13. Risks

| Risk | Mitigation |
| --- | --- |
| Curating cultural dishes and sensory data is slow | Start with a small, well-sourced set and show coverage openly. |
| Curated facts could contain errors | Require a citation per fact and validate in CI. The owner reviews health content. |
| Health content could read as medical advice | Fixed templates, educational framing, no diagnosis, and wording tests. |
| Open Food Facts share-alike terms could affect a combined database | Keep that data separated, and review terms before milestone 10. |
| Python 3.14 is recent, and only resolution has been tested | Pin versions, and verify real installs in milestone 1. |
