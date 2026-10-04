# core.py
import os, asyncio, shutil
from datetime import datetime, timezone, timedelta
from config import (
    db, log, SYMBOLS, MAX_POSITIONS, DB_PATH, BACKUP_DIR,
    get_keys, license_info, make_exchange,
    MIN_ORDER_USDT, last_trade_time, log_trade, now_utc, parse_dt,
    ENTRY_TF, CONFIRM_TF, TREND_TF, EMA_FAST, EMA_SLOW, ATR_PERIOD,
    VOLUME_LOOKBACK, VOLUME_MULT, RSI_PERIOD,
    RSI_LONG_MIN, RSI_LONG_MAX, RSI_SHORT_MIN, RSI_SHORT_MAX,
    SL_ATR_MULT, TP1_R, TP2_R, TP3_R, TP1_PCT, TP2_PCT,
    TRAIL_AFTER_R, TRAIL_ATR_MULT, TIME_STOP_HOURS,
    RISK_PCT, ENABLE_SHORTS, SANDBOX, LIVE_MODE, COOLDOWN_MIN,
    MAX_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSSES,
    SENTIMENT_WEIGHT, MIN_TOTAL_SCORE,
    FUNDAMENTAL_WEIGHT, MIN_FUNDAMENTAL_SCORE,
    ENABLE_NATIVE_SL, NATIVE_SL_OFFSET_PCT, MAX_TRADES_PER_DAY,
    MAX_TRADES_PER_SYMBOL_PER_DAY, MAX_POSITION_USDT,
    get_equity_snapshot, set_equity_snapshot, get_trades_today,
    incr_trades_today, count_trades_today_for_symbol,
    daily_pnl, trading_enabled, halt_user, set_state, open_positions,
)
from sentiment import sentiment_score
from fundamental import fundamental_score
from marketing import announce_win, bind_bot as marketing_bind_bot

_locks: dict = {}


def user_lock(uid):
    if uid not in _locks:
        _locks[uid] = asyncio.Lock()
    return _locks[uid]


class Signal:
    __slots__ = ("ok", "side", "confidence", "price", "sl", "tp", "atr",
                 "reason", "symbol", "sent_score", "breakdown")

    def __init__(self, ok, side="LONG", confidence=0, price=0, sl=0, tp=0,
                 atr=0, reason="", symbol="", sent_score=0.0, breakdown=None):
        self.ok = ok
        self.side = side
        self.confidence = confidence
        self.price = price
        self.sl = sl
        self.tp = tp
        self.atr = atr
        self.reason = reason
        self.symbol = symbol
        self.sent_score = sent_score
        self.breakdown = breakdown or {}


def _ema(vals, n):
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            g += d
        else:
            l -= d
    ag, al = g / n, l / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gg = d if d > 0 else 0
        ll = -d if d < 0 else 0
        ag = (ag * (n - 1) + gg) / n
        al = (al * (n - 1) + ll) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - (100 / (1 + rs))


def _atr(ohlcv, n=14):
    if len(ohlcv) < n + 1:
        return None
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i][2], ohlcv[i][3], ohlcv[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-n:]) / n


async def _fetch(ex, symbol, tf, limit):
    return await ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)


