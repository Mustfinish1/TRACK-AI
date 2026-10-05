# config.py
import os, sqlite3, logging, secrets, random, re, hashlib
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import ccxt.async_support as ccxt
import aiohttp

# ---------------- ENV ----------------
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN")
USDT_WALLET           = (os.getenv("USDT_WALLET", "") or "").strip()
ADMIN_IDS             = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
LIVE_MODE             = os.getenv("LIVE_MODE", "False").lower() == "true"
SANDBOX               = os.getenv("SANDBOX", "True").lower() == "true"
AUTO_TRADE            = os.getenv("AUTO_TRADE", "True").lower() == "true"
AUTO_INTERVAL_MINUTES = int(os.getenv("AUTO_INTERVAL_MINUTES", "30"))

MAX_POSITIONS         = int(os.getenv("MAX_POSITIONS", "4"))
RISK_PCT              = float(os.getenv("RISK_PCT", "1.0"))
MAX_DAILY_LOSS_PCT    = float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))
COOLDOWN_MIN          = int(os.getenv("COOLDOWN_MIN", "60"))
MIN_ORDER_USDT        = float(os.getenv("MIN_ORDER_USDT", "10"))
MAX_POSITION_USDT     = float(os.getenv("MAX_POSITION_USDT", "500"))
MAX_TRADES_PER_DAY    = int(os.getenv("MAX_TRADES_PER_DAY", "5"))
MAX_TRADES_PER_SYMBOL_PER_DAY = int(os.getenv("MAX_TRADES_PER_SYMBOL_PER_DAY", "2"))
EQUITY_SNAPSHOT_HOUR_UTC = int(os.getenv("EQUITY_SNAPSHOT_HOUR_UTC", "0"))

ENABLE_NATIVE_SL      = os.getenv("ENABLE_NATIVE_SL", "True").lower() == "true"
NATIVE_SL_OFFSET_PCT  = float(os.getenv("NATIVE_SL_OFFSET_PCT", "0.3"))

ENTRY_TF              = os.getenv("ENTRY_TF", "15m")
CONFIRM_TF            = os.getenv("CONFIRM_TF", "1h")
TREND_TF              = os.getenv("TREND_TF", "4h")
EMA_FAST              = int(os.getenv("EMA_FAST", "50"))
EMA_SLOW              = int(os.getenv("EMA_SLOW", "200"))
ATR_PERIOD            = int(os.getenv("ATR_PERIOD", "14"))
VOLUME_LOOKBACK       = int(os.getenv("VOLUME_LOOKBACK", "20"))
VOLUME_MULT           = float(os.getenv("VOLUME_MULT", "1.5"))
RSI_PERIOD            = int(os.getenv("RSI_PERIOD", "14"))
RSI_LONG_MIN          = float(os.getenv("RSI_LONG_MIN", "45"))
RSI_LONG_MAX          = float(os.getenv("RSI_LONG_MAX", "70"))
RSI_SHORT_MIN         = float(os.getenv("RSI_SHORT_MIN", "30"))
RSI_SHORT_MAX         = float(os.getenv("RSI_SHORT_MAX", "55"))

SL_ATR_MULT           = float(os.getenv("SL_ATR_MULT", "1.5"))
TP1_R                 = float(os.getenv("TP1_R", "1.0"))
TP2_R                 = float(os.getenv("TP2_R", "2.0"))
TP3_R                 = float(os.getenv("TP3_R", "3.5"))
TP1_PCT               = float(os.getenv("TP1_PCT", "0.4"))
TP2_PCT               = float(os.getenv("TP2_PCT", "0.3"))
TRAIL_AFTER_R         = float(os.getenv("TRAIL_AFTER_R", "1.0"))
TRAIL_ATR_MULT        = float(os.getenv("TRAIL_ATR_MULT", "1.5"))
TIME_STOP_HOURS       = int(os.getenv("TIME_STOP_HOURS", "12"))
ENABLE_SHORTS         = os.getenv("ENABLE_SHORTS", "False").lower() == "true"

SENTIMENT_WEIGHT      = float(os.getenv("SENTIMENT_WEIGHT", "0.25"))
FUNDAMENTAL_WEIGHT    = float(os.getenv("FUNDAMENTAL_WEIGHT", "0.15"))
MIN_TOTAL_SCORE       = float(os.getenv("MIN_TOTAL_SCORE", "6.0"))
MIN_FUNDAMENTAL_SCORE = float(os.getenv("MIN_FUNDAMENTAL_SCORE", "-0.5"))
CRYPTOPANIC_KEY       = os.getenv("CRYPTOPANIC_KEY", "")

