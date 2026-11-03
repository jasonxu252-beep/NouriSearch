"""Which of the FDA's nine major allergens a food's name reveals. Pure: no database, no network.

USDA's data lists no allergens, so these rules read names, and the loader follows recipes on top of
them. This can only ever find an allergen. Finding nothing says nothing about a food, so no rule
here or anywhere else concludes that a food is free of one.

A wrong "contains" hides a good swap. A wrong silence could hurt someone. So the rules lean toward
finding too much: when a word often means an allergen is present, it counts as "may contain".

What counts as each allergen follows the FDA's guidance (the `fda-allergen-guidance` source): which
twelve tree nuts it lists, that wheat includes triticale, einkorn, and emmer, that milk and eggs
include other animals', and that mollusks are not crustacean shellfish.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.domain.enums import AllergenRelation

# The FDA's nine, with the keys used in the curated vocabulary.
MILK = "milk"
EGGS = "eggs"
FISH = "fish"
CRUSTACEANS = "crustacean_shellfish"
TREE_NUTS = "tree_nuts"
PEANUTS = "peanuts"
WHEAT = "wheat"
SOYBEANS = "soybeans"
SESAME = "sesame"


def _not_after(*words: str) -> str:
    """The word before must not be one of these. `\\b` keeps "oat" from also catching "goat"."""
    return "".join(rf"(?<!\b{word} )" for word in words)


_NON_DAIRY_MILK = _not_after(
    "coconut", "almond", "soy", "rice", "oat", "cashew", "hemp", "walnut", "hazelnut", "plant",
    "peanut", "non-dairy", "nondairy",
)  # fmt: skip
_NON_DAIRY_BUTTER = _not_after(
    "peanut", "almond", "cashew", "nut", "apple", "cocoa", "sesame", "seed", "sunflower", "shea",
    "soy", "pumpkin", "walnut", "hazelnut", "pecan", "macadamia", "pistachio", "tahini", "mango",
    "pear", "plum", "peach",
)  # fmt: skip
_NON_WHEAT_FLOUR = _not_after(
    "rice", "corn", "potato", "almond", "soy", "oat", "chickpea", "tapioca", "peanut", "coconut",
    "sorghum", "rye", "buckwheat", "cassava", "masa", "carob", "sesame", "sunflower", "barley",
    "lupin", "arrowroot", "peanuts", "brown", "white", "millet", "quinoa", "teff",
    "sorghum,", "amaranth,", "acorn",
)  # fmt: skip
_NON_DAIRY_YOGURT = _not_after("soy", "coconut", "almond", "tofu")

# Baked and battered foods usually hold wheat, and very often eggs and milk too.
_BAKED = (
    r"cakes?|cupcakes?|cookies?|brownies?|pastry|pastries|pies?(?! pumpkin)|muffins?|waffles?|"
    r"pancakes?|doughnuts?|donuts?|croissants?|danish|strudel|turnovers?|sweet rolls?|"
    r"cinnamon rolls?|coffee ?cake|french toast|biscuits?|scones?|dumplings?|crepes?|batter|"
    r"breading|breaded|stuffing|cream puffs?|eclairs?|pop-?tarts?|pan dulce|empanadas?|phyllo|"
    r"doughs?|focaccia|frybread|fry bread|hush puppies|wafers?|pita|melba toast|toast|"
    r"egg rolls?|fruit tarts?"
)
_RESTAURANTS = (
    r"fast foods?|restaurant|applebee'?s|burger king|carrabba'?s|chick-fil-a|cracker barrel|"
    r"denny'?s|domino'?s|kfc|little caesars|mcdonald'?s|olive garden|on the border|papa john'?s|"
    r"pizza hut|popeyes|subway|t\.g\.i\.|taco bell|wendy'?s"
)
_SHAKES_AND_BARS = (
    r"\b(?:protein|meal replacement) (?:powders?|bars?|shakes?|drinks?)\b|\bmeal replacement\b|"
    r"\bnutritional supplement\b|\bnutrition bars?\b|\bensure\b|\bglucerna\b|\bslim[- ]?fast\b|"
    r"\bpediasure\b|\bformulas?\b|\bbars?\b"
)
_CANDY = r"\bchocolates?\b|\bcandy\b|\bcandies\b|\bfudge\b|\bfrozen novelties\b|\bfrozen dessert\b"
_PROCESSED_MEAT = r"\bsausages?\b|\bbologna\b|\bfrankfurters?\b|\bhot dogs?\b|\bluncheon\b"

_CONTAINS: Mapping[str, str] = {
    MILK: (
        rf"{_NON_DAIRY_MILK}\bmilk\b|buttermilk|\bmilk ?shakes?\b|"
        rf"{_NON_DAIRY_BUTTER}\bbutter\b(?! beans?| lettuce| crackers?)|\bghee\b|cheese|\bqueso\b|"
        r"\bparmesan\b|\bpaneer\b|\bricotta\b|\bmozzarella\b|\bcheddar\b|"
        r"\bcreams?\b(?! of tartar| of rice| soda| substitute| sherry| crackers?| style)|"
        rf"\bcreamsicle\b|{_NON_DAIRY_YOGURT}\byogh?urts?\b|\bkefir\b|\bwhey\b|\bcasein|"
        r"\blactose\b|\bcustards?\b|"
        r"\bgelato\b|\blatte\b|\bcappuccino\b|half and half|\bnougat\b|\balfredo\b|\bbechamel\b|"
        r"\beggnog\b|\bdairy\b|\bsherbet\b|\bpuddings?\b|\bwhite sauce\b|"
        r"\bsauce, homemade, white\b|"
        r"\bflan\b|\bleche\b|\bwhipped cream\b"
    ),
    EGGS: (
        r"\beggs?\b(?! substitute)|\beggnog\b|\bomelets?\b|\bomelettes?\b|\bmayonnaise\b|\bmayo\b|"
        r"\bmeringues?\b|\bquiche\b|\bcustards?\b|\bfrench toast\b|\bfrittata\b|\bhollandaise\b|"
        r"\baioli\b|\bsouffle\b|\bflan\b|\bcream puffs?\b|\beclairs?\b|\btartar sauce\b|"
        r"\bsauce, tartar\b"
    ),
    FISH: (
        r"\bfish\b|\bfishes\b|\banchov(?:y|ies)\b|\bbass\b|\bbluefish\b|\bburbot\b|\bbutterfish\b|"
        r"\bcarp\b|\bcatfish\b|\bcaviar\b|\bcisco\b|\bcod\b|\bcroaker\b|\bcusk\b|\bdolphinfish\b|"
        r"\beel\b|\bflatfish\b|\bflounder\b|\bgefilte\b|\bgrouper\b|\bhaddock\b|\bhake\b|"
        r"\bhalibut\b|\bherring\b|\bkipper(?:ed)?\b|\blingcod\b|\blox\b|\bmackerel\b|\bmahi\b|"
        r"\bmilkfish\b|\bmonkfish\b|\bmullet\b|\bperch\b|\bpike\b|\bpollock\b|\bpompano\b|"
        r"\bporgy\b|\brockfish\b|\broe\b|\bsablefish\b|\bsalmon\b|\bsardines?\b|\bscup\b|\bshad\b|"
        r"\bshark\b|\bsheepshead\b|\bsmelt\b|\bsnapper\b|\bsole\b|\bsturgeon\b|\bsurimi\b|"
        r"\bswordfish\b|\btilapia\b|\btilefish\b|\btrout\b|\btuna\b|\bturbot\b|\bwhitefish\b|"
        r"\bwhiting\b|\bwolffish\b|\byellowtail\b|\bworcestershire\b"
    ),
    CRUSTACEANS: (
        r"\bcrabs?\b(?! apples?)|\blobsters?\b|\bshrimps?\b|\bprawns?\b|\bcrayfish\b|\bcrawfish\b|"
        r"\blangoustines?\b|\bkrill\b|\bscampi\b|\bcrustaceans?\b"
    ),
    # Table 1 of the FDA's food allergen guidance, edition 5, January 2025.
    TREE_NUTS: (
        r"\balmonds?\b|\bbrazil ?nuts?\b|\bcashews?\b|\bfilberts?\b|\bhazelnuts?\b|\bheartnuts?\b|"
        r"\bmacadamias?\b|\bbush nuts?\b|\bpecans?\b|\bpine ?nuts?\b|\bpinyon\b|\bpinon\b|"
        r"\bpignolias?\b|\bpistachios?\b|\bwalnuts?\b|\bnutella\b|\bmarzipan\b|\bfrangipane\b|"
        r"\bpralines?\b|\bbaklava\b|\bmixed nuts\b|\bgianduja\b"
    ),
    PEANUTS: (
        r"\bpeanuts?\b|\bgroundnuts?\b|\bgoobers?\b|\breese'?s\b|\bsnickers\b|\bbutterfinger\b|"
        r"\bbaby ruth\b|\bpayday\b|\bplanters\b|\bmr\.? goodbar\b"
    ),
    WHEAT: (
        rf"\bwheat\b|{_NON_WHEAT_FLOUR}\bflour\b|(?<!\brice )\bbreads?\b|\bbreadsticks?\b|"
        r"\bcornbread\b|\bcroutons?\b|\bbuns?\b|\bbagels?\b|\bcrackers?\b|\bpretzels?\b|"
        r"(?<!\brice )\bpasta\b|(?<!\brice )(?<!\bcellophane )\bnoodles?\b|"
        r"\bspaghetti\b(?! squash)|\bmacaroni\b|\blasagna\b|\bravioli\b|\btortellini\b|\bgnocchi\b|"
        r"\bcouscous\b|\bbulgur\b|\bfarina\b|\bsemolina\b|\bdurum\b|\bspelt\b|\bkamut\b|\bseitan\b|"
        r"\btriticale\b|\beinkorn\b|\bemmer\b|"
        r"\bgluten\b|\borzo\b|\budon\b|\bramen\b|\blo mein\b|\bchow mein\b|\bwontons?\b|"
        r"\bpot ?stickers?\b|\bpizzas?\b|\bcalzones?\b|\bsandwich(?:es)?\b|\bcorn dogs?\b|"
        r"\bteriyaki\b|\bsoy sauce\b(?! made from (?:soy \(tamari\)|hydrolyzed))|\bshoyu\b|"
        r"\brolls?, (?:dinner|hamburger|hard|hot ?dog|pumpernickel|french)\b|"
        rf"(?<!\brice )\b(?:{_BAKED})\b"
    ),
    SOYBEANS: (
        r"\bsoy\b|\bsoya\b|\bsoybeans?\b|\bsoymilk\b|\bshoyu\b|\btamari\b|\btofu\b|\btempeh\b|"
        r"\bmiso\b|\bnatto\b|\bedamame\b|\bokara\b|\bteriyaki\b|\btextured vegetable protein\b|"
        r"\btvp\b"
    ),
    SESAME: r"\bsesame\b|\btahini\b|\btahina\b|\bhummus\b|\bhalvah?\b|\bbenne\b|\bgomasio\b",
}

_MAY_CONTAIN: Mapping[str, str] = {
    MILK: (
        rf"\b(?:{_BAKED})\b|{_CANDY}|\bcocoa\b(?! butter)|\bcaramels?\b|\bmargarine\b|"
        r"\bcreamers?\b|\bcream substitute\b|\bbutterscotch\b|\bmocha\b|\bgranola\b|\bcaesar\b|"
        r"\bpesto\b|"
        r"\bdressing\b|\bgravy\b|\bnon-?dairy\b|\bdairy-free\b|\btoffee\b|\bwhipped topping\b|"
        r"\bchowder\b|\bveggie\b|"
        r"\bdessert topping\b|\btoppings?, |\bfrostings?\b|\bcreamed\b|\bdips?\b|\bpuffs?\b|"
        r"\bbuffalo sauce\b|\b(?:chips?|popcorn|crisps?|sticks?)\b.*\bflavored\b|"
        rf"{_SHAKES_AND_BARS}|{_PROCESSED_MEAT}|{_RESTAURANTS}"
    ),
    EGGS: (
        rf"\b(?:{_BAKED})\b|\begg substitute\b|(?<!\brice )\bnoodles?\b|(?<!\brice )\bpasta\b|"
        r"\bcaesar\b|\bdressing\b|"
        rf"\bpuddings?\b|\bice creams?\b|\bgnocchi\b|\bfried rice\b|\bfrostings?\b|\bveggie\b|"
        rf"{_RESTAURANTS}"
    ),
    FISH: (
        r"\bseafood\b|\bcaesar\b|\bpad thai\b|\bkimchi\b|\bcurry paste\b|\bdashi\b|\bsushi\b|"
        r"\bbarbecue\b|\bcocktail sauce\b|\bsauce, cocktail\b|\bhot thai sauce\b"
    ),
    CRUSTACEANS: (
        r"\bseafood\b|\bshellfish\b|\bsurimi\b|\bpad thai\b|\bkimchi\b|\bcurry paste\b|\bsushi\b|"
        r"\bimitation crab\b|\bcocktail sauce\b|\bsauce, cocktail\b"
    ),
    # Nuts the FDA dropped from Table 1 stay here, because people avoiding tree nuts may avoid them.
    TREE_NUTS: (
        rf"\bnuts?\b|\bnutty\b|\bcoconuts?\b|(?<!\bwater )\bchestnuts?\b|\bbeechnuts?\b|"
        rf"(?<!\bwinter, )\bbutternuts?\b(?! squash)|\bhickory ?nuts?\b|\bchinquapins?\b|"
        rf"\bginkgo\b|\bpili\b|"
        rf"\bshea\b|\bsheanut\b|\blychee nuts?\b|\bacorns?\b|\bpesto\b|\bnougat\b|{_CANDY}|"
        rf"\bgranola\b|\btrail mix\b|\bmole\b|\bcereals? ready-to-eat\b|\bice creams?\b|"
        rf"\bcookies?\b|\bbrownies?\b|{_SHAKES_AND_BARS}"
    ),
    PEANUTS: (
        rf"\bnuts\b|{_CANDY}|\bsatay\b|\bgranola\b|\btrail mix\b|\bpad thai\b|\bmole\b|"
        r"\bcookies?\b|"
        rf"\bice creams?\b|\bkung pao\b|{_SHAKES_AND_BARS}"
    ),
    WHEAT: (
        r"\bgravy\b|\bcereals?\b|\bgranola\b|\boats?\b|\boatmeal\b|\brye\b|\bbarley\b|\bmalt\b|"
        r"\bbeers?\b|\bale\b|\bhoisin\b|\bsoba\b|\bvermicelli\b|\btortillas?\b|\brolls?\b|"
        r"\bsoups?\b|\bchowder\b|\bgluten-free\b|\bgluten free\b|\bmeatless\b|\bveggie\b|"
        r"\bimitation\b|(?<!\bstir-)\bfried\b|\bnuggets?\b|\bpatties\b|\bmeatballs?\b|\bmeatloaf\b|"
        r"\bjerky\b|"
        r"\bbouillon\b|\bseasoning mix\b|\blicorice\b|\bcreamed\b|\bstrips?\b|\btenders?\b|"
        r"\bfingers?\b|\bonion rings?\b|\bburritos?\b|\bspring rolls?\b|\bbarbecue\b|\benchilada\b|"
        r"\bmultigrain\b|\bpuffs?\b|\bsauce, (?:oyster|hoisin|fish|plum)\b|\bfrostings?\b|"
        rf"{_CANDY}|{_SHAKES_AND_BARS}|{_PROCESSED_MEAT}|{_RESTAURANTS}"
    ),
    SOYBEANS: (
        r"\bhoisin\b|\blecithin\b|\bmargarine\b|\bshortening\b|\bvegetable oils?\b|"
        r"\boil, soybean\b|"
        r"\bsoybean oil\b|\boil or table fat\b|\btable fat\b|\bmayonnaise\b|\bdressing\b|"
        r"\bcooking spray\b|\bmeatless\b|\bveggie\b|\bimitation\b|\bstir[- ]fr(?:y|ied)\b|"
        r"\bjerky\b|"
        r"\bsauce, (?:oyster|plum)\b|\bbarbecue\b|\bgravy\b|\bindustrial oil\b|\bfrostings?\b|"
        rf"\btoppings?, |\bwhipped topping\b|{_CANDY}|{_SHAKES_AND_BARS}|{_PROCESSED_MEAT}|"
        rf"{_RESTAURANTS}"
    ),
    # Some US bakeries began adding sesame to bread after it became a labeled allergen in 2023.
    SESAME: (
        r"\bza'?atar\b|\bfurikake\b|\beverything\b|\bfalafel\b|\bbagels?\b|\bbuns?\b|\bbreads?\b|"
        r"\brolls?, (?:dinner|hamburger|hard|hot ?dog|pumpernickel|french)\b|\bmixed seeds\b"
    ),
}

# Oils from these allergens fall outside the FDA's definition only when highly refined, and a label
# is the only way to tell. So they stay "may contain" even though the word itself is there.
_REFINED_OIL = re.compile(
    r"\boil, (?:peanut|soybean|soy)\b|\b(?:peanut|soybean|soy) oil\b", re.IGNORECASE
)
_REFINED_OIL_ALLERGENS = frozenset({PEANUTS, SOYBEANS})
# USDA's "Cheese as ingredient in sandwiches" is cheese. The words after "in" name where it goes.
_WHERE_IT_GOES = re.compile(r"\bas ingredient in\b.*", re.IGNORECASE)
_WHEAT_FREE = re.compile(r"\bgluten[- ]free\b|\bwheat[- ]free\b", re.IGNORECASE)
_DAIRY_FREE = re.compile(r"\bnon-?dairy\b|\bdairy[- ]free\b", re.IGNORECASE)

_CONTAINS_PATTERNS = {key: re.compile(value, re.IGNORECASE) for key, value in _CONTAINS.items()}
_MAY_CONTAIN_PATTERNS = {
    key: re.compile(value, re.IGNORECASE) for key, value in _MAY_CONTAIN.items()
}


def _softened(key: str, name: str) -> bool:
    """A name can state an allergen's word and also say it is only possibly there."""
    if key in _REFINED_OIL_ALLERGENS and _REFINED_OIL.search(name):
        return True
    if key == WHEAT and _WHEAT_FREE.search(name):
        return True
    return key == MILK and _DAIRY_FREE.search(name) is not None


