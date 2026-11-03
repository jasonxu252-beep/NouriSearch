"""Allergen findings. A wrong silence could hurt someone, so these are the rules' hardest cases."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.allergens import (
    CRUSTACEANS,
    EGGS,
    FISH,
    MILK,
    PEANUTS,
    SESAME,
    SOYBEANS,
    TREE_NUTS,
    WHEAT,
    AllergenRecipeNode,
    allergens_in_name,
    derive_allergens,
    merge_findings,
)
from app.domain.enums import AllergenRelation

CONTAINS = AllergenRelation.CONTAINS
MAY = AllergenRelation.MAY_CONTAIN


@pytest.mark.parametrize(
    ("name", "allergen"),
    [
        # Milk from other animals is still milk, and "goat" must not read as "oat".
        ("Goat milk", MILK),
        ("Milk, whole, 3.25% milkfat, with added vitamin D", MILK),
        ("Buttermilk, low fat", MILK),
        ("Butter, stick, salted", MILK),
        ("Cheese, cheddar", MILK),
        ("Cream, sour, full fat", MILK),
        ("Ice cream, vanilla", MILK),
        # USDA's own plural, which a first version of these rules missed.
        ("Ice creams, vanilla", MILK),
        ("Ice creams, BREYERS, 98% Fat Free Vanilla", MILK),
        ("Yogurt, Greek, plain, nonfat", MILK),
        ("Whey, sweet, dried", MILK),
        ("Dulce de leche", MILK),
        ("Puddings, vanilla, ready-to-eat", MILK),
        ("Soup, cream of mushroom, canned, condensed", MILK),
        ("Sauce, homemade, white, medium", MILK),
        ("Eggs, Grade A, Large, egg whole", EGGS),
        ("Salad dressing, mayonnaise, regular", EGGS),
        ("Mayonnaise, light", EGGS),
        ("Sauce, tartar", EGGS),
        ("Tartar sauce", EGGS),
        ("Pie, lemon meringue", EGGS),
        ("Fish, salmon, pink, cooked, dry heat", FISH),
        ("Tuna salad, made with mayonnaise", FISH),
        ("Sauce, fish, ready-to-serve", FISH),
        ("Sauce, worcestershire", FISH),
        ("Anchovy, canned", FISH),
        ("Crustaceans, shrimp, mixed species, cooked", CRUSTACEANS),
        ("Lobster salad", CRUSTACEANS),
        ("Crawfish, boiled", CRUSTACEANS),
        # All twelve names in Table 1 of the FDA's guidance, edition 5.
        ("Nuts, almonds, dry roasted", TREE_NUTS),
        ("Black walnut, chopped", TREE_NUTS),
        ("Brazil nut, raw", TREE_NUTS),
        ("California walnut", TREE_NUTS),
        ("Nuts, cashew nuts, raw", TREE_NUTS),
        ("Hazelnuts or filberts", TREE_NUTS),
        ("Heartnut, raw", TREE_NUTS),
        ("Nuts, macadamia nuts, raw", TREE_NUTS),
        ("Bush nut, raw", TREE_NUTS),
        ("Nuts, pecans, raw", TREE_NUTS),
        ("Pine nuts, dried", TREE_NUTS),
        ("Nuts, pistachio nuts, raw", TREE_NUTS),
        ("Nuts, walnuts, English, halves, raw", TREE_NUTS),
        ("Almond milk, unsweetened", TREE_NUTS),
        ("Peanut butter, creamy", PEANUTS),
        ("Peanuts, all types, raw", PEANUTS),
        ("Candies, REESE'S Peanut Butter Cups", PEANUTS),
        ("Flour, wheat, all-purpose, enriched, bleached", WHEAT),
        ("Wheat flour, whole-grain", WHEAT),
        ("Bread, white, commercially prepared", WHEAT),
        ("Pasta, cooked, enriched, without added salt", WHEAT),
        ("Couscous, cooked", WHEAT),
        ("Phyllo dough", WHEAT),
        ("Focaccia, Italian, plain", WHEAT),
        ("Pan Dulce, no topping", WHEAT),
        ("Soy sauce made from soy and wheat (shoyu)", WHEAT),
        ("Cream of wheat, cooked", WHEAT),
        # Triticale is a wheat hybrid, so its flour is not one of the other flours.
        ("Triticale flour, whole-grain", WHEAT),
        ("Triticale", WHEAT),
        ("Einkorn, raw", WHEAT),
        ("Emmer, cooked", WHEAT),
        ("Kamut, cooked", WHEAT),
        ("Pizzas, frozen", WHEAT),
        ("Soy sauce made from soy and wheat (shoyu), low sodium", SOYBEANS),
        ("Tofu, firm", SOYBEANS),
        ("Soymilk, original", SOYBEANS),
        ("Edamame, frozen", SOYBEANS),
        ("Miso", SOYBEANS),
        ("Oil, sesame, salad or cooking", SESAME),
        ("Seeds, sesame butter, tahini", SESAME),
        ("Hummus, commercial", SESAME),
    ],
)
def test_a_name_that_says_so_contains_the_allergen(name: str, allergen: str) -> None:
    assert allergens_in_name(name).get(allergen) is CONTAINS


@pytest.mark.parametrize(
    ("name", "allergen"),
    [
        # Coconut left the FDA's list, and people avoiding tree nuts can still want to know.
        ("Coconut milk", TREE_NUTS),
        ("Oil, coconut", TREE_NUTS),
        ("Nuts, chestnuts, roasted", TREE_NUTS),
        ("Acorn stew (Apache)", TREE_NUTS),
        ("Oil, sheanut", TREE_NUTS),
        # Highly refined oils are outside the FDA's definition, but only a label says it is refined.
        ("Oil, peanut", PEANUTS),
        ("Oil, soybean", SOYBEANS),
        ("Vegetable oil, NFS", SOYBEANS),
        ("Margarine, stick", SOYBEANS),
        ("Margarine, stick", MILK),
        ("Whipped topping", MILK),
        ("Cookies, oatmeal", EGGS),
        ("Cookies, oatmeal", TREE_NUTS),
        ("Cookies, oatmeal", PEANUTS),
        ("Nutrition bar (Clif Bar)", PEANUTS),
        ("Nutrition bar (Clif Bar)", SOYBEANS),
        ("Cereals, oats, regular and quick, not fortified, dry", WHEAT),
        ("Bread, gluten-free, white", WHEAT),
        ("Rolls, hamburger or hotdog, plain", SESAME),
        ("Shellfish, NFS", CRUSTACEANS),
        ("TACO BELL, Bean Burrito", MILK),
        ("Sausage, Italian, pork", SOYBEANS),
        ("Infant formula, powder", MILK),
        ("Soup, New England clam chowder", MILK),
    ],
)
def test_a_name_that_suggests_it_may_contain_the_allergen(name: str, allergen: str) -> None:
    assert allergens_in_name(name).get(allergen) is MAY


@pytest.mark.parametrize(
    ("name", "allergen"),
    [
        # Words that look like an allergen and are not.
        ("Coconut milk", MILK),
        ("Almond milk, unsweetened", MILK),
        ("Soy milk, unsweetened", MILK),
        ("Oat milk", MILK),
        ("Rice milk", MILK),
        ("Peanut butter, creamy", MILK),
        ("Oil, cocoa butter", MILK),
        ("Apple butter", MILK),
        ("Seeds, sunflower seed butter, without salt", MILK),
        ("Corn, sweet, yellow, canned, cream style, regular pack", MILK),
        ("Leavening agents, cream of tartar", MILK),
        ("Lettuce, butterhead, raw", MILK),
        ("Beans, butter, mature seeds", TREE_NUTS),
        ("Eggplant, raw", EGGS),
        ("Squash, winter, butternut, raw", TREE_NUTS),
        ("Babyfood, vegetable, butternut squash and corn", TREE_NUTS),
        ("Water chestnuts, canned", TREE_NUTS),
        ("Nutmeg, ground", TREE_NUTS),
        ("Doughnuts, cake-type", TREE_NUTS),
        ("Buckwheat, whole grain", WHEAT),
        ("Rice noodles, cooked", WHEAT),
        ("Rice noodles, cooked", EGGS),
        ("Rice flour, brown", WHEAT),
        ("Corn flour, yellow, masa, enriched", WHEAT),
        ("Spaghetti squash, raw", WHEAT),
        ("Breadfruit, raw", WHEAT),
        ("Cherries, tart, canned", WHEAT),
        ("Licorice root", SOYBEANS),
        ("Crabapples, raw", CRUSTACEANS),
        ("Mollusks, oyster, Pacific, raw", CRUSTACEANS),
        ("Jellyfish, dried, salted", FISH),
        ("Peanut butter, creamy", TREE_NUTS),
        ("Salt, table", SOYBEANS),
        # The words after "in" say where it goes, not what it is.
        ("Cheese as ingredient in sandwiches", WHEAT),
        ("Tomatoes as ingredient in omelet", EGGS),
    ],
)
def test_a_lookalike_word_is_not_that_allergen(name: str, allergen: str) -> None:
    assert allergen not in allergens_in_name(name)


@pytest.mark.parametrize(
    ("name", "allergen"),
    [
        ("Bread, gluten-free, white", WHEAT),
        ("Pasta, gluten free, corn and rice flour", WHEAT),
        ("Cream substitute, non-dairy, liquid", MILK),
    ],
)
def test_a_free_from_claim_only_softens_the_finding(name: str, allergen: str) -> None:
    """A claim like this comes from a brand, not from us, and only a label can confirm it."""
    assert allergens_in_name(name).get(allergen) is MAY


def test_a_food_whose_name_reveals_nothing_has_no_finding_and_no_claim_of_absence() -> None:
    assert allergens_in_name("Salt, table") == {}
    assert allergens_in_name("Rice, white, long-grain, regular, enriched, cooked") == {}


def test_no_rule_can_claim_a_food_is_free_of_an_allergen() -> None:
    names = ["Salt, table", "Goat milk", "Bread, gluten-free, white", "Water", "Oil, canola"]
    for name in names:
        assert AllergenRelation.FREE_OF not in allergens_in_name(name).values()


def test_contains_outranks_may_contain_whatever_the_order() -> None:
    assert merge_findings([{MILK: MAY}, {MILK: CONTAINS}]) == {MILK: CONTAINS}
    assert merge_findings([{MILK: CONTAINS}, {MILK: MAY}]) == {MILK: CONTAINS}


def test_a_stated_absence_cannot_cancel_a_finding() -> None:
    """Even if bad data says "free of", a different source's finding stands."""
    merged = merge_findings([{MILK: AllergenRelation.FREE_OF}, {MILK: MAY}])
    assert merged == {MILK: MAY}
    assert merge_findings([{MILK: AllergenRelation.FREE_OF}]) == {}


