import asyncio
import json
import logging
import websockets

# ------------------------- CONFIGURATION -------------------------

CONFIG = {
    "APP_ID": 71130,
    "INITIAL_STAKE": 0.35,
    "MARTINGALE_MULTIPLIER": 3,
    "GRANULARITY": 120,
    "MIN_CANDLES_REQUIRED": 5,
    "VOLUME_THRESHOLD": 0.5,
    "SYMBOLS": ["R_10", "R_25", "R_50", "R_75", "R_100"]
}

# ------------------------- ACCOUNTS CONFIG -------------------------

ACCOUNTS = [
    {"token": "LDG7hjLbnbK6dRu", "role": "master"},
    {"token": "TOKEN_FOLLOWER1", "role": "follower"},
    {"token": "TOKEN_FOLLOWER2", "role": "follower"},
    # Afaka manampy comptes vaovao eto
    # {"token": "TOKEN_FOLLOWER_X", "role": "follower"},
]

# ------------------------- LOGGING -------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ------------------------- SINGLE ACCOUNT BOT -------------------------

class SymbolSingleAccount:
    def __init__(self, symbol, token):
        self.symbol = symbol
        self.token = token
        self.ws = None
        self.balance = 0

    async def connect(self):
        try:
            self.ws = await websockets.connect(
                f"wss://ws.derivws.com/websockets/v3?app_id={CONFIG['APP_ID']}"
            )
            await self.send({"authorize": self.token})
            response = await self.recv()
            if "error" in response:
                logging.error(f"[{self.symbol}] Auth failed: {response['error'].get('message')} | Token: {self.token[:5]}...")
                return False
            self.balance = float(response['authorize']['balance'])
            logging.info(f"✅ [{self.symbol}] Connected | Balance: {self.balance:.2f} USD | Token: {self.token[:5]}...")
            return True
        except Exception as e:
            logging.error(f"[{self.symbol}] Connection error: {e}")
            return False

    async def send(self, data):
        await self.ws.send(json.dumps(data))

    async def recv(self):
        response = json.loads(await self.ws.recv())
        return response

    async def execute_trade(self, signal, stake_amount):
        try:
            await self.send({
                "proposal": 1,
                "amount": round(stake_amount, 2),
                "basis": "stake",
                "contract_type": signal,
                "currency": "USD",
                "duration": 2,
                "duration_unit": "m",
                "symbol": self.symbol
            })
            proposal_response = await self.recv()
            proposal_id = proposal_response.get("proposal", {}).get("id")
            if not proposal_id:
                logging.error(f"[{self.symbol}] Proposal failed | Token: {self.token[:5]}...")
                return

            await self.send({"buy": proposal_id, "price": round(stake_amount, 2)})
            buy_response = await self.recv()
            contract_id = buy_response.get("buy", {}).get("contract_id")
            if not contract_id:
                logging.error(f"[{self.symbol}] Buy failed | Token: {self.token[:5]}...")
                return

            logging.info(f"📊 [{self.symbol}] Trade sent on {self.token[:5]}... | Signal: {signal} | Stake: ${stake_amount:.2f}")

            # Wait contract result
            await asyncio.sleep(125)

            await self.send({"proposal_open_contract": 1, "contract_id": contract_id})
            result_response = await self.recv()
            contract_info = result_response.get("proposal_open_contract", {})
            profit = float(contract_info.get("profit", 0))

            if profit > 0:
                logging.info(f"✅ [{self.symbol}] WIN on {self.token[:5]}... | Profit: ${profit:.2f}")
            else:
                logging.info(f"❌ [{self.symbol}] LOSS on {self.token[:5]}... | Loss: ${abs(profit):.2f}")
        except Exception as e:
            logging.error(f"[{self.symbol}] Trade execution error: {e}")

    async def close(self):
        if self.ws:
            await self.ws.close()


# ------------------------- MASTER BOT -------------------------