async def compute_signal(ex, symbol):
    try:
        h4 = await _fetch(ex, symbol, TREND_TF, EMA_SLOW + 5)
        if len(h4) < EMA_SLOW:
            return Signal(False, reason="no 4h", symbol=symbol)
        c4 = [x[4] for x in h4]
        ef, es = _ema(c4, EMA_FAST), _ema(c4, EMA_SLOW)
        if ef is None or es is None:
            return Signal(False, reason="no 4h EMA", symbol=symbol)
        trend_up, trend_down = ef > es, ef < es

        h1 = await _fetch(ex, symbol, CONFIRM_TF, RSI_PERIOD + 5)
        rsi1 = _rsi([x[4] for x in h1], RSI_PERIOD)
        if rsi1 is None:
            return Signal(False, reason="no 1h RSI", symbol=symbol)

        m15 = await _fetch(ex, symbol, ENTRY_TF, max(ATR_PERIOD, VOLUME_LOOKBACK) + 5)
        if len(m15) < max(ATR_PERIOD, VOLUME_LOOKBACK) + 2:
            return Signal(False, reason="no entry data", symbol=symbol)
        price = float(m15[-1][4])
        if price <= 0:
            return Signal(False, reason="no price", symbol=symbol)

        atr = _atr(m15, ATR_PERIOD)
        if not atr or atr <= 0:
            return Signal(False, reason="no ATR", symbol=symbol)
        atr_pct = atr / price * 100
        if atr_pct < 0.1 or atr_pct > 5.0:
            return Signal(False, reason=f"ATR% {atr_pct:.2f}", symbol=symbol)

        vols = [x[5] for x in m15[-VOLUME_LOOKBACK:]]
        avg_vol = sum(vols[:-1]) / max(1, len(vols) - 1)
        last_vol = vols[-1]
        if avg_vol > 0 and last_vol < avg_vol * VOLUME_MULT:
            return Signal(False, reason=f"low vol {last_vol/avg_vol:.2f}x", symbol=symbol)

        side = None
        if trend_up and RSI_LONG_MIN <= rsi1 <= RSI_LONG_MAX:
            side = "LONG"
        elif ENABLE_SHORTS and trend_down and RSI_SHORT_MIN <= rsi1 <= RSI_SHORT_MAX:
            side = "SHORT"
        if side is None:
            return Signal(False, symbol=symbol,
                          reason=f"no align (4h={'up' if trend_up else 'down'} rsi={rsi1:.0f})")

        tech_conf = max(1, min(10, int(10 - abs(atr_pct - 1.2) * 2)))

        sent, bd = await sentiment_score(symbol, side)
        fund, fbd = await fundamental_score(symbol, side)

        if fund < MIN_FUNDAMENTAL_SCORE:
            return Signal(False, symbol=symbol,
                          reason=f"fund {fund:+.2f}<{MIN_FUNDAMENTAL_SCORE}")

        sent_10 = (sent + 1) * 5
        fund_10 = (fund + 1) * 5
        w_sent = SENTIMENT_WEIGHT
        w_fund = FUNDAMENTAL_WEIGHT
        w_tech = max(0.0, 1.0 - w_sent - w_fund)
        total = tech_conf * w_tech + sent_10 * w_sent + fund_10 * w_fund

        if total < MIN_TOTAL_SCORE:
            return Signal(False, symbol=symbol,
                          reason=(f"score {total:.1f}<{MIN_TOTAL_SCORE} "
                                  f"(tech {tech_conf} sent {sent:+.2f} fund {fund:+.2f})"))

        if side == "LONG":
            sl = price - SL_ATR_MULT * atr
        else:
            sl = price + SL_ATR_MULT * atr

        reason = (f"4h={'up' if trend_up else 'down'} RSI1h={rsi1:.0f} "
                  f"ATR%={atr_pct:.2f} vol={last_vol/avg_vol:.1f}x "
                  f"tech={tech_conf}/10 sent={sent:+.2f} fund={fund:+.2f} tot={total:.1f}")

        return Signal(True, side, int(total), price, sl, 0, atr, reason, symbol,
                      sent_score=sent, breakdown={"sent": bd, "fund": fbd})
    except Exception as e:
        log.exception(f"compute_signal {symbol}")
        return Signal(False, reason=str(e)[:80], symbol=symbol)


def _prep_exchange(keys):
    ex = make_exchange(keys, keys.get("exchange"))
    if SANDBOX:
        try:
            ex.set_sandbox_mode(True)
        except Exception as e:
            log.warning(f"sandbox: {e}")
    return ex


def _round_amount(ex, symbol, amount):
    try:
        return float(ex.amount_to_precision(symbol, amount))
    except Exception:
        return float(amount)


async def _equity_usdt(ex):
    try:
        b = await ex.fetch_balance()
        return float((b.get("total") or {}).get("USDT") or 0)
    except Exception:
        return 0.0


async def _place(ex, symbol, side, amount):
    try:
        o = await ex.create_order(symbol, "market", side, amount)
        try:
            t = await ex.fetch_ticker(symbol)
            px = float(t.get("last") or 0)
        except Exception:
            px = float(o.get("price") or 0)
        return True, o, px
    except Exception as e:
        log.warning(f"order fail {symbol} {side} {amount}: {e}")
        return False, str(e)[:160], 0.0


