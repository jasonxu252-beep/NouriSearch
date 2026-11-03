"""Reads foods for search and the detail page."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import TextClause, select, text
from sqlalchemy.orm import Session

from app.db.models import FoodPortion, Nutrient, NutrientReferenceValue
from app.domain.enums import (
    GENERAL_LABEL_POPULATION,
    FoodKind,
    FoodTypeFilter,
    ProcessingLevel,
    ReferenceKind,
    SearchMatch,
)

# Strongest match first. The position in this tuple is the tier the query below computes.
_MATCH_TIERS = (
    SearchMatch.EXACT,
    SearchMatch.PREFIX,
    SearchMatch.WORD_PREFIX,
    SearchMatch.ALL_WORDS,
    SearchMatch.SIMILAR,
)

_MAX_QUERY_WORDS = 12

# Word order is not required, since USDA writes "Soup, chicken noodle" for "chicken soup". The
# trigram operator catches misspellings. Hard filters run after matching, so a filter can only ever
# remove results. Each word gets its own LIKE, because an array comparison cannot use the index.
_SEARCH_TEMPLATE = """
    WITH matches AS (
        SELECT a.food_id,
               MIN(CASE
                   WHEN a.normalized_name = :query THEN 0
                   WHEN a.normalized_name LIKE :prefix THEN 1
                   WHEN a.normalized_name LIKE :word_prefix THEN 2
                   WHEN {all_words} THEN 3
                   ELSE 4
               END) AS tier,
               MAX(word_similarity(:query, a.normalized_name)) AS similarity
        FROM food_alias a
        WHERE ({all_words}) OR :query <% a.normalized_name
        GROUP BY a.food_id
    )
    SELECT f.id, f.slug, f.canonical_name, f.kind, g.key, f.processing_level, s.key, m.tier
    FROM matches m
    JOIN food f ON f.id = m.food_id
    JOIN source s ON s.id = f.source_id
    LEFT JOIN food_group g ON g.id = f.food_group_id
    LEFT JOIN food_group parent ON parent.id = g.parent_id
    WHERE f.is_discoverable
      AND (
          :food_type = 'all'
          OR (:food_type = 'whole_foods'
              AND f.processing_level IN ('whole', 'minimally_processed'))
          OR (:food_type IN ('fruits', 'vegetables', 'grains') AND g.key = :food_type)
          OR (:food_type = 'proteins' AND 'proteins' IN (g.key, parent.key))
          OR (:food_type = 'dishes' AND f.kind = 'prepared_dish')
          OR (:food_type = 'ingredients' AND EXISTS (
              SELECT 1 FROM recipe_component rc WHERE rc.component_food_id = f.id
          ))
      )
    ORDER BY m.tier, m.similarity DESC, length(f.canonical_name), s.priority, f.canonical_name, f.id
    LIMIT :limit OFFSET :offset
