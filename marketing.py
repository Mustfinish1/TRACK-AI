# marketing.py
import asyncio, random
from config import (
    db, log, MARKETING_CHANNEL_ID, MARKETING_CHANNEL_URL, BOT_USERNAME,
    REFERRAL_REWARD_PCT, REFERRAL_UNLOCK_COUNT, SHARE_WIN_THRESHOLD,
    ENABLE_MARKETING, TIERS, now_utc, parse_dt,
)

_BOT = None


def bind_bot(bot):
    global _BOT
    _BOT = bot


def get_user_count():
    with db() as c:
        return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]


def get_active_count():
    with db() as c:
        rows = c.execute("SELECT expiry FROM users WHERE expiry IS NOT NULL").fetchall()
    return sum(1 for r in rows if parse_dt(r["expiry"]) > now_utc())


def get_total_pnl():
    with db() as c:
        r = c.execute("SELECT SUM(daily_pnl) t FROM users").fetchone()
    return float((r["t"] if r else 0) or 0)


def get_recent_wins(limit=5, min_pnl=None):
    if min_pnl is None:
        min_pnl = SHARE_WIN_THRESHOLD
    with db() as c:
        rows = c.execute(
            "SELECT user_id, symbol, side, pnl, closed_at FROM positions "
            "WHERE open=0 AND pnl>=? AND closed_at IS NOT NULL "
            "ORDER BY closed_at DESC LIMIT ?",
            (float(min_pnl), int(limit))
        ).fetchall()
    return rows


def referral_count(uid):
    with db() as c:
        r = c.execute("SELECT COUNT(*) n FROM referrals WHERE inviter_id=?", (uid,)).fetchone()
    return int(r["n"] or 0)


def referral_earnings(uid):
    with db() as c:
        r = c.execute("SELECT COALESCE(SUM(amount),0) s FROM referral_rewards "
                      "WHERE inviter_id=?", (uid,)).fetchone()
    return float(r["s"] or 0)


def referral_unlocked_months(uid):
    n = referral_count(uid)
    return n // REFERRAL_UNLOCK_COUNT if REFERRAL_UNLOCK_COUNT > 0 else 0


def credit_referrer(uid, tier):
    with db() as c:
        u = c.execute("SELECT referrer_id FROM users WHERE user_id=?", (uid,)).fetchone()
        if not u or not u["referrer_id"]:
            return
        referrer = u["referrer_id"]
        amount = TIERS.get(tier, {}).get("price", 0) * (REFERRAL_REWARD_PCT / 100.0)
        c.execute(
            "INSERT INTO referral_rewards (inviter_id, referred_id, tier, amount) "
            "VALUES (?,?,?,?)",
            (referrer, uid, tier, amount)
        )
        c.commit()
    asyncio.create_task(_notify_referrer(referrer, uid, tier, amount))


async def _notify_referrer(referrer, referred, tier, amount):
    if _BOT is None:
        return
    try:
        count = referral_count(referrer)
        earnings = referral_earnings(referrer)
        unlocked = referral_unlocked_months(referrer)
        await _BOT.send_message(
            referrer,
            f"💰 *Referral reward!*\n\n"
            f"Someone you invited just bought *{tier}*.\n"
            f"You earned: *${amount:.2f}*\n\n"
            f"Total referrals: {count}\n"
            f"Total earnings: ${earnings:.2f}\n"
            f"Free months unlocked: {unlocked}\n\n"
            f"Invite more: /referral",
            parse_mode="Markdown"
        )
    except Exception as e:
        log.warning(f"notify referrer {referrer}: {e}")


def top_referrers(limit=10):
    with db() as c:
        rows = c.execute(
            "SELECT inviter_id, COUNT(*) n, COALESCE(SUM(amount),0) earned "
            "FROM referral_rewards GROUP BY inviter_id "
            "ORDER BY n DESC, earned DESC LIMIT ?",
            (int(limit),)
        ).fetchall()
    return rows


def top_traders(limit=10):
    with db() as c:
        rows = c.execute(
            "SELECT user_id, weekly_pnl FROM users "
            "WHERE weekly_pnl IS NOT NULL AND weekly_pnl > 0 "
            "ORDER BY weekly_pnl DESC LIMIT ?",
            (int(limit),)
        ).fetchall()
    return rows


