"""
isyatirim_veri.py — Veri Katmanı v4.0
══════════════════════════════════════
OHLCV  : Bigpara (Hürriyet Finans) — tüm BIST, ücretsiz, stabil
Bilanço: yfinance
Endeks : Bigpara → yfinance fallback

Bigpara endpoints:
  Günlük OHLCV : GET /api/v1/hisse/{SEM}/hissegrafik?startDate=DD.MM.YYYY&endDate=DD.MM.YYYY
  Anlık fiyat  : GET /api/v1/hisse/list
  Endeks       : GET /api/v1/endeks/hisseList/{ENDEKS}
"""

import time
import threading
import warnings
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

# ─── requests ────────────────────────────────────────────────────
try:
    import requests as _req
    _HAS_REQ = True
except ImportError:
    _HAS_REQ = False

# ─── yfinance (sadece bilanço) ───────────────────────────────────
try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

print("[ISY] ✅ Veri katmanı: Bigpara aktif")

# ─── CACHE ───────────────────────────────────────────────────────
_CACHE_LOCK    = threading.RLock()
_OHLCV_CACHE   = {}   # key → {df, ts}
_BILANCO_CACHE = {}   # key → {data, ts}
_ENDEKS_CACHE  = {}   # key → {df, ts}
_OHLCV_TTL     = 900      # 15 dakika
_BILANCO_TTL   = 86400    # 24 saat

_BP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Referer": "https://bigpara.hurriyet.com.tr/",
    "Origin": "https://bigpara.hurriyet.com.tr",
}
_BP_BASE = "https://bigpara.hurriyet.com.tr/api/v1"

def _sym_clean(sembol: str) -> str:
    return sembol.replace(".IS", "").replace(".is", "").upper().strip()

def _silence():
    import io, sys
    class _S:
        def __enter__(self):
            self._old = sys.stderr; sys.stderr = io.StringIO()
        def __exit__(self, *a):
            sys.stderr = self._old
    return _S()

def _period_to_dates(period: str) -> tuple:
    """period → (baslangic DD.MM.YYYY, bitis DD.MM.YYYY)"""
    _MAP = {
        "1d":  1,   "5d":  7,   "1mo": 32,  "3mo": 95,
        "6mo": 185, "1y":  366, "2y":  730, "3y":  1095,
        "5y":  1825,"10y": 3650,
    }
    gun = _MAP.get(period, 730)
    bitis     = datetime.now()
    baslangic = bitis - timedelta(days=gun)
    return baslangic.strftime("%d.%m.%Y"), bitis.strftime("%d.%m.%Y")

# ─── BIGPARA OHLCV ───────────────────────────────────────────────
def _bp_ohlcv(sym: str, period: str) -> Optional[pd.DataFrame]:
    """Bigpara'dan günlük OHLCV çek."""
    if not _HAS_REQ:
        return None
    try:
        start, end = _period_to_dates(period)
        url = f"{_BP_BASE}/hisse/{sym}/hissegrafik"
        r = _req.get(url, headers=_BP_HEADERS,
                     params={"startDate": start, "endDate": end},
                     timeout=15)
        if r.status_code != 200:
            return None

        data = r.json()

        # Bigpara response yapısı
        kayit = None
        if "data" in data:
            d = data["data"]
            if isinstance(d, dict):
                # hisseYuksekDusuk anahtarını ara
                for k in ["hisseYuksekDusuk", "gunlukVeriler", "veriler", "list"]:
                    if k in d and d[k]:
                        kayit = d[k]
                        break
                if kayit is None and d:
                    # İlk liste değerini al
                    for v in d.values():
                        if isinstance(v, list) and len(v) > 0:
                            kayit = v
                            break
            elif isinstance(d, list):
                kayit = d

        if not kayit:
            return None

        rows = []
        for item in kayit:
            try:
                # Tarih — çeşitli format dene
                tarih = None
                for tk in ["Tarih", "tarih", "date", "Date", "TARIH"]:
                    if tk in item and item[tk]:
                        t = str(item[tk])
                        # DD.MM.YYYY veya YYYY-MM-DD
                        for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
                                    "%d/%m/%Y", "%Y%m%d"]:
                            try:
                                tarih = datetime.strptime(t[:10], fmt)
                                break
                            except Exception:
                                continue
                        if tarih:
                            break
                if not tarih:
                    continue

                def _f(item, keys):
                    for k in keys:
                        v = item.get(k)
                        if v not in (None, "", 0):
                            try: return float(str(v).replace(",", "."))
                            except: continue
                    return None

                acilis  = _f(item, ["Acilis","acilis","Open","open","ACILIS","AcilisFiyat"])
                yuksek  = _f(item, ["Yuksek","yuksek","High","high","YUKSEK","EnYuksek"])
                dusuk   = _f(item, ["Dusuk","dusuk","Low","low","DUSUK","EnDusuk"])
                kapanis = _f(item, ["Kapanis","kapanis","Close","close","KAPANIS","KapanisFiyat","SonFiyat"])
                hacim   = _f(item, ["Hacim","hacim","Volume","volume","HACIM","IslemHacmi"])

                if kapanis and kapanis > 0:
                    rows.append({
                        "Date":   tarih,
                        "Open":   acilis  or kapanis,
                        "High":   yuksek  or kapanis,
                        "Low":    dusuk   or kapanis,
                        "Close":  kapanis,
                        "Volume": hacim   or 0.0,
                    })
            except Exception:
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df = df[["Open","High","Low","Close","Volume"]].astype(float)
        df = df.dropna(subset=["Close"])
        df = df[df["Close"] > 0]
        return df if not df.empty else None

    except Exception as e:
        return None


