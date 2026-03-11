"""
veri_kaynagi.py — Alternatif BIST Veri Kaynakları v1.0
════════════════════════════════════════════════════════
Kaynak 1: TradingView Scanner API  (15dk gecikmeli, ücretsiz, stabil ✅)
Kaynak 2: Investing.com scraper    (15dk, ücretsiz ama IP ban riski ⚠)
Kaynak 3: yfinance                 (fallback, her zaman çalışır ✅)

Kullanım:
    from veri_kaynagi import fiyat_al, toplu_fiyat_al

    fiyat = fiyat_al("THYAO")          # → 142.30
    fiyatlar = toplu_fiyat_al(["THYAO","ASELS","SASA"])
    # → {"THYAO": 142.30, "ASELS": 85.20, "SASA": 36.10}
"""

import time, threading, json
from typing import Optional

try:
    import requests as _req
    _HAS_REQ = True
except ImportError:
    _HAS_REQ = False

try:
    import yfinance as _yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

# ─── CACHE ────────────────────────────────────────────────────────
_CACHE: dict = {}
_LOCK  = threading.Lock()
_TTL   = 900  # 15 dakika (aynı kaynak gecikme süresi)

def _get(sym: str) -> Optional[float]:
    with _LOCK:
        item = _CACHE.get(sym)
        if item and (time.time() - item["ts"]) < _TTL:
            return item["f"]
    return None

def _set(sym: str, fiyat: float):
    with _LOCK:
        _CACHE[sym] = {"f": fiyat, "ts": time.time()}

# ─── KAYNAK 1: TradingView Scanner ───────────────────────────────
# En stabil kaynak — JSON API, Cloudflare yok, rate limit yüksek
_TV_URL = "https://scanner.tradingview.com/turkey/scan"
_TV_HEADERS = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Origin":       "https://www.tradingview.com",
    "Referer":      "https://www.tradingview.com/",
}

def _tv_fiyat(sembol: str) -> Optional[float]:
    """TradingView'den tek hisse fiyatı al."""
    if not _HAS_REQ:
        return None
    sym = sembol.replace(".IS", "").upper()
    try:
        body = {
            "symbols": {"tickers": [f"BIST:{sym}"], "query": {"types": []}},
            "columns": ["close", "change", "volume"],
        }
        r = _req.post(_TV_URL, json=body, headers=_TV_HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        rows = data.get("data", [])
        if rows and rows[0].get("d"):
            return float(rows[0]["d"][0])
    except Exception:
        pass
    return None

def _tv_toplu(semboller: list) -> dict:
    """TradingView'den toplu fiyat al — tek HTTP isteği."""
    if not _HAS_REQ or not semboller:
        return {}
    tickers = [f"BIST:{s.replace('.IS','').upper()}" for s in semboller]
    try:
        body = {
            "symbols": {"tickers": tickers, "query": {"types": []}},
            "columns": ["close", "change", "volume", "market_cap_basic"],
        }
        r = _req.post(_TV_URL, json=body, headers=_TV_HEADERS, timeout=15)
        if r.status_code != 200:
            return {}
        data   = r.json()
        result = {}
        for row in data.get("data", []):
            sym_full = row.get("s", "")          # "BIST:THYAO"
            sym = sym_full.replace("BIST:", "")
            if row.get("d") and row["d"][0] is not None:
                result[sym] = {
                    "fiyat":   float(row["d"][0]),
                    "degisim": round(float(row["d"][1] or 0), 2),
                    "hacim":   int(row["d"][2] or 0),
                    "piyasa_deger": row["d"][3],
                }
        return result
    except Exception as e:
        print(f"[TV] Toplu fiyat hata: {e}")
        return {}

# ─── KAYNAK 2: Investing.com ─────────────────────────────────────
# Cloudflare'ı bypass etmek için session + cookie gerekiyor
# UYARI: Çok fazla istek atılırsa IP ban yiyebilirsin.
# Sadece fallback olarak kullan.

_INV_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept":          "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "Referer":         "https://tr.investing.com/",
    "X-Requested-With":"XMLHttpRequest",
}
_INV_SESSION = None
_INV_LOCK    = threading.Lock()

# Investing.com sembol ID'leri (önemli BIST hisseleri)
# Tam liste için: https://api.investing.com/api/financialdata/assets/equities?country-id=52
_INV_IDS = {
    "THYAO": 56478,  "ASELS": 56375,  "KCHOL": 56430,  "SASA":  56468,
    "FROTO": 56410,  "EREGL": 56400,  "TUPRS": 56492,  "BIMAS": 56381,
    "AKBNK": 56335,  "GARAN": 56414,  "YKBNK": 56506,  "ISCTR": 56424,
    "PGSUS": 56458,  "TAVHL": 56483,  "TCELL": 56484,  "TTKOM": 56488,
    "EKGYO": 56399,  "HALKB": 56416,  "VAKBN": 56496,  "TOASO": 56486,
}

