from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
import os
import asyncio
import websockets
from typing import List, Dict
import json

app = FastAPI()

cache: Dict = {"gems": [], "ts": 0}
CACHE_DURATION = 60

BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
if not BIRDEYE_KEY:
    print("ERREUR : BIRDEYE_KEY manquante ! Ajoutez-la sur Render.")

# Liste pour stocker recent new tokens du WS
new_tokens = []

async def websocket_listener():
    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("WS Birdeye connecté")
                # Subscribe to new token listings
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                print("Subscribed to new token listings")
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                        token = data.get("data", {})
                        if token:
                            new_tokens.append(token)
                            print(f"New token via WS : {token.get('symbol', '???')}")
        except Exception as e:
            print(f"WS error : {e} - Reconnect in 10s")
            await asyncio.sleep(10)

# Lance le WS listener au start (background)
asyncio.create_task(websocket_listener())

def fetch_new_gems() -> List[Dict]:
    now = time.time()
    if now - cache["ts"] < CACHE_DURATION and cache["gems"]:
        print("Retour cache")
        return cache["gems"]

    gems = []
    # Priorité : new tokens du WS (recent)
    if new_tokens:
        print(f"Utilisation {len(new_tokens)} new tokens du WS")
        for t in new_tokens[-20:]:  # derniers 20
            mc = t.get("mc", 0) or 0
            volume = t.get("volume", 0) or t.get("v24hUSD", 0) or 0
            holders = t.get("holderCount", 0) or 0
            if mc > 1000 and mc < 5000000:
                score = 30 + min(volume / 1000, 50) + min(holders / 500, 20)
                risk = "vert"  # default WS new = low risk early
                gems.append({
                    "address": t.get("address", ""),
                    "symbol": t.get("symbol", "???"),
                    "mc": round(mc / 1000, 1),
                    "volume24h": round(volume / 1000, 1),
                    "holders": holders,
                    "score": round(score),
                    "risk": risk,
                    "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
                })
        new_tokens.clear()  # clear après usage

    # Fallback tokenlist si pas de new WS
    if not gems:
        print("Fallback tokenlist")
        url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=mc&sort_type=asc&offset=0&limit=50"
        headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            tokens = data.get("data", {}).get("items", []) or []
            print(f"Tokenlist : {len(tokens)} tokens")
            for t in tokens:
                mc = t.get("mc", 0)
                if 1000 < mc < 5000000:
                    score = 20 + min(t.get("v24hUSD", 0) / 1000, 50)
                    gems.append({
                        "address": t.get("address", ""),
                        "symbol": t.get("symbol", "???"),
                        "mc": round(mc / 1000, 1),
                        "score": round(score),
                        "risk": "vert",
                        "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
                    })
        except Exception as e:
            print(f"Fallback error : {e}")

    gems = sorted(gems, key=lambda x: x["score"], reverse=True)[:15]
    cache["gems"] = gems
    cache["ts"] = now
    print(f"Final : {len(gems)} gems")
    return gems

@app.get("/")
def root():
    return {"status": "Gem Scanner LIVE ! /api/gems pour data"}

@app.get("/api/gems")
def get_gems():
    return {"gems": fetch_new_gems(), "updated": time.strftime("%H:%M:%S UTC")}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "https://solanagold.co"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
