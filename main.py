from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
import os
import asyncio
import websockets
import json
from typing import List, Dict
import uvicorn
from collections import defaultdict

app = FastAPI(title="Solana Gold Gem Scanner")

# Config
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/search?q=solana"
MAX_TOKENS = 100  # limite mémoire

# Stockage (set pour éviter doublons address)
new_tokens = []  # list pour ordre chronologique
seen_addresses = set()  # pour éviter doublons

# --- 1. Chargement initial via DexScreener (tokens actifs Solana) ---
def fetch_initial_history():
    print("⚡ Chargement historique DexScreener...")
    try:
        resp = requests.get(DEXSCREENER_URL, timeout=8)
        if resp.status_code == 200:
            pairs = resp.json().get("pairs", [])
            added = 0
            for p in pairs:
                if p.get("chainId") == "solana" and added < 30:
                    addr = p.get("baseToken", {}).get("address")
                    if addr and addr not in seen_addresses:
                        seen_addresses.add(addr)
                        new_tokens.append({
                            "address": addr,
                            "symbol": p.get("baseToken", {}).get("symbol", "???"),
                            "mc": p.get("fdv", 0),
                            "volume": p.get("volume", {}).get("h24", 0),
                            "liquidity": p.get("liquidity", {}).get("usd", 0),
                            "txns": p.get("txns", {}).get("h24", {}).get("buys", 0) + p.get("txns", {}).get("h24", {}).get("sells", 0),
                            "source": "TRENDING",
                            "dex_link": p.get("url", f"https://dexscreener.com/solana/{addr}")
                        })
                        added += 1
            print(f"✅ DexScreener : {added} tokens chargés")
        else:
            print(f"⚠️ DexScreener status {resp.status_code}")
    except Exception as e:
        print(f"⚠️ Erreur DexScreener : {e}")

    # Fallback minimal si zéro
    if not new_tokens:
        print("⚠️ Pas de data DexScreener → fallback mock")
        new_tokens.append({
            "address": "So11111111111111111111111111111111111111112",
            "symbol": "READY",
            "mc": 0,
            "volume": 0,
            "source": "SYSTEM",
            "dex_link": "#"
        })

# --- 2. WebSocket Birdeye pour real-time new listings ---
async def websocket_listener():
    if not BIRDEYE_KEY:
        print("❌ Pas de clé Birdeye → WS désactivé")
        return

    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    reconnect_delay = 5

    while True:
        try:
            print(f"🔄 Connexion WS Birdeye (delay {reconnect_delay}s)...")
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                print("✅ WS connecté")
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                print("Subscribed to SUBSCRIBE_TOKEN_NEW_LISTING")

                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(msg)
                        if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                            t = data.get("data", {})
                            addr = t.get("address")
                            if addr and addr not in seen_addresses:
                                seen_addresses.add(addr)
                                token = {
                                    "address": addr,
                                    "symbol": t.get("symbol", "NEW"),
                                    "mc": t.get("mc", 0) or t.get("fdv", 0),
                                    "volume": t.get("v24hUSD", 0),
                                    "source": "LIVE_WS",
                                    "dex_link": f"https://dexscreener.com/solana/{addr}"
                                }
                                new_tokens.insert(0, token)
                                if len(new_tokens) > MAX_TOKENS:
                                    old = new_tokens.pop()
                                    seen_addresses.discard(old["address"])
                                print(f"💎 NEW LIVE : {token['symbol']} | MC {token['mc']}")
                    except asyncio.TimeoutError:
                        await ws.ping()
        except Exception as e:
            print(f"❌ WS error : {str(e)}. Reconnect in {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # backoff max 60s

# Startup : charge historique + lance WS
async def startup_event():
    fetch_initial_history()
    asyncio.create_task(websocket_listener())

app.add_event_handler("startup", startup_event)

@app.get("/")
def root():
    return {"status": "ONLINE", "tokens_mem": len(new_tokens)}

@app.get("/api/gems")
def get_gems():
    gems = []
    # Derniers 25 (les plus récents en haut)
    for t in new_tokens[:25]:
        score = 50
        if t["source"] == "LIVE_WS":
            score = 95
        elif t["source"] == "TRENDING":
            score = 75

        mc = t.get("mc", 0)
        volume = t.get("volume", 0)
        if volume > 0 and mc > 0:
            score += min(volume / mc * 20, 40)

        gems.append({
            "address": t["address"],
            "symbol": t["symbol"],
            "mc": round(mc, 2),
            "volume": round(volume, 2),
            "score": score,
            "risk": "NEW" if t["source"] == "LIVE_WS" else "TRENDING",
            "dex_link": t["dex_link"],
            "source": t["source"]
        })

    return {"gems": gems, "count": len(gems), "updated": time.strftime("%H:%M:%S UTC")}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
