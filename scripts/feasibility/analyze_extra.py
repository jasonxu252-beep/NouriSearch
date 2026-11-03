import json, sys, collections as C
paths = dict(FNDDS=sys.argv[1], SR=sys.argv[2], Foundation=sys.argv[3])
data = {}
for label, p in paths.items():
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    data[label] = d[list(d.keys())[0]]
for label, ds in data.items():
    names = C.Counter()
    for f in ds:
        for n in f.get("foodNutrients", []):
            nn = n.get("nutrient", {})
            if n.get("amount") is not None and "ugar" in str(nn.get("name")):
                names[(nn.get("number"), nn.get("name"))] += 1
    print(label, "sugar nutrients:", [(k, f"{v/len(ds):.0%}") for k, v in names.most_common(6)])
    real = 0
    for f in ds:
        ps = f.get("foodPortions", [])
        if any("not specified" not in str(p.get("portionDescription", p.get("modifier", ""))).lower() and (p.get("gramWeight") or 0) > 0 for p in ps):
            real += 1
    print(label, f"foods with a named portion and gram weight: {real}/{len(ds)} ({real/len(ds):.0%})")
    kinds = C.Counter()
    for f in ds[:3000]:
        for n in f.get("foodNutrients", []):
            kinds[(n.get("foodNutrientDerivation") or {}).get("description")] += 1
    print(label, "derivation labels (first 3000 foods):", kinds.most_common(4))
for name in ("Bibimbap, Korean", "Dal"):
    f = next(x for x in data["FNDDS"] if x["description"] == name)
    print(name, "portions:", [(p.get("portionDescription"), p.get("gramWeight")) for p in f.get("foodPortions", [])][:4])
restaurant = sum(1 for f in data["FNDDS"] if any("restaurant" in str(i.get("ingredientDescription", "")).lower() for i in f.get("inputFoods", [])))
print("FNDDS foods with a restaurant-record ingredient:", restaurant)
