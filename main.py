# main.py
import os, asyncio, threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
)
from config import (
    TELEGRAM_TOKEN, USDT_WALLET, ADMIN_IDS, LIVE_MODE, SANDBOX, AUTO_TRADE,
    AUTO_INTERVAL_MINUTES, MAX_POSITIONS, TIERS, SYMBOLS, log,
    require_production_config, init_db, db,
    create_user, license_info, grant_trial,
    make_exchange, save_keys, get_keys, detect_exchange_args,
    create_invoice, get_invoice, settle_payment,
    verify_trc20_usdt, to_dec, parse_dt, now_utc,
    daily_pnl, trading_enabled, set_state, open_positions,
    RISK_PCT, MAX_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSSES,
    SL_ATR_MULT, TP1_R, TP2_R, TP3_R, TP1_PCT, TP2_PCT,
    TRAIL_AFTER_R, TRAIL_ATR_MULT, TIME_STOP_HOURS,
    SENTIMENT_WEIGHT, MIN_TOTAL_SCORE,
    FUNDAMENTAL_WEIGHT, MIN_FUNDAMENTAL_SCORE,
    MAX_TRADES_PER_DAY, MAX_POSITION_USDT, ENABLE_NATIVE_SL,
    ENABLE_MARKETING, MARKETING_CHANNEL_ID, MARKETING_CHANNEL_URL,
    BOT_USERNAME, REFERRAL_REWARD_PCT, REFERRAL_UNLOCK_COUNT,
    SHARE_WIN_THRESHOLD, DAILY_TIP_HOUR_UTC,
)
from security import rate_ok, clean_tx_hash, clean_symbol
from core import (
    trade_for_user, user_lock, monitor_job, auto_job, equity_snapshot_job,
    backup_db, bind_bot, _prep_exchange, _close_position, compute_signal,
)
from marketing import (
    bind_bot as marketing_bind_bot,
    credit_referrer, referral_count, referral_earnings,
    referral_unlocked_months, build_referral_link,
    share_text_win, share_text_invite,
    top_referrers, top_traders,
    welcome_banner, social_proof_block, value_prop,
    post_daily_tip,
)


def is_admin(uid):
    return uid in ADMIN_IDS


async def _safe_reply(target, text, **kw):
    try:
        await target.reply_text(text, **kw)
    except Exception as e:
        log.warning(f"reply: {e}")


