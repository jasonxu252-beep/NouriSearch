import collections as C
import json
import re
import statistics as st
import sys

survey_path, sr_path, found_path = sys.argv[1:4]


def load(p):
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    return d[list(d.keys())[0]]


survey = load(survey_path)
sr = load(sr_path)
found = load(found_path)
print("COUNTS  FNDDS", len(survey), " SR Legacy", len(sr), " Foundation", len(found))
s0 = survey[0]
print("FNDDS keys:", sorted(s0.keys()))
print("inputFood keys:", sorted(s0["inputFoods"][0].keys()) if s0.get("inputFoods") else None)
print("foodCode example:", s0.get("foodCode"), "| wweia:", s0.get("wweiaFoodCategory"))

# --- ingredient coverage
n_inp = sum(1 for f in survey if f.get("inputFoods"))
counts = [len(f.get("inputFoods", [])) for f in survey]
print(
    f"\nFNDDS foods with inputFoods: {n_inp}/{len(survey)}; ingredients per food "
    f"median={st.median(counts)} max={max(counts)}; foods with >=3 ingredients: {sum(c >= 3 for c in counts)}"
)
allinp = [i for f in survey for i in f.get("inputFoods", [])]
print("input rows:", len(allinp), " with weight>0:", sum(1 for i in allinp if (i.get("ingredientWeight") or 0) > 0))


def nmap(f):
    out = {}
    for n in f.get("foodNutrients", []):
        nn = n.get("nutrient", {})
        if n.get("amount") is not None:
            out[str(nn.get("number"))] = n["amount"]
    return out


sr_by_ndb = {str(f["ndbNumber"]): f for f in sr if f.get("ndbNumber") is not None}
sv_by_code = {str(f["foodCode"]): f for f in survey}
codes = [str(i.get("ingredientCode")) for i in allinp]
in_sr = sum(c in sr_by_ndb for c in codes)
in_sv = sum(c in sv_by_code for c in codes)
neither = sum((c not in sr_by_ndb and c not in sv_by_code) for c in codes)
print(
    f"ingredientCode resolves: SR Legacy {in_sr}/{len(codes)} ({in_sr / len(codes):.1%}); "
    f"FNDDS {in_sv}/{len(codes)} ({in_sv / len(codes):.1%}); neither {neither}"
)

# --- sparsity (missing != zero)
NAMES = {
    "307": "Sodium",
    "203": "Protein",
    "401": "Vitamin C",
    "418": "Vitamin B12",
    "328": "Vitamin D",
    "430": "Vitamin K",
    "606": "Saturated fat",
    "291": "Fiber",
    "269": "Total sugars",
    "304": "Magnesium",
}
print("\nNutrient presence per dataset (share of foods with a value / share of those values equal to 0):")
for label, ds in (("FNDDS", survey), ("SR Legacy", sr), ("Foundation", found)):
    maps = [nmap(f) for f in ds]
    row = []
    for num, name in NAMES.items():
        have = [m[num] for m in maps if num in m]
        zero = sum(v == 0 for v in have) / len(have) if have else 0
        row.append(f"{name} {len(have) / len(ds):.0%}/{zero:.0%}")
    print(f"  {label}: " + "; ".join(row))
print(
    "  nutrient count per food: "
    + "; ".join(
        f"{l} median {st.median(len(nmap(f)) for f in d)}"
        for l, d in (("FNDDS", survey), ("SR", sr), ("Foundation", found))
    )
)


def per100(code, num):
    if code in sr_by_ndb:
        return nmap(sr_by_ndb[code]).get(num)
    if code in sv_by_code:
        return nmap(sv_by_code[code]).get(num)
    return None


