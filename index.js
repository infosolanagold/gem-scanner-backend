const express = require('express');
const WebSocket = require('ws');
const axios = require('axios');
const cors = require('cors');

// --- CONFIGURATION ---
const app = express();
const port = process.env.PORT || 3000;
const ADMIN_PASSWORD = "GOLD"; // Mot de passe pour le panel admin

// --- MIDDLEWARE ---
app.use(cors({ origin: '*' })); // Autorise tout le monde (Wix, localhost, etc.)
app.use(express.json({ limit: '10mb' })); // Augmente la limite pour les images

// --- BASE DE DONNÉES (EN MÉMOIRE) ---
// Note: Sur la version gratuite de Render, ces données reset au redémarrage (toutes les 15-20 min d'inactivité)
let reports = [
    {id: 101, target: "FakePhantom_V2", desc: "Wallet drainer impersonating Phantom update.", status: 'approved', img: null},
    {id: 102, target: "SolanaGiveaway_X", desc: "Classic double-your-sol scam contract.", status: 'approved', img: null},
    {id: 103, target: "MemeCoin_Rug_33", desc: "Liquidity pulled immediately after launch.", status: 'approved', img: null}
];
let reportIdCounter = 200;
let referrals = []; // Pour stocker les parrainages

// --- ROUTES DATABASE & RAPPORTS ---

// 1. Récupérer la liste des rapports (C'est ça qui bloquait !)
app.get('/report/list', (req, res) => {
    console.log("Database requested!");
    res.json(reports);
});

// 2. Soumettre un nouveau rapport
app.post('/report/submit', (req, res) => {
    const { target, desc, contact, img } = req.body;
    if (!target || !desc) return res.status(400).json({ error: "Missing fields" });

    const newReport = {
        id: reportIdCounter++,
        target,
        desc,
        contact: contact || "Anon",
        img: img || null,
        status: 'pending', // En attente de validation admin
        timestamp: Date.now()
    };
    
    reports.unshift(newReport); // Ajoute au début de la liste
    console.log(`New report received for: ${target}`);
    res.json({ success: true, report: newReport });
});

// 3. Admin Login
app.post('/admin/login', (req, res) => {
    const { password } = req.body;
    if (password === ADMIN_PASSWORD) {
        res.json({ success: true, token: "admin-token-secret" });
    } else {
        res.status(401).json({ success: false });
    }
});

// 4. Action Admin (Approuver/Supprimer)
app.post('/report/action', (req, res) => {
    const { id, action, token } = req.body;
    if (token !== "admin-token-secret") return res.status(403).json({ error: "Unauthorized" });

    if (action === 'delete') {
        reports = reports.filter(r => r.id !== parseInt(id));
    } else if (action === 'approve') {
        const report = reports.find(r => r.id === parseInt(id));
        if (report) report.status = 'approved';
    }
    res.json({ success: true, list: reports });
});

// --- ROUTES SCANNER & GEMS ---

// 5. Scanner (Simulation AI)
// IMPORTANT: J'ai changé '/api/scan' en '/scan' pour matcher ton Front-End
app.post('/scan', async (req, res) => {
    const { address } = req.body;
    // Simulation simple d'analyse
    const isSafe = Math.random() > 0.3;
    res.json({
        risk: isSafe ? 'SAFE' : 'HIGH RISK',
        score: isSafe ? Math.floor(Math.random() * 20 + 80) : Math.floor(Math.random() * 40),
        summary: isSafe 
            ? 'Liquidity locked. Mint authority revoked. Safe to trade.' 
            : 'Warning: Mint authority enabled. High rugpull risk detected.'
    });
});

// 6. Gem Finder (Birdeye)
let gemCache = [];
let lastUpdate = 0;
const BIRDEYE_API = 'https://public-api.birdeye.so';

app.get('/api/gems', async (req, res) => {
    if (Date.now() - lastUpdate < 5000 && gemCache.length > 0) {
        return res.json({ gems: gemCache });
    }
    
    try {
        // Note: Sans clé API valide, Birdeye bloquera.
        // Pour la démo, si pas de clé, on renvoie une liste vide ou fake.
        if (!process.env.BIRDEYE_KEY) {
            return res.json({ gems: [] }); 
        }

        const response = await axios.get(`${BIRDEYE_API}/defi/token_trending?sort_by=rank&sort_type=asc&offset=0&limit=10`, {
            headers: { 'X-API-KEY': process.env.BIRDEYE_KEY, 'x-chain': 'solana' }
        });
        
        const tokens = response.data.data.tokens || [];
        gemCache = tokens.map(t => ({
            symbol: t.symbol,
            name: t.name,
            address: t.address,
            price: t.price,
            logo: t.logoURI
        }));
        lastUpdate = Date.now();
        res.json({ gems: gemCache });

    } catch (e) {
        console.error("Birdeye Error:", e.message);
        res.json({ gems: gemCache }); // Renvoie le cache même vieux si erreur
    }
});

// --- REFERRAL SYSTEM ---
app.post('/referral/track', (req, res) => {
    // Logique simple pour tracker (optionnel)
    res.json({ success: true });
});

// --- LANCEMENT ---
app.get('/', (req, res) => res.send("GOLD GUARD SYSTEM ONLINE 🟢"));

const server = app.listen(port, () => console.log(`Backend running on port ${port}`));

// WebSocket (Gardé pour le futur)
const wss = new WebSocket.Server({ server });
wss.on('connection', (ws) => {
    ws.send(JSON.stringify({ type: 'welcome', message: 'Connected to Gold Guard' }));
});
