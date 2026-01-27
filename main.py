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
CACHE_DURATION = 30 # Cache plus court pour le test

# On récupère la clé
BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")

# Liste pour stocker les tokens entrants
new_tokens = []

# --- TÂCHE DE FOND (WEBSOCKET) ---
async def websocket_listener():
    """Écoute Birdeye et capture TOUT pour le test"""
    if not BIRDEYE_KEY:
        print("❌ ERREUR FATALE : Pas de BIRDEYE_KEY trouvée !")
        return

    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    
    while True:
        try:
            print(f"🔄 Tentative de connexion WS avec clé : {BIRDEYE_KEY[:5]}...")
            async with websockets.connect(uri) as ws:
                print("✅ WS Connecté ! En attente de tokens...")
                
                # Abonnement aux nouveaux listings
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                
                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=20)
                        data = json.loads(message)
                        
                        if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                            token = data.get("data", {})
                            if token:
                                symbol = token.get('symbol', 'UNK')
                                mc = token.get('mc', 0)
                                print(f"📥 REÇU : {symbol} | MC: {mc}") # LOG IMPORTANT
                                
                                # On ajoute tout ce qui bouge pour le test
                                new_tokens.insert(0, token)
                                if len(new_tokens) > 50:
                                    new_tokens.pop()
                                    
                    except asyncio.TimeoutError:
                        # Juste un ping pour garder la connexion en vie
                        await ws.send(json.dumps({"type": "ping"}))
                        
        except Exception as e:
            print(f"❌ Erreur WS : {e}")
            await asyncio.sleep(5)

# Démarrage automatique
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(websocket_listener())

# --- API ---
@app.get("/")
def root():
    return {
        "status": "Scanner DEBUG MODE", 
        "tokens_in_memory": len(new_tokens),
        "api_key_detected": bool(BIRDEYE_KEY)
    }

@app.get("/api/gems")
def get_gems():
    # En mode test, on renvoie tout ce qu'on a reçu sans filtre strict
    gems = []
    
    print(f"🔍 Demande API reçue. Tokens en mémoire : {len(new_tokens)}")
    
    current_batch = list(new_tokens)
    
    for t in current_batch[:15]: # Prend les 15 derniers
        mc = t.get("mc", 0) or 0
        volume = t.get("v24hUSD", 0) or 0
        
        # Filtre ULTRA léger pour le test (MC > 100$)
        if mc > 100: 
            gems.append({
                "address": t.get("address", "NoCA"),
                "symbol": t.get("symbol", "???"),
                "mc": round(mc, 2),
                "volume": round(volume, 2),
                "liquidity": t.get("liquidity", 0),
                "score": 99, # Score fake pour tester l'affichage
                "risk": "TEST_MODE",
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
