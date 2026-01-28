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
new_tokens = []

# --- 1. FONCTION DE SECOURS (HYBRIDE) ---
def fetch_initial_history():
    """Tente de charger l'API, sinon injecte des données de secours"""
    print("⚡ Démarrage : Tentative de chargement historique...")
    
    # Tentative via API
    try:
        url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&offset=0&limit=10"
        headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
        resp = requests.get(url, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            items = resp.json().get("data", {}).get("items", [])
            for t in items:
                new_tokens.append({
                    "address": t.get("address"),
                    "symbol": t.get("symbol", "UNK"),
                    "mc": t.get("mc", 0),
                    "v24hUSD": t.get("v24hUSD", 0),
                    "source": "API_HIST"
                })
    except Exception as e:
        print(f"⚠️ API Erreur: {e}")

    # --- LE FILET DE SÉCURITÉ (SI L'API A ECHOUE) ---
    if len(new_tokens) == 0:
        print("🚨 API vide -> Injection de tokens de secours (Backup Mode)")
        # On injecte manuellement des tokens connus pour que le site ne soit pas vide
        backups = [
            {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL", "mc": 65000000000, "v24hUSD": 2000000000},
            {"address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "symbol": "JUP", "mc": 1200000000, "v24hUSD": 50000000},
            {"address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK", "mc": 1500000000, "v24hUSD": 80000000},
            {"address": "7i5KKsX2weiTkry7jA4ZwSuXGhs5eJBEjY8vVxR4pfRx", "symbol": "GMT", "mc": 300000000, "v24hUSD": 15000000}
        ]
        for b in backups:
            b["source"] = "BACKUP"
            new_tokens.append(b)

    print(f"✅ Démarrage terminé : {len(new_tokens)} tokens en mémoire.")

# --- 2. WEBSOCKET (LIVE) ---
async def websocket_listener():
    if not BIRDEYE_KEY: return
    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("✅ WS Connecté")
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=20)
                        data = json.loads(msg)
                        if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                            t = data.get("data", {})
                            if t:
                                t['source'] = "LIVE_WS"
                                print(f"💎 LIVE: {t.get('symbol')}")
                                new_tokens.insert(0, t)
                                if len(new_tokens) > 50: new_tokens.pop()
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"type": "ping"}))
        except Exception:
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    fetch_initial_history()
    asyncio.create_task(websocket_listener())

@app.get("/")
def root():
    return {"status": "ONLINE", "tokens_loaded": len(new_tokens)}

@app.get("/api/gems")
def get_gems():
    gems = []
    for t in list(new_tokens)[:20]:
        mc = t.get("mc", 0) or 0
        gems.append({
            "address": t.get("address", ""),
            "symbol": t.get("symbol", "???"),
            "mc": round(mc, 2),
            "volume": round(t.get("v24hUSD", 0), 2),
            "score": 90 if t.get("source") == "LIVE_WS" else 50,
            "risk": "NEW" if t.get("source") == "LIVE_WS" else "VERIFIED",
            "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
        })
    return {"gems": gems, "count": len(gems), "updated": time.strftime("%H:%M:%S")}

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
