"""Execution layer: Order data structure and ExecutionEngine.

Maps trading signals to Bitget API order parameters.
Supports the demo trading PAPTRADING conventions discovered in Step 2.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .decision import Signal, SignalType
from .config import AgentConfig


@dataclass
class Order:
    """Represents a Bitget futures order ready for API submission."""
    symbol: str
    side: str               # "buy" or "sell"
    order_type: str         # "market" or "limit"
    size: str               # quantity as string
    product_type: str = "USDT-FUTURES"
    margin_coin: str = "USDT"
    margin_mode: str = "isolated"
    trade_side: str = "open"  # "open" or "close"
    price: Optional[str] = None     # for limit orders
    client_oid: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_mcp_params(self) -> dict:
        """Convert to the format expected by Bitget MCP futures_place_order.

        Returns a dict that can be JSON-serialized as the `orders` array element.
        NOTE: Bitget demo API uses side=positionSide for CLOSE orders.
              side='buy' closes long, side='sell' closes short.
        """
        params = {
            "productType": self.product_type,
            "symbol": self.symbol,
            "marginCoin": self.margin_coin,
            "side": self.side,
            "orderType": self.order_type,
            "size": self.size,
            "marginMode": self.margin_mode,
            "tradeSide": self.trade_side,
        }
        if self.price:
            params["price"] = self.price
        if self.client_oid:
            params["clientOid"] = self.client_oid
        return params

    def to_api_params(self) -> dict:
        """Convert to direct Bitget REST API parameters."""
        return {
            "productType": self.product_type,
            "symbol": self.symbol,
            "marginCoin": self.margin_coin,
            "side": self.side,
            "orderType": self.order_type,
            "size": self.size,
            "marginMode": self.margin_mode,
            "tradeSide": self.trade_side,
        }

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "size": self.size,
            "trade_side": self.trade_side,
            "margin_mode": self.margin_mode,
        }


class ExecutionEngine:
    """Converts Signals into executable Orders for Bitget API."""

    def __init__(self, config: AgentConfig):
        self.config = config

    def signal_to_order(self, signal: Signal, position_size: Optional[float] = None) -> Order:
        """Create an Order from a Signal.

        Args:
            signal: The trading signal from the decision layer.
            position_size: Override size (from risk manager). If None, uses signal.size.

        Returns:
            An Order ready for API execution.
        """
        size = position_size if position_size is not None else (signal.size or 0.001)
        size_str = f"{size:.{self.config.size_precision}f}"

        if signal.type == SignalType.ENTRY_LONG:
            return Order(
                symbol=signal.symbol, side="buy", order_type=self.config.default_order_type,
                size=size_str, trade_side="open", margin_mode=self.config.margin_mode,
                product_type=self.config.product_type, margin_coin=self.config.margin_coin,
            )

        elif signal.type == SignalType.ENTRY_SHORT:
            return Order(
                symbol=signal.symbol, side="sell", order_type=self.config.default_order_type,
                size=size_str, trade_side="open", margin_mode=self.config.margin_mode,
                product_type=self.config.product_type, margin_coin=self.config.margin_coin,
            )

        elif signal.type == SignalType.EXIT_LONG:
            # CRITICAL (Step 2 finding): side='buy' closes long in Bitget demo API
            return Order(
                symbol=signal.symbol, side="buy", order_type=self.config.default_order_type,
                size=size_str, trade_side="close", margin_mode=self.config.margin_mode,
                product_type=self.config.product_type, margin_coin=self.config.margin_coin,
            )

        elif signal.type == SignalType.EXIT_SHORT:
            # CRITICAL (Step 2 finding): side='sell' closes short in Bitget demo API
            return Order(
                symbol=signal.symbol, side="sell", order_type=self.config.default_order_type,
                size=size_str, trade_side="close", margin_mode=self.config.margin_mode,
                product_type=self.config.product_type, margin_coin=self.config.margin_coin,
            )

        else:
            raise ValueError(f"Cannot create order for signal type: {signal.type}")

    def exit_order_for_position(self, position: dict) -> Order:
        """Create a close order for an existing position.

        Uses the position's available size and holdSide to construct the correct
        close order per Bitget demo API conventions.
        """
        hold_side = position.get("holdSide", "long")
        available = position.get("available", "0.001")
        symbol = position.get("symbol", self.config.symbol)

        if hold_side == "long":
            side = "buy"   # buy closes long
        else:
            side = "sell"  # sell closes short

        return Order(
            symbol=symbol, side=side, order_type="market",
            size=str(available), trade_side="close",
            margin_mode=self.config.margin_mode,
            product_type=self.config.product_type,
            margin_coin=self.config.margin_coin,
        )

    def cancel_order_params(self, order_id: str, symbol: str) -> dict:
        """Build cancel-order API parameters."""
        return {
            "productType": self.config.product_type,
            "symbol": symbol,
            "marginCoin": self.config.margin_coin,
            "orderId": order_id,
        }
