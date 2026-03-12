"""
isyatirim_veri.py — Veri Katmanı v5.0
══════════════════════════════════════
OHLCV  : yfinance (stabil, Python 3.12 uyumlu)
Bilanço: yfinance
Blacklist: YOK — tüm hisseler her taramada denenir
"""

import time
import threading
import warnings
import io
import sys
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    _HAS_YF = True
    print("[ISY] ✅ yfinance aktif")
except ImportError:
    _HAS_YF = False
    print("[ISY] ❌ yfinance bulunamadı!")

# ─── CACHE ───────────────────────────────────────────────────────
_CACHE_LOCK    = threading.RLock()
_OHLCV_CACHE   = {}
_BILANCO_CACHE = {}
_ENDEKS_CACHE  = {}
_OHLCV_TTL     = 900      # 15 dakika
_BILANCO_TTL   = 86400    # 24 saat

def _sym_clean(sembol: str) -> str:
    return sembol.replace(".IS", "").replace(".is", "").upper().strip()

def _sessiz_indir(ticker_sym, period, interval):
    """yfinance'i sessizce çalıştır — hata mesajlarını gizle."""
    old_err = sys.stderr
    old_out = sys.stdout
    try:
        sys.stderr = io.StringIO()
        sys.stdout = io.StringIO()
        df = yf.download(
            ticker_sym,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        df = None
    finally:
        sys.stderr = old_err
        sys.stdout = old_out
    return df

def _temizle(df) -> Optional[pd.DataFrame]:
    """MultiIndex ve duplicate kolonları temizle."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    needed = {"Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(df.columns):
        return None
    df = df[list(needed)].copy()
    df = df.astype(float)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    return df if not df.empty else None

# ─── ANA OHLCV FONKSİYONU ────────────────────────────────────────
def ohlcv_al(sembol: str, period: str = "2y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    OHLCV verisi — yfinance.
    sembol: THYAO veya THYAO.IS her ikisini kabul eder.
    Blacklist YOK — başarısız olursa None döner, bir dahaki taramada tekrar dener.
    """
    sym = _sym_clean(sembol)
    cache_key = f"{sym}_{period}_{interval}"

    with _CACHE_LOCK:
        hit = _OHLCV_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _OHLCV_TTL:
            return hit["df"].copy()

    if not _HAS_YF:
        return None

    df = _sessiz_indir(f"{sym}.IS", period, interval)
    df = _temizle(df)

    if df is not None:
        with _CACHE_LOCK:
            _OHLCV_CACHE[cache_key] = {"df": df.copy(), "ts": time.time()}
    return df


# ─── ENDEKS VERİSİ ───────────────────────────────────────────────
def endeks_al(endeks: str = "XU100") -> Optional[pd.DataFrame]:
    """XU100 / XU030 endeks verisi."""
    cache_key = f"endeks_{endeks}"
    with _CACHE_LOCK:
        hit = _ENDEKS_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _OHLCV_TTL:
            return hit["df"].copy()

    if not _HAS_YF:
        return None

    yf_sym = {"XU100": "XU100.IS", "XU030": "XU030.IS"}.get(endeks, f"{endeks}.IS")
    df = _sessiz_indir(yf_sym, "5d", "1d")
    df = _temizle(df)

    if df is not None:
        with _CACHE_LOCK:
            _ENDEKS_CACHE[cache_key] = {"df": df.copy(), "ts": time.time()}
    return df


# ─── BİLANÇO ─────────────────────────────────────────────────────
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
        old_err = sys.stderr; sys.stderr = io.StringIO()
        try:
            ticker  = yf.Ticker(f"{sym}.IS")
            info    = ticker.info or {}
            income  = ticker.financials
            balance = ticker.balance_sheet
        finally:
            sys.stderr = old_err

        pe = info.get("trailingPE") or info.get("forwardPE")
        pb = info.get("priceToBook")
        eg = info.get("earningsGrowth")
        de = info.get("debtToEquity")

        net_kar=[]; ciro=[]; favok=[]; yillar=[]

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

        toplam_borc=None; ozkaynaklar=None; net_borc=None; borc_favok=None

        if balance is not None and not balance.empty:
            try:
                cols_b = sorted(balance.columns)
                lc = cols_b[-1] if cols_b else None
                if lc:
                    def _g(rows):
                        for r in rows:
                            if r in balance.index:
                                v = balance.loc[r,lc]
                                if pd.notna(v): return float(v)
                        return None
                    toplam_borc = _g(["Total Debt","Long Term Debt","Total Liabilities Net Minority Interest"])
                    ozkaynaklar = _g(["Stockholders Equity","Total Stockholder Equity","Common Stock Equity","Total Equity Gross Minority Interest"])
                    nakit       = _g(["Cash And Cash Equivalents","Cash Cash Equivalents And Short Term Investments"])
                    if nakit and toplam_borc: net_borc = toplam_borc - nakit
                    if net_borc and favok and favok[-1] and favok[-1]>0:
                        borc_favok = round(net_borc/favok[-1],2)
            except Exception:
                pass

        kd = "belirsiz"
        if len(net_kar)>=2:
            s,p = net_kar[-1], net_kar[-2]
            if s is not None and p is not None:
                if s<0: kd="zarar"
                elif p>0 and s>p*1.05: kd="artiyor"
                elif p>0 and s<p*0.95: kd="azaliyor"
        elif eg is not None:
            if eg>0.05: kd="artiyor"
            elif eg<-0.1: kd="azaliyor"

        ts=0; uy=[]
        if kd=="artiyor":   ts+=1; uy.append("✅ Kar Artıyor")
        elif kd=="zarar":   ts-=2; uy.append("🚨 Zararda")
        elif kd=="azaliyor":ts-=1; uy.append("⚠ Kar Azalıyor")
        if pe and pe>0:
            if pe<10:  ts+=1; uy.append(f"✅ F/K Ucuz ({pe:.1f}x)")
            elif pe>30:ts-=1; uy.append(f"⚠ F/K Yüksek ({pe:.1f}x)")
            else:      uy.append(f"F/K Normal ({pe:.1f}x)")
        if pb and pb>0:
            if pb<1.0: ts+=1; uy.append(f"✅ PD/DD < 1 ({pb:.2f}x)")
            elif pb>5: ts-=1; uy.append(f"⚠ PD/DD Yüksek ({pb:.2f}x)")
        if de and de>0:
            if de>200: ts-=1; uy.append(f"🚨 Yüksek D/E ({de:.0f}%)")
            elif de<50:ts+=1; uy.append(f"✅ Düşük D/E ({de:.0f}%)")

        veri_var = bool(net_kar or pe or pb)
        return {
            "veri_var":veri_var,"kaynak":"yfinance" if veri_var else "yok",
            "sembol":sym,"net_kar":net_kar,"ciro":ciro,"favok":favok,
            "toplam_borc":toplam_borc,"ozkaynaklar":ozkaynaklar,
            "net_borc":net_borc,"borc_favok":borc_favok,
            "kar_durumu":kd,"temel_skor":max(-3,min(4,ts)),
            "uyarilar":uy,"yillar":yillar,"ham_df":None,
            "pe":round(float(pe),1) if pe and pe>0 else None,
            "pb":round(float(pb),2) if pb and pb>0 else None,
        }
    except Exception:
        return {**_BOSTA_BILANCO, "sembol": sym}


def oranlar_al(sembol: str, fiyat: float = 0.0) -> dict:
    sym = _sym_clean(sembol)
    _B = {"pe":None,"pd_dd":None,"roe":None,"net_marj":None,
          "kaynak":"yok","uyarilar":[],"skor":0,"yatirimlik":False}
    try:
        b = bilanco_al(sym)
        if not b.get("veri_var"): return _B
        nk=b.get("net_kar",[]); ci=b.get("ciro",[]); oz=b.get("ozkaynaklar")
        pe=b.get("pe"); pb=b.get("pb")
        sk=nk[-1] if nk else None; sc=ci[-1] if ci else None
        nm=round(sk/sc*100,1) if sk and sc else None
        roe=round(sk/oz*100,1) if sk and oz and oz>0 else None
        s=0; u=[]; y=False
        if pe and pe>0:
            if pe>30:  s-=1; u.append(f"⚠ F/K Pahalı: {pe:.1f}x")
            elif pe<10:s+=1; u.append(f"✅ F/K Ucuz: {pe:.1f}x")
        if pb and pb>0:
            if pb<1.0: s+=1; y=True; u.append(f"✅ PD/DD < 1 ({pb:.2f}x)")
            elif pb>5: s-=1; u.append(f"⚠ PD/DD Pahalı: {pb:.2f}x")
        if roe:
            if roe>25:  s+=1; u.append(f"✅ ROE: %{roe:.1f}")
            elif roe<0: s-=2; u.append(f"🚨 ROE Negatif: %{roe:.1f}")
        return {"pe":pe,"pd_dd":pb,"roe":roe,"net_marj":nm,
                "kaynak":"yfinance","uyarilar":u,"skor":max(-3,min(3,s)),"yatirimlik":y}
    except Exception:
        return _B


def zayif_bilanc_kontrol(sembol: str) -> dict:
    sym = _sym_clean(sembol)
    _B = {"risk":False,"etiket":"","sebep":"","dusus_pct":None}
    try:
        b = bilanco_al(sym)
        if not b.get("veri_var"): return _B
        nk = b.get("net_kar",[])
        if len(nk)<2: return _B
        s,p = nk[-1],nk[-2]
        if s is not None and s<0:
            return {"risk":True,"etiket":"🚨 ZAYIF BİLANÇO: ZARARDA",
                    "sebep":f"Net zarar: {s/1e6:.0f}M₺","dusus_pct":None}
        if s is not None and p and p>0:
            d=(s-p)/p*100
            if d<=-30:
                return {"risk":True,"etiket":f"⚠ ZAYIF BİLANÇO: Kar -{abs(d):.0f}% düştü",
                        "sebep":f"{p/1e6:.0f}M₺ → {s/1e6:.0f}M₺","dusus_pct":round(d,1)}
        return _B
    except Exception:
        return _B


def bilanco_ozet_json(sembol: str) -> dict:
    b=bilanco_al(sembol); r=oranlar_al(sembol); z=zayif_bilanc_kontrol(sembol)
    yl=b.get("yillar",[])
    def _f(lst):
        return [{"yil":y,"deger":v,"fmt":f"{v/1e6:.0f}M₺" if v else "?"}
                for y,v in zip(yl[-len(lst):],lst) if v is not None]
    return {
        "veri_var":b["veri_var"],"kaynak":b["kaynak"],
        "kar_durumu":b["kar_durumu"],"temel_skor":b["temel_skor"],
        "uyarilar":b["uyarilar"],"borc_favok":b["borc_favok"],
        "net_borc":b["net_borc"],
        "net_kar_grafik":_f(b["net_kar"]),"ciro_grafik":_f(b["ciro"]),"favok_grafik":_f(b["favok"]),
        "pe":r.get("pe") or b.get("pe"),"pb":r.get("pd_dd") or b.get("pb"),
        "roe":r.get("roe"),"net_marj":r.get("net_marj"),
        "oran_uyarilar":r.get("uyarilar",[]),"oran_skor":r.get("skor",0),
        "yatirimlik":r.get("yatirimlik",False),
        "zayif_bilanc":z["risk"],"zayif_bilanc_etiket":z["etiket"],
        "zayif_bilanc_sebep":z["sebep"],"dusus_pct":z["dusus_pct"],
    }


def durum_mesaji() -> str:
    return "yfinance ✅ aktif | blacklist ❌ kapalı"