# ---------------- user commands ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or ""
    ref = context.args[0] if context.args else None
    try:
        create_user(uid, username, ref)
    except Exception:
        log.exception("create_user")

    lic = license_info(uid) or {"valid": False, "tier": "NONE"}

    kb = [
        [InlineKeyboardButton("🎁 FREE Trial", callback_data="trial"),
         InlineKeyboardButton("💳 Subscribe", callback_data="buy")],
        [InlineKeyboardButton("🔑 Set Keys", callback_data="setkeys"),
         InlineKeyboardButton("📊 Trade", callback_data="trade")],
        [InlineKeyboardButton("👥 Invite & Earn", callback_data="referral"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📈 Status", callback_data="status"),
         InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("📡 Signals", callback_data="signals"),
         InlineKeyboardButton("🆘 Help", callback_data="help")],
    ]
    if MARKETING_CHANNEL_URL:
        kb.append([InlineKeyboardButton("📣 Our Channel", url=MARKETING_CHANNEL_URL)])

    admin = " 👑 ADMIN" if is_admin(uid) else ""
    banner = welcome_banner()
    proof = social_proof_block(limit=3)
    props = value_prop()

    txt = (
        f"{banner}"
        f"Welcome {username or uid}!{admin}\n\n"
        f"*{lic['tier']}* license {'✅' if lic['valid'] else '❌ (start with /trial)'}\n\n"
        f"*What you get*\n{props}\n"
        f"{proof}"
        f"*Tiers*\n"
        f"• BASIC ${TIERS['BASIC']['price']} — 2 pairs / 60 days\n"
        f"• PRO ${TIERS['PRO']['price']} — 3 pairs / 60 days\n"
        f"• ELITE ${TIERS['ELITE']['price']} — 7 pairs / 60 days\n\n"
        f"👇 Choose:"
    )
    await update.message.reply_text(
        txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    d = q.data or ""
    try:
        if d == "trial":
            await trial_cmd(update, context, True)
        elif d == "buy":
            await buy_cmd(update, context, True)
        elif d == "setkeys":
            await _safe_reply(q.message,
                              "Use:\n`/setkeys okx KEY SECRET PASSPHRASE`\n"
                              "`/setkeys binance KEY SECRET`\n\n"
                              "🔒 Keys are encrypted at rest and removed from chat.",
                              parse_mode="Markdown")
        elif d == "trade":
            await trade_cmd(update, context, True)
        elif d == "referral":
            await referral_cmd(update, context, True)
        elif d == "leaderboard":
            await leaderboard_from_callback(q, context)
        elif d == "status":
            await status_cmd(update, context, True)
        elif d == "balance":
            await balance_cmd(update, context, True)
        elif d == "signals":
            await signals_cmd(update, context)
        elif d == "help":
            await _safe_reply(q.message, HELP_TEXT, parse_mode="Markdown")
        elif d.startswith("sub_"):
            parts = d.split("_", 1)
            if len(parts) < 2 or parts[1] not in TIERS:
                await _safe_reply(q.message, "❌ Invalid tier")
                return
            tier = parts[1]
            inv = create_invoice(q.from_user.id, tier)
            if not inv:
                await _safe_reply(q.message, "❌ Invoice failed")
                return
            await _safe_reply(q.message,
                              f"💳 *{tier} — ${TIERS[tier]['price']}*\n\n"
                              f"Invoice: `{inv['invoice_id']}`\n"
                              f"*Send exactly* `${inv['exact']:.2f}` USDT (TRC20)\n"
                              f"To: `{USDT_WALLET}`\n\n"
                              f"⏱ 30 min\nThen: `/verify {inv['invoice_id']} TX_HASH`",
                              parse_mode="Markdown")
        else:
            await _safe_reply(q.message, "❓ Unknown action")
    except Exception:
        log.exception(f"cb {d}")
        try:
            await q.message.reply_text("⚠️ Error, try again")
        except Exception:
            pass


async def trial_cmd(update, context, is_cb=False):
    uid = update.callback_query.from_user.id if is_cb else update.effective_user.id
    target = update.callback_query.message if is_cb else update.message
    if not rate_ok(f"trial:{uid}"):
        await _safe_reply(target, "⏳ Wait a minute")
        return
    ok, msg = grant_trial(uid)
    if ok:
        await _safe_reply(target, "🎁 Trial active (BASIC, 24h)\nUse /setkeys then /trade")
    else:
        await _safe_reply(target, f"❌ {msg}\nUse /buy")


async def buy_cmd(update, context, is_cb=False):
    kb = [
        [InlineKeyboardButton(f"BASIC ${TIERS['BASIC']['price']}", callback_data="sub_BASIC")],
        [InlineKeyboardButton(f"PRO ${TIERS['PRO']['price']}", callback_data="sub_PRO")],
        [InlineKeyboardButton(f"ELITE ${TIERS['ELITE']['price']}", callback_data="sub_ELITE")],
    ]
    target = update.callback_query.message if is_cb else update.message
    await _safe_reply(target, "💳 Choose tier:", reply_markup=InlineKeyboardMarkup(kb))


async def setkeys_cmd(update, context):
    uid = update.effective_user.id
    if not rate_ok(f"setkeys:{uid}"):
        await _safe_reply(update.message, "⏳ Wait a minute")
        return

    parsed = detect_exchange_args(context.args or [])
    if not parsed:
        await _safe_reply(update.message,
                          "Usage:\n`/setkeys okx KEY SECRET PASSPHRASE`\n"
                          "`/setkeys binance KEY SECRET`",
                          parse_mode="Markdown")
        return

        exchange, ak, sec, pp = parsed
    keys = {"exchange": exchange, "apiKey": ak, "secret": sec, "password": pp}
    ex = make_exchange(keys, exchange, sandbox=SANDBOX)
    try:
        await ex.load_markets()
        bal = await ex.fetch_balance()
        usdt = float((bal.get("total") or {}).get("USDT") or 0)
        save_keys(uid, exchange, ak, sec, pp)
        await _safe_reply(update.message,
                          f"✅ {exchange.upper()} keys saved & verified!\n"
                          f"USDT: ${usdt:.2f}\n\nUse /balance /trade")
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id,
                                             message_id=update.message.message_id)
        except Exception:
            pass
    except Exception as e:
        await _safe_reply(update.message, f"❌ Keys invalid: {str(e)[:120]}")
    finally:
        try:
            await ex.close()
        except Exception:
            pass


async def trade_cmd(update, context, is_cb=False):
    uid = update.callback_query.from_user.id if is_cb else update.effective_user.id
    target = update.callback_query.message if is_cb else update.message
    if not rate_ok(f"trade:{uid}"):
        await _safe_reply(target, "⏳ Wait a minute")
        return
    try:
        await _safe_reply(target, "🔍 Scanning…")
        await trade_for_user(uid, context.bot, broadcast=True)
    except Exception as e:
        log.exception("trade_cmd")
        await _safe_reply(target, f"⚠️ {str(e)[:120]}")


async def signals_cmd(update, context):
    uid = update.effective_user.id
    if not rate_ok(f"signals:{uid}"):
        await _safe_reply(update.message, "⏳ Wait a minute")
        return
    keys = get_keys(uid)
    if not keys:
        await _safe_reply(update.message, "❌ /setkeys first")
        return
    lic = license_info(uid)
    if not lic.get("valid"):
        await _safe_reply(update.message, "❌ No license")
        return
    ex = _prep_exchange(keys)
    try:
        await ex.load_markets()
        syms = SYMBOLS.get(lic["tier"], SYMBOLS["BASIC"])
        lines = [f"📡 Signals ({lic['tier']})"]
        for s in syms:
            sig = await compute_signal(ex, s)
            if sig.ok:
                fb = (sig.breakdown or {}).get("fund", {})
                extra = ""
                if fb:
                    extra = (f"\n   🏛 mcap ${fb.get('mcap', 0)/1e6:.0f}M "
                             f"vol24 ${fb.get('vol24', 0)/1e6:.0f}M "
                             f"dev {fb.get('commits', 0)}/4w")
                lines.append(
                    f"✅ {s} {sig.side} {sig.confidence}/10 @ {sig.price:.6f}\n"
                    f"   SL {sig.sl:.6f}{extra}\n   {sig.reason}"
                )
            else:
                lines.append(f"⏸ {s} — {sig.reason}")
        await _safe_reply(update.message, "\n".join(lines))
    except Exception as e:
        await _safe_reply(update.message, f"❌ {str(e)[:120]}")
    finally:
        try:
            await ex.close()
        except Exception:
            pass


async def positions_cmd(update, context):
    uid = update.effective_user.id
    pos = open_positions(uid)
    if not pos:
        await _safe_reply(update.message, "📭 No open positions")
        return
    lines = ["📍 *Open positions:*\n"]
    for p in pos:
        pnl = float(p["pnl"] or 0)
        native = "🛡" if (p["native_sl_id"] or "") else "⚠️"
        lines.append(
            f"• {p['symbol']} {p['side']} entry {p['entry_price']:.6f}\n"
            f"  SL {p['sl']:.6f} {native} | TP1 {p['tp1']:.6f} "
            f"TP2 {p['tp2']:.6f} TP3 {p['tp3']:.6f}\n"
            f"  size {p['size']:.6f} tranche {p['tranche_hit']}/3 PnL ${pnl:+.2f}"
        )
    await _safe_reply(update.message, "\n".join(lines), parse_mode="Markdown")


async def balance_cmd(update, context, is_cb=False):
    uid = update.callback_query.from_user.id if is_cb else update.effective_user.id
    target = update.callback_query.message if is_cb else update.message
    keys = get_keys(uid)
    if not keys:
        await _safe_reply(target, "❌ /setkeys first")
        return
    ex = _prep_exchange(keys)
    try:
        await ex.load_markets()
        b = await ex.fetch_balance()
        free = float((b.get("free") or {}).get("USDT") or 0)
        total = float((b.get("total") or {}).get("USDT") or free)
        await _safe_reply(target,
                          f"💰 *{keys['exchange'].upper()} Balance*\n"
                          f"Free: ${free:.2f}\nTotal: ${total:.2f}",
                          parse_mode="Markdown")
    except Exception as e:
        await _safe_reply(target, f"❌ {str(e)[:120]}")
    finally:
        try:
            await ex.close()
        except Exception:
            pass


async def status_cmd(update, context, is_cb=False):
    uid = update.callback_query.from_user.id if is_cb else update.effective_user.id
    target = update.callback_query.message if is_cb else update.message
    lic = license_info(uid) or {"valid": False, "tier": "NONE"}
    pos = open_positions(uid) or []
    dp, wp = daily_pnl(uid)
    en = trading_enabled(uid)
    keys = get_keys(uid)
    ex_name = keys["exchange"].upper() if keys else "—"
    txt = (
        f"📈 *Status v8.3*\n"
        f"License: {lic.get('tier', 'NONE')} {'✅' if lic.get('valid') else '❌'}\n"
        f"Exchange: {ex_name}\n"
        f"Trading: {'🟢 ON' if en else '🔴 OFF'}\n"
        f"Daily PnL: ${float(dp):+.2f}  Weekly: ${float(wp):+.2f}\n"
        f"Open: {len(pos)}/{MAX_POSITIONS}\n"
        f"Auto: {'ON' if AUTO_TRADE else 'OFF'} {AUTO_INTERVAL_MINUTES}m\n"
        f"Native SL: {'ON' if ENABLE_NATIVE_SL else 'OFF'}\n"
        f"LIVE: {LIVE_MODE}  SANDBOX: {SANDBOX}"
    )
    await _safe_reply(target, txt, parse_mode="Markdown")


async def close_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await _safe_reply(update.message, "Usage: /close BTC/USDT")
        return
    sym = clean_symbol(context.args[0])
    if not sym:
        await _safe_reply(update.message, "❌ Bad symbol")
        return
    keys = get_keys(uid)
    if not keys:
        await _safe_reply(update.message, "❌ /setkeys first")
        return
    with db() as c:
        pos = c.execute("SELECT * FROM positions WHERE user_id=? AND symbol=? AND open=1",
                        (uid, sym)).fetchone()
    if not pos:
        await _safe_reply(update.message, "❌ No open position")
        return
    ex = _prep_exchange(keys)
    try:
        await ex.load_markets()
        t = await ex.fetch_ticker(sym)
        price = float(t.get("last") or 0)
        ok = await _close_position(uid, ex, pos, "MANUAL", price)
        await _safe_reply(update.message, "✅ Closed" if ok else "❌ Close failed")
    except Exception as e:
        await _safe_reply(update.message, f"❌ {str(e)[:120]}")
    finally:
        try:
            await ex.close()
        except Exception:
            pass


async def referral_cmd(update, context, is_cb=False):
    uid = update.callback_query.from_user.id if is_cb else update.effective_user.id
    target = update.callback_query.message if is_cb else update.message

    count = referral_count(uid)
    earned = referral_earnings(uid)
    unlocked = referral_unlocked_months(uid)
    link = build_referral_link(uid)
    progress = count % REFERRAL_UNLOCK_COUNT if REFERRAL_UNLOCK_COUNT > 0 else 0
    remaining = (REFERRAL_UNLOCK_COUNT - progress) if REFERRAL_UNLOCK_COUNT > 0 else 0

    share_txt = share_text_invite(uid)
    share_url = f"https://t.me/share/url?url={link}&text={share_txt}"

    kb = [
        [InlineKeyboardButton("📤 Share Invite", url=share_url)],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
    ]

    txt = (
        f"👥 *Invite & Earn*\n\n"
        f"*Your link*\n`{link}`\n\n"
        f"*Stats*\n"
        f"Referrals: *{count}*\n"
        f"Earned: *${earned:.2f}*\n"
        f"Free months unlocked: *{unlocked}*\n\n"
        f"*How it works*\n"
        f"• Friend joins via your link\n"
        f"• Friend buys any tier\n"
        f"• You get *{REFERRAL_REWARD_PCT}%* cash credit\n"
        f"• Every *{REFERRAL_UNLOCK_COUNT}* referrals → *1 free month*\n\n"
        f"{remaining} more to next free month."
    )
    await _safe_reply(target, txt, reply_markup=InlineKeyboardMarkup(kb),
                      parse_mode="Markdown", disable_web_page_preview=True)


async def leaderboard_cmd(update, context):
    refs = top_referrers(limit=10)
    traders = top_traders(limit=10)
    lines = ["🏆 *Leaderboard*\n", "*Top Referrers*"]
    if refs:
        for i, r in enumerate(refs, 1):
            lines.append(f"{i}. `{r['inviter_id']}` — {r['n']} refs  (${float(r['earned']):.2f})")
    else:
        lines.append("_No referrals yet_")
    lines.append("\n*Top Traders (weekly)*")
    if traders:
        for i, t in enumerate(traders, 1):
            lines.append(f"{i}. `{t['user_id']}` — ${float(t['weekly_pnl']):.2f}")
    else:
        lines.append("_No wins logged yet_")
    await _safe_reply(update.message, "\n".join(lines), parse_mode="Markdown")


async def leaderboard_from_callback(q, context):
    refs = top_referrers(limit=10)
    traders = top_traders(limit=10)
    lines = ["🏆 *Leaderboard*\n", "*Top Referrers*"]
    if refs:
        for i, r in enumerate(refs, 1):
            lines.append(f"{i}. `{r['inviter_id']}` — {r['n']} refs  (${float(r['earned']):.2f})")
    else:
        lines.append("_No referrals yet_")
    lines.append("\n*Top Traders (weekly)*")
    if traders:
        for i, t in enumerate(traders, 1):
            lines.append(f"{i}. `{t['user_id']}` — ${float(t['weekly_pnl']):.2f}")
    else:
        lines.append("_No wins logged yet_")
    await _safe_reply(q.message, "\n".join(lines), parse_mode="Markdown")


async def share_cmd(update, context):
    uid = update.effective_user.id
    with db() as c:
        row = c.execute(
            "SELECT symbol, side, pnl FROM positions "
            "WHERE user_id=? AND open=0 AND pnl>0 "
            "ORDER BY closed_at DESC LIMIT 1",
            (uid,)
        ).fetchone()
    if not row:
        await _safe_reply(update.message, "📭 No winning trade yet to share.")
        return
    text = share_text_win(row["symbol"], row["side"], float(row["pnl"]))
    link = build_referral_link(uid)
    share_url = f"https://t.me/share/url?url={link}&text={text}"
    kb = [[InlineKeyboardButton("📤 Share this win", url=share_url)]]
    await _safe_reply(update.message,
                      f"🏆 *Your latest win*\n\n{text}",
                      reply_markup=InlineKeyboardMarkup(kb),
                      parse_mode="Markdown")


async def settings_cmd(update, context):
    txt = (
        f"⚙️ *Strategy Settings*\n"
        f"Risk per trade: {RISK_PCT}%\n"
        f"SL: {SL_ATR_MULT}×ATR\n"
        f"TP1: {TP1_R}R ({int(TP1_PCT*100)}%)\n"
        f"TP2: {TP2_R}R ({int(TP2_PCT*100)}%)\n"
        f"TP3: {TP3_R}R (trail remainder)\n"
        f"Trail: after +{TRAIL_AFTER_R}R at {TRAIL_ATR_MULT}×ATR\n"
        f"Time stop: {TIME_STOP_HOURS}h\n"
        f"Sentiment weight: {int(SENTIMENT_WEIGHT*100)}%\n"
        f"Fundamental weight: {int(FUNDAMENTAL_WEIGHT*100)}%\n"
        f"Min total score: {MIN_TOTAL_SCORE}/10\n"
        f"Min fundamental score: {MIN_FUNDAMENTAL_SCORE}\n"
        f"Max trades/day: {MAX_TRADES_PER_DAY}\n"
        f"Max position: ${MAX_POSITION_USDT}\n"
        f"Daily loss halt: {MAX_DAILY_LOSS_PCT}%\n"
        f"Max consecutive losses: {MAX_CONSECUTIVE_LOSSES}\n"
        f"Native exchange SL: {'ON' if ENABLE_NATIVE_SL else 'OFF'}\n"
    )
    await _safe_reply(update.message, txt, parse_mode="Markdown")


async def pause_cmd(update, context):
    set_state(f"TRADING_ENABLED_{update.effective_user.id}", "false")
    await _safe_reply(update.message, "⏸ Paused")


async def resume_cmd(update, context):
    set_state(f"TRADING_ENABLED_{update.effective_user.id}", "true")
    await _safe_reply(update.message, "▶️ Resumed")


async def users_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await _safe_reply(update.message, "❌ Not admin")
        return
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        basic = c.execute("SELECT COUNT(*) n FROM users WHERE license_tier='BASIC'").fetchone()["n"]
        pro = c.execute("SELECT COUNT(*) n FROM users WHERE license_tier='PRO'").fetchone()["n"]
        elite = c.execute("SELECT COUNT(*) n FROM users WHERE license_tier='ELITE'").fetchone()["n"]
        trials = c.execute("SELECT COUNT(*) n FROM users WHERE trial_used=1").fetchone()["n"]
        keys = c.execute("SELECT COUNT(*) n FROM users WHERE api_key IS NOT NULL").fetchone()["n"]
        today = c.execute("SELECT COUNT(*) n FROM users WHERE date(created_at)=date('now')").fetchone()["n"]
        rows = c.execute("SELECT expiry FROM users WHERE expiry IS NOT NULL").fetchall()
    active = sum(1 for r in rows if parse_dt(r["expiry"]) > now_utc())
    txt = (f"👥 *Users*\nTotal: {total}\nActive: {active}\n"
           f"BASIC {basic} | PRO {pro} | ELITE {elite}\n"
           f"Trials {trials} | Keys {keys} | New today {today}")
    await _safe_reply(update.message, txt, parse_mode="Markdown")


async def stats_cmd(update, context):
    await users_cmd(update, context)


async def admin_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await _safe_reply(update.message, "❌ Not admin")
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        paid = c.execute("SELECT COUNT(*) n FROM users WHERE license_tier!='NONE'").fetchone()["n"]
        invs = c.execute("SELECT COUNT(*) n FROM invoices WHERE status='PENDING'").fetchone()["n"]
        pnl = c.execute("SELECT SUM(daily_pnl) t FROM users").fetchone()["t"] or 0
    txt = (f"👑 *ADMIN v8.3*\nUsers: {users} (paid {paid})\nPending invoices: {invs}\n"
           f"Total PnL: ${float(pnl):.2f}\n"
           f"LIVE {LIVE_MODE}  SANDBOX {SANDBOX}  AUTO {AUTO_TRADE}  MKT {ENABLE_MARKETING}")
    await _safe_reply(update.message, txt, parse_mode="Markdown")


async def pendingrefs_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await _safe_reply(update.message, "❌ Not admin")
        return
    with db() as c:
        rows = c.execute("SELECT * FROM referral_rewards WHERE claimed=0 LIMIT 20").fetchall()
    if not rows:
        await _safe_reply(update.message, "✅ None")
        return
    txt = "Pending:\n" + "\n".join(
        f"{r['inviter_id']} ← {r['referred_id']} ({r['tier']})" for r in rows)
    await _safe_reply(update.message, txt)


async def backupnow_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await _safe_reply(update.message, "❌ Not admin")
        return
    try:
        await asyncio.to_thread(backup_db)
        await _safe_reply(update.message, "✅ Backup done")
    except Exception as e:
        await _safe_reply(update.message, f"❌ {e}")


async def broadcast_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await _safe_reply(update.message, "❌ Not admin")
        return
    if not context.args:
        await _safe_reply(update.message, "Usage: /broadcast msg")
        return
    msg = " ".join(context.args)
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=f"📢 {msg}")
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await _safe_reply(update.message, f"✅ Sent {sent}/{len(users)}")


