from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
import os
import json
from typing import List, Dict

app = FastAPI()

# Cache simple
cache: Dict = {"gems": [], "ts": 0}
CACHE_DURATION = 60  # refresh toutes les 60s

# Clé API Birdeye sécurisée
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
if not BIRDEYE_KEY:
    print("ERREUR CRITIQUE : BIRDEYE_KEY non définie dans les variables d'environnement ! Ajoutez-la sur Render.")

def fetch_new_gems() -> List[Dict]:
    now = time.time()
    if now - cache["ts"] < CACHE_DURATION and cache["gems"]:
        return cache["gems"]

    print("Fetch new gems from Birdeye...")
    url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=mc&sort_type=asc&offset=0&limit=100"
    headers = {
        "X-API-KEY": BIRDEYE_KEY,
        "x-chain": "solana"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        tokens = data.get("data", {}).get("items", []) or data.get("data", {}).get("tokens", []) or []
        print(f"Birdeye a renvoyé {len(tokens)} tokens")
    except Exception as e:
        print(f"Erreur Birdeye API : {str(e)}")
        tokens = []

    gems = []
    for t in tokens[:50]:
        mc = t.get("mc", 0) or t.get("marketCap", 0)
        volume_5m = t.get("v5mUSD", 0) or t.get("volume5m", 0) or 0
        volume_24h = t.get("v24hUSD", 0) or t.get("volume24h", 0) or 0
        holders = t.get("holderCount", 0) or t.get("holders", 0)

        # Filtre allégé : low MC + un peu de volume
        if 10000 < mc < 3000000 and (volume_5m > 1000 or volume_24h > 5000):
            score = 0
            if mc > 0:
                score += min(volume_5m / mc * 20, 40)  # spike volume
            score += min(holders / 100, 20) if holders else 0
            score += 10  # base pour low MC

            risk = "vert"
            dev_sell = t.get("dev_sell_percent", 0) or 0
            top10 = t.get("top10_holders_percent", 0) or t.get("topHoldersRatio", 0)
            if dev_sell > 20:
                risk = "jaune"
            if top10 > 60:
                risk = "rouge"

            gems.append({
                "address": t.get("address", ""),
                "symbol": t.get("symbol", "???"),
                "mc": round(mc / 1000, 1),
                "volume5m": round(volume_5m / 1000, 1),
                "holders": holders,
                "score": round(score),
                "risk": risk,
                "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
            })

    # Tri + limite
    gems = sorted(gems, key=lambda x: x["score"], reverse=True)[:20]
    cache["gems"] = gems
    cache["ts"] = now
    print(f"Retour {len(gems)} gems après filtre")
    return gems

@app.get("/")
def root():
    return {"status": "Gem Scanner API LIVE ! Essayez /api/gems pour voir les pépites"}

@app.get("/api/gems")
def get_gems():
    return {"gems": fetch_new_gems(), "updated": time.strftime("%H:%M:%S UTC")}

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://solanagold.co", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
