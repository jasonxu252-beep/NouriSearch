"""Reads what ranking a swap needs: options, roles, sensory data, allergens, and diet facts."""

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.allergens import merge_findings
from app.domain.enums import AllergenRelation, SensoryKind, Verification

# A swap limited to a cuisine applies only to dishes of that cuisine.
_OPTIONS_SQL = text(
    """
    SELECT o.id, o.culinary_fit, o.notes, o.verification, o.source_id, r.key, sc.to_food_id,
           sc.ratio_by_weight, f.canonical_name
    FROM substitution_option o
    JOIN substitution_component sc ON sc.option_id = o.id
    JOIN food f ON f.id = sc.to_food_id
    LEFT JOIN ingredient_role r ON r.id = o.role_id
    WHERE o.from_food_id = :from_food_id
      AND (o.cuisine_id IS NULL OR o.cuisine_id IN (
            SELECT fc.cuisine_id FROM food_cuisine fc WHERE fc.food_id = :dish_id))
    ORDER BY o.id, f.id
    """
)

_ROLE_SQL = text(
    """
    SELECT r.key, g.key, fr.source_id
    FROM food_role fr
    JOIN ingredient_role r ON r.id = fr.role_id
    JOIN food f ON f.id = fr.food_id
    LEFT JOIN food_group g ON g.id = f.food_group_id
    WHERE fr.food_id = :food_id
    ORDER BY fr.source_id
    LIMIT 1
    """
)

# USDA's "as ingredient" records sit in a catch-all group, which says nothing about what they are.
_SAME_ROLE_SQL = text(
    """
    SELECT f.id, f.canonical_name, fr.source_id
    FROM food_role fr
    JOIN ingredient_role r ON r.id = fr.role_id
    JOIN food f ON f.id = fr.food_id
    LEFT JOIN food_group g ON g.id = f.food_group_id
    WHERE r.key = :role AND fr.is_offered AND f.id <> :food_id
      AND (CAST(:food_group AS text) IS NULL OR :food_group = 'other' OR g.key = :food_group)
    ORDER BY f.id
    """
)

_ALLERGENS_SQL = text(
    """
    SELECT fa.food_id, a.key, fa.relation, fa.verification
    FROM food_allergen fa
    JOIN allergen a ON a.id = fa.allergen_id
    WHERE fa.food_id = ANY(:food_ids) AND fa.relation <> 'free_of'
    """
)

_ALLERGEN_NAMES_SQL = text("SELECT key, name FROM allergen ORDER BY id")

_SENSORY_SQL = text(
    """
    SELECT fs.food_id, sa.kind, sa.key, fs.intensity
    FROM food_sensory fs
    JOIN sensory_attribute sa ON sa.id = fs.attribute_id
    WHERE fs.food_id = ANY(:food_ids)
    """
)

_CLASSIFICATIONS_SQL = text(
    """
    SELECT food_id, classification
    FROM food_classification
    WHERE food_id = ANY(:food_ids) AND classification = ANY(:kinds)
    """
)


@dataclass(frozen=True, slots=True)
class OptionTarget:
    food_id: int
    name: str
    ratio: float


@dataclass(frozen=True, slots=True)
class CuratedOption:
    id: int
    culinary_fit: int | None
    notes: str | None
    verification: Verification
    source_id: int
    required_role: str | None
    targets: tuple[OptionTarget, ...]


@dataclass(frozen=True, slots=True)
class FoodRoleRecord:
    role: str
    food_group: str | None
    source_id: int


@dataclass(frozen=True, slots=True)
class OfferedFood:
    id: int
    name: str
    source_id: int


@dataclass(frozen=True, slots=True)
class AllergenFinding:
    relation: AllergenRelation
    # How the strongest claim is known, so a hand assessment is not reported as a guess.
    verification: Verification


@dataclass(frozen=True, slots=True)
class SensoryProfile:
    flavor: Mapping[str, float]
    texture: Mapping[str, float]


