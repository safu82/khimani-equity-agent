"""
tools.py
Tool definitions and implementations for the Khimani Equity Agent.
All tools query Supabase (holdings, live_prices, transactions,
portfolio_snapshots, cash_flows, alerts, entry_signals).
"""
import os
import json
from datetime import datetime, date, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

PORTFOLIO = "INDIAN"


# ─────────────────────────────────────────────────────────────────
# TOOL 1: get_portfolio_summary
# ─────────────────────────────────────────────────────────────────
def get_portfolio_summary() -> str:
    """
    Total portfolio value, day P&L, overall unrealized P&L,
    top gainer and top loser.
    """
    try:
        holdings = sb.table("holdings") \
                     .select("ticker, name, quantity, avg_cost, sector") \
                     .eq("portfolio", PORTFOLIO) \
                     .execute().data

        if not holdings:
            return json.dumps({"error": "No holdings found"})

        tickers = [h["ticker"] for h in holdings]
        prices_raw = sb.table("live_prices") \
                       .select("ticker, price, day_change, day_change_pct, prev_close") \
                       .in_("ticker", tickers) \
                       .execute().data

        prices = {p["ticker"]: p for p in prices_raw}

        total_invested   = 0.0
        total_value      = 0.0
        total_day_change = 0.0
        rows             = []

        for h in holdings:
            t   = h["ticker"]
            qty = float(h["quantity"])
            avg = float(h["avg_cost"])
            p   = prices.get(t, {})
            ltp = float(p.get("price") or avg)
            day_chg = float(p.get("day_change") or 0) * qty

            invested      = qty * avg
            current_value = qty * ltp
            pnl           = current_value - invested
            pnl_pct       = (pnl / invested * 100) if invested else 0

            total_invested   += invested
            total_value      += current_value
            total_day_change += day_chg

            rows.append({
                "ticker":  t,
                "name":    h["name"],
                "pnl":     pnl,
                "pnl_pct": pnl_pct,
            })

        total_pnl     = total_value - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

        rows_sorted = sorted(rows, key=lambda x: x["pnl_pct"], reverse=True)
        top_gainer  = rows_sorted[0]  if rows_sorted else None
        top_loser   = rows_sorted[-1] if rows_sorted else None

        return json.dumps({
            "total_invested":    round(total_invested, 2),
            "total_value":       round(total_value, 2),
            "total_pnl":         round(total_pnl, 2),
            "total_pnl_pct":     round(total_pnl_pct, 2),
            "total_day_change":  round(total_day_change, 2),
            "num_holdings":      len(holdings),
            "top_gainer":        top_gainer,
            "top_loser":         top_loser,
            "prices_updated_at": prices_raw[0].get("updated_at") if prices_raw else None,
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 2: get_holdings
# ─────────────────────────────────────────────────────────────────
def get_holdings(sector: str = None) -> str:
    """
    Full position list with LTP, unrealized P&L per stock.
    Optionally filtered by sector.
    """
    try:
        query = sb.table("holdings") \
                  .select("ticker, name, quantity, avg_cost, sector") \
                  .eq("portfolio", PORTFOLIO)

        if sector:
            query = query.ilike("sector", f"%{sector}%")

        holdings = query.execute().data

        if not holdings:
            return json.dumps({"error": "No holdings found", "sector_filter": sector})

        tickers    = [h["ticker"] for h in holdings]
        prices_raw = sb.table("live_prices") \
                       .select("ticker, price, day_change, day_change_pct") \
                       .in_("ticker", tickers) \
                       .execute().data

        prices = {p["ticker"]: p for p in prices_raw}

        result = []
        for h in holdings:
            t   = h["ticker"]
            qty = float(h["quantity"])
            avg = float(h["avg_cost"])
            p   = prices.get(t, {})
            ltp = float(p.get("price") or avg)

            invested      = qty * avg
            current_value = qty * ltp
            pnl           = current_value - invested
            pnl_pct       = (pnl / invested * 100) if invested else 0
            day_chg_pct   = float(p.get("day_change_pct") or 0)

            result.append({
                "ticker":        t,
                "name":          h["name"],
                "sector":        h["sector"],
                "quantity":      qty,
                "avg_cost":      avg,
                "ltp":           round(ltp, 2),
                "invested":      round(invested, 2),
                "current_value": round(current_value, 2),
                "pnl":           round(pnl, 2),
                "pnl_pct":       round(pnl_pct, 2),
                "day_change_pct": round(day_chg_pct, 2),
            })

        result.sort(key=lambda x: x["pnl_pct"], reverse=True)

        return json.dumps({
            "holdings":      result,
            "count":         len(result),
            "sector_filter": sector,
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 3: get_stock_detail
# ─────────────────────────────────────────────────────────────────
def get_stock_detail(ticker: str) -> str:
    """
    Full detail on a single stock: entry, current, P&L, day change.
    Accepts partial name match too (e.g. 'infosys', 'INFY').
    """
    try:
        # Try exact ticker match first
        holding = sb.table("holdings") \
                    .select("ticker, name, quantity, avg_cost, sector") \
                    .eq("portfolio", PORTFOLIO) \
                    .ilike("ticker", f"%{ticker}%") \
                    .limit(1) \
                    .execute().data

        # Fall back to name match
        if not holding:
            holding = sb.table("holdings") \
                        .select("ticker, name, quantity, avg_cost, sector") \
                        .eq("portfolio", PORTFOLIO) \
                        .ilike("name", f"%{ticker}%") \
                        .limit(1) \
                        .execute().data

        if not holding:
            return json.dumps({"error": f"No holding found matching '{ticker}'"})

        h   = holding[0]
        t   = h["ticker"]
        qty = float(h["quantity"])
        avg = float(h["avg_cost"])

        price_row = sb.table("live_prices") \
                      .select("price, day_change, day_change_pct, prev_close, volume, updated_at") \
                      .eq("ticker", t) \
                      .limit(1) \
                      .execute().data

        p   = price_row[0] if price_row else {}
        ltp = float(p.get("price") or avg)

        invested      = qty * avg
        current_value = qty * ltp
        pnl           = current_value - invested
        pnl_pct       = (pnl / invested * 100) if invested else 0

        return json.dumps({
            "ticker":         t,
            "name":           h["name"],
            "sector":         h["sector"],
            "quantity":       qty,
            "avg_cost":       round(avg, 2),
            "ltp":            round(ltp, 2),
            "prev_close":     p.get("prev_close"),
            "day_change":     p.get("day_change"),
            "day_change_pct": p.get("day_change_pct"),
            "volume":         p.get("volume"),
            "invested":       round(invested, 2),
            "current_value":  round(current_value, 2),
            "pnl":            round(pnl, 2),
            "pnl_pct":        round(pnl_pct, 2),
            "prices_as_of":   p.get("updated_at"),
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 4: get_sector_breakdown
# ─────────────────────────────────────────────────────────────────
def get_sector_breakdown() -> str:
    """
    Portfolio allocation and P&L contribution broken down by sector.
    """
    try:
        holdings = sb.table("holdings") \
                     .select("ticker, quantity, avg_cost, sector") \
                     .eq("portfolio", PORTFOLIO) \
                     .execute().data

        tickers    = [h["ticker"] for h in holdings]
        prices_raw = sb.table("live_prices") \
                       .select("ticker, price") \
                       .in_("ticker", tickers) \
                       .execute().data

        prices = {p["ticker"]: float(p.get("price") or 0) for p in prices_raw}

        sectors: dict = {}
        total_value   = 0.0

        for h in holdings:
            t       = h["ticker"]
            qty     = float(h["quantity"])
            avg     = float(h["avg_cost"])
            ltp     = prices.get(t, avg)
            sector  = h["sector"] or "Unknown"

            invested = qty * avg
            current  = qty * ltp
            pnl      = current - invested

            if sector not in sectors:
                sectors[sector] = {"invested": 0, "current_value": 0, "pnl": 0, "stocks": 0}

            sectors[sector]["invested"]      += invested
            sectors[sector]["current_value"] += current
            sectors[sector]["pnl"]           += pnl
            sectors[sector]["stocks"]        += 1
            total_value                      += current

        result = []
        for sector, data in sectors.items():
            allocation_pct = (data["current_value"] / total_value * 100) if total_value else 0
            pnl_pct        = (data["pnl"] / data["invested"] * 100) if data["invested"] else 0
            result.append({
                "sector":         sector,
                "stocks":         data["stocks"],
                "invested":       round(data["invested"], 2),
                "current_value":  round(data["current_value"], 2),
                "pnl":            round(data["pnl"], 2),
                "pnl_pct":        round(pnl_pct, 2),
                "allocation_pct": round(allocation_pct, 2),
            })

        result.sort(key=lambda x: x["current_value"], reverse=True)

        return json.dumps({
            "sectors":     result,
            "total_value": round(total_value, 2),
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 5: get_portfolio_history
# ─────────────────────────────────────────────────────────────────
def get_portfolio_history(period: str = "1m") -> str:
    """
    Portfolio value over time from snapshots, with benchmark comparison.
    period: '1w', '1m', '3m', '6m', '1y'
    """
    period_map = {
        "1w": 7, "week": 7,
        "1m": 30, "month": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
    }
    days = period_map.get(period.lower(), 30)
    from_date = (date.today() - timedelta(days=days)).isoformat()

    try:
        snapshots = sb.table("portfolio_snapshots") \
                      .select("snapshot_date, total_value, benchmark_ticker, benchmark_price, benchmark_xirr") \
                      .eq("portfolio", PORTFOLIO) \
                      .gte("snapshot_date", from_date) \
                      .order("snapshot_date") \
                      .execute().data

        if not snapshots:
            return json.dumps({"error": "No snapshots found for this period", "period": period})

        first = snapshots[0]
        last  = snapshots[-1]

        start_value   = float(first["total_value"])
        end_value     = float(last["total_value"])
        value_change  = end_value - start_value
        change_pct    = (value_change / start_value * 100) if start_value else 0

        return json.dumps({
            "period":          period,
            "from_date":       first["snapshot_date"],
            "to_date":         last["snapshot_date"],
            "start_value":     round(start_value, 2),
            "end_value":       round(end_value, 2),
            "value_change":    round(value_change, 2),
            "change_pct":      round(change_pct, 2),
            "num_snapshots":   len(snapshots),
            "benchmark_xirr":  last.get("benchmark_xirr"),
            "benchmark_ticker": last.get("benchmark_ticker"),
            "snapshots":       [
                {
                    "date":  s["snapshot_date"],
                    "value": float(s["total_value"]),
                }
                for s in snapshots
            ],
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 6: get_signals
# ─────────────────────────────────────────────────────────────────
def get_signals(scope: str = "holdings") -> str:
    """
    Recent technical signals.
    scope: 'holdings' (only my stocks) or 'market' (all signals)
    """
    try:
        since = (date.today() - timedelta(days=7)).isoformat()

        # Get my tickers if filtering to holdings
        my_tickers = set()
        if scope == "holdings":
            holdings = sb.table("holdings") \
                         .select("ticker") \
                         .eq("portfolio", PORTFOLIO) \
                         .execute().data
            my_tickers = {h["ticker"] for h in holdings}

        # Query alerts table
        alerts_query = sb.table("alerts") \
                         .select("ticker, stock_name, alert_type, alert_category, alert_title, alert_description, price, alert_date") \
                         .gte("alert_date", since) \
                         .order("alert_date", desc=True) \
                         .limit(50) \
                         .execute().data

        # Query entry_signals table
        signals_query = sb.table("entry_signals") \
                          .select("ticker, stock_name, signal_type, signal_strength, price, alert_date, details") \
                          .gte("alert_date", since) \
                          .order("alert_date", desc=True) \
                          .limit(50) \
                          .execute().data

        if scope == "holdings":
            alerts_query  = [a for a in alerts_query  if a["ticker"] in my_tickers]
            signals_query = [s for s in signals_query if s["ticker"] in my_tickers]

        return json.dumps({
            "scope":         scope,
            "since":         since,
            "alerts":        alerts_query,
            "entry_signals": signals_query,
            "alert_count":   len(alerts_query),
            "signal_count":  len(signals_query),
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 7: get_transactions
# ─────────────────────────────────────────────────────────────────
def get_transactions(
    start_date: str = None,
    end_date:   str = None,
    type:       str = None,
    ticker:     str = None,
    n:          int = 50,
) -> str:
    """
    Fetch transactions with optional date range, type and ticker filters.
    No hardcoded date limits — queries whatever is in Supabase.
    """
    try:
        n = min(max(int(n), 1), 200)  # clamp 1-200

        query = sb.table("transactions") \
                  .select("date, type, stock, ticker, quantity, price, sector, strategy") \
                  .eq("portfolio", PORTFOLIO) \
                  .order("date", desc=True)

        if start_date:
            query = query.gte("date", start_date)
        if end_date:
            query = query.lte("date", end_date)
        if type:
            query = query.eq("type", type.upper())
        if ticker:
            # Match on ticker or stock name
            holdings_match = sb.table("holdings") \
                               .select("ticker") \
                               .eq("portfolio", PORTFOLIO) \
                               .ilike("ticker", f"%{ticker}%") \
                               .execute().data
            name_match = sb.table("holdings") \
                           .select("ticker") \
                           .eq("portfolio", PORTFOLIO) \
                           .ilike("name", f"%{ticker}%") \
                           .execute().data
            matched_tickers = list({h["ticker"] for h in holdings_match + name_match})
            if matched_tickers:
                query = query.in_("ticker", matched_tickers)
            else:
                # Fall back to direct ilike on transactions table
                query = query.ilike("ticker", f"%{ticker}%")

        query = query.limit(n)
        txns  = query.execute().data

        for t in txns:
            qty        = float(t["quantity"])
            price      = float(t["price"])
            t["value"] = round(qty * price, 2)

        return json.dumps({
            "transactions": txns,
            "count":        len(txns),
            "filters": {
                "start_date": start_date,
                "end_date":   end_date,
                "type":       type,
                "ticker":     ticker,
            },
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 8: get_xirr
# ─────────────────────────────────────────────────────────────────
def _compute_xirr(cash_flows: list, dates: list) -> float:
    """
    Newton-Raphson XIRR solver matching the dashboard Custom Period card.
    Uses 365.25 day year, 1000 iterations, step capping and rate clamping.
    cash_flows: negative = money out, positive = money in
    Returns annualised rate as a decimal (e.g. 0.15 for 15%).
    """
    t0             = dates[0]
    days           = [(d - t0).days for d in dates]
    max_iterations = 1000
    tolerance      = 1e-6
    max_change     = 0.5
    guesses        = [0.1, 0.0, -0.1, 0.5, -0.5]

    for initial_guess in guesses:
        guess = initial_guess
        npv   = 0.0
        for _ in range(max_iterations):
            npv  = 0.0
            dnpv = 0.0
            for cf, d in zip(cash_flows, days):
                year_frac = d / 365.25
                factor    = (1 + guess) ** year_frac
                npv  += cf / factor
                dnpv += -year_frac * cf / factor / (1 + guess)

            if abs(npv) < tolerance:
                return guess

            if abs(dnpv) < 1e-10:
                guess = guess * 0.5
                continue

            new_guess = guess - npv / dnpv

            if abs(new_guess - guess) > max_change:
                new_guess = guess + (max_change if new_guess > guess else -max_change)

            guess = new_guess

            if guess < -0.99:
                guess = -0.5
            if guess > 10:
                guess = 1.0

        if abs(npv) < 0.01:
            return guess

    raise ValueError("XIRR did not converge")


def get_xirr(start_date: str = None, end_date: str = None) -> str:
    """
    Compute XIRR matching the dashboard Custom Period card exactly.
    Two data sources:
    - cash_flows table: up to CASH_FLOWS_END_DATE (2025-10-01)
    - transactions table: from CASH_FLOWS_END_DATE onwards

    start_date: YYYY-MM-DD (agent will use last snapshot of that month as opening)
    end_date: YYYY-MM-DD (defaults to today)
    """
    CASH_FLOWS_END_DATE = '2025-10-01'

    try:
        today_str = date.today().isoformat()
        end_str   = end_date or today_str

        cf_dates  = []
        cf_values = []

        if start_date:
            # Match dashboard: use last snapshot of the start month
            start_dt   = date.fromisoformat(start_date)
            if start_dt.month == 12:
                month_end = date(start_dt.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(start_dt.year, start_dt.month + 1, 1) - timedelta(days=1)

            snap = sb.table("portfolio_snapshots") \
                     .select("snapshot_date, total_value") \
                     .eq("portfolio", PORTFOLIO) \
                     .lte("snapshot_date", month_end.isoformat()) \
                     .gte("snapshot_date", start_date) \
                     .order("snapshot_date", desc=True) \
                     .limit(1) \
                     .execute().data

            if not snap:
                snap = sb.table("portfolio_snapshots") \
                         .select("snapshot_date, total_value") \
                         .eq("portfolio", PORTFOLIO) \
                         .lte("snapshot_date", start_date) \
                         .order("snapshot_date", desc=True) \
                         .limit(1) \
                         .execute().data

            if not snap:
                return json.dumps({"error": "No snapshot found for start date"})

            opening_value    = float(snap[0]["total_value"])
            actual_start_str = snap[0]["snapshot_date"]
            cf_dates.append(date.fromisoformat(actual_start_str))
            cf_values.append(-opening_value)

        else:
            actual_start_str = '2000-01-01'  # inception — include all

        # Source 1: cash_flows table (up to CASH_FLOWS_END_DATE)
        # Sign convention matching dashboard:
        # Withdrawl (positive stored) → positive
        # Deposit (negative stored) → negated → positive
        # i.e. dashboard does: Withdrawl ? amount : -amount
        # Paginate cash_flows — can exceed 1000 rows for long periods
        hist_flows = []
        page_size  = 1000
        offset     = 0
        end_cf     = min(end_str, CASH_FLOWS_END_DATE)
        while True:
            batch = sb.table("cash_flows") \
                      .select("date, amount, description") \
                      .eq("portfolio", PORTFOLIO) \
                      .gt("date", actual_start_str) \
                      .lte("date", end_cf) \
                      .order("date") \
                      .range(offset, offset + page_size - 1) \
                      .execute().data
            hist_flows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        for f in hist_flows:
            # Deposits (buys) stored as negative → keep negative (money out)
            # Withdrawals (sells) stored as positive → keep positive (money in)
            cf_values.append(float(f["amount"]))
            cf_dates.append(date.fromisoformat(f["date"]))

        # Source 2: transactions table (Oct 2025 onwards)
        # BUY = -(qty * price), SELL = +(qty * price)
        txn_start = max(actual_start_str, CASH_FLOWS_END_DATE)
        txns = sb.table("transactions") \
                 .select("date, type, quantity, price") \
                 .eq("portfolio", PORTFOLIO) \
                 .gte("date", txn_start) \
                 .lte("date", end_str) \
                 .order("date") \
                 .execute().data

        for t in txns:
            qty   = float(t["quantity"])
            price = float(t["price"])
            value = qty * price
            cf_values.append(-value if t["type"] == "BUY" else value)
            cf_dates.append(date.fromisoformat(t["date"]))

        if not cf_values:
            return json.dumps({"error": "No cash flows found for this period"})

        # Terminal value: current portfolio value
        holdings = sb.table("holdings") \
                     .select("ticker, quantity, avg_cost") \
                     .eq("portfolio", PORTFOLIO) \
                     .execute().data

        tickers    = [h["ticker"] for h in holdings]
        prices_raw = sb.table("live_prices") \
                       .select("ticker, price") \
                       .in_("ticker", tickers) \
                       .execute().data

        prices = {p["ticker"]: float(p.get("price") or 0) for p in prices_raw}

        total_value = sum(
            float(h["quantity"]) * prices.get(h["ticker"], float(h["avg_cost"]))
            for h in holdings
        )

        cf_dates.append(date.fromisoformat(end_str))
        cf_values.append(total_value)

        xirr_rate = _compute_xirr(cf_values, cf_dates)

        return json.dumps({
            "xirr_pct":           round(xirr_rate * 100, 2),
            "start_date":         cf_dates[0].isoformat(),
            "end_date":           end_str,
            "current_value":      round(total_value, 2),
            "num_hist_cashflows": len(hist_flows),
            "num_transactions":   len(txns),
        })

    except ValueError as e:
        return json.dumps({"error": f"XIRR computation failed: {str(e)}"})
    except Exception as e:
        return json.dumps({"error": str(e)})




# ─────────────────────────────────────────────────────────────────
# TOOL 9: get_portfolio_ath
# ─────────────────────────────────────────────────────────────────
def get_portfolio_ath() -> str:
    """
    Analyse portfolio snapshots from Jan 2023 to find:
    - All-time high value and when it occurred
    - Current drawdown from ATH
    - Best and worst months by absolute gain
    - Cumulative gain since Jan 2023 baseline
    """
    try:
        snapshots = sb.table("portfolio_snapshots") \
                      .select("snapshot_date, total_value") \
                      .eq("portfolio", PORTFOLIO) \
                      .gte("snapshot_date", "2023-01-01") \
                      .order("snapshot_date") \
                      .execute().data

        if not snapshots:
            return json.dumps({"error": "No snapshots found"})

        # Current portfolio value from live prices
        holdings = sb.table("holdings") \
                     .select("ticker, quantity, avg_cost") \
                     .eq("portfolio", PORTFOLIO) \
                     .execute().data

        tickers    = [h["ticker"] for h in holdings]
        prices_raw = sb.table("live_prices") \
                       .select("ticker, price") \
                       .in_("ticker", tickers) \
                       .execute().data

        prices = {p["ticker"]: float(p.get("price") or 0) for p in prices_raw}

        current_value = sum(
            float(h["quantity"]) * prices.get(h["ticker"], float(h["avg_cost"]))
            for h in holdings
        )

        baseline    = float(snapshots[0]["total_value"])
        baseline_dt = snapshots[0]["snapshot_date"]

        # Find ATH across all snapshots + current value
        ath_value = baseline
        ath_date  = baseline_dt

        monthly_gains = []
        for i in range(1, len(snapshots)):
            prev  = float(snapshots[i - 1]["total_value"])
            curr  = float(snapshots[i]["total_value"])
            gain  = curr - prev
            monthly_gains.append({
                "date":  snapshots[i]["snapshot_date"],
                "value": round(curr, 2),
                "gain":  round(gain, 2),
            })
            if curr > ath_value:
                ath_value = curr
                ath_date  = snapshots[i]["snapshot_date"]

        # Check if current value is a new ATH
        if current_value > ath_value:
            ath_value = current_value
            ath_date  = date.today().isoformat()

        drawdown        = current_value - ath_value
        drawdown_pct    = (drawdown / ath_value * 100) if ath_value else 0
        cumulative_gain = current_value - baseline
        cumulative_pct  = (cumulative_gain / baseline * 100) if baseline else 0

        monthly_gains_sorted = sorted(monthly_gains, key=lambda x: x["gain"], reverse=True)

        return json.dumps({
            "baseline_value":   round(baseline, 2),
            "baseline_date":    baseline_dt,
            "ath_value":        round(ath_value, 2),
            "ath_date":         ath_date,
            "current_value":    round(current_value, 2),
            "drawdown":         round(drawdown, 2),
            "drawdown_pct":     round(drawdown_pct, 2),
            "cumulative_gain":  round(cumulative_gain, 2),
            "cumulative_pct":   round(cumulative_pct, 2),
            "best_month":       monthly_gains_sorted[0]  if monthly_gains_sorted else None,
            "worst_month":      monthly_gains_sorted[-1] if monthly_gains_sorted else None,
            "total_snapshots":  len(snapshots),
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────
# TOOL 10: get_technical_overview
# ─────────────────────────────────────────────────────────────────
def get_technical_overview(filter: str = "all") -> str:
    """
    EMA position and stack analysis for holdings.
    Queries stock_ema_values filtered to Indian portfolio holdings.
    filter: 'all', 'above_200', 'below_200', 'bullish_stack', 'bearish_stack'
    """
    try:
        # Get holding tickers
        holdings = sb.table("holdings") \
                     .select("ticker, name") \
                     .eq("portfolio", PORTFOLIO) \
                     .execute().data

        tickers    = [h["ticker"] for h in holdings]
        ticker_map = {h["ticker"]: h["name"] for h in holdings}

        # Get EMA data for holdings
        ema_raw = sb.table("stock_ema_values") \
                    .select("ticker, stock_name, current_price, ema_20, ema_50, ema_200, is_stacked, is_bearish_stacked") \
                    .in_("ticker", tickers) \
                    .execute().data

        if not ema_raw:
            return json.dumps({"error": "No EMA data found for holdings"})

        # Enrich and filter
        result = []
        for e in ema_raw:
            price   = float(e.get("current_price") or 0)
            ema_200 = float(e.get("ema_200") or 0)
            ema_50  = float(e.get("ema_50") or 0)
            ema_20  = float(e.get("ema_20") or 0)

            above_200     = price > ema_200 if ema_200 else None
            bullish_stack = e.get("is_stacked") or False
            bearish_stack = e.get("is_bearish_stacked") or False

            # Apply filter
            if filter == "above_200"    and not above_200:      continue
            if filter == "below_200"    and above_200 is not False: continue
            if filter == "bullish_stack" and not bullish_stack: continue
            if filter == "bearish_stack" and not bearish_stack: continue

            dist_200 = ((price - ema_200) / ema_200 * 100) if ema_200 else None

            result.append({
                "ticker":        e["ticker"],
                "name":          ticker_map.get(e["ticker"], e.get("stock_name", "")),
                "current_price": round(price, 2),
                "ema_20":        round(ema_20, 2)  if ema_20  else None,
                "ema_50":        round(ema_50, 2)  if ema_50  else None,
                "ema_200":       round(ema_200, 2) if ema_200 else None,
                "above_200":     above_200,
                "dist_from_200_pct": round(dist_200, 2) if dist_200 is not None else None,
                "bullish_stack": bullish_stack,
                "bearish_stack": bearish_stack,
            })

        # Summary counts
        all_data   = [e for e in result]
        above_cnt  = sum(1 for e in all_data if e["above_200"])
        below_cnt  = sum(1 for e in all_data if e["above_200"] is False)
        bull_cnt   = sum(1 for e in all_data if e["bullish_stack"])
        bear_cnt   = sum(1 for e in all_data if e["bearish_stack"])

        result.sort(key=lambda x: x["dist_from_200_pct"] or 0, reverse=True)

        return json.dumps({
            "filter":        filter,
            "count":         len(result),
            "summary": {
                "above_200":     above_cnt,
                "below_200":     below_cnt,
                "bullish_stack": bull_cnt,
                "bearish_stack": bear_cnt,
                "total":         len(all_data),
            },
            "stocks": result,
        })

    except Exception as e:
        return json.dumps({"error": str(e)})

# ─────────────────────────────────────────────────────────────────
# TOOL DEFINITIONS (JSON schemas for Claude)
# ─────────────────────────────────────────────────────────────────
TOOL_DEFINITIONS = [
    {
        "name": "get_portfolio_summary",
        "description": "Get a full portfolio summary: total value, day P&L, overall unrealized P&L, top gainer and top loser. Use this for 'how am I doing today' type questions.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_holdings",
        "description": "Get all holdings with LTP, invested value, unrealized P&L and day change. Optionally filter by sector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "Optional sector filter, e.g. 'Technology', 'Banking', 'Pharma'",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_stock_detail",
        "description": "Get detailed info on a single stock: entry price, LTP, P&L, day change, volume. Accepts ticker symbol or partial company name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker symbol (e.g. 'INFY.NS') or partial company name (e.g. 'infosys')",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_sector_breakdown",
        "description": "Get portfolio allocation and P&L broken down by sector. Use for questions about which sectors are performing well or dragging.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_portfolio_history",
        "description": "Get portfolio value over time with benchmark comparison. Use for performance over a period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: '1w', '1m', '3m', '6m', '1y'",
                    "enum": ["1w", "1m", "3m", "6m", "1y"],
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_signals",
        "description": "Get recent technical signals and alerts from the last 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "'holdings' to see signals only on stocks I own, 'market' for all market-wide signals",
                    "enum": ["holdings", "market"],
                },
            },
            "required": ["scope"],
        },
    },
    {
        "name": "get_transactions",
        "description": (
            "Get transactions with flexible filters. Use for questions like "
            "'what did I buy in February', 'have I sold Infosys', "
            "'all buys this FY', 'transactions last month'. "
            "All filters are optional and fully dynamic — any date range works."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD. e.g. '2026-02-01' for February",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD. e.g. '2026-02-28' for end of February",
                },
                "type": {
                    "type": "string",
                    "description": "Transaction type filter: 'BUY' or 'SELL'",
                    "enum": ["BUY", "SELL"],
                },
                "ticker": {
                    "type": "string",
                    "description": "Filter by ticker symbol or partial company name, e.g. 'INFY' or 'infosys'",
                },
                "n": {
                    "type": "integer",
                    "description": "Max number of transactions to return (default 50, max 200)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_xirr",
        "description": "Compute XIRR (annualised return) for the portfolio between two dates. Defaults to inception to today. Use for questions like 'what is my XIRR since January' or 'how did I do in FY 2025-26'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. Defaults to inception.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Defaults to today.",
                },
            },
            "required": [],
        },
    },
,
    {
        "name": "get_portfolio_ath",
        "description": (
            "Analyse portfolio all-time high (ATH), cumulative gains since Jan 2023, "
            "drawdown from ATH, and best/worst months. Use for questions like "
            "'when was my portfolio at its peak?', 'how far am I from ATH?', "
            "'what was my best month?', 'what are my cumulative gains?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_technical_overview",
        "description": (
            "EMA position and bullish/bearish stack analysis for portfolio holdings. "
            "Use for questions like 'how many stocks are above the 200 EMA?', "
            "'which stocks have a bullish stack?', 'show me stocks below 200 EMA', "
            "'what is the technical picture of my portfolio?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Filter to apply: 'all', 'above_200', 'below_200', 'bullish_stack', 'bearish_stack'",
                    "enum": ["all", "above_200", "below_200", "bullish_stack", "bearish_stack"],
                },
            },
            "required": [],
        },
    },
]


# ─────────────────────────────────────────────────────────────────
# TOOL DISPATCHER
# ─────────────────────────────────────────────────────────────────
def execute_tool(name: str, params: dict) -> str:
    """Route tool calls from agent.py to the correct function."""
    if name == "get_portfolio_summary":
        return get_portfolio_summary()
    elif name == "get_holdings":
        return get_holdings(sector=params.get("sector"))
    elif name == "get_stock_detail":
        return get_stock_detail(ticker=params.get("ticker", ""))
    elif name == "get_sector_breakdown":
        return get_sector_breakdown()
    elif name == "get_portfolio_history":
        return get_portfolio_history(period=params.get("period", "1m"))
    elif name == "get_signals":
        return get_signals(scope=params.get("scope", "holdings"))
    elif name == "get_transactions":
        return get_transactions(
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            type=params.get("type"),
            ticker=params.get("ticker"),
            n=params.get("n", 50),
        )
    elif name == "get_xirr":
        return get_xirr(
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
        )
    elif name == "get_portfolio_ath":
        return get_portfolio_ath()
    elif name == "get_technical_overview":
        return get_technical_overview(filter=params.get("filter", "all"))
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})