def allergens_in_name(name: str) -> dict[str, AllergenRelation]:
    """What a food's name reveals. An empty result means only that the name revealed nothing."""
    found: dict[str, AllergenRelation] = {}
    name = _WHERE_IT_GOES.sub("", name)
    for key, pattern in _CONTAINS_PATTERNS.items():
        if pattern.search(name):
            found[key] = (
                AllergenRelation.MAY_CONTAIN if _softened(key, name) else AllergenRelation.CONTAINS
            )
    for key, pattern in _MAY_CONTAIN_PATTERNS.items():
        if key not in found and pattern.search(name):
            found[key] = AllergenRelation.MAY_CONTAIN
    return found


def merge_findings(
    findings: Iterable[Mapping[str, AllergenRelation]],
) -> dict[str, AllergenRelation]:
    """Combines several foods' findings. "Contains" outranks "may contain"."""
    merged: dict[str, AllergenRelation] = {}
    for finding in findings:
        for key, relation in finding.items():
            if relation is AllergenRelation.FREE_OF:
                continue
            if merged.get(key) is not AllergenRelation.CONTAINS:
                merged[key] = relation
    return merged


@dataclass(frozen=True, slots=True)
class AllergenRecipeNode:
    """A food and the foods its recipes use, for following allergens through recipes."""

    food_id: int
    name: str
    component_food_ids: tuple[int, ...]


def derive_allergens(
    nodes: Mapping[int, AllergenRecipeNode],
) -> dict[int, dict[str, AllergenRelation]]:
    """Finds each food's allergens from its name and, recursively, its ingredients' allergens.

    A cycle in bad data stops at the food already being visited, so nothing loops forever. A result
    reached while inside a cycle can be incomplete, so it is not reused for other foods.
    """
    done: dict[int, dict[str, AllergenRelation]] = {}

    def visit(food_id: int, path: frozenset[int]) -> tuple[dict[str, AllergenRelation], bool]:
        if food_id in done:
            return done[food_id], True
        node = nodes.get(food_id)
        if node is None:
            return {}, True
        if food_id in path:
            return {}, False
        inner = path | {food_id}
        findings: list[Mapping[str, AllergenRelation]] = [allergens_in_name(node.name)]
        complete = True
        for child in node.component_food_ids:
            found, child_complete = visit(child, inner)
            findings.append(found)
            complete = complete and child_complete
        merged = merge_findings(findings)
        if complete:
            done[food_id] = merged
        return merged, complete

    return {food_id: visit(food_id, frozenset())[0] for food_id in nodes}
