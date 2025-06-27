import asyncio
import json
import logging
import websockets

# ------------------------- CONFIGURATION -------------------------

CONFIG = {
    "APP_ID": 76510,
    "TOKEN": "LDG7hjLbnbK6dRu",
    "INITIAL_STAKE": 0.35,
    "SYMBOLS": ["R_10", "R_25", "R_50", "R_75", "R_100"],
    "GRANULARITY": 1800,  # 🔁 30 minutes
    "MIN_CANDLES_REQUIRED": 5,
    "VOLUME_THRESHOLD": 0.5
}

# ------------------------- LOGGING -------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class SymbolBot:
    def __init__(self, symbol, token):
        self.symbol = symbol
        self.token = token
        self.ws = None
        self.balance = 0
        self.trade_open = False
        self.last_win_stake = CONFIG["INITIAL_STAKE"]
        self.stake = CONFIG["INITIAL_STAKE"]
        self.volume_stats = []

    async def connect(self):
        try:
            self.ws = await websockets.connect(f"wss://ws.derivws.com/websockets/v3?app_id={CONFIG['APP_ID']}")
            await self.send({"authorize": self.token})
            response = await self.recv()
            if "error" in response:
                logging.error(f"[{self.symbol}] Auth failed: {response['error'].get('message')}")
                return False
            self.balance = float(response['authorize']['balance'])
            logging.info(f"✅ [{self.symbol}] Connected | Balance: {self.balance:.2f} USD")
            return True
        except Exception as e:
            logging.error(f"[{self.symbol}] Connection error: {e}")
            return False

    async def send(self, data):
        await self.ws.send(json.dumps(data))

    async def recv(self):
        response = json.loads(await self.ws.recv())
        return response

    async def get_candles(self):
        await self.send({
            "ticks_history": self.symbol,
            "end": "latest",
            "count": 10,
            "granularity": CONFIG["GRANULARITY"],
            "style": "candles"
        })
        candles_response = await self.recv()
        candles = candles_response.get("candles", [])
        self.volume_stats = [c.get("volume", 0) for c in candles if "volume" in c]
        return candles

    def is_weak_volume(self, last_candle):
        if not self.volume_stats:
            return True
        avg_volume = sum(self.volume_stats[:-1]) / max(len(self.volume_stats[:-1]), 1)
        return last_candle['volume'] < avg_volume * CONFIG["VOLUME_THRESHOLD"]

    def analyze_signal(self, candles):
        if len(candles) < CONFIG["MIN_CANDLES_REQUIRED"]:
            return None

        body_colors = []
        for candle in candles[-5:]:
            if candle['close'] > candle['open']:
                body_colors.append("green")
            elif candle['close'] < candle['open']:
                body_colors.append("red")
            else:
                body_colors.append("doji")

        trend_color = body_colors[0]
        if all(c == trend_color for c in body_colors[:4]):
            last = body_colors[4]
            if trend_color == "green" and last == "red":
                if self.is_weak_volume(candles[-2]):
                    return "PUT"
            elif trend_color == "red" and last == "green":
                if self.is_weak_volume(candles[-2]):
                    return "CALL"
        return None

    async def execute_trade(self, signal):
        if self.trade_open:
            logging.info(f"[{self.symbol}] Trade already open, skipping...")
            return

        stake_amount = round(self.stake, 2)

        await self.send({
            "proposal": 1,
            "amount": stake_amount,
            "basis": "stake",
            "contract_type": signal,
            "currency": "USD",
            "duration": 30,  # 🔁 30 minutes
            "duration_unit": "m",
            "symbol": self.symbol
        })
        proposal_response = await self.recv()
        proposal_id = proposal_response.get("proposal", {}).get("id")
        if not proposal_id:
            logging.error(f"[{self.symbol}] Proposal failed")
            return

        await self.send({"buy": proposal_id, "price": stake_amount})
        buy_response = await self.recv()
        contract_id = buy_response.get("buy", {}).get("contract_id")
        if not contract_id:
            logging.error(f"[{self.symbol}] Buy failed")
            return

        logging.info(f"📊 [{self.symbol}] Trade sent: {signal} | Stake: ${stake_amount:.2f}")
        self.trade_open = True

        await asyncio.sleep(1805)  # 🔁 Wait 30 minutes + buffer

        max_wait = 60
        attempts = 0
        while attempts < max_wait:
            await self.send({"proposal_open_contract": 1, "contract_id": contract_id})
            result_response = await self.recv()
            contract_info = result_response.get("proposal_open_contract", {})
            if contract_info.get("status") == "sold":
                break
            await asyncio.sleep(2)
            attempts += 1
        else:
            logging.error(f"[{self.symbol}] Timed out waiting for contract to close.")
            self.trade_open = False
            return

        profit = float(contract_info.get("profit", 0))
        logging.debug(f"[{self.symbol}] Contract info received: {contract_info}")

        if profit > 0:
            logging.info(f"✅ [{self.symbol}] WIN | Profit: ${profit:.2f}")
            self.stake += profit  # Compound
        else:
            logging.info(f"❌ [{self.symbol}] LOSS | Resetting stake to initial")
            self.stake = CONFIG["INITIAL_STAKE"]

        self.trade_open = False

    async def trade_loop(self):
        while True:
            try:
                if not await self.connect():
                    await asyncio.sleep(10)
                    continue
                candles = await self.get_candles()
                signal = self.analyze_signal(candles)
                if signal:
                    await self.execute_trade(signal)
                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"[{self.symbol}] Error: {e}")
                await asyncio.sleep(10)

# ------------------------- MAIN -------------------------

async def main():
    bots = [SymbolBot(symbol, CONFIG["TOKEN"]) for symbol in CONFIG["SYMBOLS"]]
    await asyncio.gather(*(bot.trade_loop() for bot in bots))

if __name__ == "__main__":
    asyncio.run(main())
