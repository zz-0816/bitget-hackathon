#!/usr/bin/env python
"""Python-based MCP server for Bitget API — replaces Node.js bitget-mcp-server.

Uses DemoClient (local urllib) because Node.js on this machine can't connect
to api.bitget.com (ECONNRESET).  Python urllib works fine.

Provides the same tool interface as bitget-mcp-server so Claude Code
can use mcp__bitget__* tools without changes.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp.server.fastmcp import FastMCP
from demo_trading_test import DemoClient

# ── Init ─────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_CFG_PATH = os.path.join(PROJECT_DIR, ".mcp.json")

_client = None

def get_client() -> DemoClient:
    global _client
    if _client is None:
        with open(MCP_CFG_PATH) as f:
            cfg = json.load(f)
        env = cfg.get("mcpServers", {}).get("bitget", {}).get("env", {})
        _client = DemoClient(
            api_key=env.get("BITGET_API_KEY", ""),
            secret=env.get("BITGET_SECRET_KEY", ""),
            passphrase=env.get("BITGET_PASSPHRASE", ""),
        )
    return _client

mcp = FastMCP("bitget-python-mcp")


# ═══════════════ Account ═══════════════

@mcp.tool()
def get_account_assets(accountType: str = "all", coin: str = "", productType: str = "") -> dict:
    """Get spot/futures/funding/all account balances."""
    c = get_client()
    try:
        if accountType == "futures":
            return {"code": "00000", "data": [c.get_futures_account()]}
        if accountType == "spot":
            return {"code": "00000", "data": c.get_spot_account()}
        return {"code": "00000", "data": {"futures": [c.get_futures_account()], "spot": c.get_spot_account()}}
    except Exception as e:
        return {"code": "error", "msg": str(e)}


# ═══════════════ Futures ═══════════════

@mcp.tool()
def futures_place_order(orders: list) -> dict:
    """Place one or more futures orders with optional TP/SL. [CAUTION] Executes real trades."""
    c = get_client()
    results = []
    for order in orders:
        body = {
            "symbol": order.get("symbol", ""),
            "marginCoin": order.get("marginCoin", "USDT"),
            "productType": order.get("productType", "USDT-FUTURES"),
            "side": order.get("side", "buy"),
            "tradeSide": order.get("tradeSide", "open"),
            "orderType": order.get("orderType", "market"),
            "size": str(order.get("size", "")),
            "marginMode": order.get("marginMode", "crossed"),
        }
        if body["orderType"] == "limit" and order.get("price"):
            body["price"] = str(order["price"])
        if order.get("holdSide") and body.get("tradeSide") != "close":
            body["holdSide"] = order["holdSide"]
        if order.get("presetStopLossPrice"):
            body["presetStopLossPrice"] = str(order["presetStopLossPrice"])
        if order.get("presetTakeProfitPrice"):
            body["presetTakeProfitPrice"] = str(order["presetTakeProfitPrice"])
        try:
            results.append(c.post("/api/v2/mix/order/place-order", body))
        except Exception as e:
            results.append({"error": str(e)})
    return {"code": "00000", "data": results if len(results) > 1 else (results[0] if results else {})}


@mcp.tool()
def futures_get_positions(productType: str = "USDT-FUTURES", symbol: str = "", marginCoin: str = "") -> dict:
    """Get current or historical futures positions."""
    c = get_client()
    try:
        params = f"?productType={productType}"
        if marginCoin:
            params += f"&marginCoin={marginCoin}"
        resp = c.get(f"/api/v2/mix/position/all-position{params}")
        if symbol and resp.get("data"):
            resp["data"] = [p for p in resp["data"] if p.get("symbol") == symbol]
        return resp
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_orders(productType: str = "USDT-FUTURES", orderId: str = "", symbol: str = "",
                       status: str = "open", startTime: str = "", endTime: str = "", limit: int = 100) -> dict:
    """Query futures orders by id, open status, or history."""
    c = get_client()
    try:
        if orderId:
            return c.get(f"/api/v2/mix/order/detail?productType={productType}&orderId={orderId}")
        if status == "open":
            return c.get_orders_pending(symbol)
        params = f"?productType={productType}&symbol={symbol}&limit={limit}"
        if startTime: params += f"&startTime={startTime}"
        if endTime: params += f"&endTime={endTime}"
        return c.get(f"/api/v2/mix/order/history{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_cancel_orders(productType: str = "USDT-FUTURES", symbol: str = "",
                          orderId: str = "", orderIds: list = None, cancelAll: bool = False,
                          marginCoin: str = "") -> dict:
    """Cancel futures orders by order id, batch ids, or cancel-all mode."""
    c = get_client()
    try:
        mc = marginCoin or "USDT"
        if cancelAll:
            return c.post("/api/v2/mix/order/cancel-all-orders", {"symbol": symbol, "marginCoin": mc, "productType": productType})
        if orderId:
            return c.post("/api/v2/mix/order/cancel-order", {"symbol": symbol, "marginCoin": mc, "productType": productType, "orderId": orderId})
        if orderIds:
            results = []
            for oid in orderIds:
                results.append(c.post("/api/v2/mix/order/cancel-order", {"symbol": symbol, "marginCoin": mc, "productType": productType, "orderId": oid}))
            return {"code": "00000", "data": results}
        return {"code": "error", "msg": "Provide orderId, orderIds, or cancelAll=true"}
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_ticker(productType: str = "USDT-FUTURES", symbol: str = "") -> dict:
    """Get futures ticker for one symbol or all symbols."""
    c = get_client()
    try:
        if symbol:
            return c.get_ticker(symbol)
        return c.get(f"/api/v2/mix/market/tickers?productType={productType}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_candles(productType: str = "USDT-FUTURES", symbol: str = "",
                        granularity: str = "15min", startTime: str = "",
                        endTime: str = "", limit: int = 200, priceType: str = "trade") -> dict:
    """Get futures candles from trade/index/mark price sources."""
    c = get_client()
    try:
        df = c.get_candles(symbol, granularity, limit)
        records = df.to_dict(orient="records")
        return {"code": "00000", "data": records}
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_depth(productType: str = "USDT-FUTURES", symbol: str = "",
                      limit: int = 100, precision: str = "") -> dict:
    """Get futures orderbook depth."""
    c = get_client()
    try:
        params = f"?productType={productType}&symbol={symbol}&limit={limit}"
        if precision: params += f"&precision={precision}"
        return c.get(f"/api/v2/mix/market/depth{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_fills(productType: str = "USDT-FUTURES", symbol: str = "",
                      orderId: str = "", startTime: str = "", endTime: str = "", limit: int = 100) -> dict:
    """Get futures fills and fill history records."""
    c = get_client()
    try:
        params = f"?productType={productType}&limit={limit}"
        if symbol: params += f"&symbol={symbol}"
        if orderId: params += f"&orderId={orderId}"
        if startTime: params += f"&startTime={startTime}"
        if endTime: params += f"&endTime={endTime}"
        return c.get(f"/api/v2/mix/order/fills{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_set_leverage(productType: str = "USDT-FUTURES", symbol: str = "",
                         marginCoin: str = "USDT", leverage: str = "10", holdSide: str = "") -> dict:
    """Set futures leverage. [CAUTION] Affects risk exposure."""
    c = get_client()
    try:
        body = {"symbol": symbol, "marginCoin": marginCoin, "productType": productType, "leverage": leverage}
        if holdSide: body["holdSide"] = holdSide
        return c.post("/api/v2/mix/account/set-leverage", body)
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_update_config(productType: str = "USDT-FUTURES", symbol: str = "",
                          marginCoin: str = "USDT", setting: str = "marginMode",
                          value: str = "", holdSide: str = "") -> dict:
    """Update futures margin mode, position mode, or auto-margin setting."""
    c = get_client()
    try:
        body = {"symbol": symbol, "marginCoin": marginCoin, "productType": productType}
        if setting == "marginMode": body["marginMode"] = value
        elif setting == "positionMode": body["posMode"] = value
        elif setting == "autoMargin": body["autoMargin"] = value
        if holdSide: body["holdSide"] = holdSide
        return c.post("/api/v2/mix/account/set-margin-mode", body)
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_contracts(productType: str = "USDT-FUTURES", symbol: str = "") -> dict:
    """Get futures contract configuration details."""
    c = get_client()
    try:
        params = f"?productType={productType}"
        if symbol: params += f"&symbol={symbol}"
        return c.get(f"/api/v2/mix/market/contracts{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_open_interest(productType: str = "USDT-FUTURES", symbol: str = "") -> dict:
    """Get open interest for a futures contract."""
    c = get_client()
    try:
        return c.get(f"/api/v2/mix/market/open-interest?productType={productType}&symbol={symbol}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def futures_get_funding_rate(productType: str = "USDT-FUTURES", symbol: str = "",
                             history: bool = False, pageSize: int = 20, pageNo: int = 1) -> dict:
    """Get current or historical funding rates."""
    c = get_client()
    try:
        if history:
            return c.get(f"/api/v2/mix/market/funding-rate-history?productType={productType}&symbol={symbol}&pageSize={pageSize}&pageNo={pageNo}")
        return c.get(f"/api/v2/mix/market/funding-rate?productType={productType}&symbol={symbol}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


# ═══════════════ Spot ═══════════════

@mcp.tool()
def spot_place_order(orders: list) -> dict:
    """Place one or more spot orders. [CAUTION] Executes real trades."""
    c = get_client()
    results = []
    for order in orders:
        body = {
            "symbol": order.get("symbol", ""),
            "side": order.get("side", "buy"),
            "orderType": order.get("orderType", "market"),
            "force": order.get("force", "gtc"),
            "size": str(order.get("size", "")),
        }
        if body["orderType"] == "limit":
            body["price"] = str(order.get("price", ""))
        try:
            results.append(c.post("/api/v2/spot/trade/place-order", body))
        except Exception as e:
            results.append({"error": str(e)})
    return {"code": "00000", "data": results if len(results) > 1 else (results[0] if results else {})}


@mcp.tool()
def spot_get_orders(orderId: str = "", symbol: str = "", status: str = "open",
                    startTime: str = "", endTime: str = "", limit: int = 100) -> dict:
    """Query spot order detail, open orders, or history orders."""
    c = get_client()
    try:
        if orderId:
            return c.get(f"/api/v2/spot/trade/orderInfo?orderId={orderId}")
        if status == "open":
            return c.get(f"/api/v2/spot/trade/open-orders?symbol={symbol}")
        params = f"?symbol={symbol}&limit={limit}"
        if startTime: params += f"&startTime={startTime}"
        if endTime: params += f"&endTime={endTime}"
        return c.get(f"/api/v2/spot/trade/history{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def spot_cancel_orders(symbol: str = "", orderId: str = "",
                       orderIds: list = None, cancelAll: bool = False) -> dict:
    """Cancel one or more spot orders."""
    c = get_client()
    try:
        if cancelAll:
            return c.post("/api/v2/spot/trade/cancel-symbol-order", {"symbol": symbol})
        if orderId:
            return c.post("/api/v2/spot/trade/cancel-order", {"symbol": symbol, "orderId": orderId})
        if orderIds:
            results = []
            for oid in orderIds:
                results.append(c.post("/api/v2/spot/trade/cancel-order", {"symbol": symbol, "orderId": oid}))
            return {"code": "00000", "data": results}
        return {"code": "error", "msg": "Provide orderId, orderIds, or cancelAll=true"}
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def spot_get_ticker(symbol: str = "") -> dict:
    """Get real-time ticker data for spot trading pair(s)."""
    c = get_client()
    try:
        if symbol:
            return c.get(f"/api/v2/spot/market/ticker?symbol={symbol}")
        return c.get("/api/v2/spot/market/tickers")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def spot_get_candles(symbol: str = "", granularity: str = "15min",
                     startTime: str = "", endTime: str = "", limit: int = 200) -> dict:
    """Get K-line data for spot trading pair."""
    c = get_client()
    try:
        params = f"?symbol={symbol}&granularity={granularity}&limit={limit}"
        if startTime: params += f"&startTime={startTime}"
        if endTime: params += f"&endTime={endTime}"
        return c.get(f"/api/v2/spot/market/candles{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def spot_get_depth(symbol: str = "", type: str = "step0", limit: int = 150) -> dict:
    """Get orderbook depth for a spot trading pair."""
    c = get_client()
    try:
        return c.get(f"/api/v2/spot/market/depth?symbol={symbol}&type={type}&limit={limit}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def spot_get_fills(symbol: str = "", orderId: str = "",
                   startTime: str = "", endTime: str = "", limit: int = 100) -> dict:
    """Get spot fills for order execution details."""
    c = get_client()
    try:
        params = f"?symbol={symbol}&limit={limit}"
        if orderId: params += f"&orderId={orderId}"
        if startTime: params += f"&startTime={startTime}"
        if endTime: params += f"&endTime={endTime}"
        return c.get(f"/api/v2/spot/trade/fills{params}")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


@mcp.tool()
def spot_get_symbols(type: str = "symbols", symbol: str = "", coin: str = "") -> dict:
    """Get spot symbol info or coin chain info."""
    c = get_client()
    try:
        if type == "symbols" and symbol:
            return c.get(f"/api/v2/spot/public/symbols?symbol={symbol}")
        return c.get("/api/v2/spot/public/symbols")
    except Exception as e:
        return {"code": "error", "msg": str(e)}


# ═══════════════ System ═══════════════

@mcp.tool()
def system_get_capabilities() -> dict:
    """Return machine-readable server capabilities and module availability."""
    return {
        "readOnly": False,
        "hasAuth": True,
        "moduleAvailability": {
            "spot": {"status": "enabled"}, "futures": {"status": "enabled"},
            "account": {"status": "enabled"}, "margin": {"status": "enabled"},
            "copytrading": {"status": "enabled"}, "convert": {"status": "enabled"},
            "earn": {"status": "enabled"}, "p2p": {"status": "enabled"},
            "broker": {"status": "enabled"},
        },
        "_note": "Python MCP bridge via DemoClient — Node.js cannot reach api.bitget.com on this machine",
    }


@mcp.tool()
def transfer(fromAccountType: str = "", toAccountType: str = "",
             coin: str = "", amount: str = "", subAccountUid: str = "",
             symbol: str = "", clientOid: str = "") -> dict:
    """Transfer funds between accounts or sub-account. [CAUTION] Moves funds."""
    c = get_client()
    try:
        body = {"fromType": fromAccountType, "toType": toAccountType, "coin": coin, "amount": amount}
        if subAccountUid: body["subAccountUid"] = subAccountUid
        if symbol: body["symbol"] = symbol
        if clientOid: body["clientOid"] = clientOid
        return c.post("/api/v2/account/transfer", body)
    except Exception as e:
        return {"code": "error", "msg": str(e)}


# ═══════════════ Entry ═══════════════

if __name__ == "__main__":
    mcp.run()