def load_options(session: Session, from_food_id: int, dish_id: int) -> list[CuratedOption]:
    grouped: dict[int, list[tuple[object, ...]]] = defaultdict(list)
    rows = session.execute(_OPTIONS_SQL, {"from_food_id": from_food_id, "dish_id": dish_id})
    for row in rows:
        grouped[row[0]].append(tuple(row))
    return [
        CuratedOption(
            id=option_id,
            culinary_fit=_int_or_none(items[0][1]),
            notes=items[0][2] if isinstance(items[0][2], str) else None,
            verification=Verification(str(items[0][3])),
            source_id=int(str(items[0][4])),
            required_role=items[0][5] if isinstance(items[0][5], str) else None,
            targets=tuple(
                OptionTarget(int(str(item[6])), str(item[8]), float(str(item[7]))) for item in items
            ),
        )
        for option_id, items in grouped.items()
    ]


def _int_or_none(value: object) -> int | None:
    return int(str(value)) if value is not None else None


def load_food_role(session: Session, food_id: int) -> FoodRoleRecord | None:
    row = session.execute(_ROLE_SQL, {"food_id": food_id}).first()
    return FoodRoleRecord(row[0], row[1], row[2]) if row else None


def load_same_role_foods(session: Session, role: FoodRoleRecord, food_id: int) -> list[OfferedFood]:
    rows = session.execute(
        _SAME_ROLE_SQL, {"role": role.role, "food_id": food_id, "food_group": role.food_group}
    )
    return [OfferedFood(row[0], row[1], row[2]) for row in rows]


def load_allergen_findings(
    session: Session, food_ids: Collection[int]
) -> dict[int, dict[str, AllergenFinding]]:
    """One finding per food and allergen, merged across sources. "Contains" outranks the rest."""
    ids = list(food_ids)
    if not ids:
        return {}
    relations: dict[int, dict[str, list[tuple[AllergenRelation, Verification]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for food_id, key, relation, verification in session.execute(_ALLERGENS_SQL, {"food_ids": ids}):
        relations[food_id][key].append((AllergenRelation(relation), Verification(verification)))

    findings: dict[int, dict[str, AllergenFinding]] = {}
    for food_id, by_allergen in relations.items():
        findings[food_id] = {}
        for key, claims in by_allergen.items():
            merged = merge_findings({key: relation} for relation, _ in claims)[key]
            supporting = [verification for relation, verification in claims if relation is merged]
            findings[food_id][key] = AllergenFinding(
                merged,
                # A hand assessment outranks a rule reading a name.
                Verification.TYPICAL if Verification.TYPICAL in supporting else supporting[0],
            )
    return findings


def load_allergen_names(session: Session) -> dict[str, str]:
    return {row[0]: row[1] for row in session.execute(_ALLERGEN_NAMES_SQL)}


def load_sensory_profiles(session: Session, food_ids: Collection[int]) -> dict[int, SensoryProfile]:
    flavor: dict[int, dict[str, float]] = defaultdict(dict)
    texture: dict[int, dict[str, float]] = defaultdict(dict)
    ids = list(food_ids)
    if ids:
        for food_id, kind, key, intensity in session.execute(_SENSORY_SQL, {"food_ids": ids}):
            target = flavor if SensoryKind(kind) is SensoryKind.FLAVOR else texture
            target[food_id][key] = float(intensity)
    return {
        food_id: SensoryProfile(flavor.get(food_id, {}), texture.get(food_id, {}))
        for food_id in ids
    }


def load_diet_classifications(
    session: Session, food_ids: Collection[int], kinds: Collection[str]
) -> dict[int, set[str]]:
    found: dict[int, set[str]] = defaultdict(set)
    ids = list(food_ids)
    if ids:
        rows = session.execute(_CLASSIFICATIONS_SQL, {"food_ids": ids, "kinds": list(kinds)})
        for food_id, classification in rows:
            found[food_id].add(classification)
    return found