async def checktx_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await _safe_reply(update.message, "❌ Not admin")
        return
    if not context.args:
        await _safe_reply(update.message, "Usage: /checktx TX")
        return
    tx = clean_tx_hash(context.args[0])
    if not tx:
        await _safe_reply(update.message, "❌ Bad hash")
        return
    ok, received, msg = await verify_trc20_usdt(tx, to_dec("0"), USDT_WALLET)
    await _safe_reply(update.message, f"{'✅' if ok else '❌'} {msg}\nReceived {received} USDT")


async def verify_cmd(update, context):
    uid = update.effective_user.id
    if not rate_ok(f"verify:{uid}", limit=5):
        await _safe_reply(update.message, "⏳ Wait")
        return
    if len(context.args) < 2:
        await _safe_reply(update.message, "Usage: /verify INVOICE_ID TX_HASH")
        return
    inv_id = context.args[0].upper()
    tx = clean_tx_hash(context.args[1])
    if not tx:
        await _safe_reply(update.message, "❌ Bad TX hash")
        return
    inv = get_invoice(inv_id, uid)
    if not inv:
        await _safe_reply(update.message, "❌ Invoice not found")
        return
    if inv["status"] == "PAID":
        await _safe_reply(update.message, "✅ Already paid")
        return
    if parse_dt(inv["expires_at"]) < now_utc():
        await _safe_reply(update.message, "❌ Expired — /buy new")
        return

    await _safe_reply(update.message, "🔍 Verifying on-chain…")
    async with user_lock(uid):
        inv = get_invoice(inv_id, uid)
        if not inv or inv["status"] == "PAID":
            await _safe_reply(update.message, "✅ Already paid")
            return
        expected = to_dec(inv["exact_amount"])
        ok, received, msg = await verify_trc20_usdt(tx, expected, USDT_WALLET)
        if not ok:
            await _safe_reply(update.message, f"❌ {msg}")
            return
        ok2, res = settle_payment(uid, inv_id, tx, received)
        if not ok2:
            await _safe_reply(update.message, f"❌ {res}")
            return
        try:
            credit_referrer(uid, res["tier"])
        except Exception:
            log.exception("credit_referrer")
        await _safe_reply(update.message,
                          f"✅ Payment confirmed!\nAmount: {received} USDT\n"
                          f"Tier: {res['tier']}\n"
                          f"Expires: {res['expiry'].strftime('%Y-%m-%d')}")