def _inv_fiyat(sembol: str) -> Optional[float]:
    """Investing.com'dan fiyat al (sadece ID bilinen hisseler)."""
    if not _HAS_REQ:
        return None
    sym = sembol.replace(".IS","").upper()
    inv_id = _INV_IDS.get(sym)
    if not inv_id:
        return None  # ID bilinmiyor, fallback'e geç

    global _INV_SESSION
    with _INV_LOCK:
        if _INV_SESSION is None:
            _INV_SESSION = _req.Session()
            # Önce ana sayfayı ziyaret et (cookie al)
            try:
                _INV_SESSION.get("https://tr.investing.com/", headers=_INV_HEADERS, timeout=10)
            except Exception:
                pass

    try:
        url = f"https://api.investing.com/api/financialdata/{inv_id}/historical/chart/"
        params = {"period": "P1D", "interval": "PT5M", "pointscount": 1}
        r = _INV_SESSION.get(url, headers=_INV_HEADERS, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            bars = data.get("data", {}).get("bars", [])
            if bars:
                return float(bars[-1][4])  # close fiyatı
    except Exception as e:
        print(f"[INV] {sym} hata: {e}")
    return None

# ─── KAYNAK 3: yfinance fallback ─────────────────────────────────
def _yf_fiyat(sembol: str) -> Optional[float]:
    if not _HAS_YF:
        return None
    try:
        sym = sembol if sembol.endswith(".IS") else sembol + ".IS"
        ticker = _yf.Ticker(sym)
        hist = ticker.history(period="2d", interval="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None

# ─── ANA FONKSİYONLAR ────────────────────────────────────────────
def fiyat_al(sembol: str) -> Optional[float]:
    """
    Hisse fiyatını sırayla kaynaklardan dener:
    1) Cache kontrolü
    2) TradingView
    3) Investing.com (sadece bilinen hisseler)
    4) yfinance (fallback)
    """
    sym = sembol.replace(".IS","").upper()

    # Cache
    cached = _get(sym)
    if cached:
        return cached

    # TradingView
    f = _tv_fiyat(sym)
    if f:
        _set(sym, f)
        return f

    # Investing.com
    f = _inv_fiyat(sym)
    if f:
        _set(sym, f)
        return f

    # yfinance fallback
    f = _yf_fiyat(sym)
    if f:
        _set(sym, f)
        return f

    return None


def toplu_fiyat_al(semboller: list) -> dict:
    """
    Tüm hisselerin fiyatını tek seferde çeker.
    TradingView toplu API kullanır → çok hızlı!
    """
    if not semboller:
        return {}

    # 1) Cache'den gelenleri topla, eksikleri bul
    result = {}
    eksik  = []
    for sym in [s.replace(".IS","").upper() for s in semboller]:
        cached = _get(sym)
        if cached:
            result[sym] = cached
        else:
            eksik.append(sym)

    if not eksik:
        return result

    # 2) TradingView toplu çek
    tv_data = _tv_toplu(eksik)
    for sym, d in tv_data.items():
        result[sym] = d["fiyat"]
        _set(sym, d["fiyat"])
        eksik2 = [s for s in eksik if s not in result]

    # 3) Kalıyorsa yfinance fallback
    for sym in [s for s in eksik if s not in result]:
        f = _yf_fiyat(sym + ".IS")
        if f:
            result[sym] = f
            _set(sym, f)

    return result


def tv_tarama_verisi(limit: int = 150) -> list:
    """
    TradingView'den BIST hisselerinin temel verilerini çeker.
    Tarama için kullanılabilir — fiyat, değişim, hacim, RSI, MACD.
    
    Returns: [{"sembol":"THYAO", "fiyat":142, "degisim":2.4, ...}, ...]
    """
    if not _HAS_REQ:
        return []
    try:
        body = {
            "filter": [
                {"left": "exchange", "operation": "equal", "right": "BIST"},
                {"left": "type",     "operation": "equal", "right": "stock"},
            ],
            "options": {"lang": "tr"},
            "columns": [
                "name", "close", "change", "change_abs",
                "volume", "average_volume_10d_calc",
                "RSI", "MACD.macd", "MACD.signal",
                "EMA20", "EMA50", "EMA200",
                "Stoch.K", "Stoch.D",
                "market_cap_basic", "P/E",
            ],
            "sort":  {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, limit],
        }
        r = _req.post(
            "https://scanner.tradingview.com/turkey/scan",
            json=body, headers=_TV_HEADERS, timeout=20
        )
        if r.status_code != 200:
            return []

        sonuc = []
        for row in r.json().get("data", []):
            s = row.get("s","").replace("BIST:","")
            d = row.get("d",[])
            if len(d) < 10 or not d[1]:
                continue
            sonuc.append({
                "sembol":      s,
                "fiyat":       float(d[1]),
                "degisim":     round(float(d[2] or 0), 2),
                "degisim_abs": float(d[3] or 0),
                "hacim":       int(d[4] or 0),
                "ort_hacim":   int(d[5] or 0),
                "rsi":         round(float(d[6] or 50), 1),
                "macd":        float(d[7] or 0),
                "macd_signal": float(d[8] or 0),
                "ema20":       float(d[9] or 0),
                "ema50":       float(d[10] or 0),
                "ema200":      float(d[11] or 0),
                "stoch_k":     float(d[12] or 50),
                "stoch_d":     float(d[13] or 50),
                "pe":          float(d[15]) if d[15] else None,
            })
            _set(s, float(d[1]))  # cache'e de yaz
        return sonuc

    except Exception as e:
        print(f"[TV] Tarama verisi hata: {e}")
        return []
