from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
import os
import asyncio
import websockets
from typing import List, Dict
import json
import uvicorn

app = FastAPI()

# --- CONFIGURATION ---
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
gem_storage = []

# --- 1. RÉCUPÉRATION DES GEMS (TRENDING) ---
def fetch_trending():
    """Récupère les tokens chauds AVEC LOGOS"""
    print("🔥 Mise à jour des Trending Tokens...")
    # On utilise l'endpoint trending qui fournit les logos (logoURI)
    url = "https://public-api.birdeye.so/defi/token_trending?sort_by=rank&sort_type=asc&offset=0&limit=20"
    headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana", "accept": "application/json"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            tokens = data.get("data", {}).get("tokens", [])
            
            # On vide et on remplit
            global gem_storage
            temp_list = []
            
            for t in tokens:
                temp_list.append({
                    "address": t.get("address"),
                    "symbol": t.get("symbol", "UNK"),
                    "name": t.get("name", "Unknown"),
                    # ICI C'EST IMPORTANT : On chope le logo
                    "logo": t.get("logoURI"), 
                    "mc": t.get("liquidity", 0) * 10,
                    "volume": t.get("volume24hUSD", 0),
                    "rank": t.get("rank", 999),
                    "source": "TRENDING"
                })
            
            if len(temp_list) > 0:
                gem_storage = temp_list
                print(f"✅ {len(gem_storage)} Gems chargés avec Logos.")
            else:
                print("⚠️ Liste trending vide reçue.")
        else:
            print(f"⚠️ Erreur Birdeye: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ Exception: {e}")

# --- 2. WEBSOCKET (LIVE) ---
async def websocket_listener():
    if not BIRDEYE_KEY: return
    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("✅ WebSocket Live")
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=20)
                        data = json.loads(msg)
                        if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                            t = data.get("data", {})
                            if t:
                                # Les nouveaux n'ont souvent pas de logo, on met None
                                gem_storage.insert(0, {
                                    "address": t.get("address"),
                                    "symbol": t.get("symbol", "NEW"),
                                    "name": "New Listing",
                                    "logo": None, 
                                    "mc": t.get("liquidity", 0),
                                    "volume": 0,
                                    "source": "LIVE_NEW"
                                })
                                if len(gem_storage) > 50: gem_storage.pop()
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"type": "ping"}))
        except Exception:
            await asyncio.sleep(5)

async def background_refresher():
    while True:
        fetch_trending()
        await asyncio.sleep(300) # Refresh toutes les 5 min

@app.on_event("startup")
async def startup_event():
    fetch_trending()
    asyncio.create_task(websocket_listener())
    asyncio.create_task(background_refresher())

@app.get("/")
def root():
    return {"status": "GEMS_API_READY", "count": len(gem_storage)}

@app.get("/api/gems")
def get_gems():
    return {"gems": gem_storage, "count": len(gem_storage), "updated": time.strftime("%H:%M:%S")}

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
