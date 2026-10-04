# fundamental.py
import time, aiohttp, asyncio
from config import log

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
DEFILLAMA_SLUGS = {
    "ETH": "Ethereum", "SOL": "Solana", "BNB": "BSC", "AVAX": "Avalanche",
    "MATIC": "Polygon", "ADA": "Cardano", "DOT": "Polkadot",
}


async def _get_json(url, ttl=600):
    cached = _cget(url)
    if cached is not None:
        return cached
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                j = await r.json()
                _cset(url, j, ttl)
                return j
    except Exception as e:
        log.warning(f"fund GET {url[:60]}: {e}")
        return None


async def tokenomics(symbol):
    base = (symbol or "").split("/")[0].upper()
    cid = COIN_IDS.get(base)
    if not cid:
        return None
    j = await _get_json(
        f"https://api.coingecko.com/api/v3/coins/{cid}"
        "?localization=false&tickers=false&community_data=true&developer_data=true",
        ttl=1800,
    )
    if not j:
        return None
    md = j.get("market_data") or {}
    dev = j.get("developer_data") or {}
    comm = j.get("community_data") or {}
    return {
        "market_cap_usd": float(md.get("market_cap", {}).get("usd") or 0),
        "fdv_usd": float(md.get("fully_diluted_valuation", {}).get("usd") or 0),
        "circulating": float(md.get("circulating_supply") or 0),
        "max_supply": float(md.get("max_supply") or 0),
        "volume_24h": float(md.get("total_volume", {}).get("usd") or 0),
        "ath_change_pct": float(md.get("ath_change_percentage", {}).get("usd") or 0),
        "commits_4w": int(dev.get("commit_count_4_weeks") or 0),
        "twitter_followers": int(comm.get("twitter_followers") or 0),
    }


async def defi_tvl(symbol):
    base = (symbol or "").split("/")[0].upper()
    slug = DEFILLAMA_SLUGS.get(base)
    if not slug:
        return None
    j = await _get_json("https://api.llama.fi/v2/chains", ttl=900)
    for ch in j or []:
        if (ch.get("name") or "").lower() == slug.lower():
            return {"tvl_usd": float(ch.get("tvl") or 0)}
    return None


async def stablecoin_flow():
    j = await _get_json("https://stablecoins.llama.fi/stablecoins?includePrices=true", ttl=3600)
    if not j or "peggedAssets" not in j:
        return None
    total = 0.0
    for a in j.get("peggedAssets", []):
        if a.get("pegType") != "peggedUSD":
            continue
        circ = a.get("circulating") or {}
        total += float(circ.get("peggedUSD") or 0)
    return {"total_usd": total}


def score_supply(t):
    s = 0.0
    circ = t.get("circulating", 0)
    maxs = t.get("max_supply", 0)
    fdv = t.get("fdv_usd", 0)
    mcap = t.get("market_cap_usd", 0)
    if maxs and circ:
        ratio = circ / maxs
        if ratio > 0.9:
            s += 0.4
        elif ratio > 0.7:
            s += 0.2
        elif ratio < 0.4:
            s -= 0.3
    if mcap > 0 and fdv > 0:
        r = mcap / fdv
        if r < 0.5:
            s -= 0.3
        elif r > 0.85:
            s += 0.2
    return max(-1.0, min(1.0, s))


def score_liquidity(t):
    mcap = t.get("market_cap_usd", 0)
    vol = t.get("volume_24h", 0)
    if mcap <= 0:
        return 0.0
    r = vol / mcap
    if r > 0.3:  return 0.5
    if r > 0.1:  return 0.3
    if r > 0.03: return 0.1
    if r < 0.01: return -0.5
    return 0.0


def score_dev(t):
    c = t.get("commits_4w", 0)
    if c >= 50: return 0.6
    if c >= 20: return 0.4
    if c >= 5:  return 0.2
    if c >= 1:  return 0.0
    return -0.3


def score_valuation(t):
    ath = t.get("ath_change_pct", 0)
    if ath <= -80: return 0.4
    if ath <= -60: return 0.3
    if ath <= -40: return 0.1
    if ath >= -10: return -0.4
    if ath >= -20: return -0.2
    return 0.0


def score_tvl(tvl):
    if not tvl:
        return 0.0
    v = tvl.get("tvl_usd", 0)
    if v >= 10e9:  return 0.5
    if v >= 1e9:   return 0.3
    if v >= 100e6: return 0.1
    if v < 10e6:   return -0.2
    return 0.0


def score_stablecoins(sc):
    if not sc:
        return 0.0
    v = sc.get("total_usd", 0)
    if v >= 150e9: return 0.3
    if v >= 100e9: return 0.15
    if v < 50e9:   return -0.2
    return 0.0


async def fundamental_score(symbol, side):
    tok, tvl, sc = await asyncio.gather(
        tokenomics(symbol), defi_tvl(symbol), stablecoin_flow(),
        return_exceptions=True,
    )
    if isinstance(tok, Exception): tok = None
    if isinstance(tvl, Exception): tvl = None
    if isinstance(sc, Exception):  sc = None
    if not tok:
        return 0.0, {"reason": "no fundamental data"}

    s_supply = score_supply(tok)
    s_liq    = score_liquidity(tok)
    s_dev    = score_dev(tok)
    s_val    = score_valuation(tok)
    s_tvl    = score_tvl(tvl)
    s_stable = score_stablecoins(sc)

    score = (0.25 * s_supply + 0.20 * s_liq + 0.20 * s_dev +
             0.15 * s_val + 0.10 * s_tvl + 0.10 * s_stable)
    score = max(-1.0, min(1.0, score))
    if side == "SHORT":
        score = -score

    return score, {
        "supply": round(s_supply, 2), "liq": round(s_liq, 2),
        "dev": round(s_dev, 2), "val": round(s_val, 2),
        "tvl": round(s_tvl, 2), "stable": round(s_stable, 2),
        "mcap": tok.get("market_cap_usd", 0),
        "vol24": tok.get("volume_24h", 0),
        "ath_pct": tok.get("ath_change_pct", 0),
        "commits": tok.get("commits_4w", 0),
    }
