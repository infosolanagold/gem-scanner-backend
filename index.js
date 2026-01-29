const express = require('express');
const WebSocket = require('ws');
const axios = require('axios');
const { Connection, PublicKey } = require('@solana/web3.js');
const cors = require('cors');

// Config
const app = express();
const port = process.env.PORT || 3000;
const BIRDEYE_API = 'https://public-api.birdeye.so'; 
const SOLANA_RPC = 'https://api.mainnet-beta.solana.com';

// Autoriser ton site web (CORS)
app.use(cors({ origin: '*' })); 

// Cache simple pour optimiser
let gemCache = [];
let lastUpdate = 0;

// Fetch gems from Birdeye
async function fetchGems() {
  if (Date.now() - lastUpdate < 5000) return gemCache; 
  try {
    const res = await axios.get(`${BIRDEYE_API}/defi/token_trending?sort_by=rank&sort_type=asc&offset=0&limit=20`, {
      headers: { 
        'X-API-KEY': process.env.BIRDEYE_KEY || '', // Ta clé sera dans Render
        'x-chain': 'solana'
      } 
    });
    
    // Adaptation au format de réponse Birdeye
    const tokens = res.data.data.tokens || [];
    gemCache = tokens.map(token => ({
      symbol: token.symbol,
      address: token.address,
      name: token.name,
      logo: token.logoURI, 
      mc: token.liquidity, 
      volume: token.volume24hUSD,
      score: calculateAIScore(token),
      source: "TRENDING"
    }));
    
    lastUpdate = Date.now();
    return gemCache;
  } catch (e) {
    console.error('Birdeye Error:', e.message);
    return gemCache; 
  }
}

// AI Scoring simple
function calculateAIScore(token) {
  let score = 50;
  if (token.liquidity > 10000) score += 20; 
  if (token.volume24hUSD > 50000) score += 20;
  if (token.rank < 10) score += 10;
  return Math.min(100, score);
}

// Routes API
app.use(express.json());

app.get('/', (req, res) => {
    res.send("Solana Gold Backend is Running 🚀");
});

app.get('/api/gems', async (req, res) => {
  const gems = await fetchGems();
  res.json({ gems: gems, count: gems.length });
});

app.post('/api/scan', async (req, res) => {
  res.json({ risk: 'LOW', score: 85, summary: 'Scan simulation OK' });
});

// Lancement du serveur
const server = app.listen(port, () => console.log(`Backend running on port ${port}`));

// WebSocket
const wss = new WebSocket.Server({ server });
wss.on('connection', (ws) => {
    console.log('Client connected');
    ws.send(JSON.stringify({ type: 'welcome', message: 'Connected to Gold Guard' }));
});
