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

# --- 1. FONCTION DE SECOURS (CORRIGÉE : NEW LISTINGS) ---
def fetch_initial_history():
    """Récupère les 10 derniers listings officiels pour remplir le scanner"""
    print("⚡ Démarrage: Récupération des 'New Listings'...")
    # On change l'URL pour celle des nouveaux listings, plus fiable
    url = "https://public-api.birdeye.so/defi/new_listing?limit=10"
    headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # L'API new_listing renvoie souvent une liste directe dans 'items'
            items = data.get("data", {}).get("items", [])
            
            if not items:
                print("⚠️ API REST a renvoyé une liste vide.")
                
            for t in items:
                # On formate pour que ça ressemble au WebSocket
                token_clean = {
                    "address": t.get("address"),
                    "symbol": t.get("symbol", "UNK"),
                    "mc": t.get("mc", 0) or t.get("fdv", 0), # Fallback sur FDV
                    "v24hUSD": t.get("v24hUSD", 0),
                    "liquidity": t.get("liquidity", 0),
                    "source": "HISTORY"
                }
                new_tokens.append(token_clean)
            print(f"✅ Historique chargé : {len(new_tokens)} tokens ajoutés.")
        else:
            print(f"⚠️ Erreur API REST: {resp.status_code} - {resp.text}")
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
                                t['source'] = "LIVE"
                                symbol = t.get('symbol', '???')
                                print(f"🔥 NOUVEAU TOKEN : {symbol}")
                                new_tokens.insert(0, t)
                                if len(new_tokens) > 50: new_tokens.pop()
                                
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"type": "ping"}))
                        
        except Exception as e:
            print(f"❌ Reconnexion WS dans 5s... ({e})")
            await asyncio.sleep(5)

# --- DÉMARRAGE ---
@app.on_event("startup")
async def startup_event():
    fetch_initial_history()
    asyncio.create_task(websocket_listener())

# --- API ENDPOINT ---
@app.get("/api/gems")
def get_gems():
    gems = []
    # Copie de sécurité
    current_list = list(new_tokens)
    
    for t in current_list[:20]:
        # On force l'affichage même si MC est 0 pour le test
        mc = t.get("mc", 0) or t.get("fdv", 0) or 0
        
        gems.append({
            "address": t.get("address", ""),
            "symbol": t.get("symbol", "???"),
            "mc": round(mc, 2),
            "volume": round(t.get("v24hUSD", 0), 2),
            "source": t.get("source", "UNK"),
            "score": 80 if t.get("source") == "LIVE" else 50, # Score visuel
            "risk": "NEW",
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