def nodes(*items: tuple[int, str, tuple[int, ...]]) -> dict[int, AllergenRecipeNode]:
    return {i: AllergenRecipeNode(i, name, parts) for i, name, parts in items}


def test_a_dish_inherits_what_its_ingredients_contain() -> None:
    found = derive_allergens(nodes((1, "House special", (2, 3)), (2, "Tofu", ()), (3, "Rice", ())))
    assert found[1] == {SOYBEANS: CONTAINS}


def test_findings_travel_through_every_level_of_a_recipe() -> None:
    found = derive_allergens(
        nodes(
            (1, "Casserole", (2,)),
            (2, "House sauce", (3,)),
            (3, "House base", (4,)),
            (4, "Sesame paste", ()),
        )
    )
    assert found[1] == {SESAME: CONTAINS}
    assert found[2] == {SESAME: CONTAINS}


def test_may_contain_travels_as_may_contain_and_never_grows() -> None:
    found = derive_allergens(nodes((1, "Fried vegetables", (2,)), (2, "Vegetable oil, NFS", ())))
    assert found[1][SOYBEANS] is MAY


def test_an_ingredient_can_turn_a_dish_may_contain_into_contains() -> None:
    found = derive_allergens(nodes((1, "Margarine blend", (2,)), (2, "Soybeans", ())))
    assert found[1][SOYBEANS] is CONTAINS


