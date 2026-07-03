"""
xtb_api.py — XTB xAPI client (official WebSocket API)

Direct order execution with atomic SL/TP — replaces browser automation.

CLI usage:
    python xtb_api.py price US100
    python xtb_api.py positions
    python xtb_api.py balance
    python xtb_api.py open LONG 0.2 --sl-pts 61 --tp-pts 134
    python xtb_api.py open SHORT 0.2 --sl-pts 61 --tp-pts 134
    python xtb_api.py close <order_id>
    python xtb_api.py close-all
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import websocket
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

WS_URL = "wss://ws.xapi.pro/demo"
SYMBOL_DEFAULT = "US100"

CMD_BUY = 0
CMD_SELL = 1
TYPE_OPEN = 0
TYPE_CLOSE = 2


class XTBError(Exception):
    pass


class XTBClient:
    def __init__(self):
        self.ws = websocket.create_connection(WS_URL, timeout=15)
        self._login()

    def _call(self, command: str, arguments: dict | None = None) -> dict:
        payload = {"command": command}
        if arguments:
            payload["arguments"] = arguments
        self.ws.send(json.dumps(payload))
        resp = json.loads(self.ws.recv())
        if not resp.get("status"):
            raise XTBError(f"{command} failed: {resp.get('errorCode')} {resp.get('errorDescr')}")
        return resp

    def _login(self):
        user = os.environ["XTB_ACCOUNT_ID"]
        pwd = os.environ["XTB_PASSWORD"]
        self._call("login", {"userId": user, "password": pwd})

    def price(self, symbol: str = SYMBOL_DEFAULT) -> dict:
        r = self._call("getSymbol", {"symbol": symbol})["returnData"]
        return {"symbol": symbol, "bid": r["bid"], "ask": r["ask"], "spread": round(r["ask"] - r["bid"], 2)}

    def balance(self) -> dict:
        r = self._call("getMarginLevel")["returnData"]
        return {"balance": r["balance"], "equity": r["equity"], "margin": r["margin"]}

    def positions(self) -> list[dict]:
        r = self._call("getTrades", {"openedOnly": True})["returnData"]
        return [
            {
                "order": t["order"],
                "symbol": t["symbol"],
                "side": "LONG" if t["cmd"] == CMD_BUY else "SHORT",
                "volume": t["volume"],
                "open_price": t["open_price"],
                "sl": t["sl"],
                "tp": t["tp"],
                "profit": t["profit"],
            }
            for t in r
        ]

    def open_trade(self, side: str, volume: float, sl_pts: float, tp_pts: float,
                   symbol: str = SYMBOL_DEFAULT) -> dict:
        q = self.price(symbol)
        if side.upper() == "LONG":
            cmd, ref = CMD_BUY, q["ask"]
            sl, tp = round(ref - sl_pts, 1), round(ref + tp_pts, 1)
        else:
            cmd, ref = CMD_SELL, q["bid"]
            sl, tp = round(ref + sl_pts, 1), round(ref - tp_pts, 1)

        info = {
            "cmd": cmd, "type": TYPE_OPEN, "symbol": symbol,
            "volume": volume, "price": ref, "sl": sl, "tp": tp,
            "offset": 0, "expiration": 0, "order": 0, "customComment": "claude-xapi",
        }
        r = self._call("tradeTransaction", {"tradeTransInfo": info})["returnData"]
        status = self._await_order(r["order"])
        return {"side": side.upper(), "volume": volume, "requested": ref, "sl": sl, "tp": tp, **status}

    def close_trade(self, order_id: int) -> dict:
        pos = next((p for p in self.positions() if p["order"] == order_id), None)
        if pos is None:
            raise XTBError(f"position {order_id} not found")
        q = self.price(pos["symbol"])
        price = q["bid"] if pos["side"] == "LONG" else q["ask"]
        info = {
            "cmd": CMD_BUY if pos["side"] == "SHORT" else CMD_SELL,
            "type": TYPE_CLOSE, "symbol": pos["symbol"], "volume": pos["volume"],
            "price": price, "order": order_id,
            "sl": 0, "tp": 0, "offset": 0, "expiration": 0, "customComment": "claude-xapi-close",
        }
        r = self._call("tradeTransaction", {"tradeTransInfo": info})["returnData"]
        return self._await_order(r["order"])

    def _await_order(self, order_id: int, timeout: float = 10.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self._call("tradeTransactionStatus", {"order": order_id})["returnData"]
            # requestStatus: 0=ERROR 1=PENDING 3=ACCEPTED 4=REJECTED
            if r["requestStatus"] == 3:
                return {"order": order_id, "status": "ACCEPTED", "price": r.get("price")}
            if r["requestStatus"] in (0, 4):
                raise XTBError(f"order {order_id} rejected: {r.get('message')}")
            time.sleep(0.3)
        raise XTBError(f"order {order_id} status timeout")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser(description="XTB xAPI CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("price"); sp.add_argument("symbol", nargs="?", default=SYMBOL_DEFAULT)
    sub.add_parser("positions")
    sub.add_parser("balance")

    so = sub.add_parser("open")
    so.add_argument("side", choices=["LONG", "SHORT", "long", "short"])
    so.add_argument("volume", type=float)
    so.add_argument("--sl-pts", type=float, required=True)
    so.add_argument("--tp-pts", type=float, required=True)
    so.add_argument("--symbol", default=SYMBOL_DEFAULT)

    sc = sub.add_parser("close"); sc.add_argument("order_id", type=int)
    sub.add_parser("close-all")

    args = p.parse_args()
    client = XTBClient()
    try:
        if args.cmd == "price":
            out = client.price(args.symbol)
        elif args.cmd == "positions":
            out = client.positions()
        elif args.cmd == "balance":
            out = client.balance()
        elif args.cmd == "open":
            out = client.open_trade(args.side, args.volume, args.sl_pts, args.tp_pts, args.symbol)
        elif args.cmd == "close":
            out = client.close_trade(args.order_id)
        elif args.cmd == "close-all":
            out = [client.close_trade(t["order"]) for t in client.positions()]
        print(json.dumps(out, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
