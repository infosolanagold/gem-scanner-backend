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
cache: Dict = {"gems": [], "ts": 0}
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")

# Liste pour stocker les tokens
new_tokens = []

# --- 1. FONCTION DE SECOURS (API REST) ---
def fetch_initial_history():
    """Va chercher les tokens récents via API HTTP si le WebSocket est lent"""
    print("⚡ Démarrage: Récupération de l'historique via API REST...")
    url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&offset=0&limit=20"
    headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            count = 0
            for t in items:
                # On convertit le format API REST au format WebSocket pour uniformiser
                token_clean = {
                    "address": t.get("address"),
                    "symbol": t.get("symbol", "UNK"),
                    "mc": t.get("mc", 0),
                    "v24hUSD": t.get("v24hUSD", 0),
                    "liquidity": t.get("liquidity", 0),
                    "source": "REST_API" # Marqueur pour savoir d'où ça vient
                }
                new_tokens.append(token_clean)
                count += 1
            print(f"✅ Historique chargé : {count} tokens ajoutés.")
        else:
            print(f"⚠️ Erreur API REST: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ Exception API REST: {e}")

# --- 2. TÂCHE DE FOND (WEBSOCKET) ---
async def websocket_listener():
    """Écoute les NOUVEAUX tokens en temps réel"""
    if not BIRDEYE_KEY:
        print("❌ ERREUR : Pas de clé API !")
        return

    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    
    while True:
        try:
            print("🔄 Connexion WebSocket...")
            async with websockets.connect(uri) as ws:
                print("✅ WebSocket Connecté (Mode Live)")
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=20)
                        data = json.loads(msg)
                        
                        if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                            t = data.get("data", {})
                            if t:
                                t['source'] = "LIVE_WS" # Marqueur Live
                                print(f"🔥 NOUVEAU TOKEN LIVE : {t.get('symbol')}")
                                new_tokens.insert(0, t) # Ajoute tout en haut
                                if len(new_tokens) > 50: new_tokens.pop()
                                
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"type": "ping"}))
                        
        except Exception as e:
            print(f"❌ Reconnexion WS dans 5s... ({e})")
            await asyncio.sleep(5)

# --- DÉMARRAGE ---
@app.on_event("startup")
async def startup_event():
    # 1. On lance l'API REST tout de suite pour remplir la liste
    fetch_initial_history()
    # 2. On lance le WebSocket pour la suite
    asyncio.create_task(websocket_listener())

# --- API ENDPOINT ---
@app.get("/api/gems")
def get_gems():
    gems = []
    # On prend une copie de la liste pour éviter les conflits
    current_list = list(new_tokens)
    
    for t in current_list[:20]: # Top 20
        # FILTRES (On garde les filtres souples pour le test)
        mc = t.get("mc", 0) or 0
        
        # On accepte tout ce qui a un MC > 0 pour le test
        if mc >= 0: 
            gems.append({
                "address": t.get("address", ""),
                "symbol": t.get("symbol", "???"),
                "mc": round(mc, 2),
                "volume": round(t.get("v24hUSD", 0), 2),
                "source": t.get("source", "UNK"),
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
