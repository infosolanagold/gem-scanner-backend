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

# --- 1. HISTORIQUE VIA DEXSCREENER (Beaucoup plus vivant) ---
def fetch_initial_history():
    """Charge des vrais tokens actifs depuis DexScreener pour remplir le tableau"""
    print("⚡ Démarrage : Récupération des tokens actifs via DexScreener...")
    
    try:
        # On cherche les paires Solana actives
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        resp = requests.get(url, timeout=5)
        
        if resp.status_code == 200:
            pairs = resp.json().get("pairs", [])
            count = 0
            
            # On prend les 20 premiers résultats pertinents
            for p in pairs:
                if p.get("chainId") == "solana" and count < 20:
                    new_tokens.append({
                        "address": p.get("baseToken", {}).get("address"),
                        "symbol": p.get("baseToken", {}).get("symbol", "UNK"),
                        "mc": p.get("fdv", 0), # MarketCap
                        "v24hUSD": p.get("volume", {}).get("h24", 0),
                        "source": "TRENDING", # Marqué comme Trending
                        "dex_link": p.get("url")
                    })
                    count += 1
            print(f"✅ DexScreener : {count} tokens chargés.")
        else:
            print("⚠️ DexScreener n'a pas répondu.")

    except Exception as e:
        print(f"⚠️ Erreur chargement DexScreener: {e}")

    # Si vraiment DexScreener plante, on met UN seul backup pour pas que ce soit vide
    if len(new_tokens) == 0:
        new_tokens.append({
            "address": "So11111111111111111111111111111111111111112", 
            "symbol": "SYSTEM_READY", 
            "mc": 0, 
            "v24hUSD": 0, 
            "source": "WAITING"
        })

# --- 2. WEBSOCKET BIRDEYE (POUR LE LIVE) ---
async def websocket_listener():
    if not BIRDEYE_KEY:
        print("❌ Clé Birdeye manquante pour le WebSocket")
        return

    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    
    while True:
        try:
            print("🔄 Connexion WebSocket...")
            async with websockets.connect(uri) as ws:
                print("✅ WS Connecté : En attente de Nouveaux Listings...")
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=20)
                        data = json.loads(msg)
                        
                        if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                            t = data.get("data", {})
                            if t:
                                # On nettoie les données entrantes
                                token_live = {
                                    "address": t.get("address"),
                                    "symbol": t.get("symbol", "NEW"),
                                    "mc": t.get("mc", 0) or t.get("fdv", 0) or 0,
                                    "v24hUSD": t.get("v24hUSD", 0),
                                    "source": "LIVE_WS", # Marqué comme NOUVEAU
                                    "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
                                }
                                print(f"💎 LIVE DETECTED: {token_live['symbol']}")
                                new_tokens.insert(0, token_live) # Ajoute tout en haut
                                if len(new_tokens) > 50: new_tokens.pop()
                                
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"type": "ping"}))
                        
        except Exception as e:
            print(f"❌ Erreur WS (Reconnexion...): {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    fetch_initial_history()
    asyncio.create_task(websocket_listener())

@app.get("/")
def root():
    return {"status": "ONLINE", "tokens_mem": len(new_tokens)}

@app.get("/api/gems")
def get_gems():
    gems = []
    # Copie pour éviter les conflits pendant la boucle
    for t in list(new_tokens)[:25]:
        
        # Calcul du score dynamique
        score = 50 # Base
        if t.get("source") == "LIVE_WS": score = 95 # Les nouveaux sont Hot
        elif t.get("source") == "TRENDING": score = 75 # Les trending sont bons
        
        # Ajustement Market Cap pour l'affichage
        mc = t.get("mc", 0)
        
        gems.append({
            "address": t.get("address", ""),
            "symbol": t.get("symbol", "???"),
            "mc": round(mc, 2),
            "volume": round(t.get("v24hUSD", 0), 2),
            "score": score,
            "risk": "NEW" if t.get("source") == "LIVE_WS" else "TRENDING",
            "dex_link": t.get("dex_link", "#")
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