def build_referral_link(uid):
    with db() as c:
        u = c.execute("SELECT ref_code FROM users WHERE user_id=?", (uid,)).fetchone()
    code = (u["ref_code"] if u and u["ref_code"] else f"TRUCK{uid}")
    bn = BOT_USERNAME or "YourBot"
    return f"https://t.me/{bn}?start={code}"


def share_text_win(symbol, side, pnl):
    bn = BOT_USERNAME or "YourBot"
    return (
        f"🚀 Just closed a winning {side} trade on {symbol}\n"
        f"PnL: +${pnl:.2f}\n\n"
        f"Automated by @{bn} — trend + sentiment + fundamentals, "
        f"3-tranche exits, native exchange stop-loss."
    )


def share_text_invite(uid):
    link = build_referral_link(uid)
    bn = BOT_USERNAME or "YourBot"
    return (
        f"📈 I use @{bn} for automated crypto trading.\n"
        f"Signal engine: 4h trend + 1h RSI + 15m volume + sentiment + fundamentals.\n"
        f"Risk 1% per trade, 3-tranche exits, native exchange SL.\n\n"
        f"Try it free: {link}"
    )


async def post_to_channel(text, parse_mode="Markdown"):
    if not ENABLE_MARKETING or not MARKETING_CHANNEL_ID or _BOT is None:
        return False
    try:
        await _BOT.send_message(chat_id=MARKETING_CHANNEL_ID, text=text, parse_mode=parse_mode)
        return True
    except Exception as e:
        log.warning(f"channel post failed: {e}")
        return False


async def announce_win(user_id, symbol, side, pnl):
    if pnl < SHARE_WIN_THRESHOLD:
        return
    users = get_user_count()
    active = get_active_count()
    text = (
        f"🎯 *WIN ALERT*\n\n"
        f"Symbol: `{symbol}`\n"
        f"Side: {side}\n"
        f"PnL: *+${pnl:.2f}*\n\n"
        f"👥 {users} traders  •  ✅ {active} active\n"
        f"🤖 Auto-traded by our signal engine\n\n"
        f"👉 Try it: /start"
    )
    await post_to_channel(text)


async def post_daily_tip(context):
    if not ENABLE_MARKETING or not MARKETING_CHANNEL_ID:
        return
    tips = [
        "📊 *Tip of the day*\nTrend is your friend. Our bot only longs when 4h EMA50 > EMA200.",
        "📊 *Tip of the day*\nNever risk more than 1% of your account per trade. Enforced automatically.",
        "📊 *Tip of the day*\nPartial exits lock in gains. 40% at +1R, 30% at +2R, trail the rest.",
        "📊 *Tip of the day*\nNative exchange stop-loss protects you even if the bot goes offline.",
        "📊 *Tip of the day*\nSentiment + fundamentals filter out fake breakouts.",
        "📊 *Tip of the day*\n5 losses in a row → 24h auto-halt. Discipline beats revenge.",
        "📊 *Tip of the day*\nDaily loss cap of 3% means you live to trade tomorrow.",
    ]
    tip = random.choice(tips)
    users = get_user_count()
    active = get_active_count()
    await post_to_channel(tip + f"\n\n👥 {users} traders  •  ✅ {active} active licenses")


def welcome_banner():
    users = get_user_count()
    active = get_active_count()
    return (
        f"🚀 *TruckLink AutoBot v8.3*\n"
        f"👥 *{users}* traders  •  ✅ *{active}* active\n\n"
    )


def social_proof_block(limit=3):
    wins = get_recent_wins(limit=limit, min_pnl=SHARE_WIN_THRESHOLD)
    if not wins:
        return ""
    lines = ["📈 *Recent wins:*"]
    for w in wins:
        try:
            lines.append(f"• {w['symbol']} {w['side']}  +${float(w['pnl']):.2f}")
        except Exception:
            continue
    return "\n".join(lines) + "\n\n" if len(lines) > 1 else ""


def value_prop():
    return (
        "✅ 4h trend + 1h RSI + 15m volume + ATR\n"
        "✅ Sentiment (Fear&Greed + news + global)\n"
        "✅ Fundamentals (tokenomics + TVL + dev)\n"
        "✅ 3-tranche exits — 40% / 30% / trail\n"
        "✅ Native exchange stop-loss\n"
        "✅ 1% risk per trade, 3% daily loss cap\n"
        "✅ OKX + Binance\n"
  )