async def _place_native_sl(ex, exchange_name, symbol, side, amount, sl_price):
    if not ENABLE_NATIVE_SL:
        return "", "disabled"

    if side == "LONG":
        trigger = sl_price * (1 - NATIVE_SL_OFFSET_PCT / 100.0)
        order_side = "sell"
    else:
        trigger = sl_price * (1 + NATIVE_SL_OFFSET_PCT / 100.0)
        order_side = "buy"

    ex_name = (exchange_name or "").lower()

    try:
        if ex_name == "binance":
            try:
                trigger = float(ex.price_to_precision(symbol, trigger))
            except Exception:
                pass
            limit_price = trigger * (0.995 if side == "LONG" else 1.005)
            try:
                limit_price = float(ex.price_to_precision(symbol, limit_price))
            except Exception:
                pass
            params = {"stopPrice": trigger, "timeInForce": "GTC"}
            try:
                order = await ex.create_order(symbol, "STOP_LOSS_LIMIT", order_side,
                                              amount, limit_price, params)
                return str(order.get("id", "")), ""
            except Exception as e:
                return "", f"binance SL: {str(e)[:80]}"

        if ex_name == "okx":
            try:
                trigger = float(ex.price_to_precision(symbol, trigger))
            except Exception:
                pass
            params = {"stopLossPrice": trigger, "triggerPrice": trigger}
            try:
                order = await ex.create_order(symbol, "market", order_side, amount, None, params)
                return str(order.get("id", "")), ""
            except Exception:
                try:
                    order = await ex.create_order(symbol, "stop", order_side, amount, None, params)
                    return str(order.get("id", "")), ""
                except Exception as e2:
                    return "", f"okx SL: {str(e2)[:80]}"

        return "", f"unsupported exchange {ex_name}"
    except Exception as e:
        return "", f"native SL: {str(e)[:100]}"


async def _cancel_native_sl(ex, symbol, order_id):
    if not order_id:
        return True
    try:
        await ex.cancel_order(order_id, symbol)
        return True
    except Exception as e:
        log.warning(f"cancel native SL {order_id} {symbol}: {e}")
        try:
            await ex.cancel_all_orders(symbol)
            return True
        except Exception as e2:
            log.warning(f"cancel_all {symbol}: {e2}")
    return False


async def _move_native_sl(ex, p, new_sl_price, new_amount=None):
    if not ENABLE_NATIVE_SL:
        return
    old_id = p["native_sl_id"] or ""
    if old_id:
        await _cancel_native_sl(ex, p["symbol"], old_id)

    amount = float(new_amount if new_amount is not None else (p["size"] or 0))
    if amount <= 0:
        return
    try:
        amount = float(ex.amount_to_precision(p["symbol"], amount))
    except Exception:
        pass

    try:
        ex_name = ex.id
    except Exception:
        ex_name = ""

    new_id, err = await _place_native_sl(ex, ex_name, p["symbol"], p["side"], amount, new_sl_price)
    if new_id:
        with db() as c:
            c.execute("UPDATE positions SET native_sl_id=?, native_sl_price=? WHERE id=?",
                      (new_id, new_sl_price, p["id"]))
            c.commit()
    elif err and err != "disabled":
        log.warning(f"move native SL {p['symbol']}: {err}")


_BOT = None


def bind_bot(bot):
    global _BOT
    _BOT = bot
    marketing_bind_bot(bot)


async def _notify(uid, text):
    if _BOT is None:
        return
    try:
        await _BOT.send_message(uid, text)
    except Exception as e:
        log.warning(f"notify {uid}: {e}")


