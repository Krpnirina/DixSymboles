import json
import websocket
import time
from datetime import datetime, timedelta, timezone
from collections import deque
import threading
import os
import requests
import sys

# Configuration
APP_ID = 71130
TOKEN = "REzKac9b5BR7DmF"  # À remplacer par votre token réel
ACCOUNT_ID = "VRTC1597457"  # À remplacer par votre ID de compte

# Liste complète des 10 symboles
SYMBOLS = [
    "R_10", "R_10_1s",
    "R_25", "R_25_1s",
    "R_50", "R_50_1s",
    "R_75", "R_75_1s",
    "R_100", "R_100_1s"
]

# Configuration des timeframes adaptés
TIMEFRAMES = {
    "M1": 60,     # 1 minute (pour les symboles 1s)
    "M5": 300,    # 5 minutes
    "M15": 900    # 15 minutes
}

# Configuration spécifique par symbole
SYMBOL_CONFIG = {
    "R_10": {"stake": 1, "duration": 5, "timeframes": ["M5", "M15"]},
    "R_10_1s": {"stake": 1, "duration": 1, "timeframes": ["M1"]},
    "R_25": {"stake": 1, "duration": 5, "timeframes": ["M5", "M15"]},
    "R_25_1s": {"stake": 1, "duration": 1, "timeframes": ["M1"]},
    "R_50": {"stake": 1, "duration": 5, "timeframes": ["M5", "M15"]},
    "R_50_1s": {"stake": 1, "duration": 1, "timeframes": ["M1"]},
    "R_75": {"stake": 1, "duration": 5, "timeframes": ["M5", "M15"]},
    "R_75_1s": {"stake": 1, "duration": 1, "timeframes": ["M1"]},
    "R_100": {"stake": 1, "duration": 5, "timeframes": ["M5", "M15"]},
    "R_100_1s": {"stake": 1, "duration": 1, "timeframes": ["M1"]}
}

# Fichiers de données
POSITIONS_FILE = "positions.json"
LOG_FILE = "trading_log.txt"

# Initialisation des données
candles_data = {symbol: {tf: {} for tf in TIMEFRAMES if tf in SYMBOL_CONFIG[symbol]["timeframes"]} for symbol in SYMBOLS}
volumes = {symbol: {tf: deque(maxlen=20) for tf in TIMEFRAMES if tf in SYMBOL_CONFIG[symbol]["timeframes"]} for symbol in SYMBOLS}
TICK_COUNTER = {symbol: 0 for symbol in SYMBOLS}
LAST_ACTIVITY = time.time()
ACTIVE_POSITIONS = {}

# Initialisation du logging
def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry + "\n")

# Gestion des positions
def load_positions():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                # Initialisation des symboles manquants
                for symbol in SYMBOLS:
                    if symbol not in data:
                        data[symbol] = {
                            "active": False,
                            "stake": SYMBOL_CONFIG[symbol]["stake"],
                            "history": []
                        }
                return data
        except Exception as e:
            log_message(f"⚠️ Erreur de chargement des positions: {e}")
    
    # Positions par défaut
    return {symbol: {
        "active": False,
        "stake": SYMBOL_CONFIG[symbol]["stake"],
        "history": []
    } for symbol in SYMBOLS}

def save_positions(data):
    try:
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_message(f"⚠️ Erreur de sauvegarde des positions: {e}")

positions = load_positions()