# --- bottom-up reconstruction
TESTS = {
    "307": "Sodium",
    "203": "Protein",
    "204": "Total fat",
    "606": "Saturated fat",
    "401": "Vitamin C",
    "291": "Fiber",
}
print(
    "\nBottom-up reconstruction vs published FNDDS value "
    "(foods with >=3 ingredients, all weights and codes resolved, published value > 0):"
)
print("  Weight-normalized: sum(w*v/100)/sum(w)*100")
for num, name in TESTS.items():
    errs, signed = [], []
    skipped = 0
    for f in survey:
        inp = f.get("inputFoods", [])
        if len(inp) < 3:
            continue
        pub = nmap(f).get(num)
        if not pub:
            continue
        tot, w, ok = 0.0, 0.0, True
        for i in inp:
            wt = i.get("ingredientWeight") or 0
            v = per100(str(i.get("ingredientCode")), num)
            if wt <= 0 or v is None:
                ok = False
                break
            tot += wt * v / 100
            w += wt
        if not ok or w == 0:
            skipped += 1
            continue
        calc = tot / w * 100
        errs.append(abs(calc - pub) / pub)
        signed.append((calc - pub) / pub)
    if len(errs) > 10:
        p90 = st.quantiles(errs, n=10)[8]
        print(
            f"  {name:14s} n={len(errs):5d} skipped={skipped:5d} median|err|={st.median(errs):6.1%} "
            f"p90|err|={p90:7.1%} within10%={sum(e <= .10 for e in errs) / len(errs):.0%} "
            f"within25%={sum(e <= .25 for e in errs) / len(errs):.0%} medianSigned={st.median(signed):+.1%}"
        )


def show(name):
    m = [f for f in survey if f["description"].lower() == name.lower()]
    if not m:
        print(" none", name)
        return None
    f = m[0]
    n = nmap(f)
    wweia = f.get("wweiaFoodCategory", {}).get("wweiaFoodCategoryDescription")
    print(f"\n{f['description']} (fdcId {f['fdcId']}, foodCode {f.get('foodCode')}, WWEIA {wweia})")
    print(
        f"  published per 100 g: sodium {n.get('307')} mg, protein {n.get('203')} g, "
        f"sat fat {n.get('606')} g, vit C {n.get('401')} mg"
    )
    tw = sum(i.get("ingredientWeight") or 0 for i in f["inputFoods"])
    calc = 0.0
    miss = []
    for i in f["inputFoods"]:
        code = str(i.get("ingredientCode"))
        w = i.get("ingredientWeight") or 0
        v = per100(code, "307")
        c = None if v is None else w * v / 100
        if c is None:
            miss.append(i.get("ingredientDescription"))
        else:
            calc += c
        amount = f"{c:.0f} mg" if c is not None else "UNKNOWN"
        print(
            f"    {str(i.get('ingredientDescription', ''))[:58]:58s} {w:8.1f} g  code {code:9s} "
            f"sodium/100g {v}  -> {amount}"
        )
    print(
        f"  recipe weight {tw:.1f} g; bottom-up sodium {calc / tw * 100 if tw else 0:.0f} mg/100g "
        f"vs published {n.get('307')}; unresolved: {miss}"
    )
    return f


for dish in ("Kung pao chicken", "Bibimbap, Korean", "Dal"):
    show(dish)


def grep(ds, pat, lim=8):
    r = re.compile(pat, re.I)
    hits = [f["description"] for f in ds if r.search(f["description"])]
    return len(hits), hits[:lim]


print("\nUser example coverage (hits, first examples):")
for pat in (
    r"salted",
    r"fish.*(salt|dried)|(salt|dried).*fish",
    r"duck.*egg|egg.*duck",
    r"pickled|preserved|fermented",
    r"soy sauce",
    r"soy sauce.*low sodium|low sodium.*soy sauce",
    r"mapo|ma po|douban|fish sauce|gochujang|miso|paneer|ghee",
):
    for label, ds in (("FNDDS", survey), ("SR", sr), ("Found", found)):
        c, h = grep(ds, pat, 5)
        print(f"  /{pat}/ {label}: {c}  {h}")

print("\nCuisine vocabulary in FNDDS descriptions (rough keyword counts, not a classification):")
parts = []
for term in (
    "chinese", "mexican", "puerto rican", "korean", "japanese", "indian",
    "thai", "vietnamese", "filipino", "italian", "greek", "middle eastern", "african", "ethiopian",
):
    parts.append(f"{term}: {grep(survey, chr(92) + 'b' + term + chr(92) + 'b', 0)[0]}")
print("  " + "; ".join(parts))
print(
    "Top WWEIA categories:",
    C.Counter(f.get("wweiaFoodCategory", {}).get("wweiaFoodCategoryDescription") for f in survey).most_common(8),
)
print(
    "Dish vocabulary sample:",
    grep(survey, r"stir|egg foo|lo mein|chow|fried rice|pad thai|curry|tikka|samosa|sushi|pho\b|tamale|enchilada", 14),
)
print("FNDDS publicationDate:", C.Counter(f.get("publicationDate") for f in survey).most_common(2))