ENABLE_MARKETING      = os.getenv("ENABLE_MARKETING", "True").lower() == "true"
MARKETING_CHANNEL_ID  = os.getenv("MARKETING_CHANNEL_ID", "").strip()
MARKETING_CHANNEL_URL = os.getenv("MARKETING_CHANNEL_URL", "").strip()
BOT_USERNAME          = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
REFERRAL_REWARD_PCT   = float(os.getenv("REFERRAL_REWARD_PCT", "10"))
REFERRAL_UNLOCK_COUNT = int(os.getenv("REFERRAL_UNLOCK_COUNT", "3"))
SHARE_WIN_THRESHOLD   = float(os.getenv("SHARE_WIN_THRESHOLD", "20"))
DAILY_TIP_HOUR_UTC    = int(os.getenv("DAILY_TIP_HOUR_UTC", "14"))

DB_PATH               = os.getenv("DB_PATH", "bot.db")
BACKUP_DIR            = os.getenv("BACKUP_DIR", "backups")

TRONGRID_API          = os.getenv("TRONGRID_API", "https://api.trongrid.io")
TRONGRID_API_KEY      = os.getenv("TRONGRID_API_KEY", "")
TRON_CONFIRMATIONS    = int(os.getenv("TRON_CONFIRMATIONS", "19"))
USDT_TRC20_CONTRACT   = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_DECIMALS         = 6

DEFAULT_EXCHANGE      = os.getenv("DEFAULT_EXCHANGE", "okx").lower()
SUPPORTED_EXCHANGES   = ("okx", "binance")

