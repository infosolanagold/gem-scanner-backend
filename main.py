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

# --- 1. ROUE DE SECOURS (TOP VOLUME) ---
def fetch_initial_history():
    """Charge les tokens les plus actifs pour ne pas démarrer à vide"""
    print("⚡ Démarrage: Chargement du TOP VOLUME (Méthode Infaillible)...")
    # On demande les tokens par volume 24h. Impossible d'avoir une 404 ici.
    url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&offset=0&limit=20"
    headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            
            for t in items:
                # On nettoie les données
                token_clean = {
                    "address": t.get("address"),
                    "symbol": t.get("symbol", "UNK"),
                    "mc": t.get("mc", 0) or t.get("v24hUSD", 0), # Fallback
                    "v24hUSD": t.get("v24hUSD", 0),
                    "liquidity": t.get("liquidity", 0),
                    "source": "HISTORY_VOL" # On marque que c'est de l'historique
                }
                new_tokens.append(token_clean)
            print(f"✅ Historique chargé : {len(new_tokens)} tokens en mémoire.")
        else:
            print(f"⚠️ Erreur API: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ Exception API: {e}")

# --- 2. WEBSOCKET (NOUVEAUX TOKENS) ---
async def websocket_listener():
    if not BIRDEYE_KEY:
        print("❌ ERREUR : Clé manquante")
        return

    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    
    while True:
        try:
            print("🔄 Connexion WS...")
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
                                t['source'] = "LIVE_NEW"
                                print(f"💎 NOUVEAU GEM : {t.get('symbol')}")
                                new_tokens.insert(0, t) # Ajoute au début
                                if len(new_tokens) > 50: new_tokens.pop()
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"type": "ping"}))
        except Exception as e:
            print(f"❌ Erreur WS: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    fetch_initial_history()
    asyncio.create_task(websocket_listener())

# --- PAGE D'ACCUEIL (Pour voir si ça marche) ---
@app.get("/")
def root():
    return {
        "status": "ONLINE", 
        "tokens_loaded": len(new_tokens), 
        "message": "Va sur /api/gems pour voir la liste"
    }

# --- PAGE DES DONNÉES ---
@app.get("/api/gems")
def get_gems():
    gems = []
    current_list = list(new_tokens)
    
    for t in current_list[:20]:
        mc = t.get("mc", 0) or 0
        gems.append({
            "address": t.get("address", ""),
            "symbol": t.get("symbol", "???"),
            "mc": round(mc, 2),
            "volume": round(t.get("v24hUSD", 0), 2),
            "score": 85 if t.get("source") == "LIVE_NEW" else 40,
            "risk": "NEW" if t.get("source") == "LIVE_NEW" else "ESTABLISHED",
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