def test_a_cycle_in_bad_data_terminates_and_keeps_what_it_found() -> None:
    found = derive_allergens(nodes((1, "Tofu loaf", (2,)), (2, "House sauce", (1,))))
    assert found[1] == {SOYBEANS: CONTAINS}
    assert found[2] == {SOYBEANS: CONTAINS}


def test_a_cycle_does_not_leave_a_food_outside_it_with_less_than_it_should_have() -> None:
    found = derive_allergens(
        nodes(
            (1, "Plain", (2,)),
            (2, "Also plain", (3,)),
            (3, "Tofu loaf", (2,)),
            (4, "Other", (3,)),
        )
    )
    for food_id in (1, 2, 3, 4):
        assert found[food_id].get(SOYBEANS) is CONTAINS


def test_an_unknown_ingredient_adds_nothing_and_breaks_nothing() -> None:
    found = derive_allergens(nodes((1, "Tofu dish", (99,))))
    assert found[1] == {SOYBEANS: CONTAINS}


NAMES = st.sampled_from(
    ["Tofu", "Cheese", "Rice", "Salt, table", "Peanuts", "Water", "Egg", "Bread", "Onions, raw"]
)


@settings(max_examples=150)
@given(
    st.dictionaries(
        st.integers(1, 12),
        st.tuples(NAMES, st.lists(st.integers(1, 12), max_size=4)),
        min_size=1,
    )
)
def test_a_food_holds_at_least_everything_each_ingredient_holds(
    recipes: dict[int, tuple[str, list[int]]],
) -> None:
    """The property that keeps an excluded allergen out: nothing is lost on the way up a recipe."""
    graph = {
        food_id: AllergenRecipeNode(food_id, name, tuple(parts))
        for food_id, (name, parts) in recipes.items()
    }
    found = derive_allergens(graph)

    def reachable(food_id: int) -> set[int]:
        seen: set[int] = set()
        stack = [food_id]
        while stack:
            current = stack.pop()
            if current in seen or current not in graph:
                continue
            seen.add(current)
            stack.extend(graph[current].component_food_ids)
        return seen

    for food_id in graph:
        for descendant in reachable(food_id):
            for allergen, relation in allergens_in_name(graph[descendant].name).items():
                assert allergen in found[food_id]
                if relation is CONTAINS:
                    assert found[food_id][allergen] is CONTAINS
