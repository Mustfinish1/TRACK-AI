# sentiment.py
import time, aiohttp, asyncio
from config import log, CRYPTOPANIC_KEY

_cache: dict = {}


def _cget(k):
    v = _cache.get(k)
    return v[1] if v and time.time() < v[0] else None


def _cset(k, v, ttl):
    _cache[k] = (time.time() + ttl, v)


COIN_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "LINK": "chainlink", "PEPE": "pepe",
    "DOGE": "dogecoin", "AVAX": "avalanche-2", "MATIC": "matic-network",
    "DOT": "polkadot", "LTC": "litecoin", "TRX": "tron",
}


async def _get_json(url, ttl=300):
    cached = _cget(url)
    if cached is not None:
        return cached
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                j = await r.json()
                _cset(url, j, ttl)
                return j
    except Exception as e:
        log.warning(f"sent GET {url[:60]}: {e}")
        return None


async def fear_greed():
    j = await _get_json("https://api.alternative.me/fng/?limit=1", ttl=900)
    if not j or not j.get("data"):
        return {"value": 50, "class": "Neutral"}
    d = j["data"][0]
    return {"value": int(d.get("value", 50)), "class": d.get("value_classification", "Neutral")}


async def global_market():
    j = await _get_json("https://api.coingecko.com/api/v3/global", ttl=600)
    if not j or not j.get("data"):
        return {"btc_dom": 0, "mcap_change_24h": 0, "total_mcap": 0}
    d = j["data"]
    return {
        "btc_dom": float((d.get("market_cap_percentage") or {}).get("btc", 0)),
        "mcap_change_24h": float(d.get("market_cap_change_percentage_24h_usd", 0)),
        "total_mcap": float((d.get("total_market_cap") or {}).get("usd", 0)),
    }


async def coin_snapshot(symbol):
    base = (symbol or "").split("/")[0].upper()
    cid = COIN_IDS.get(base)
    if not cid:
        return None
    j = await _get_json(
        f"https://api.coingecko.com/api/v3/coins/{cid}"
        "?localization=false&tickers=false&community_data=false&developer_data=false",
        ttl=600,
    )
    if not j:
        return None
    md = j.get("market_data") or {}
    return {
        "price_change_24h": float(md.get("price_change_percentage_24h") or 0),
        "price_change_7d": float(md.get("price_change_percentage_7d") or 0),
        "sentiment_up_pct": float((j.get("sentiment_votes_up_percentage") or 50)),
    }


async def news_sentiment(symbol):
    if not CRYPTOPANIC_KEY:
        return 0.0
    base = (symbol or "").split("/")[0].upper()
    url = (f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_KEY}"
           f"&currencies={base}&filter=hot")
    j = await _get_json(url, ttl=1800)
    if not j or "results" not in j:
        return 0.0
    pos = neg = 0
    for p in j["results"][:20]:
        votes = p.get("votes") or {}
        pos += int(votes.get("positive", 0) or 0)
        neg += int(votes.get("negative", 0) or 0)
    total = pos + neg
    return 0.0 if total == 0 else (pos - neg) / total


def score_fear_greed(fg):
    v = fg.get("value", 50)
    if v <= 20: return -1.0
    if v <= 40: return -0.3
    if v <= 60: return 0.3
    if v <= 80: return 0.6
    return -0.5


def score_global(gm, side):
    s = 0.0
    ch = gm.get("mcap_change_24h", 0)
    if ch > 2:
        s += 0.5
    elif ch < -2:
        s -= 0.5
    if side == "SHORT":
        s = -s
    return max(-1.0, min(1.0, s))


def score_coin(snap, side):
    if not snap:
        return 0.0
    s = 0.0
    pc24 = snap.get("price_change_24h", 0)
    if pc24 > 5:
        s += 0.4
    elif pc24 < -5:
        s -= 0.4
    s += (snap.get("sentiment_up_pct", 50) - 50) / 100.0
    if side == "SHORT":
        s = -s
    return max(-1.0, min(1.0, s))


async def sentiment_score(symbol, side):
    fg, gm, snap, news = await asyncio.gather(
        fear_greed(), global_market(), coin_snapshot(symbol), news_sentiment(symbol),
        return_exceptions=True,
    )
    if isinstance(fg, Exception):   fg = {"value": 50}
    if isinstance(gm, Exception):   gm = {}
    if isinstance(snap, Exception): snap = None
    if isinstance(news, Exception): news = 0.0

    s = (0.35 * score_fear_greed(fg) +
         0.25 * score_global(gm, side) +
         0.25 * score_coin(snap, side) +
         0.15 * news)
    return max(-1.0, min(1.0, s)), {"fg": fg, "gm": gm, "news": news}
