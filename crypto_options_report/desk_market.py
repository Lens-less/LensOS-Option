"""Bounded public Deribit discovery and exact-leg reads for the decision desk.

Discovery retains the complete BTC/ETH option registry and summary universe.
Only explicitly identified linear USDC instruments can become desk candidates;
summaries never substitute for fresh, two-sided exchange book observations.
No account, order, trust-promotion or historical-model capabilities live here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from ._http import json_getter
from .market_data import ALLOWED_DERIBIT_BASE_URLS, DEFAULT_DERIBIT_BASE_URL

SCHEMA_VERSION = "desk_market.v1"
ASSETS = frozenset({"BTC", "ETH"})
PARTITIONS = ("BTC", "ETH", "USDC")
FRESHNESS_SECONDS = 60
DISCOVERY_CACHE_SECONDS = 15
REGISTRY_CACHE_SECONDS = 60
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_EXACT_LEGS = 120
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_get_json = json_getter(max_bytes=MAX_RESPONSE_BYTES, description="Deribit desk response")


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if isfinite(result) else None


def _positive(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _integer(value: Any) -> int | None:
    number = _positive(value)
    return int(number) if number is not None and number.is_integer() else None


def _exchange_time(value: Any) -> tuple[int | None, str | None]:
    timestamp = _integer(value)
    try:
        return timestamp, _stamp(datetime.fromtimestamp(timestamp / 1000, UTC)) if timestamp else None
    except (ValueError, OverflowError, OSError):
        return None, None


class _Pacer:
    """Shared process-wide two-request-per-second ceiling for desk collectors."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_request = 0.0

    def wait(self, deadline: float, clock: Callable[[], float], sleep: Callable[[float], None], *, interval: float = 0.5) -> None:
        with self.lock:
            now = clock()
            delay = max(0.0, self.next_request - now)
            if now + delay >= deadline:
                raise ValueError("COLLECTION_DEADLINE: retry with fewer candidate legs")
            if delay:
                sleep(delay)
            self.next_request = clock() + interval


_PUBLIC_PACER = _Pacer()