TIERS = {
    "BASIC": {"price": 20, "days": 60, "pairs": 2},
    "PRO":   {"price": 50, "days": 60, "pairs": 3},
    "ELITE": {"price": 70, "days": 60, "pairs": 7},
}
SYMBOLS = {
    "BASIC": ["BTC/USDT", "ETH/USDT"],
    "PRO":   ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "ELITE": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT",
              "BNB/USDT", "XRP/USDT", "ADA/USDT"],
}
SYMBOLS["ADMIN"] = SYMBOLS["ELITE"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("trucklink")


# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _add_column(c, table, col, ddl):
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def init_db():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, ref_code TEXT,
            referrer_id INTEGER, license_tier TEXT DEFAULT 'NONE',
            expiry TEXT, trial_used INTEGER DEFAULT 0,
            exchange TEXT DEFAULT 'okx',
            api_key TEXT, api_secret TEXT, api_passphrase TEXT,
            daily_pnl REAL DEFAULT 0, weekly_pnl REAL DEFAULT 0,
            consecutive_losses INTEGER DEFAULT 0,
            halted_until TEXT,
            equity_snapshot REAL DEFAULT 0, equity_snapshot_date TEXT,
            trades_today INTEGER DEFAULT 0, trades_today_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS invoices (
            invoice_id TEXT PRIMARY KEY, user_id INTEGER, tier TEXT,
            exact_amount TEXT, status TEXT DEFAULT 'PENDING',
            tx_hash TEXT, created_at TEXT, expires_at TEXT
        )""")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_tx ON invoices(tx_hash) WHERE tx_hash IS NOT NULL")
        c.execute("""CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            symbol TEXT, side TEXT, entry_price REAL,
            sl REAL, tp REAL, tp1 REAL DEFAULT 0, tp2 REAL DEFAULT 0, tp3 REAL DEFAULT 0,
            size REAL DEFAULT 0, original_amount REAL DEFAULT 0,
            tranche_hit INTEGER DEFAULT 0,
            trail_active INTEGER DEFAULT 0, trail_sl REAL DEFAULT 0, peak_price REAL DEFAULT 0,
            atr_at_entry REAL DEFAULT 0, risk_per_unit REAL DEFAULT 0,
            native_sl_id TEXT DEFAULT '', native_sl_price REAL DEFAULT 0,
            pnl REAL DEFAULT 0, open INTEGER DEFAULT 1,
            opened_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            symbol TEXT, side TEXT, amount REAL, price REAL,
            order_id TEXT, status TEXT, error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_symbol ON trades(user_id, symbol)")
        c.execute("""CREATE TABLE IF NOT EXISTS referrals (inviter_id INTEGER, referred_id INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS referral_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER, referred_id INTEGER, tier TEXT,
            amount REAL DEFAULT 0, claimed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS states (key TEXT PRIMARY KEY, value TEXT)""")
        _add_column(c, "users", "exchange", "TEXT DEFAULT 'okx'")
        _add_column(c, "users", "weekly_pnl", "REAL DEFAULT 0")
        _add_column(c, "users", "consecutive_losses", "INTEGER DEFAULT 0")
        _add_column(c, "users", "halted_until", "TEXT")
        _add_column(c, "users", "equity_snapshot", "REAL DEFAULT 0")
        _add_column(c, "users", "equity_snapshot_date", "TEXT")
        _add_column(c, "users", "trades_today", "INTEGER DEFAULT 0")
        _add_column(c, "users", "trades_today_date", "TEXT")
        _add_column(c, "positions", "tp1", "REAL DEFAULT 0")
        _add_column(c, "positions", "tp2", "REAL DEFAULT 0")
        _add_column(c, "positions", "tp3", "REAL DEFAULT 0")
        _add_column(c, "positions", "tranche_hit", "INTEGER DEFAULT 0")
        _add_column(c, "positions", "trail_active", "INTEGER DEFAULT 0")
        _add_column(c, "positions", "trail_sl", "REAL DEFAULT 0")
        _add_column(c, "positions", "peak_price", "REAL DEFAULT 0")
        _add_column(c, "positions", "atr_at_entry", "REAL DEFAULT 0")
        _add_column(c, "positions", "risk_per_unit", "REAL DEFAULT 0")
        _add_column(c, "positions", "native_sl_id", "TEXT DEFAULT ''")
        _add_column(c, "positions", "native_sl_price", "REAL DEFAULT 0")
        c.commit()


def now_utc(): return datetime.now(timezone.utc)


def parse_dt(s):
    if not s:
        return now_utc()
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return now_utc()


def to_dec(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(0)


def require_production_config():
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not os.getenv("ENCRYPTION_KEY"):
        missing.append("ENCRYPTION_KEY")
    if not USDT_WALLET or not USDT_WALLET.startswith("T") or len(USDT_WALLET) != 34:
        missing.append("USDT_WALLET (T... 34 chars)")
    if missing:
        raise RuntimeError(f"Missing config: {', '.join(missing)}")


def make_exchange(keys=None, exchange_name=None, sandbox=None):
    name = (exchange_name or (keys or {}).get("exchange") or DEFAULT_EXCHANGE).lower()
    if name not in SUPPORTED_EXCHANGES:
        name = DEFAULT_EXCHANGE

    if sandbox is None:
        sandbox = SANDBOX

    opts = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
    if keys:
        opts["apiKey"] = keys.get("apiKey") or ""
        opts["secret"] = keys.get("secret") or ""
        if name == "okx":
            opts["password"] = keys.get("password") or ""

    # OKX demo requires this header. set_sandbox_mode breaks OKX in newer ccxt.
    if sandbox and name == "okx":
        opts["headers"] = {"x-simulated-trading": "1"}

    if name == "binance":
        ex = ccxt.binance(opts)
    else:
        ex = ccxt.okx(opts)

    if sandbox and name == "binance":
        try:
            ex.set_sandbox_mode(True)
        except Exception:
            pass

    return ex


def detect_exchange_args(args):
    if not args:
        return None
    first = args[0].lower()
    if first in SUPPORTED_EXCHANGES:
        rest = args[1:]
        if first == "okx":
            if len(rest) < 3:
                return None
            return ("okx", rest[0], rest[1], rest[2])
        if len(rest) < 2:
            return None
        return ("binance", rest[0], rest[1], "")
    if len(args) >= 3:
        return ("okx", args[0], args[1], args[2])
    return None


def create_user(uid, username, ref_code=None):
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
            c.execute("UPDATE users SET username=? WHERE user_id=?", (username or "", uid))
            c.commit()
            return
        my_code = f"TRUCK{uid}{secrets.token_hex(2).upper()}"
        referrer = None
        if ref_code:
            r = c.execute("SELECT user_id FROM users WHERE ref_code=?", (ref_code,)).fetchone()
            if r and r["user_id"] != uid:
                referrer = r["user_id"]
        c.execute("INSERT INTO users (user_id,username,ref_code,referrer_id) VALUES (?,?,?,?)",
                  (uid, username, my_code, referrer))
        if referrer:
            c.execute("INSERT INTO referrals (inviter_id, referred_id) VALUES (?,?)", (referrer, uid))
        c.commit()


def license_info(uid):
    # --- ADMIN OVERRIDE ---
    if uid in ADMIN_IDS:
        return {"valid": True, "tier": "ADMIN", "expiry": "FOREVER"}
    # -----------------------

    with db() as c:
        u = c.execute("SELECT license_tier, expiry FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        return {"valid": False, "tier": "NONE"}
    tier = u["license_tier"] or "NONE"
    exp = u["expiry"]
    if tier == "NONE" or not exp:
        return {"valid": False, "tier": "NONE"}
    return {"valid": parse_dt(exp) > now_utc(), "tier": tier, "expiry": exp}


def grant_trial(uid):
    with db() as c:
        u = c.execute("SELECT trial_used FROM users WHERE user_id=?", (uid,)).fetchone()
        if not u:
            return False, "No user"
        if u["trial_used"]:
            return False, "Already used"
        exp = now_utc() + timedelta(days=1)
        c.execute("UPDATE users SET license_tier='BASIC', expiry=?, trial_used=1 WHERE user_id=?",
                  (exp.isoformat(), uid))
        c.commit()
    return True, "ok"


def daily_pnl(uid):
    with db() as c:
        u = c.execute("SELECT daily_pnl, weekly_pnl FROM users WHERE user_id=?", (uid,)).fetchone()
    return (to_dec(u["daily_pnl"] or 0), to_dec(u["weekly_pnl"] or 0)) if u else (Decimal(0), Decimal(0))


def trading_enabled(uid):
    with db() as c:
        r = c.execute("SELECT value FROM states WHERE key=?", (f"TRADING_ENABLED_{uid}",)).fetchone()
        if r and r["value"] == "false":
            return False
        u = c.execute("SELECT halted_until FROM users WHERE user_id=?", (uid,)).fetchone()
        if u and u["halted_until"]:
            if parse_dt(u["halted_until"]) > now_utc():
                return False
    return True


def halt_user(uid, hours, reason=""):
    with db() as c:
        c.execute("UPDATE users SET halted_until=? WHERE user_id=?",
                  ((now_utc() + timedelta(hours=hours)).isoformat(), uid))
        c.commit()
    log.warning(f"halt {uid} {hours}h: {reason}")


def set_state(k, v):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO states (key,value) VALUES (?,?)", (k, str(v)))
        c.commit()


def save_keys(uid, exchange, ak, sec, pp):
    from security import encrypt
    with db() as c:
        c.execute("UPDATE users SET exchange=?, api_key=?, api_secret=?, api_passphrase=? WHERE user_id=?",
                  (exchange, encrypt(ak), encrypt(sec), encrypt(pp or ""), uid))
        c.commit()


def get_keys(uid):
    from security import decrypt
    with db() as c:
        u = c.execute("SELECT exchange,api_key,api_secret,api_passphrase FROM users WHERE user_id=?",
                      (uid,)).fetchone()
    if not u or not u["api_key"]:
        return None
    ak = decrypt(u["api_key"])
    sec = decrypt(u["api_secret"])
    pp = decrypt(u["api_passphrase"]) if u["api_passphrase"] else ""
    if not ak or not sec:
        return None
    return {"exchange": u["exchange"] or "okx", "apiKey": ak, "secret": sec, "password": pp}


def get_equity_snapshot(uid):
    with db() as c:
        u = c.execute("SELECT equity_snapshot, equity_snapshot_date FROM users WHERE user_id=?",
                      (uid,)).fetchone()
    if not u:
        return 0.0, ""
    return float(u["equity_snapshot"] or 0), (u["equity_snapshot_date"] or "")


def set_equity_snapshot(uid, equity, date_str=None):
    if date_str is None:
        date_str = now_utc().date().isoformat()
    with db() as c:
        c.execute("UPDATE users SET equity_snapshot=?, equity_snapshot_date=? WHERE user_id=?",
                  (float(equity), date_str, uid))
        c.commit()


def get_trades_today(uid):
    today = now_utc().date().isoformat()
    with db() as c:
        u = c.execute("SELECT trades_today, trades_today_date FROM users WHERE user_id=?",
                      (uid,)).fetchone()
        if not u:
            return 0, today
        if (u["trades_today_date"] or "") != today:
            c.execute("UPDATE users SET trades_today=0, trades_today_date=? WHERE user_id=?",
                      (today, uid))
            c.commit()
            return 0, today
        return int(u["trades_today"] or 0), today


def incr_trades_today(uid):
    today = now_utc().date().isoformat()
    with db() as c:
        u = c.execute("SELECT trades_today, trades_today_date FROM users WHERE user_id=?",
                      (uid,)).fetchone()
        if u and (u["trades_today_date"] or "") == today:
            c.execute("UPDATE users SET trades_today=trades_today+1 WHERE user_id=?", (uid,))
        else:
            c.execute("UPDATE users SET trades_today=1, trades_today_date=? WHERE user_id=?",
                      (today, uid))
        c.commit()


def count_trades_today_for_symbol(uid, symbol):
    today = now_utc().date().isoformat()
    with db() as c:
        r = c.execute(
            "SELECT COUNT(*) n FROM trades WHERE user_id=? AND symbol=? "
            "AND date(created_at)=? AND status='OPEN'",
            (uid, symbol, today)
        ).fetchone()
    return int(r["n"] or 0) if r else 0


def last_trade_time(uid, symbol):
    with db() as c:
        r = c.execute("SELECT created_at FROM trades WHERE user_id=? AND symbol=? ORDER BY id DESC LIMIT 1",
                      (uid, symbol)).fetchone()
    return parse_dt(r["created_at"]) if r else None


def log_trade(uid, symbol, side, amount, price, order_id, status, error=""):
    with db() as c:
        c.execute("INSERT INTO trades (user_id,symbol,side,amount,price,order_id,status,error) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (uid, symbol, side, float(amount), float(price), str(order_id), status, error))
        c.commit()


def open_positions(uid):
    with db() as c:
        return c.execute("SELECT * FROM positions WHERE user_id=? AND open=1", (uid,)).fetchall()


def create_invoice(uid, tier):
    if tier not in TIERS:
        return None
    base = Decimal(str(TIERS[tier]["price"]))
    with db() as c:
        exact = None
        for _ in range(60):
            cents = Decimal(random.randint(1, 99)) / Decimal(100)
            cand = (base + cents).quantize(Decimal("0.01"))
            clash = c.execute("SELECT 1 FROM invoices WHERE exact_amount=? AND status='PENDING'",
                              (str(cand),)).fetchone()
            if not clash:
                exact = cand
                break
        if exact is None:
            exact = (base + Decimal("0.99")).quantize(Decimal("0.01"))
        invoice_id = f"INV{uid}{secrets.token_hex(3).upper()}"
        exp = now_utc() + timedelta(minutes=30)
        c.execute("INSERT INTO invoices (invoice_id,user_id,tier,exact_amount,created_at,expires_at) "
                  "VALUES (?,?,?,?,?,?)",
                  (invoice_id, uid, tier, str(exact), now_utc().isoformat(), exp.isoformat()))
        c.commit()
    return {"invoice_id": invoice_id, "exact": float(exact), "exact_amount": str(exact)}


def get_invoice(inv_id, uid):
    with db() as c:
        return c.execute("SELECT * FROM invoices WHERE invoice_id=? AND user_id=?", (inv_id, uid)).fetchone()


def settle_payment(uid, inv_id, tx, received):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            inv = c.execute("SELECT tier,status,tx_hash FROM invoices WHERE invoice_id=?", (inv_id,)).fetchone()
            if not inv:
                c.rollback(); return False, "Invoice not found"
            if inv["status"] == "PAID":
                c.rollback(); return False, "Already paid"
            if inv["tx_hash"] and inv["tx_hash"] != tx:
                c.rollback(); return False, "Invoice bound to another TX"
            dup = c.execute("SELECT 1 FROM invoices WHERE tx_hash=? AND invoice_id<>?",
                            (tx, inv_id)).fetchone()
            if dup:
                c.rollback(); return False, "TX already used"
            tier = inv["tier"]
            days = TIERS[tier]["days"]
            exp = now_utc() + timedelta(days=days)
            c.execute("UPDATE users SET license_tier=?, expiry=? WHERE user_id=?",
                      (tier, exp.isoformat(), uid))
            c.execute("UPDATE invoices SET status='PAID', tx_hash=?, exact_amount=? WHERE invoice_id=?",
                      (tx, str(received), inv_id))
            c.commit()
            return True, {"tier": tier, "expiry": exp, "days": days}
        except Exception:
            c.rollback()
            log.exception("settle_payment")
            return False, "DB error"


# ---------------- TRC20 ----------------
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = 0
    for x in b:
        if x == 0:
            pad += 1
        else:
            break
    return "1" * pad + (out or "")


def _hex_to_tron(hex_addr):
    hex_addr = hex_addr.lower().replace("0x", "")
    if len(hex_addr) == 42 and hex_addr.startswith("41"):
        raw = bytes.fromhex(hex_addr)
    elif len(hex_addr) == 40:
        raw = b"\x41" + bytes.fromhex(hex_addr)
    else:
        raise ValueError("bad hex")
    checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    return _b58encode(raw + checksum)


def _normalize_addr(a):
    if not a:
        return ""
    a = a.strip()
    if a.startswith("T") and len(a) == 34:
        return a
    if re.fullmatch(r"(0x)?[0-9a-fA-F]{40,42}", a):
        try:
            return _hex_to_tron(a)
        except Exception:
            return a
    return a


async def _tron_post(session, url, payload):
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
    async with session.post(url, json=payload, headers=headers,
                            timeout=aiohttp.ClientTimeout(total=15)) as r:
        return await r.json()


async def _tron_get(session, url):
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
    async with session.get(url, headers=headers,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        return await r.json()


async def verify_trc20_usdt(tx_hash, expected, wallet):
    tx_hash = (tx_hash or "").strip()
    wallet = (wallet or "").strip()
    expected = to_dec(expected or 0)
    if not _HEX64.match(tx_hash):
        return False, Decimal(0), "Invalid TX hash"
    if not (wallet.startswith("T") and len(wallet) == 34):
        return False, Decimal(0), "Wallet misconfigured"

    try:
        async with aiohttp.ClientSession() as s:
            info = await _tron_post(s, f"{TRONGRID_API}/wallet/gettransactioninfobyid", {"value": tx_hash})
            if not info or not info.get("id"):
                return False, Decimal(0), "TX not found on Tron"
            receipt = info.get("receipt") or {}
            if receipt.get("result") not in (None, "", "SUCCESS"):
                return False, Decimal(0), f"TX failed: {receipt.get('result')}"
            tx_block = info.get("blockNumber")
            if not tx_block:
                return False, Decimal(0), "TX not mined yet"
            now_blk = await _tron_post(s, f"{TRONGRID_API}/wallet/getnowblock", {})
            current = ((now_blk.get("block_header") or {}).get("raw_data") or {}).get("number", 0) or 0
            confs = max(0, current - int(tx_block))
            if confs < TRON_CONFIRMATIONS:
                return False, Decimal(0), f"{confs}/{TRON_CONFIRMATIONS} confs — retry"

            ev = await _tron_get(s, f"{TRONGRID_API}/v1/transactions/{tx_hash}/events?only_confirmed=true")
            received = None
            for e in (ev or {}).get("data", []):
                if (e.get("event_name") or "").lower() != "transfer":
                    continue
                if (e.get("contract_address") or "").lower() != USDT_TRC20_CONTRACT.lower():
                    continue
                res = e.get("result") or {}
                to_raw = res.get("to") or res.get("1")
                val_raw = res.get("value") or res.get("2")
                if _normalize_addr(to_raw or "") != wallet:
                    continue
                try:
                    received = Decimal(int(val_raw)) / (Decimal(10) ** USDT_DECIMALS)
                except Exception:
                    continue
                break

            if received is None:
                for e in (info.get("log") or []):
                    if (e.get("address") or "").lower() != USDT_TRC20_CONTRACT.lower():
                        continue
                    topics = e.get("topics") or []
                    if len(topics) < 3:
                        continue
                    try:
                        to_addr = _hex_to_tron("41" + topics[2][-40:])
                    except Exception:
                        continue
                    if to_addr != wallet:
                        continue
                    try:
                        v = int(e.get("data") or "0", 16)
                        received = Decimal(v) / (Decimal(10) ** USDT_DECIMALS)
                        break
                    except Exception:
                        continue

            if received is None:
                return False, Decimal(0), "No USDT Transfer to our wallet in this TX"
            tol = max(Decimal("0.01"), expected * Decimal("0.005"))
            if received + tol < expected:
                return False, received, f"Underpaid: {received} < {expected}"
            return True, received, f"OK — {received} USDT, {confs} confs"
    except Exception:
        log.exception("verify_trc20_usdt")
        return False, Decimal(0), "Verification error"
