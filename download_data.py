#!/usr/bin/env python3
# download_data.py — Downloads base stats for all ~1000 Pokémon from PokeAPI
# Run once before using the bot: python download_data.py

import json
import os
import urllib.request
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_FILE = os.path.join(DATA_DIR, "base_stats.json")

# Pokémon GO uses a specific formula to derive GO stats from main-series base stats:
#   go_atk = round(2 * (7/8 * max(Atk, SpA) + 1/8 * min(Atk, SpA)))
#   go_def = round(2 * (7/8 * max(Def, SpD) + 1/8 * min(Def, SpD)))
#   go_sta = floor(Spe/2) + 40  ... (simplified; actual formula varies per mon)
# NOTE: We use the already-computed GO stats from a community data source for accuracy.

GO_STATS_URL = (
    "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/pokemon/"
    # We'll use the PokéMiners game master instead — more accurate GO stats
)

# Best source: Pokémon GO GameMaster parsed stats from Silph Road community
SILPH_STATS_URL = "https://raw.githubusercontent.com/pokemongo-dev-contrib/pokemongo-game-master/master/versions/latest/pokemon.json"

def download_from_silph():
    """Download Pokémon GO base stats from community GameMaster parse."""
    print("Downloading Pokémon GO base stats from GameMaster...")
    try:
        with urllib.request.urlopen(SILPH_STATS_URL, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  ⚠️  Failed to download from Silph source: {e}")
        return None

    stats = {}
    for entry in data:
        name = entry.get("name", "")
        if not name or "POKEMON_" not in name.upper():
            continue

        # Clean name: POKEMON_PIKACHU → Pikachu
        clean = name.replace("POKEMON_", "").replace("_", " ").title()

        base = entry.get("stats", {})
        atk = base.get("baseAttack")
        def_ = base.get("baseDefense")
        sta = base.get("baseStamina")

        if atk and def_ and sta:
            stats[clean] = {"atk": atk, "def": def_, "sta": sta}

    return stats

def download_from_pokeapi():
    """Fallback: compute GO stats from PokeAPI main-series stats."""
    print("Downloading from PokeAPI (computing GO stats)...")
    stats = {}
    
    # Get list of all pokemon
    try:
        url = "https://pokeapi.co/api/v2/pokemon?limit=1000&offset=0"
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        pokemon_list = data["results"]
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return {}

    total = len(pokemon_list)
    for i, poke in enumerate(pokemon_list):
        try:
            with urllib.request.urlopen(poke["url"], timeout=10) as resp:
                pdata = json.loads(resp.read())

            base = {s["stat"]["name"]: s["base_stat"] for s in pdata["stats"]}
            name = pdata["name"].replace("-", " ").title()

            # Approximate GO stat conversion
            hp   = base.get("hp", 0)
            atk  = base.get("attack", 0)
            def_ = base.get("defense", 0)
            spa  = base.get("special-attack", 0)
            spd  = base.get("special-defense", 0)
            spe  = base.get("speed", 0)

            go_atk = round(2 * (7/8 * max(atk, spa) + 1/8 * min(atk, spa)))
            go_def = round(2 * (7/8 * max(def_, spd) + 1/8 * min(def_, spd)))
            go_sta = max(1, hp + 10) * 2

            stats[name] = {"atk": go_atk, "def": go_def, "sta": go_sta}

            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{total}...")
            time.sleep(0.05)  # Be polite to PokeAPI

        except Exception as e:
            continue

    return stats

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    stats = download_from_silph()
    if not stats or len(stats) < 100:
        print("Falling back to PokeAPI...")
        stats = download_from_pokeapi()

    if stats:
        with open(OUT_FILE, "w") as f:
            json.dump(stats, f, indent=2, sort_keys=True)
        print(f"\n✅ Saved {len(stats)} Pokémon to {OUT_FILE}")
    else:
        print("\n❌ Could not download stats. The bot will use a limited fallback set.")
        print("   Try again later or manually place base_stats.json in the data/ folder.")
        print("   Format: {\"Pikachu\": {\"atk\": 112, \"def\": 96, \"sta\": 111}, ...}")

if __name__ == "__main__":
    main()
