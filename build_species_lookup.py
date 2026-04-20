# build_species_lookup.py
import requests, json
from bs4 import BeautifulSoup

resp = requests.get("https://pokemondb.net/pokedex/stats/height-weight")
soup = BeautifulSoup(resp.text, "html.parser")

lookup = {}
for row in soup.select("table tbody tr"):
    cols = row.find_all("td")
    if len(cols) < 7:
        continue

    name       = cols[1].get_text(strip=True)
    type_links = cols[2].find_all("a")
    types      = [a.get_text(strip=True) for a in type_links]

    # Columns: 0=#  1=Name  2=Type  3=Ht(ft)  4=Ht(m)  5=Wt(lbs)  6=Wt(kg)  7=BMI
    try:
        height_m  = float(cols[4].get_text(strip=True).replace(",", ""))
    except ValueError:
        height_m  = None
    try:
        weight_kg = float(cols[6].get_text(strip=True).replace(",", ""))
    except ValueError:
        weight_kg = None

    if name and types:
        lookup[name] = {
            "types":     types,
            "height_m":  height_m,
            "weight_kg": weight_kg
        }

with open("species_lookup.json", "w") as f:
    json.dump(lookup, f, indent=2)

print(f"Built species_lookup.json — {len(lookup)} species")
for test in ["Pikachu", "Charizard", "Mewtwo"]:
    print(f"  {test}: {lookup.get(test)}")