HELP_TEXT = (
    "🆘 *Help*\n\n"
    "/start /buy /trial /setkeys /trade /signals /positions /balance\n"
    "/status /settings /close SYMBOL /referral /leaderboard /share\n"
    "/pause /resume /verify"
)


async def help_cmd(update, context):
    await _safe_reply(update.message, HELP_TEXT, parse_mode="Markdown")


def _start_health_server():
    port = int(os.getenv("PORT", "8080"))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    try:
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception as e:
        log.warning(f"health server: {e}")


async def heartbeat(context):
    with db() as c:
        n = c.execute("SELECT COUNT(*) n FROM positions WHERE open=1").fetchone()["n"]
    log.info(f"💓 heartbeat — open positions: {n}")


async def post_init(app):
    bind_bot(app.bot)
    marketing_bind_bot(app.bot)
    cmds = [
        BotCommand("start", "🚀 Menu"),
        BotCommand("status", "📈 Status"),
        BotCommand("trade", "📊 Scan"),
        BotCommand("signals", "📡 Signals"),
        BotCommand("positions", "📍 Positions"),
        BotCommand("balance", "💰 Balance"),
        BotCommand("buy", "💳 Subscribe"),
        BotCommand("trial", "🎁 Trial"),
        BotCommand("setkeys", "🔑 Keys"),
        BotCommand("settings", "⚙️ Settings"),
        BotCommand("close", "✋ Close"),
        BotCommand("verify", "🧾 Verify"),
        BotCommand("referral", "👥 Invite & Earn"),
        BotCommand("leaderboard", "🏆 Leaderboard"),
        BotCommand("share", "📤 Share win"),
        BotCommand("pause", "⏸ Pause"),
        BotCommand("resume", "▶️ Resume"),
        BotCommand("help", "🆘 Help"),
        BotCommand("admin", "👑 Admin"),
        BotCommand("users", "👥 Users"),
        BotCommand("broadcast", "📢 Broadcast"),
        BotCommand("backupnow", "💾 Backup"),
        BotCommand("checktx", "🔍 TX"),
    ]
    await app.bot.set_my_commands(cmds)