def _bp_weekly(sym: str, period: str) -> Optional[pd.DataFrame]:
    """Günlük veriyi haftalığa resample et."""
    df = _bp_ohlcv(sym, period)
    if df is None or df.empty:
        return None
    try:
        weekly = df.resample("W").agg({
            "Open":   "first",
            "High":   "max",
            "Low":    "min",
            "Close":  "last",
            "Volume": "sum",
        }).dropna(subset=["Close"])
        return weekly if not weekly.empty else None
    except Exception:
        return None


# ─── yfinance OHLCV fallback ──────────────────────────────────────
def _yf_ohlcv(sym: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    if not _HAS_YF:
        return None
    try:
        with _silence():
            df = yf.download(f"{sym}.IS", period=period, interval=interval,
                             progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
        needed = {"Open","High","Low","Close","Volume"}
        if not needed.issubset(df.columns):
            return None
        return df[list(needed)].astype(float).sort_index().dropna(subset=["Close"])
    except Exception:
        return None


# ─── ANA OHLCV FONKSİYONU ────────────────────────────────────────
def ohlcv_al(sembol: str, period: str = "2y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    OHLCV verisi.
    1. Bigpara (günlük veya haftalık resample)
    2. yfinance fallback
    """
    sym = _sym_clean(sembol)
    cache_key = f"{sym}_{period}_{interval}"

    with _CACHE_LOCK:
        hit = _OHLCV_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _OHLCV_TTL:
            return hit["df"].copy()

    df = None

    if interval == "1wk":
        df = _bp_weekly(sym, period)
    else:
        df = _bp_ohlcv(sym, period)

    if df is None:
        df = _yf_ohlcv(sym, period, interval)

    if df is not None and not df.empty:
        with _CACHE_LOCK:
            _OHLCV_CACHE[cache_key] = {"df": df.copy(), "ts": time.time()}
    return df


# ─── ENDEKS VERİSİ ───────────────────────────────────────────────
def endeks_al(endeks: str = "XU100") -> Optional[pd.DataFrame]:
    """Endeks verisi — Bigpara → yfinance fallback."""
    cache_key = f"endeks_{endeks}"
    with _CACHE_LOCK:
        hit = _ENDEKS_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _OHLCV_TTL:
            return hit["df"].copy()

    df = None

    # Bigpara endeks — XU100 için BIST sembolü
    _BP_ENDEKS = {
        "XU100": "XU100",
        "XU030": "XU030",
        "XBANK": "XBANK",
        "XUSIN": "XUSIN",
    }
    if _HAS_REQ:
        try:
            bp_sym = _BP_ENDEKS.get(endeks, endeks)
            url = f"{_BP_BASE}/endeks/hisseList/{bp_sym}"
            r = _req.get(url, headers=_BP_HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Endeks için sadece anlık değer yeterli
                if "data" in data:
                    d = data["data"]
                    son_deger = None
                    if isinstance(d, dict):
                        for k in ["endeksDetay","endeks","deger","value"]:
                            if k in d:
                                v = d[k]
                                if isinstance(v, (int, float)):
                                    son_deger = float(v)
                                    break
                    if son_deger:
                        df = pd.DataFrame([{"Close": son_deger, "Open": son_deger,
                                            "High": son_deger, "Low": son_deger,
                                            "Volume": 0}],
                                          index=[pd.Timestamp.now()])
        except Exception:
            df = None

    # Bigpara'dan 5 günlük XU100 çek
    if df is None and _HAS_REQ:
        try:
            start, end = _period_to_dates("5d")
            url = f"{_BP_BASE}/endeks/{endeks}/endeksGrafik"
            r = _req.get(url, headers=_BP_HEADERS,
                         params={"startDate": start, "endDate": end},
                         timeout=10)
            if r.status_code == 200:
                data = r.json()
                rows = []
                kayit = None
                if "data" in data:
                    d = data["data"]
                    if isinstance(d, list): kayit = d
                    elif isinstance(d, dict):
                        for v in d.values():
                            if isinstance(v, list): kayit = v; break
                if kayit:
                    for item in kayit:
                        try:
                            kapanis = float(str(item.get("Kapanis") or item.get("kapanis") or item.get("Deger") or 0).replace(",","."))
                            tarih_str = str(item.get("Tarih") or item.get("tarih",""))
                            for fmt in ["%d.%m.%Y","%Y-%m-%d"]:
                                try:
                                    tarih = datetime.strptime(tarih_str[:10], fmt)
                                    break
                                except: tarih = None
                            if kapanis > 0 and tarih:
                                rows.append({"Date": tarih, "Close": kapanis,
                                             "Open": kapanis, "High": kapanis,
                                             "Low": kapanis, "Volume": 0})
                        except: continue
                if rows:
                    df = pd.DataFrame(rows).set_index("Date").sort_index()
        except Exception:
            df = None

    # yfinance fallback
    if df is None and _HAS_YF:
        try:
            yf_sym = {"XU100":"XU100.IS","XU030":"XU030.IS"}.get(endeks, f"{endeks}.IS")
            with _silence():
                df = yf.download(yf_sym, period="5d", interval="1d",
                                 progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.index = pd.to_datetime(df.index)
                df = df.sort_index()
        except Exception:
            df = None

    if df is not None and not df.empty:
        with _CACHE_LOCK:
            _ENDEKS_CACHE[cache_key] = {"df": df.copy(), "ts": time.time()}
    return df


# ─── BİLANÇO (yfinance) ─────────────────────────────────────────
_BOSTA_BILANCO = {
    "veri_var": False, "kaynak": "yok", "sembol": "",
    "net_kar": [], "ciro": [], "favok": [],
    "toplam_borc": None, "ozkaynaklar": None,
    "net_borc": None, "borc_favok": None,
    "kar_durumu": "belirsiz", "temel_skor": 0,
    "uyarilar": [], "yillar": [], "ham_df": None,
    "pe": None, "pb": None,
}


def bilanco_al(sembol: str, yil_sayisi: int = 3) -> dict:
    sym = _sym_clean(sembol)
    cache_key = f"bilanco_{sym}"
    with _CACHE_LOCK:
        hit = _BILANCO_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _BILANCO_TTL:
            return hit["data"]
    result = _yf_bilanco(sym)
    with _CACHE_LOCK:
        _BILANCO_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return result


def _yf_bilanco(sym: str) -> dict:
    if not _HAS_YF:
        return {**_BOSTA_BILANCO, "sembol": sym}
    try:
        with _silence():
            ticker  = yf.Ticker(f"{sym}.IS")
            info    = ticker.info or {}
            income  = ticker.financials
            balance = ticker.balance_sheet

        pe = info.get("trailingPE") or info.get("forwardPE")
        pb = info.get("priceToBook")
        eg = info.get("earningsGrowth")
        de = info.get("debtToEquity")

        net_kar = []; ciro = []; favok = []; yillar = []

        if income is not None and not income.empty:
            try:
                cols = sorted(income.columns)[-4:]
                yillar = [c.year if hasattr(c,"year") else int(str(c)[:4]) for c in cols]
                for row in ["Net Income","Net Income Common Stockholders"]:
                    if row in income.index:
                        net_kar = [float(income.loc[row,c]) if pd.notna(income.loc[row,c]) else None for c in cols]
                        break
                for row in ["Total Revenue","Revenue"]:
                    if row in income.index:
                        ciro = [float(income.loc[row,c]) if pd.notna(income.loc[row,c]) else None for c in cols]
                        break
                for row in ["EBITDA","Operating Income"]:
                    if row in income.index:
                        favok = [float(income.loc[row,c]) if pd.notna(income.loc[row,c]) else None for c in cols]
                        break
            except Exception:
                pass

        toplam_borc = None; ozkaynaklar = None
        net_borc = None; borc_favok = None

        if balance is not None and not balance.empty:
            try:
                cols_b = sorted(balance.columns)
                last_col = cols_b[-1] if cols_b else None
                if last_col:
                    def _get(rows):
                        for r in rows:
                            if r in balance.index:
                                v = balance.loc[r, last_col]
                                if pd.notna(v): return float(v)
                        return None
                    toplam_borc = _get(["Total Debt","Long Term Debt","Total Liabilities Net Minority Interest"])
                    ozkaynaklar = _get(["Stockholders Equity","Total Stockholder Equity",
                                        "Common Stock Equity","Total Equity Gross Minority Interest"])
                    nakit       = _get(["Cash And Cash Equivalents",
                                        "Cash Cash Equivalents And Short Term Investments"])
                    if nakit and toplam_borc:
                        net_borc = toplam_borc - nakit
                    if net_borc and favok and favok[-1] and favok[-1] > 0:
                        borc_favok = round(net_borc / favok[-1], 2)
            except Exception:
                pass

        kar_durumu = "belirsiz"
        if len(net_kar) >= 2:
            son, prev = net_kar[-1], net_kar[-2]
            if son is not None and prev is not None:
                if son < 0: kar_durumu = "zarar"
                elif prev > 0 and son > prev*1.05: kar_durumu = "artiyor"
                elif prev > 0 and son < prev*0.95: kar_durumu = "azaliyor"
        elif eg is not None:
            if eg > 0.05: kar_durumu = "artiyor"
            elif eg < -0.1: kar_durumu = "azaliyor"

        temel_skor = 0; uyarilar = []
        if kar_durumu == "artiyor":  temel_skor += 1; uyarilar.append("✅ Kar Artıyor")
        elif kar_durumu == "zarar":  temel_skor -= 2; uyarilar.append("🚨 Zararda")
        elif kar_durumu == "azaliyor": temel_skor -= 1; uyarilar.append("⚠ Kar Azalıyor")
        if pe and pe > 0:
            if pe < 10:   temel_skor += 1; uyarilar.append(f"✅ F/K Ucuz ({pe:.1f}x)")
            elif pe > 30: temel_skor -= 1; uyarilar.append(f"⚠ F/K Yüksek ({pe:.1f}x)")
            else:         uyarilar.append(f"F/K Normal ({pe:.1f}x)")
        if pb and pb > 0:
            if pb < 1.0: temel_skor += 1; uyarilar.append(f"✅ PD/DD < 1 ({pb:.2f}x)")
            elif pb > 5: temel_skor -= 1; uyarilar.append(f"⚠ PD/DD Yüksek ({pb:.2f}x)")
        if de and de > 0:
            if de > 200: temel_skor -= 1; uyarilar.append(f"🚨 Yüksek D/E ({de:.0f}%)")
            elif de < 50: temel_skor += 1; uyarilar.append(f"✅ Düşük D/E ({de:.0f}%)")

        veri_var = bool(net_kar or pe or pb)
        return {
            "veri_var":    veri_var,
            "kaynak":      "yfinance" if veri_var else "yok",
            "sembol":      sym,
            "net_kar":     net_kar, "ciro": ciro, "favok": favok,
            "toplam_borc": toplam_borc, "ozkaynaklar": ozkaynaklar,
            "net_borc":    net_borc, "borc_favok": borc_favok,
            "kar_durumu":  kar_durumu,
            "temel_skor":  max(-3, min(4, temel_skor)),
            "uyarilar":    uyarilar, "yillar": yillar, "ham_df": None,
            "pe": round(float(pe),1) if pe and pe > 0 else None,
            "pb": round(float(pb),2) if pb and pb > 0 else None,
        }
    except Exception:
        return {**_BOSTA_BILANCO, "sembol": sym}


def oranlar_al(sembol: str, fiyat: float = 0.0) -> dict:
    sym = _sym_clean(sembol)
    _BOSTA = {"pe":None,"pd_dd":None,"roe":None,"net_marj":None,
              "kaynak":"yok","uyarilar":[],"skor":0,"yatirimlik":False}
    try:
        b = bilanco_al(sym)
        if not b.get("veri_var"): return _BOSTA
        net_kar_list = b.get("net_kar",[])
        ciro_list    = b.get("ciro",[])
        ozkaynaklar  = b.get("ozkaynaklar")
        pe = b.get("pe"); pb = b.get("pb")
        son_kar  = net_kar_list[-1] if net_kar_list else None
        son_ciro = ciro_list[-1]    if ciro_list    else None
        net_marj = round(son_kar/son_ciro*100,1) if son_kar and son_ciro else None
        roe      = round(son_kar/ozkaynaklar*100,1) if son_kar and ozkaynaklar and ozkaynaklar > 0 else None
        skor=0; uyarilar=[]; yatirimlik=False
        if pe and pe > 0:
            if pe > 30:   skor -= 1; uyarilar.append(f"⚠ F/K Pahalı: {pe:.1f}x")
            elif pe < 10: skor += 1; uyarilar.append(f"✅ F/K Ucuz: {pe:.1f}x")
        if pb and pb > 0:
            if pb < 1.0:  skor += 1; yatirimlik=True; uyarilar.append(f"✅ PD/DD < 1 ({pb:.2f}x)")
            elif pb > 5:  skor -= 1; uyarilar.append(f"⚠ PD/DD Pahalı: {pb:.2f}x")
        if roe:
            if roe > 25:  skor += 1; uyarilar.append(f"✅ ROE: %{roe:.1f}")
            elif roe < 0: skor -= 2; uyarilar.append(f"🚨 ROE Negatif: %{roe:.1f}")
        return {"pe":pe,"pd_dd":pb,"roe":roe,"net_marj":net_marj,
                "kaynak":"yfinance","uyarilar":uyarilar,
                "skor":max(-3,min(3,skor)),"yatirimlik":yatirimlik}
    except Exception:
        return _BOSTA


def zayif_bilanc_kontrol(sembol: str) -> dict:
    sym = _sym_clean(sembol)
    _BOSTA = {"risk":False,"etiket":"","sebep":"","dusus_pct":None}
    try:
        b = bilanco_al(sym)
        if not b.get("veri_var"): return _BOSTA
        net_kar = b.get("net_kar",[])
        if len(net_kar) < 2: return _BOSTA
        son_kar, prev_kar = net_kar[-1], net_kar[-2]
        if son_kar is not None and son_kar < 0:
            return {"risk":True,"etiket":"🚨 ZAYIF BİLANÇO: ZARARDA",
                    "sebep":f"Net zarar: {son_kar/1e6:.0f}M₺","dusus_pct":None}
        if son_kar is not None and prev_kar and prev_kar > 0:
            dusus = (son_kar-prev_kar)/prev_kar*100
            if dusus <= -30:
                return {"risk":True,
                        "etiket":f"⚠ ZAYIF BİLANÇO: Kar -{abs(dusus):.0f}% düştü",
                        "sebep":f"{prev_kar/1e6:.0f}M₺ → {son_kar/1e6:.0f}M₺",
                        "dusus_pct":round(dusus,1)}
        return _BOSTA
    except Exception:
        return _BOSTA


def bilanco_ozet_json(sembol: str) -> dict:
    b = bilanco_al(sembol); r = oranlar_al(sembol); z = zayif_bilanc_kontrol(sembol)
    yillar = b.get("yillar",[])
    def _fmt(lst):
        return [{"yil":y,"deger":v,"fmt":f"{v/1e6:.0f}M₺" if v else "?"}
                for y,v in zip(yillar[-len(lst):],lst) if v is not None]
    return {
        "veri_var":b["veri_var"],"kaynak":b["kaynak"],
        "kar_durumu":b["kar_durumu"],"temel_skor":b["temel_skor"],
        "uyarilar":b["uyarilar"],"borc_favok":b["borc_favok"],
        "net_borc":b["net_borc"],
        "net_kar_grafik":_fmt(b["net_kar"]),
        "ciro_grafik":_fmt(b["ciro"]),
        "favok_grafik":_fmt(b["favok"]),
        "pe":r.get("pe") or b.get("pe"), "pb":r.get("pd_dd") or b.get("pb"),
        "roe":r.get("roe"),"net_marj":r.get("net_marj"),
        "oran_uyarilar":r.get("uyarilar",[]),"oran_skor":r.get("skor",0),
        "yatirimlik":r.get("yatirimlik",False),
        "zayif_bilanc":z["risk"],"zayif_bilanc_etiket":z["etiket"],
        "zayif_bilanc_sebep":z["sebep"],"dusus_pct":z["dusus_pct"],
    }


def durum_mesaji() -> str:
    return "Bigpara ✅ aktif | yfinance bilanço ✅"