class MasterBot(SymbolSingleAccount):
    def __init__(self, symbol, token):
        super().__init__(symbol, token)
        self.martingale_step = 0
        self.stake_active = CONFIG["INITIAL_STAKE"]

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
        return candles

    def analyze_signal(self, candles):
        if len(candles) < CONFIG["MIN_CANDLES_REQUIRED"]:
            logging.info(f"[{self.symbol}] Not enough candles.")
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
                return "PUT"
            elif trend_color == "red" and last == "green":
                return "CALL"

        logging.info(f"[{self.symbol}] No valid pattern found.")
        return None

    async def execute_trade(self, signal, stake_amount=None):
        if stake_amount is None:
            stake_amount = self.stake_active
        else:
            self.stake_active = stake_amount

        try:
            await self.send({
                "proposal": 1,
                "amount": round(stake_amount, 2),
                "basis": "stake",
                "contract_type": signal,
                "currency": "USD",
                "duration": 2,
                "duration_unit": "m",
                "symbol": self.symbol
            })
            proposal_response = await self.recv()
            proposal_id = proposal_response.get("proposal", {}).get("id")
            if not proposal_id:
                logging.error(f"[{self.symbol}] Proposal failed | Token: {self.token[:5]}...")
                return False

            await self.send({"buy": proposal_id, "price": round(stake_amount, 2)})
            buy_response = await self.recv()
            contract_id = buy_response.get("buy", {}).get("contract_id")
            if not contract_id:
                logging.error(f"[{self.symbol}] Buy failed | Token: {self.token[:5]}...")
                return False

            logging.info(f"📊 [{self.symbol}] Trade sent on {self.token[:5]}... | Signal: {signal} | Stake: ${stake_amount:.2f}")

            # Wait contract result
            await asyncio.sleep(125)

            await self.send({"proposal_open_contract": 1, "contract_id": contract_id})
            result_response = await self.recv()
            contract_info = result_response.get("proposal_open_contract", {})
            profit = float(contract_info.get("profit", 0))

            if profit > 0:
                logging.info(f"✅ [{self.symbol}] WIN on {self.token[:5]}... | Profit: ${profit:.2f}")
                self.martingale_step = 0
                self.stake_active = CONFIG["INITIAL_STAKE"]
                return True
            else:
                logging.info(f"❌ [{self.symbol}] LOSS on {self.token[:5]}... | Loss: ${abs(profit):.2f}")
                self.martingale_step += 1
                self.stake_active *= CONFIG["MARTINGALE_MULTIPLIER"]
                return False
        except Exception as e:
            logging.error(f"[{self.symbol}] Trade execution error: {e}")
            return False


# ------------------------- MULTI-ACCOUNT MANAGER -------------------------

class MultiAccountBot:
    def __init__(self, accounts, symbol):
        self.symbol = symbol
        self.master_account = None
        self.followers = []
        for acc in accounts:
            if acc["role"] == "master":
                self.master_account = MasterBot(symbol, acc["token"])
            else:
                self.followers.append(SymbolSingleAccount(symbol, acc["token"]))

    async def run(self):
        while True:
            if not await self.master_account.connect():
                await asyncio.sleep(5)
                continue

            candles = await self.master_account.get_candles()
            signal = self.master_account.analyze_signal(candles)
            if signal:
                result = await self.master_account.execute_trade(signal)

                # Execute trade on all followers
                for follower in self.followers:
                    if await follower.connect():
                        await follower.execute_trade(signal, self.master_account.stake_active)
                        await follower.close()

            await self.master_account.close()
            await asyncio.sleep(5)


# ------------------------- MAIN -------------------------

async def main():
    bots = []
    for symbol in CONFIG["SYMBOLS"]:
        bot = MultiAccountBot(ACCOUNTS, symbol)
        bots.append(bot.run())

    await asyncio.gather(*bots)

if __name__ == "__main__":
    asyncio.run(main())
