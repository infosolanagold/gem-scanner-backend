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

# --- 1. FONCTION INTELLIGENTE (Tente tout pour avoir des données) ---
def fetch_initial_history():
    print("⚡ Démarrage : Recherche de données initiales...")
    
    headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana", "accept": "application/json"}
    found_data = False

    # TENTATIVE A : Les Nouveaux Listings (V2 - La route correcte)
    try:
        print("👉 Essai 1 : New Listings V2...")
        # La route V2 officielle qui remplace l'ancienne qui faisait 404
        url_new = "https://public-api.birdeye.so/defi/v2/tokens/new_listing?limit=10"
        resp = requests.get(url_new, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            if items:
                for t in items:
                    new_tokens.append({
                        "address": t.get("address"),
                        "symbol": t.get("symbol", "New"),
                        "mc": t.get("mc", 0) or t.get("liquidity", 0),
                        "v24hUSD": t.get("v24hUSD", 0),
                        "source": "NEW_V2"
                    })
                print(f"✅ SUCCÈS : {len(items)} nouveaux listings chargés.")
                found_data = True
    except Exception as e:
        print(f"⚠️ Échec New Listings: {e}")

    # TENTATIVE B : Les Tokens Trending (Si le A est vide ou plante)
    if not found_data:
        try:
            print("👉 Essai 2 : Trending Tokens...")
            # Endpoint très stable qui renvoie toujours du monde
            url_trend = "https://public-api.birdeye.so/defi/token_trending?sort_by=rank&sort_type=asc&offset=0&limit=10"
            resp = requests.get(url_trend, headers=headers, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("tokens", [])
                if items:
                    for t in items:
                        new_tokens.append({
                            "address": t.get("address"),
                            "symbol": t.get("symbol", "HOT"), # Parfois trending n'a pas le symbole, on met HOT
                            "mc": t.get("liquidity", 0) * 10, # Estimation grossière MC via Liquidity si manquant
                            "v24hUSD": t.get("volume24hUSD", 0),
                            "source": "TRENDING"
                        })
                    print(f"✅ SUCCÈS : {len(items)} tokens trending chargés.")
                    found_data = True
        except Exception as e:
            print(f"⚠️ Échec Trending: {e}")

    # TENTATIVE C : Le Filet de Sécurité (Backups)
    if not found_data or len(new_tokens) == 0:
        print("🚨 ECHEC TOTAL API -> Injection Backup Manuelle")
        backups = [
            {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL", "mc": 70000000000, "v24hUSD": 2000000000},
            {"address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "symbol": "JUP", "mc": 1200000000, "v24hUSD": 50000000},
            {"address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK", "mc": 1500000000, "v24hUSD": 80000000}
        ]
        for b in backups:
            b["source"] = "BACKUP"
            new_tokens.append(b)

# --- 2. WEBSOCKET (Reste inchangé car il marchait bien) ---
async def websocket_listener():
    if not BIRDEYE_KEY: return
    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("✅ WS Connecté (Mode Live)")
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
    # On protège la lecture de la liste
    current_list = list(new_tokens)
    
    for t in current_list[:20]:
        mc = t.get("mc", 0) or 0
        gems.append({
            "address": t.get("address", ""),
            "symbol": t.get("symbol", "???"),
            "mc": round(mc, 2),
            "volume": round(t.get("v24hUSD", 0), 2),
            "score": 95 if t.get("source") == "LIVE_WS" else 60,
            "risk": "NEW" if t.get("source") == "LIVE_WS" else "TRUSTED",
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