"""

_FOOD_SQL = text(
    """
    SELECT f.id, f.slug, f.canonical_name, f.description, f.kind, g.key, g.name,
           f.processing_level, f.is_discoverable, f.source_id, f.classification_source_id
    FROM food f
    LEFT JOIN food_group g ON g.id = f.food_group_id
    WHERE f.id = :food_id
    """
)

_SOURCES_SQL = text(
    """
    SELECT id, key, publisher, title, url, version, license
    FROM source
    WHERE id = ANY(CAST(:ids AS integer[]))
    ORDER BY priority, id
    """
)


@dataclass(frozen=True, slots=True)
class FoodHit:
    id: int
    slug: str
    name: str
    kind: FoodKind
    food_group: str | None
    processing_level: ProcessingLevel
    source_key: str
    match: SearchMatch


@dataclass(frozen=True, slots=True)
class FoodRecord:
    id: int
    slug: str
    name: str
    description: str | None
    kind: FoodKind
    food_group_key: str | None
    food_group_name: str | None
    processing_level: ProcessingLevel
    is_discoverable: bool
    source_id: int
    classification_source_id: int | None


@dataclass(frozen=True, slots=True)
class PortionRecord:
    description: str
    gram_weight: float
    is_household_measure: bool


@dataclass(frozen=True, slots=True)
class NutrientRecord:
    id: int
    key: str
    name: str
    unit: str
    daily_value: float | None
    daily_value_source_id: int | None


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: int
    key: str
    publisher: str
    title: str
    url: str | None
    version: str | None
    license: str | None


@lru_cache(maxsize=_MAX_QUERY_WORDS)
def _search_sql(word_count: int) -> TextClause:
    """The statement varies only with the number of words. Their values stay bound parameters."""
    words = " AND ".join(f"a.normalized_name LIKE :word_{i}" for i in range(word_count))
    return text(_SEARCH_TEMPLATE.format(all_words=words))


def search_food_aliases(
    session: Session,
    query: str,
    food_type: FoodTypeFilter,
    limit: int,
    offset: int,
) -> list[FoodHit]:
    """Expects a normalized query. Normalizing removes punctuation, so no LIKE wildcards remain."""
    words = query.split()[:_MAX_QUERY_WORDS]
    rows = session.execute(
        _search_sql(len(words)),
        {
            **{f"word_{i}": f"%{word}%" for i, word in enumerate(words)},
            "query": query,
            "prefix": f"{query}%",
            "word_prefix": f"% {query}%",
            "food_type": food_type.value,
            "limit": limit,
            "offset": offset,
        },
    )
    return [
        FoodHit(
            id=row[0],
            slug=row[1],
            name=row[2],
            kind=FoodKind(row[3]),
            food_group=row[4],
            processing_level=ProcessingLevel(row[5]),
            source_key=row[6],
            match=_MATCH_TIERS[row[7]],
        )
        for row in rows
    ]


def load_food(session: Session, food_id: int) -> FoodRecord | None:
    row = session.execute(_FOOD_SQL, {"food_id": food_id}).first()
    if row is None:
        return None
    return FoodRecord(
        id=row[0],
        slug=row[1],
        name=row[2],
        description=row[3],
        kind=FoodKind(row[4]),
        food_group_key=row[5],
        food_group_name=row[6],
        processing_level=ProcessingLevel(row[7]),
        is_discoverable=row[8],
        source_id=row[9],
        classification_source_id=row[10],
    )


def load_portions(session: Session, food_id: int) -> list[PortionRecord]:
    rows = session.execute(
        select(FoodPortion.description, FoodPortion.gram_weight, FoodPortion.is_household_measure)
        .where(FoodPortion.food_id == food_id)
        .order_by(FoodPortion.position, FoodPortion.id)
    )
    return [PortionRecord(row[0], float(row[1]), row[2]) for row in rows]


def load_nutrient_catalog(session: Session) -> list[NutrientRecord]:
    """Every nutrient the product tracks, so a food's missing values can be shown as unknown.

    Total sugars gets no Daily Value here because the FDA does not set one. Only added sugars does.
    """
    rows = session.execute(
        select(
            Nutrient.id,
            Nutrient.key,
            Nutrient.name,
            Nutrient.unit,
            NutrientReferenceValue.amount,
            NutrientReferenceValue.source_id,
        )
        .outerjoin(
            NutrientReferenceValue,
            (NutrientReferenceValue.nutrient_id == Nutrient.id)
            & (NutrientReferenceValue.kind == ReferenceKind.DV)
            & (NutrientReferenceValue.population == GENERAL_LABEL_POPULATION),
        )
        .order_by(Nutrient.display_order)
    )
    return [
        NutrientRecord(
            id=row[0],
            key=row[1],
            name=row[2],
            unit=row[3],
            daily_value=float(row[4]) if row[4] is not None else None,
            daily_value_source_id=row[5],
        )
        for row in rows
    ]


def load_sources(session: Session, source_ids: Sequence[int]) -> list[SourceRecord]:
    rows = session.execute(_SOURCES_SQL, {"ids": list(source_ids)})
    return [SourceRecord(*row) for row in rows]