# Fonction de conversion de timestamp
def timestamp_to_str(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

# Construction des chandeliers
def build_candles(symbol, tf_name, tick):
    try:
        tf_sec = TIMEFRAMES[tf_name]
        timestamp = tick['epoch']
        period = timestamp - (timestamp % tf_sec)
        price = tick["quote"]

        if period not in candles_data[symbol][tf_name]:
            candles_data[symbol][tf_name][period] = {
                "time": timestamp_to_str(period),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1
            }
        else:
            candle = candles_data[symbol][tf_name][period]
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
            candle["volume"] += 1
            
    except Exception as e:
        log_message(f"⚠️ Erreur de construction de chandelier ({symbol}/{tf_name}): {e}")

# Détection des signaux
def detect_signal(symbol, tf, prev_candle, curr_candle):
    try:
        # Analyse de volume
        vol = curr_candle["volume"]
        avg_vol = sum(volumes[symbol][tf])/len(volumes[symbol][tf]) if volumes[symbol][tf] else 0
        volumes[symbol][tf].append(vol)
        
        # Signaux de prix
        is_bullish = (curr_candle["close"] > curr_candle["open"] and 
                      curr_candle["open"] < prev_candle["close"] and 
                      curr_candle["close"] > prev_candle["open"])
        
        is_bearish = (curr_candle["close"] < curr_candle["open"] and 
                      curr_candle["open"] > prev_candle["close"] and 
                      curr_candle["close"] < prev_candle["open"])
        
        if vol > avg_vol * 1.5:  # Volume 50% supérieur à la moyenne
            if is_bullish:
                execute_trade(symbol, "CALL", tf)
            elif is_bearish:
                execute_trade(symbol, "PUT", tf)
                
    except Exception as e:
        log_message(f"⚠️ Erreur de détection de signal ({symbol}/{tf}): {e}")

# Exécution des trades
def execute_trade(symbol, direction, timeframe):
    pos = positions[symbol]
    if pos["active"]:
        return
        
    config = SYMBOL_CONFIG[symbol]
    stake = config["stake"]
    duration = config["duration"]
    
    try:
        contract_type = "CALL" if direction == "CALL" else "PUT"
        payload = {
            "buy": 1,
            "price": stake,
            "parameters": {
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": duration,
                "duration_unit": "m",
                "symbol": symbol
            }
        }
        
        response = requests.post(
            "https://api.deriv.com/binary/v3/buy",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if 'error' in result:
                log_message(f"❌ Échec du trade: {result['error']['message']}")
                return
                
            log_message(f"🚀 Position {direction} ouverte: {symbol} ({timeframe}) | Mise: ${stake}")
            log_message(f"📊 ID de contrat: {result.get('contract_id')}")
            
            # Mise à jour de la position
            pos["active"] = True
            pos["entry_time"] = datetime.now().isoformat()
            pos["direction"] = direction
            pos["contract_id"] = result.get('contract_id')
            pos["history"].append({
                "time": datetime.now().isoformat(),
                "direction": direction,
                "stake": stake,
                "timeframe": timeframe
            })
            save_positions(positions)
            ACTIVE_POSITIONS[symbol] = pos
            
        else:
            log_message(f"❌ Erreur API trade: {response.status_code} - {response.text}")
            
    except Exception as e:
        log_message(f"❌ Erreur d'exécution du trade: {e}")

# Analyse du marché
def analyze_market():
    while True:
        try:
            for symbol in SYMBOLS:
                for tf in SYMBOL_CONFIG[symbol]["timeframes"]:
                    cs = list(candles_data[symbol][tf].values())
                    if len(cs) < 2:
                        continue
                        
                    prev, curr = cs[-2], cs[-1]
                    detect_signal(symbol, tf, prev, curr)
            
            time.sleep(5)  # Analyse toutes les 5 secondes
        except Exception as e:
            log_message(f"⚠️ Erreur d'analyse de marché: {e}")
            time.sleep(10)

# Surveillance des positions
def monitor_positions():
    while True:
        try:
            for symbol, pos in list(ACTIVE_POSITIONS.items()):
                if not pos["active"]:
                    continue
                    
                # Vérification de l'état des positions (simplifiée)
                if "contract_id" in pos:
                    # Ici vous devriez vérifier l'état du contrat via l'API
                    # Pour la démo, on simule une fermeture après un certain temps
                    entry_time = datetime.fromisoformat(pos["entry_time"])
                    if datetime.now() > entry_time + timedelta(minutes=pos.get("duration", 5)):
                        log_message(f"🛑 Simulation de fermeture pour {symbol}")
                        pos["active"] = False
                        pos["exit_time"] = datetime.now().isoformat()
                        save_positions(positions)
                        ACTIVE_POSITIONS.pop(symbol)
            
            time.sleep(30)  # Vérification toutes les 30 secondes
            
        except Exception as e:
            log_message(f"⚠️ Erreur de surveillance des positions: {e}")
            time.sleep(60)

# Gestion du WebSocket
def on_tick(ws, message):
    global LAST_ACTIVITY
    try:
        data = json.loads(message)
        if "tick" in data:
            tick = data["tick"]
            symbol = tick["symbol"]
            TICK_COUNTER[symbol] += 1
            LAST_ACTIVITY = time.time()
            
            if TICK_COUNTER[symbol] % 100 == 0:
                log_message(f"📈 {symbol} tick #{TICK_COUNTER[symbol]} @ {tick['quote']}")
            
            for tf in SYMBOL_CONFIG[symbol]["timeframes"]:
                build_candles(symbol, tf, tick)
                
    except Exception as e:
        log_message(f"⚠️ Erreur de traitement du tick: {e}")

def on_open(ws):
    try:
        ws.send(json.dumps({"authorize": TOKEN}))
        time.sleep(1)
        for sym in SYMBOLS:
            ws.send(json.dumps({"ticks": sym, "subscribe": 1}))
        log_message(f"✅ Connecté & abonné à {len(SYMBOLS)} symboles")
        
        # Lancement des threads d'analyse
        threading.Thread(target=analyze_market, daemon=True).start()
        threading.Thread(target=monitor_positions, daemon=True).start()
        
    except Exception as e:
        log_message(f"❌ Erreur d'ouverture WebSocket: {e}")

# Fonction principale
def main():
    log_message("🚀 Lancement du bot de trading optimisé")
    log_message(f"🔧 Configuration: {len(SYMBOLS)} symboles, {len(TIMEFRAMES)} timeframes")
    log_message(f"💼 Compte: {ACCOUNT_ID}")
    
    ws_url = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_tick,
        on_error=lambda ws, e: log_message(f"❌ Erreur WebSocket: {e}"),
        on_close=lambda ws, *args: log_message("🔌 WebSocket fermé")
    )
    
    # Logique de reconnexion automatique
    while True:
        try:
            ws.run_forever()
        except Exception as e:
            log_message(f"⚠️ Crash WebSocket: {e}")
        time.sleep(5)
        log_message("♻️ Tentative de reconnexion...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_message("🛑 Bot arrêté par l'utilisateur")
    except Exception as e:
        log_message(f"💥 Erreur critique: {e}")