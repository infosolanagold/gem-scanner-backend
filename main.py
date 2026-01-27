from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
from typing import List, Dict

app = FastAPI()

# Cache pour éviter de spammer les APIs
cache: Dict = {"gems": [], "ts": 0}
CACHE_DURATION = 60  # refresh toutes les 60s

# Ta clé Birdeye (obtiens-la sur birdeye.so/dashboard/api)
BIRDEYE_KEY = "TA_CLE_ICI"

def fetch_new_gems() -> List[Dict]:
    now = time.time()
    if now - cache["ts"] < CACHE_DURATION and cache["gems"]:
        return cache["gems"]

    # Exemple Birdeye trending/new tokens (adapte selon leur doc actuelle)
    url = "https://public-api.birdeye.so/defi/new_pairs?chain=solana&sort_by=created_timestamp&sort_type=desc&limit=50"
    headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}

    try:
        resp = requests.get(url, headers=headers, timeout=10).json()
        pairs = resp.get("data", {}).get("items", [])
    except:
        pairs = []

    gems = []
    for p in pairs[:30]:  # top récents
        mc = p.get("mc", 0)
        volume_5m = p.get("volume_5m", 0) or p.get("v5mUSD", 0)
        age_min = (time.time() - p.get("created_timestamp", 0) / 1000) / 60
        holders = p.get("holderCount", 0)

        if mc < 3000000 and mc > 10000 and age_min < 1440 and volume_5m > 5000:
            score = 0
            score += min(volume_5m / mc * 20, 40)  # volume spike
            score += min(holders / 100, 20) if holders else 0
            score += 20 if age_min < 60 else 10  # très récent = + points
            # Plus tard : + buzz X si ticker mentionné récemment

            risk = "vert"
            if p.get("dev_sell_percent", 0) > 20: risk = "jaune"
            if p.get("top10_holders_percent", 0) > 60: risk = "rouge"

            gems.append({
                "address": p.get("address"),
                "symbol": p.get("symbol", "???"),
                "mc": round(mc / 1000, 1),  # en k
                "volume5m": round(volume_5m / 1000, 1),
                "holders": holders,
                "age_min": round(age_min),
                "score": round(score),
                "risk": risk,
                "dex_link": f"https://dexscreener.com/solana/{p.get('address')}"
            })

    # Tri par score descendant
    gems = sorted(gems, key=lambda x: x["score"], reverse=True)[:15]

    cache["gems"] = gems
    cache["ts"] = now
    return gems

@app.get("/api/gems")
def get_gems():
    return {"gems": fetch_new_gems(), "updated": time.strftime("%H:%M:%S")}

# CORS pour que ton site .co puisse fetch sans bloquer
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://solanagold.co", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