async def _risk_check(uid, ex=None, symbol=None):
    with db() as c:
        u = c.execute("SELECT consecutive_losses, halted_until FROM users WHERE user_id=?",
                      (uid,)).fetchone()
    if u and u["halted_until"]:
        if parse_dt(u["halted_until"]) > now_utc():
            return False
    if u and u["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        halt_user(uid, 24, "consecutive losses")
        await _notify(uid, "🛑 Halted 24h — 5 losses in a row")
        return False

    if ex is not None and MAX_DAILY_LOSS_PCT > 0:
        try:
            current_equity = await _equity_usdt(ex)
        except Exception:
            current_equity = 0
        if current_equity > 0:
            snap_val, snap_date = get_equity_snapshot(uid)
            today = now_utc().date().isoformat()
            if snap_date != today or snap_val <= 0:
                set_equity_snapshot(uid, current_equity, today)
                snap_val = current_equity
            loss_pct = (current_equity - snap_val) / snap_val * 100.0
            if loss_pct <= -MAX_DAILY_LOSS_PCT:
                set_state(f"TRADING_ENABLED_{uid}", "false")
                await _notify(uid, f"🛑 Daily loss {loss_pct:.1f}% — paused today")
                return False

    if MAX_TRADES_PER_DAY > 0:
        count, _ = get_trades_today(uid)
        if count >= MAX_TRADES_PER_DAY:
            await _notify(uid, f"⏸ Daily cap {count}/{MAX_TRADES_PER_DAY}")
            return False

    if symbol and MAX_TRADES_PER_SYMBOL_PER_DAY > 0:
        if count_trades_today_for_symbol(uid, symbol) >= MAX_TRADES_PER_SYMBOL_PER_DAY:
            return False

    return True


async def _open_position(uid, ex, sig, keys_exchange=None):
    if sig.side == "SHORT" and not ENABLE_SHORTS:
        return False

    equity = await _equity_usdt(ex)
    if equity <= 0:
        await _notify(uid, f"⚠️ {sig.symbol}: no USDT")
        return False

    risk_usdt = equity * (RISK_PCT / 100.0)
    dist = abs(sig.price - sig.sl)
    if dist <= 0:
        return False
    amount = risk_usdt / dist

    if MAX_POSITION_USDT > 0:
        max_units = MAX_POSITION_USDT / sig.price
        if amount > max_units:
            amount = max_units

    if amount * sig.price < MIN_ORDER_USDT:
        await _notify(uid, f"⚠️ {sig.symbol}: below min ${MIN_ORDER_USDT}")
        return False
    amount = _round_amount(ex, sig.symbol, amount)
    if amount <= 0:
        return False

    side = "buy" if sig.side == "LONG" else "sell"
    ok, o, px = await _place(ex, sig.symbol, side, amount)
    if not ok:
        log_trade(uid, sig.symbol, sig.side, amount, 0, "", "ERROR", o)
        return False
    px = px or sig.price
    rpu = abs(px - sig.sl)

    if sig.side == "LONG":
        tp1 = px + TP1_R * rpu
        tp2 = px + TP2_R * rpu
        tp3 = px + TP3_R * rpu
    else:
        tp1 = px - TP1_R * rpu
        tp2 = px - TP2_R * rpu
        tp3 = px - TP3_R * rpu

    with db() as c:
        c.execute("""INSERT INTO positions
            (user_id,symbol,side,entry_price,sl,tp,tp1,tp2,tp3,size,original_amount,
             tranche_hit,trail_active,trail_sl,peak_price,atr_at_entry,risk_per_unit,
             native_sl_id,native_sl_price,open,opened_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?,?,'',0,1,?)""",
            (uid, sig.symbol, sig.side, px, sig.sl, tp3, tp1, tp2, tp3,
             amount, amount, px, sig.atr, rpu, now_utc().isoformat()))
        c.commit()
        row = c.execute("SELECT last_insert_rowid() id").fetchone()
        pid = row["id"] if row else 0

    log_trade(uid, sig.symbol, sig.side, amount, px, o.get("id", ""), "OPEN")
    incr_trades_today(uid)

    native_sl_id = ""
    sl_id, sl_err = await _place_native_sl(ex, keys_exchange, sig.symbol, sig.side, amount, sig.sl)
    if sl_id:
        native_sl_id = sl_id
        with db() as c:
            c.execute("UPDATE positions SET native_sl_id=?, native_sl_price=? WHERE id=?",
                      (sl_id, sig.sl, pid))
            c.commit()
    elif sl_err and sl_err != "disabled":
        log.warning(f"native SL missing {sig.symbol}: {sl_err}")

    sl_tag = "🛡 native" if native_sl_id else "⚠️ bot-only"
    await _notify(
        uid,
        f"🟢 Opened {sig.side} {sig.symbol}\n"
        f"Qty: {amount}\nEntry: {px:.6f}\n"
        f"SL: {sig.sl:.6f} ({sl_tag})\n"
        f"TP1 (+{TP1_R}R): {tp1:.6f}\n"
        f"TP2 (+{TP2_R}R): {tp2:.6f}\n"
        f"TP3 (+{TP3_R}R): {tp3:.6f}\n"
        f"Score: {sig.confidence}/10 | {sig.reason}"
    )
    return True


async def _close_position(uid, ex, pos, reason, price, amount=None, tranche=0):
    remaining = float(pos["size"] or 0)
    if remaining <= 0:
        return False
    close_amt = remaining if amount is None else min(amount, remaining)
    close_amt = _round_amount(ex, pos["symbol"], close_amt)
    if close_amt <= 0:
        return False

    side = "sell" if pos["side"] == "LONG" else "buy"
    ok, o, px = await _place(ex, pos["symbol"], side, close_amt)
    if not ok:
        await _notify(uid, f"⚠️ close fail {pos['symbol']}: {o}")
        return False
    px = px or price

    pnl = (px - pos["entry_price"]) * close_amt
    if pos["side"] == "SHORT":
        pnl = -pnl

    new_size = remaining - close_amt

    native_sl_id = pos["native_sl_id"] or ""
    if native_sl_id and new_size <= 1e-12:
        await _cancel_native_sl(ex, pos["symbol"], native_sl_id)

    with db() as c:
        c.execute("UPDATE positions SET size=?, pnl=pnl+?, tranche_hit=? WHERE id=?",
                  (new_size, pnl, max(int(pos["tranche_hit"] or 0), tranche), pos["id"]))
        if new_size <= 1e-12:
            c.execute("UPDATE positions SET open=0, closed_at=?, native_sl_id='', native_sl_price=0 WHERE id=?",
                      (now_utc().isoformat(), pos["id"]))
        c.execute("UPDATE users SET daily_pnl=daily_pnl+?, weekly_pnl=weekly_pnl+? WHERE user_id=?",
                  (pnl, pnl, uid))
        if new_size <= 1e-12:
            if pnl < 0:
                c.execute("UPDATE users SET consecutive_losses=consecutive_losses+1 WHERE user_id=?", (uid,))
            else:
                c.execute("UPDATE users SET consecutive_losses=0 WHERE user_id=?", (uid,))
        c.commit()

    log_trade(uid, pos["symbol"], pos["side"], close_amt, px, o.get("id", ""), f"CLOSE_{reason}")
    tag = {"TP1": "🎯", "TP2": "🎯🎯", "TP3": "🏆", "SL": "🛑",
           "TRAIL": "📉", "TIME": "⏱", "MANUAL": "✋"}.get(reason, "❌")
    await _notify(uid, f"{tag} {reason} {pos['symbol']} @ {px:.6f}  PnL ${pnl:+.2f}")

    if new_size <= 1e-12 and pnl > 0:
        try:
            await announce_win(uid, pos["symbol"], pos["side"], pnl)
        except Exception as e:
            log.warning(f"announce_win: {e}")
    return True


async def trade_for_user(uid, bot=None, broadcast=False):
    if bot is not None:
        bind_bot(bot)

    async with user_lock(uid):
        keys = get_keys(uid)
        if not keys:
            if broadcast:
                await _notify(uid, "❌ /setkeys first")
            return
        lic = license_info(uid)
        if not lic.get("valid"):
            if broadcast:
                await _notify(uid, "❌ No license")
            return
        if not trading_enabled(uid):
            return

        with db() as c:
            n = c.execute("SELECT COUNT(*) n FROM positions WHERE user_id=? AND open=1",
                          (uid,)).fetchone()["n"]
        if n >= MAX_POSITIONS:
            if broadcast:
                await _notify(uid, f"⏸ Max positions {n}/{MAX_POSITIONS}")
            return

        ex = _prep_exchange(keys)
        try:
            await ex.load_markets()
            syms = SYMBOLS.get(lic["tier"], SYMBOLS["BASIC"])
            for s in syms:
                if n >= MAX_POSITIONS:
                    break

                if not await _risk_check(uid, ex, s):
                    break

                with db() as c:
                    existing = c.execute(
                        "SELECT 1 FROM positions WHERE user_id=? AND symbol=? AND open=1",
                        (uid, s)).fetchone()
                if existing:
                    continue

                lt = last_trade_time(uid, s)
                if lt and (now_utc() - lt) < timedelta(minutes=COOLDOWN_MIN):
                    continue

                sig = await compute_signal(ex, s)
                if not sig.ok:
                    if broadcast:
                        await _notify(uid, f"⏸ {s}: {sig.reason}")
                    continue

                if broadcast:
                    await _notify(uid, f"🔎 {s} {sig.side} {sig.confidence}/10\n{sig.reason}"