def main():
    require_production_config()
    init_db()
    if os.getenv("PORT"):
        threading.Thread(target=_start_health_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).concurrent_updates(True).build()

    handlers = [
        ("start", start), ("trial", trial_cmd), ("buy", buy_cmd),
        ("setkeys", setkeys_cmd), ("trade", trade_cmd), ("signals", signals_cmd),
        ("positions", positions_cmd), ("balance", balance_cmd),
        ("users", users_cmd), ("stats", stats_cmd), ("admin", admin_cmd),
        ("pendingrefs", pendingrefs_cmd), ("backupnow", backupnow_cmd),
        ("broadcast", broadcast_cmd), ("checktx", checktx_cmd),
        ("verify", verify_cmd), ("referral", referral_cmd), ("status", status_cmd),
        ("settings", settings_cmd), ("close", close_cmd),
        ("leaderboard", leaderboard_cmd), ("share", share_cmd),
        ("pause", pause_cmd), ("resume", resume_cmd), ("help", help_cmd),
    ]
    for name, fn in handlers:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(cb_handler))

    if app.job_queue is None:
        raise RuntimeError("python-telegram-bot[job-queue] required")

    app.job_queue.run_repeating(monitor_job, interval=60, first=15)
    app.job_queue.run_repeating(heartbeat, interval=600, first=60)
    app.job_queue.run_repeating(equity_snapshot_job, interval=3600, first=120)

    if AUTO_TRADE:
        app.job_queue.run_repeating(auto_job, interval=AUTO_INTERVAL_MINUTES * 60, first=45)

    if ENABLE_MARKETING and MARKETING_CHANNEL_ID:
        now = datetime.now(timezone.utc)
        seconds_until = ((DAILY_TIP_HOUR_UTC - now.hour) % 24) * 3600 - now.minute * 60 - now.second
        app.job_queue.run_repeating(post_daily_tip, interval=24 * 3600,
                                    first=max(10, seconds_until))

    log.info(f"🚀 Bot v8.3 started LIVE={LIVE_MODE} SANDBOX={SANDBOX} AUTO={AUTO_TRADE}")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