class DeskMarketCollector:
    """Single-flight, finite-cache collector with a shared discovery/deepening deadline.

    Injectable clocks and transport support fixture-only tests. The default
    transport retains the existing public host and no-redirect boundaries.
    Returned dictionaries are detached copies; callers cannot mutate caches.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_DERIBIT_BASE_URL,
        transport: Callable[[str, Mapping[str, Any], int], dict[str, Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        deadline_seconds: float = 60,
        pacer: _Pacer | None = None,
    ) -> None:
        if base_url not in ALLOWED_DERIBIT_BASE_URLS:
            raise ValueError("desk source must be an approved Deribit public host")
        if not 0 < deadline_seconds <= 60:
            raise ValueError("desk collection deadline must be between zero and 60 seconds")
        self.base_url = base_url
        self.transport = transport or _get_json
        self.clock, self.sleep = clock, sleep
        self.now = now or (lambda: datetime.now(UTC))
        self.deadline_seconds = deadline_seconds
        self.pacer = pacer or _PUBLIC_PACER
        self._lock = threading.RLock()
        self._registry: tuple[float, dict[str, dict[str, Any]], list[dict[str, Any]]] | None = None
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._cache_until = 0.0
        self._deadlines: dict[str, float] = {}

    def _request(self, endpoint: str, params: Mapping[str, Any], deadline: float) -> Any:
        for attempt in range(3):
            # The instrument registry has its own stricter sustained limit.
            self.pacer.wait(deadline, self.clock, self.sleep, interval=1.0 if endpoint == "get_instruments" else 0.5)
            remaining = deadline - self.clock()
            if remaining < 1:
                raise ValueError("COLLECTION_DEADLINE: refresh the public snapshot")
            try:
                payload = self.transport(f"{self.base_url}/api/v2/public/{endpoint}", params, min(10, max(1, int(remaining))))
                if not isinstance(payload, dict):
                    raise ValueError("INVALID_RESPONSE: expected a JSON-RPC object")
                error = payload.get("error")
                if error:
                    code = error.get("code") if isinstance(error, dict) else None
                    raise ValueError(f"UPSTREAM_ERROR:{code}: {error}")
                if "result" not in payload:
                    raise ValueError("INVALID_RESPONSE: JSON-RPC result is missing")
                if self.clock() >= deadline:
                    raise ValueError("COLLECTION_DEADLINE: public response arrived too late")
                return payload["result"]
            except (ValueError, OSError) as exc:
                message = str(exc)
                retryable = "10028" in message or "http 429" in message
                backoff = 1.0 * (2**attempt)
                if not retryable or attempt == 2 or self.clock() + backoff >= deadline:
                    raise
                self.sleep(backoff)
        raise ValueError("COLLECTION_DEADLINE")  # pragma: no cover

    @staticmethod
    def _failure(endpoint: str, scope: str, exc: Exception) -> dict[str, Any]:
        message = str(exc)
        code = "RATE_LIMITED" if "10028" in message or "http 429" in message else "PUBLIC_DATA_UNAVAILABLE"
        if "COLLECTION_DEADLINE" in message:
            code = "COLLECTION_DEADLINE"
        return {"code": code, "endpoint": f"public/{endpoint}", "scope": scope, "message": message[:400]}

    def _registry_rows(self, deadline: float) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        if self._registry is not None and self.clock() < self._registry[0]:
            return copy.deepcopy(self._registry[1]), copy.deepcopy(self._registry[2])
        rows: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, Any]] = []
        for currency in PARTITIONS:
            try:
                result = self._request("get_instruments", {"currency": currency, "kind": "option", "expired": "false"}, deadline)
                if not isinstance(result, list):
                    raise ValueError("INVALID_RESPONSE: instrument registry must be a list")
                for raw in result:
                    if not isinstance(raw, dict) or not isinstance(raw.get("instrument_name"), str):
                        raise ValueError("INVALID_RESPONSE: instrument registry contains an invalid row")
                    if raw.get("base_currency") in ASSETS:
                        name = raw["instrument_name"]
                        previous = rows.get(name)
                        if previous is not None and previous != raw:
                            raise ValueError(f"REGISTRY_CONFLICT: inconsistent metadata for {name}")
                        rows[name] = raw
            except (ValueError, OSError, TypeError) as exc:
                failures.append(self._failure("get_instruments", currency, exc))
        # Failed partitions are retried on the next refresh, never cached as a complete registry.
        if not failures:
            self._registry = (self.clock() + REGISTRY_CACHE_SECONDS, copy.deepcopy(rows), [])
        return rows, failures

    def fetch_snapshot(self, asset: str, *, force: bool = False) -> dict[str, Any]:
        asset = self._asset(asset)
        with self._lock:
            if not force and self.clock() < self._cache_until and asset in self._snapshots:
                return copy.deepcopy(self._snapshots[asset])
            started = self.now()
            deadline = self.clock() + self.deadline_seconds
            registry, failures = self._registry_rows(deadline)
            summaries: dict[str, dict[str, Any]] = {}
            for currency in PARTITIONS:
                try:
                    result = self._request("get_book_summary_by_currency", {"currency": currency, "kind": "option"}, deadline)
                    if not isinstance(result, list):
                        raise ValueError("INVALID_RESPONSE: book summaries must be a list")
                    observed = _stamp(self.now())
                    for raw in result:
                        if not isinstance(raw, dict) or not isinstance(raw.get("instrument_name"), str):
                            raise ValueError("INVALID_RESPONSE: book summary contains an invalid row")
                        name = raw["instrument_name"]
                        # Preserve unmatched target summaries too. A newly listed
                        # name can appear between the registry and summary reads;
                        # its missing metadata must remain visible, never guessed.
                        if name in registry or name.startswith(("BTC-", "BTC_USDC-", "ETH-", "ETH_USDC-")):
                            value = self._summary(raw, observed)
                            prior = summaries.get(name)
                            if prior is None or (value["exchange_timestamp"] or 0) >= (prior["exchange_timestamp"] or 0):
                                summaries[name] = value
                except (ValueError, OSError, TypeError) as exc:
                    failures.append(self._failure("get_book_summary_by_currency", currency, exc))
            snapshots: dict[str, dict[str, Any]] = {}
            for selected_asset in sorted(ASSETS):
                snapshot = self._snapshot(selected_asset, registry, summaries, started, failures)
                index_names = {row["index_name"] for row in snapshot["instruments"].values() if row["eligible"]}
                if len(index_names) == 1:
                    index_name = next(iter(index_names))
                    try:
                        result = self._request("get_index_price", {"index_name": index_name}, deadline)
                        if not isinstance(result, dict) or _positive(result.get("index_price")) is None:
                            raise ValueError("INVALID_INDEX: public index price must be positive")
                        snapshot["index"] = {"price": _positive(result["index_price"]), "currency": "USDC", "name": index_name, "observed_at": _stamp(self.now()), "source_endpoint": "public/get_index_price"}
                    except (ValueError, OSError, TypeError) as exc:
                        snapshot["coverage"]["failures"].append(self._failure("get_index_price", selected_asset, exc))
                elif index_names:
                    snapshot["coverage"]["failures"].append({"code": "INCONSISTENT_INDEX_METADATA", "scope": selected_asset, "endpoint": "public/get_instruments", "message": "linear instruments must identify one explicit USDC index"})
                snapshot["coverage"]["scan_complete"] = not failures
                self._identify(snapshot, deadline)
                snapshots[selected_asset] = snapshot
            self._snapshots = snapshots
            self._cache_until = self.clock() + (DISCOVERY_CACHE_SECONDS if not failures else 0)
            return copy.deepcopy(snapshots[asset])

    @staticmethod
    def _asset(value: str) -> str:
        if value not in ASSETS:
            raise ValueError("desk asset must be BTC or ETH")
        return value

    @staticmethod
    def _summary(raw: dict[str, Any], observed: str) -> dict[str, Any]:
        timestamp, exchange_at = _exchange_time(raw.get("creation_timestamp"))
        return {"instrument_name": raw["instrument_name"], "bid": _number(raw.get("bid_price")), "ask": _number(raw.get("ask_price")), "mark_price": _number(raw.get("mark_price")), "mark_iv": _number(raw.get("mark_iv")), "iv_unit": "percent_points", "observed_at": observed, "exchange_timestamp": timestamp, "exchange_at": exchange_at, "timestamp_kind": "summary_created", "source_endpoint": "public/get_book_summary_by_currency", "open_interest": _number(raw.get("open_interest")), "volume": _number(raw.get("volume")), "underlying_price": _positive(raw.get("underlying_price")), "underlying_index": raw.get("underlying_index")}

    def _instrument(self, raw: dict[str, Any], instant: datetime) -> dict[str, Any]:
        expiry_ms, expiry_at = _exchange_time(raw.get("expiration_timestamp"))
        ticks = raw.get("tick_size_steps", [])
        def valid_tick(step: Any) -> bool:
            if not isinstance(step, dict):
                return False
            above = _number(step.get("above_price"))
            return above is not None and above >= 0 and _positive(step.get("tick_size")) is not None

        valid_ticks = isinstance(ticks, list) and all(valid_tick(step) for step in ticks)
        index_name = raw.get("price_index")
        errors = []
        if not _NAME.fullmatch(raw["instrument_name"]):
            errors.append("INVALID_INSTRUMENT_NAME")
        required = {"strike": _positive(raw.get("strike")), "contract_size": _positive(raw.get("contract_size")), "min_trade_amount": _positive(raw.get("min_trade_amount")), "tick_size": _positive(raw.get("tick_size"))}
        for key, value in required.items():
            if value is None:
                errors.append(f"INVALID_{key.upper()}")
        if expiry_ms is None:
            errors.append("INVALID_EXPIRATION_TIMESTAMP")
        if raw.get("option_type") not in ("call", "put"):
            errors.append("INVALID_OPTION_TYPE")
        if raw.get("kind") != "option":
            errors.append("INVALID_INSTRUMENT_KIND")
        if not valid_ticks:
            errors.append("INVALID_TICK_SCHEDULE")
        if raw.get("is_active") not in (True, False) or not isinstance(raw.get("is_active"), bool):
            errors.append("UNKNOWN_ACTIVE_STATE")
        if raw.get("instrument_type") == "linear" and index_name != f"{raw.get('base_currency', '').lower()}_usdc":
            errors.append("UNKNOWN_INDEX_BASIS")
        eligible = not errors and raw.get("is_active") is True and raw.get("instrument_type") == "linear" and raw.get("settlement_currency") == "USDC" and raw.get("quote_currency") == "USDC" and expiry_ms is not None and expiry_ms > instant.timestamp() * 1000
        return {"instrument_name": raw["instrument_name"], "asset": raw.get("base_currency"), "option_type": raw.get("option_type"), "expiry_date": expiry_at[:10] if expiry_at else None, "expiration_timestamp": expiry_ms, **required, "tick_size_steps": copy.deepcopy(ticks) if valid_ticks else None, "instrument_type": raw.get("instrument_type"), "settlement_currency": raw.get("settlement_currency"), "price_currency": raw.get("quote_currency"), "base_currency": raw.get("base_currency"), "index_name": index_name, "active": raw.get("is_active"), "settlement_period": raw.get("settlement_period"), "maker_commission": _number(raw.get("maker_commission")), "taker_commission": _number(raw.get("taker_commission")), "eligible": eligible, "validation_errors": errors}

    def _snapshot(self, asset: str, registry: dict[str, dict[str, Any]], summaries: dict[str, dict[str, Any]], instant: datetime, failures: list[dict[str, Any]]) -> dict[str, Any]:
        instruments = {name: self._instrument(raw, instant) for name, raw in sorted(registry.items()) if raw.get("base_currency") == asset}
        selected_summaries = {name: copy.deepcopy(value) for name, value in summaries.items() if name in instruments or name.startswith((f"{asset}-", f"{asset}_USDC-"))}
        exclusions: Counter[str] = Counter()
        exclusions["MISSING_INSTRUMENT_METADATA"] = sum(name not in instruments for name in selected_summaries)
        expiries: Counter[str] = Counter()
        for name, row in instruments.items():
            if row["instrument_type"] == "reversed":
                exclusions["INVERSE_EXCLUDED"] += 1
            elif row["instrument_type"] != "linear" or row["settlement_currency"] != "USDC" or row["price_currency"] != "USDC":
                exclusions["UNSUPPORTED_CONTRACT_FAMILY"] += 1
            elif row["validation_errors"]:
                exclusions["INVALID_INSTRUMENT_METADATA"] += 1
            elif not row["active"]:
                exclusions["INACTIVE_INSTRUMENT"] += 1
            elif not row["eligible"]:
                exclusions["EXPIRED_INSTRUMENT"] += 1
            elif name not in selected_summaries:
                exclusions["MISSING_SUMMARY"] += 1
            else:
                expiries[row["expiry_date"]] += 1
        environment = "production" if self.base_url == DEFAULT_DERIBIT_BASE_URL else "testnet"
        notice = "Public observations for research; inverse contracts are counted and excluded from USDC strategy qualification."
        if environment == "testnet":
            notice = "Testnet observations, not production market opportunities. " + notice
        return {"schema_version": SCHEMA_VERSION, "snapshot_id": "", "asset": asset, "venue": "DERIBIT", "contract_family": "LINEAR_USDC", "execution_allowed": False, "captured_at": _stamp(instant), "expires_at": _stamp(instant + timedelta(seconds=FRESHNESS_SECONDS)), "source": {"mode": "live", "provider": "DERIBIT_PUBLIC" if environment == "production" else "DERIBIT_TESTNET_PUBLIC", "environment": environment, "base_url": self.base_url, "captured_at": _stamp(instant), "notice": notice}, "index": {"price": None, "currency": "USDC", "name": None, "observed_at": None}, "coverage": {"registry_count": len(instruments), "summary_count": len(selected_summaries), "scan_complete": not failures, "inverse_excluded_count": exclusions["INVERSE_EXCLUDED"], "eligible_instrument_count": sum(expiries.values()), "deepened_count": 0, "failures": copy.deepcopy(failures), "exclusions": {key: value for key, value in sorted(exclusions.items()) if value}, "expiry_counts": [{"expiry_date": expiry, "count": count} for expiry, count in sorted(expiries.items())]}, "instruments": instruments, "summaries": selected_summaries, "quotes": {}}

    def _identify(self, snapshot: dict[str, Any], deadline: float) -> None:
        snapshot["snapshot_id"] = ""
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        snapshot["snapshot_id"] = f"desk-market-{digest[:24]}"
        self._deadlines[snapshot["snapshot_id"]] = deadline
        if len(self._deadlines) > 64:
            for key in list(self._deadlines)[:-64]:
                del self._deadlines[key]

    def deepen(self, snapshot: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
        """Read only explicitly requested candidate legs; never sample the chain."""
        selected = self._names(names)
        with self._lock:
            if snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("asset") not in ASSETS:
                raise ValueError("exact-leg review requires a desk market snapshot")
            result = copy.deepcopy(snapshot)
            # A missing collection context cannot start a fresh clock for an old
            # snapshot. review_exact obtains a new context through discovery.
            deadline = self._deadlines.get(snapshot.get("snapshot_id", ""), self.clock())
            for name in selected:
                instrument = result["instruments"].get(name)
                if instrument is None:
                    result["coverage"]["failures"].append({"code": "UNKNOWN_INSTRUMENT", "endpoint": "public/get_instruments", "scope": name, "message": "exact leg metadata is missing; refresh the registry"})
                    continue
                if instrument.get("asset") != result["asset"] or not instrument.get("eligible") or (instrument.get("expiration_timestamp") or 0) <= self.now().timestamp() * 1000:
                    result["coverage"]["failures"].append({"code": "UNSUPPORTED_EXACT_LEG", "endpoint": "public/get_instruments", "scope": name, "message": "only active, fully specified linear USDC exact legs can be reviewed"})
                    continue
                try:
                    raw = self._request("get_order_book", {"instrument_name": name, "depth": 1}, deadline)
                    if not isinstance(raw, dict) or raw.get("instrument_name") != name:
                        raise ValueError("INVALID_RESPONSE: exact leg identity does not match")
                    result["quotes"][name] = self._quote(raw)
                except (ValueError, OSError, TypeError) as exc:
                    # Failed refresh cannot preserve an earlier apparently current quote.
                    result["quotes"].pop(name, None)
                    result["coverage"]["failures"].append(self._failure("get_order_book", name, exc))
            result["coverage"]["deepened_count"] = len(result["quotes"])
            self._identify(result, deadline)
            return result

    @staticmethod
    def _names(names: Iterable[str]) -> list[str]:
        if isinstance(names, (str, bytes)):
            raise ValueError("exact leg names must be a collection")
        selected: list[str] = []
        for name in names:
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise ValueError("exact leg name is invalid")
            if name not in selected:
                selected.append(name)
            if len(selected) > MAX_EXACT_LEGS:
                raise ValueError("exact review exceeds the bounded public request budget")
        return selected

    def _quote(self, raw: dict[str, Any]) -> dict[str, Any]:
        def side(key: str) -> tuple[float | None, float | None]:
            rows = raw.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[0], (list, tuple)) and len(rows[0]) == 2:
                return _number(rows[0][0]), _number(rows[0][1])
            return None, None

        bid, bid_size = side("bids")
        ask, ask_size = side("asks")
        timestamp, exchange_at = _exchange_time(raw.get("timestamp"))
        observed = self.now()
        errors = []
        for key, value in {"bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size}.items():
            if value is None or value <= 0:
                errors.append(f"INVALID_{key.upper()}")
        if bid is not None and ask is not None and bid > ask:
            errors.append("CROSSED_QUOTE")
        if timestamp is None:
            errors.append("MISSING_EXCHANGE_TIMESTAMP")
        else:
            age = observed.timestamp() - timestamp / 1000
            if age > FRESHNESS_SECONDS:
                errors.append("STALE_QUOTE")
            if age < -5:
                errors.append("FUTURE_QUOTE_TIMESTAMP")
        if raw.get("state") != "open":
            errors.append("INSTRUMENT_NOT_OPEN")
        return {"instrument_name": raw["instrument_name"], "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size, "mark_iv": _number(raw.get("mark_iv")), "iv_unit": "percent_points", "index_price": _positive(raw.get("index_price")), "underlying_price": _positive(raw.get("underlying_price")), "greeks": {key: _number(value) for key, value in raw.get("greeks", {}).items()} if isinstance(raw.get("greeks"), dict) else None, "observed_at": _stamp(observed), "exchange_timestamp": timestamp, "exchange_at": exchange_at, "timestamp_kind": "exchange_quote", "state": raw.get("state"), "source_endpoint": "public/get_order_book", "valid": not errors, "validation_errors": errors}

    def review_exact(self, asset: str, names: Iterable[str]) -> dict[str, Any]:
        """Refetch saved identities directly, regardless of the new candidate ranking."""
        selected = self._names(names)
        snapshot = self.fetch_snapshot(asset, force=True)
        with self._lock:
            deadline = self._deadlines[snapshot["snapshot_id"]]
            for name in selected:
                if name not in snapshot["instruments"]:
                    try:
                        raw = self._request("get_instrument", {"instrument_name": name}, deadline)
                        if not isinstance(raw, dict) or raw.get("instrument_name") != name or raw.get("base_currency") != asset:
                            raise ValueError("INVALID_RESPONSE: exact instrument identity does not match")
                        snapshot["instruments"][name] = self._instrument(raw, self.now())
                    except (ValueError, OSError, TypeError) as exc:
                        snapshot["coverage"]["failures"].append(self._failure("get_instrument", name, exc))
            return self.deepen(snapshot, selected)


_DEFAULT_COLLECTOR = DeskMarketCollector()


def fetch_snapshot(asset: str) -> dict[str, Any]:
    return _DEFAULT_COLLECTOR.fetch_snapshot(asset)


def deepen(snapshot: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    return _DEFAULT_COLLECTOR.deepen(snapshot, names)


def review_exact(asset: str, names: Iterable[str]) -> dict[str, Any]:
    return _DEFAULT_COLLECTOR.review_exact(asset, names)
