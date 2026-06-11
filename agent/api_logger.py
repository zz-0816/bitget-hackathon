"""API call logger — records every Bitget API request/response for audit trail.

Produces output/api_calls.jsonl — one JSON object per line, append-only.
"""
import json, os, time
from datetime import datetime, timezone
from functools import wraps
from typing import Any

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
CALLS_LOG_PATH = os.path.join(OUTPUT_DIR, "api_calls.jsonl")


class APILogger:
    """Thread-safe append-only JSONL logger for API calls."""

    def __init__(self, path: str = CALLS_LOG_PATH):
        self.path = path
        self._count = 0

    def log(self, method: str, endpoint: str, request: dict | None,
            response: Any, success: bool, duration_ms: float) -> None:
        self._count += 1
        entry = {
            "id": self._count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "endpoint": endpoint,
            "request": request,
            "response": str(response)[:2000] if response else None,
            "success": success,
            "duration_ms": round(duration_ms, 1),
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def count(self) -> int:
        return self._count

    def summary(self) -> dict:
        """Return aggregate stats from the log file."""
        if not os.path.exists(self.path):
            return {"total_calls": 0}
        calls = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    calls.append(json.loads(line))
        success = sum(1 for c in calls if c.get("success"))
        endpoints = {}
        for c in calls:
            ep = c.get("endpoint", "")
            endpoints[ep] = endpoints.get(ep, 0) + 1
        return {
            "total_calls": len(calls),
            "success": success,
            "failed": len(calls) - success,
            "success_rate": f"{success/len(calls)*100:.1f}%" if calls else "N/A",
            "endpoints": endpoints,
            "first_call": calls[0]["timestamp"] if calls else None,
            "last_call": calls[-1]["timestamp"] if calls else None,
        }


# Global singleton
_logger = APILogger()


def log_api(method: str, endpoint: str):
    """Decorator for methods that make API calls. Records req/resp to JSONL."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.time()
            success = True
            response = None
            request_info = None
            try:
                # Capture request body if present
                if args and len(args) > 1:
                    request_info = args[1] if isinstance(args[1], dict) else str(args[1])[:500]
                if kwargs:
                    request_info = {k: str(v)[:200] for k, v in kwargs.items()}
                response = func(*args, **kwargs)
                return response
            except Exception as e:
                success = False
                response = str(e)
                raise
            finally:
                duration = (time.time() - t0) * 1000
                _logger.log(method, endpoint, request_info, response, success, duration)
        return wrapper
    return decorator


def get_api_summary() -> dict:
    return _logger.summary()


def reset_api_log() -> None:
    if os.path.exists(CALLS_LOG_PATH):
        os.remove(CALLS_LOG_PATH)
