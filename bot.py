import asyncio
import json
import logging
import websockets

# ------------------------- CONFIGURATION -------------------------

CONFIG = {
    "APP_ID": 71130,
    "TOKEN": "REzKac9b5BR7DmF",
    "INITIAL_STAKE": 0.35,
    "MARTINGALE_MULTIPLIER": 2.05,
    "SYMBOLS": ["R_10", "R_25", "R_50", "R_75", "R_100"],
    "GRANULARITY": 60,
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
        self.martingale_step = 0
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
                    # Mifamadika: PUT no tokony ho CALL
                    return "CALL"
            elif trend_color == "red" and last == "green":
                if self.is_weak_volume(candles[-2]):
                    # Mifamadika: CALL no tokony ho PUT
                    return "PUT"
        return None

    async def execute_trade(self, signal):
        if self.trade_open:
            logging.info(f"[{self.symbol}] Trade already open, skipping...")
            return

        stake_amount = CONFIG["INITIAL_STAKE"] * (CONFIG["MARTINGALE_MULTIPLIER"] ** self.martingale_step)

        await self.send({
            "proposal": 1,
            "amount": round(stake_amount, 2),
            "basis": "stake",
            "contract_type": signal,
            "currency": "USD",
            "duration": 10,
            "duration_unit": "m",
            "symbol": self.symbol
        })
        proposal_response = await self.recv()
        proposal_id = proposal_response.get("proposal", {}).get("id")
        if not proposal_id:
            logging.error(f"[{self.symbol}] Proposal failed")
            return

        await self.send({"buy": proposal_id, "price": round(stake_amount, 2)})
        buy_response = await self.recv()
        contract_id = buy_response.get("buy", {}).get("contract_id")
        if not contract_id:
            logging.error(f"[{self.symbol}] Buy failed")
            return

        logging.info(f"📊 [{self.symbol}] Trade sent: {signal} | Stake: ${stake_amount:.2f} | Martingale step: {self.martingale_step}")
        self.trade_open = True

        # Attendre la fin du contrat (3 minutes + buffer)
        await asyncio.sleep(185)

        await self.send({"proposal_open_contract": 1, "contract_id": contract_id})
        result_response = await self.recv()
        contract_info = result_response.get("proposal_open_contract", {})
        profit = float(contract_info.get("profit", 0))

        if profit > 0:
            logging.info(f"✅ [{self.symbol}] WIN | Profit: ${profit:.2f}")
            self.martingale_step = 0
        else:
            logging.info(f"❌ [{self.symbol}] LOSS | Martingale up")
            self.martingale_step += 1

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
                await self.ws.close()
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
