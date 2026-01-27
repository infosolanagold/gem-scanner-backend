from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
import os
import json
from typing import List, Dict

app = FastAPI()

# Cache pour éviter de spammer les APIs
cache: Dict = {"gems": [], "ts": 0}
CACHE_DURATION = 60  # refresh toutes les 60s

# Clé API Birdeye (sécurisée via variable d'environnement)
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
if not BIRDEYE_KEY:
    print("ERREUR : BIRDEYE_KEY non définie dans les variables d'environnement !")

def fetch_new_gems() -> List[Dict]:
    now = time.time()
    if now - cache["ts"] < CACHE_DURATION and cache["gems"]:
        return cache["gems"]

    # Endpoint Birdeye pour liste de tokens (trending / low cap)
    # Note : /defi/new_pairs n'existe pas → on utilise tokenlist et on filtre les récents/low MC
    url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=mc&sort_type=asc&offset=0&limit=100"
    headers = {
        "X-API-KEY": BIRDEYE_KEY,
        "x-chain": "solana"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()  # lève exception si erreur HTTP
        data = resp.json()
        tokens = data.get("data", {}).get("items", [])  # ou "tokens" selon version API
    except Exception as e:
        print(f"Erreur Birdeye API : {e}")
        tokens = []

    gems = []
    for t in tokens[:50]:  # limite pour perf
        mc = t.get("mc", 0) or t.get("marketCap", 0)
        volume_5m = t.get("v5mUSD", 0) or t.get("volume5m", 0) or 0
        volume_24h = t.get("v24hUSD", 0) or t.get("volume24h", 0) or 0
        age_min = (time.time() - (t.get("created_timestamp", 0) / 1000)) / 60 if t.get("created_timestamp") else 9999
        holders = t.get("holderCount", 0) or t.get("holders", 0)

        # Filtre gem potentielle : low MC, récent, volume qui monte
        if (
            10000 < mc < 3000000 and
            age_min < 1440 and  # < 24h
            (volume_5m > 5000 or volume_24h > 20000)  # volume significatif
        ):
            score = 0
            score += min(volume_5m / mc * 20, 40) if mc > 0 else 0  # spike volume
            score += min(holders / 100, 20) if holders else 0
            score += 30 if age_min < 60 else 15 if age_min < 180 else 5  # très récent = boost
            # À ajouter plus tard : score buzz X

            risk = "vert"
            dev_sell = t.get("dev_sell_percent", 0) or 0
            top10_holders = t.get("top10_holders_percent", 0) or t.get("topHoldersRatio", 0)
            if dev_sell > 20:
                risk = "jaune"
            if top10_holders > 60:
                risk = "rouge"

            gems.append({
                "address": t.get("address", ""),
                "symbol": t.get("symbol", "???"),
                "mc": round(mc / 1000, 1),  # en k
                "volume5m": round(volume_5m / 1000, 1),
                "holders": holders,
                "age_min": round(age_min),
                "score": round(score),
                "risk": risk,
                "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
            })

    # Tri par score descendant + limite 15
    gems = sorted(gems, key=lambda x: x["score"], reverse=True)[:15]

    cache["gems"] = gems
    cache["ts"] = now
    return gems

@app.get("/api/gems")
def get_gems():
    return {"gems": fetch_new_gems(), "updated": time.strftime("%H:%M:%S UTC")}

# CORS pour autoriser ton site solanagold.co
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://solanagold.co", "http://localhost:3000", "*"],  # "*" temporaire pour tests
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
