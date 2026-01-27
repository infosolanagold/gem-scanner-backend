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
CACHE_DURATION = 60

BIRDEYE_KEY = os.getenv("BIRDEYE_KEY")
if not BIRDEYE_KEY:
    print("⚠️ WARNING : BIRDEYE_KEY manquante ! L'API ne marchera pas bien.")

# Liste pour stocker new tokens du WS
new_tokens = []

# --- WEBSOCKET TASK ---
async def websocket_listener():
    """Écoute les nouveaux tokens en arrière-plan"""
    uri = f"wss://public-api.birdeye.so/socket/solana?x-api-key={BIRDEYE_KEY}"
    while True:
        try:
            print("🔄 Tentative de connexion WS Birdeye...")
            async with websockets.connect(uri) as ws:
                print("✅ WS Birdeye connecté")
                # Subscribe to new token listings
                await ws.send(json.dumps({"type": "subscribe", "event": "SUBSCRIBE_TOKEN_NEW_LISTING"}))
                
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    if data.get("type") == "SUBSCRIBE_TOKEN_NEW_LISTING":
                        token = data.get("data", {})
                        if token:
                            # On ajoute au début de la liste pour avoir les plus récents
                            new_tokens.insert(0, token)
                            # On garde seulement les 50 derniers en mémoire pour éviter de saturer
                            if len(new_tokens) > 50:
                                new_tokens.pop()
                            print(f"💎 New token via WS : {token.get('symbol', '???')}")
        except Exception as e:
            print(f"❌ WS error : {e} - Reconnexion dans 10s...")
            await asyncio.sleep(10)

# --- CORRECTION 1 : Lancer le WS au démarrage de FastAPI ---
@app.on_event("startup")
async def startup_event():
    # C'est ici qu'on crée la tache de fond, quand la loop tourne déjà
    asyncio.create_task(websocket_listener())

# --- LOGIQUE MÉTIER ---
def fetch_new_gems() -> List[Dict]:
    now = time.time()
    
    # Cache simple
    if now - cache["ts"] < CACHE_DURATION and cache["gems"]:
        return cache["gems"]

    gems = []
    
    # 1. Traitement des données WebSocket (Priorité)
    if new_tokens:
        print(f"Traitement de {len(new_tokens)} tokens du WS")
        # On ne clear pas new_tokens ici brutalement, on prend juste une copie
        # pour éviter les bugs si le WS écrit en même temps
        current_batch = list(new_tokens) 
        
        for t in current_batch[:20]:
            mc = t.get("mc", 0) or 0
            # Parfois v24hUSD n'existe pas sur un token qui a 2 secondes de vie
            volume = t.get("v24hUSD", 0) or 0
            holders = t.get("holderCount", 0) or 0
            
            # Filtres souples pour les tokens très récents
            if mc > 500: 
                score = 50  # Bonus "Fresh"
                gems.append({
                    "address": t.get("address", ""),
                    "symbol": t.get("symbol", "???"),
                    "mc": round(mc / 1000, 1),
                    "volume24h": round(volume / 1000, 1),
                    "holders": holders,
                    "score": score,
                    "risk": "new",
                    "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
                })

    # 2. Fallback API classique si pas assez de gems
    if len(gems) < 5:
        print("Appel API REST Birdeye (Fallback)")
        url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=mc&sort_type=asc&offset=0&limit=20"
        headers = {"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("items", []) or []
                for t in items:
                    mc = t.get("mc", 0)
                    if 1000 < mc < 5000000:
                        gems.append({
                            "address": t.get("address", ""),
                            "symbol": t.get("symbol", "???"),
                            "mc": round(mc / 1000, 1),
                            "score": 30, # Score basique
                            "risk": "verified",
                            "dex_link": f"https://dexscreener.com/solana/{t.get('address')}"
                        })
        except Exception as e:
            print(f"Erreur Fallback: {e}")

    # Mise à jour cache
    gems = sorted(gems, key=lambda x: x["score"], reverse=True)[:15]
    cache["gems"] = gems
    cache["ts"] = now
    return gems

@app.get("/")
def root():
    return {"status": "Gem Scanner LIVE", "ws_tokens_buffered": len(new_tokens)}

@app.get("/api/gems")
def get_gems():
    return {"gems": fetch_new_gems(), "updated": time.strftime("%H:%M:%S UTC")}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permet à ton site d'accéder à l'API
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CORRECTION 2 : Gestion du Port Dynamique ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080)) # Prend le port de Render OU 8080 par défaut
    uvicorn.run(app, host="0.0.0.0", port=port)
