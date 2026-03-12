"""
isyatirim_veri.py — İş Yatırım Veri Katmanı v1.0
══════════════════════════════════════════════════
isyatirimhisse kütüphanesi üzerinden:
  ✅ Günlük OHLCV verisi  (yfinance yerine)
  ✅ Bilanço / Gelir Tablosu  (gerçek KAP verileri)
  ✅ Endeks verisi (XU100 vb.)
  ✅ Cache (15 dk fiyat, 24 saat bilanço)
  ✅ yfinance fallback (kütüphane yoksa)

Kullanım:
    from isyatirim_veri import ohlcv_al, bilanco_al, endeks_al
"""

import time
import threading
import warnings
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

# ─── Kütüphane Kontrolü ──────────────────────────────────────────
try:
    from isyatirimhisse import fetch_stock_data, fetch_index_data, fetch_financials
    _HAS_ISY = True
    print("[ISY] ✅ isyatirimhisse kütüphanesi yüklendi")
except ImportError:
    _HAS_ISY = False
    print("[ISY] ⚠ isyatirimhisse bulunamadı — yfinance fallback aktif")

try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

# ─── CACHE ────────────────────────────────────────────────────────
_OHLCV_CACHE: dict  = {}  # sembol → {df, ts}
_BILANCO_CACHE: dict = {}  # sembol → {data, ts}
_ENDEKS_CACHE: dict  = {}  # indeks → {df, ts}
_CACHE_LOCK = threading.RLock()
_OHLCV_TTL   = 900   # 15 dakika
_BILANCO_TTL = 86400 # 24 saat

# ─── YARDIMCI: Tarih Formatı ─────────────────────────────────────
def _bugun() -> str:
    return datetime.now().strftime("%d-%m-%Y")

def _gecmis(yil: int = 2, ay: int = 0) -> str:
    """N yıl/ay geriye giden tarihi DD-MM-YYYY formatında döndür."""
    d = datetime.now()
    try:
        yeni_yil = d.year - yil
        yeni_ay  = d.month - ay
        while yeni_ay <= 0:
            yeni_ay  += 12
            yeni_yil -= 1
        return datetime(yeni_yil, yeni_ay, d.day).strftime("%d-%m-%Y")
    except Exception:
        return (datetime.now() - timedelta(days=yil*365)).strftime("%d-%m-%Y")

def _period_to_dates(period: str) -> tuple:
    """yfinance period string → (start_date, end_date) DD-MM-YYYY"""
    _MAP = {
        "1d":  (0, 5),    "5d":  (0, 7),    "1mo": (0, 35),
        "3mo": (0, 95),   "6mo": (0, 185),  "1y":  (1, 0),
        "2y":  (2, 0),    "3y":  (3, 0),    "5y":  (5, 0),
    }
    yil, gun_ekstra = _MAP.get(period, (2, 0))
    bitis = datetime.now()
    if yil > 0:
        try:
            baslangic = datetime(bitis.year - yil, bitis.month, bitis.day)
        except Exception:
            baslangic = bitis - timedelta(days=yil*365)
    else:
        baslangic = bitis - timedelta(days=gun_ekstra)
    return baslangic.strftime("%d-%m-%Y"), bitis.strftime("%d-%m-%Y")

def _sym_clean(sembol: str) -> str:
    """THYAO.IS → THYAO"""
    return sembol.replace(".IS", "").replace(".is", "").upper().strip()

# ─── OHLCV VERİSİ ────────────────────────────────────────────────
def ohlcv_al(sembol: str, period: str = "2y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    Hisse OHLCV verisi.
    - interval != "1d" → yfinance'e düş (isyatirimhisse sadece günlük)
    - interval == "1d" → isyatirimhisse önce, yfinance fallback
    """
    sym = _sym_clean(sembol)
    cache_key = f"{sym}_{period}_{interval}"

    # Cache kontrolü
    with _CACHE_LOCK:
        hit = _OHLCV_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _OHLCV_TTL:
            return hit["df"].copy()

    df = None

    # Sadece günlük veri için isyatirimhisse kullan
    if interval == "1d" and _HAS_ISY:
        df = _isy_ohlcv(sym, period)

    # Fallback: yfinance
    if df is None and _HAS_YF:
        df = _yf_ohlcv(sym, period, interval)

    if df is not None and not df.empty:
        with _CACHE_LOCK:
            _OHLCV_CACHE[cache_key] = {"df": df.copy(), "ts": time.time()}

    return df


def _isy_ohlcv(sym: str, period: str) -> Optional[pd.DataFrame]:
    """isyatirimhisse'den günlük OHLCV al."""
    try:
        start, end = _period_to_dates(period)
        raw = fetch_stock_data(symbols=sym, start_date=start, end_date=end)
        if raw is None or raw.empty:
            return None
        raw = raw.reset_index()
        # isyatirimhisse sütun adları: Date, {SYM}_Close, {SYM}_Open, vb.
        # veya tek hisse için doğrudan: Date, Close, Open...
        col_map = {}
        for col in raw.columns:
            cl = col.replace(f"{sym}_", "").replace(f"{sym.lower()}_", "")
            cl_cap = cl.capitalize() if cl.lower() != "date" else "Date"
            # İsmi normalize et
            name_map = {
                "close": "Close", "open": "Open",
                "high": "High",   "low": "Low",
                "volume": "Volume", "date": "Date",
            }
            normalized = name_map.get(cl.lower(), cl)
            col_map[col] = normalized

        raw = raw.rename(columns=col_map)
        if "Date" in raw.columns:
            raw["Date"] = pd.to_datetime(raw["Date"])
            raw = raw.set_index("Date")
        raw = raw.sort_index()
        needed = {"Open", "High", "Low", "Close", "Volume"}
        if not needed.issubset(raw.columns):
            return None
        raw = raw[list(needed)].astype(float)
        raw = raw.dropna(subset=["Close"])
        return raw if not raw.empty else None
    except Exception as e:
        print(f"[ISY] OHLCV hata {sym}: {e}")
        return None


def _yf_ohlcv(sym: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """yfinance fallback."""
    if not _HAS_YF:
        return None
    try:
        import io, sys
        old_err = sys.stderr
        sys.stderr = io.StringIO()
        try:
            df = yf.download(
                f"{sym}.IS", period=period, interval=interval,
                progress=False, auto_adjust=True
            )
        finally:
            sys.stderr = old_err
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
        needed = {"Open", "High", "Low", "Close", "Volume"}
        if not needed.issubset(df.columns):
            return None
        return df[list(needed)].astype(float).dropna(subset=["Close"])
    except Exception as e:
        print(f"[YF] OHLCV hata {sym}: {e}")
        return None


# ─── BİLANÇO / GELİR TABLOSU ─────────────────────────────────────
def bilanco_al(sembol: str, yil_sayisi: int = 3) -> dict:
    """
    Son N yılın finansal verilerini çeker.
    Returns: {
        veri_var:       bool,
        kaynak:         "isyatirimhisse" | "yfinance" | "yok",
        net_kar:        list[float],  # son 3 yıl
        ciro:           list[float],
        favok:          list[float],
        toplam_borc:    float | None,
        ozkaynaklar:    float | None,
        net_borc:       float | None,
        borc_favok:     float | None,
        kar_durumu:     "artiyor" | "azaliyor" | "zarar" | "belirsiz",
        temel_skor:     int,   # 0..4
        uyarilar:       list[str],
        yillar:         list[int],
        ham_df:         DataFrame | None,
    }
    """
    sym = _sym_clean(sembol)
    cache_key = f"bilanco_{sym}"

    with _CACHE_LOCK:
        hit = _BILANCO_CACHE.get(cache_key)
        if hit and (time.time() - hit["ts"]) < _BILANCO_TTL:
            return hit["data"]

    result = _BOSTA_BILANCO.copy()
    result["sembol"] = sym

    if _HAS_ISY:
        result = _isy_bilanco(sym, yil_sayisi)
        if not result["veri_var"] and _HAS_YF:
            result = _yf_bilanco(sym)
    elif _HAS_YF:
        result = _yf_bilanco(sym)

    with _CACHE_LOCK:
        _BILANCO_CACHE[cache_key] = {"data": result, "ts": time.time()}

    return result


_BOSTA_BILANCO = {
    "veri_var": False, "kaynak": "yok", "sembol": "",
    "net_kar": [], "ciro": [], "favok": [],
    "toplam_borc": None, "ozkaynaklar": None,
    "net_borc": None, "borc_favok": None,
    "kar_durumu": "belirsiz", "temel_skor": 0,
    "uyarilar": ["Bilanço verisi bulunamadı"],
    "yillar": [], "ham_df": None,
    "pe": None, "pb": None,
}


def _isy_bilanco(sym: str, yil_sayisi: int = 3) -> dict:
    """isyatirimhisse fetch_financials ile bilanço çek."""
    try:
        bitis_yil  = datetime.now().year
        baslangic_yil = bitis_yil - yil_sayisi

        # financial_group='2' → IFRS (büyük şirketler)
        # financial_group='1' → XI_29 (KOBİ)
        df = None
        for fg in ["2", "1", "3", "4"]:
            try:
                df = fetch_financials(
                    symbols=sym,
                    start_year=baslangic_yil,
                    end_year=bitis_yil,
                    exchange="TRY",
                    financial_group=fg,
                )
                if df is not None and not df.empty:
                    break
            except Exception:
                continue

        if df is None or df.empty:
            # Bilanço yok ama hisseyi elemeyiz — boş ama geçerli sonuç dön
            return {**_BOSTA_BILANCO, "sembol": sym, "veri_var": False, "kaynak": "yok"}

        # ─── Bilanço kalemlerini bul ──────────────────────────────
        # isyatirimhisse DataFrame yapısı:
        # Index = kalem adları, Columns = dönem (ör. "2023/12", "2024/12")
        # veya yatay formatta olabilir

        # Index'i string'e çevir ve küçük harf yap
        if isinstance(df.index, pd.RangeIndex):
            # Yatay format olabilir
            df = df.set_index(df.columns[0]) if len(df.columns) > 1 else df

        df.index = df.index.astype(str).str.strip()

        # Sütunları dönemlere göre sırala
        try:
            kolonlar = sorted(
                [c for c in df.columns if "/" in str(c) or str(c).isdigit()],
                key=lambda x: str(x)
            )
        except Exception:
            kolonlar = list(df.columns)

        # Son yılları al
        son_kolonlar = kolonlar[-yil_sayisi:] if len(kolonlar) >= yil_sayisi else kolonlar
        yillar = [int(str(k).split("/")[0]) if "/" in str(k) else int(k) for k in son_kolonlar]

        def _bul(anahtar_listesi: list) -> Optional[list]:
            """Bilanço kalemini bul (birden fazla isim denemesi)."""
            for anahtar in anahtar_listesi:
                for idx_val in df.index:
                    if anahtar.lower() in idx_val.lower():
                        try:
                            degerler = []
                            for k in son_kolonlar:
                                v = df.loc[idx_val, k]
                                if pd.notna(v):
                                    degerler.append(float(v))
                                else:
                                    degerler.append(None)
                            if any(v is not None for v in degerler):
                                return degerler
                        except Exception:
                            continue
            return None

        def _tek(anahtar_listesi: list) -> Optional[float]:
            """Son dönem tek değer."""
            sonuc = _bul(anahtar_listesi)
            if sonuc:
                for v in reversed(sonuc):
                    if v is not None:
                        return v
            return None

        # ─── Temel kalemleri çek ──────────────────────────────────
        # Net Kar
        net_kar_list = _bul([
            "Net Dönem Karı", "Net Kar", "Net Dönem Kârı",
            "Dönem Net Karı", "Net Profit", "Net Income",
            "Dönem Kârı", "Dönem Karı"
        ])

        # Ciro / Hasılat
        ciro_list = _bul([
            "Hasılat", "Satış Gelirleri", "Ciro", "Net Satışlar",
            "Revenue", "Satışlar", "Brüt Satışlar"
        ])

        # FAVÖK / Brüt Kar proxy
        favok_list = _bul([
            "FAVÖK", "EBITDA", "Faaliyet Karı",
            "Brüt Kar", "Esas Faaliyet Karı"
        ])

        # Toplam Borç
        toplam_borc = _tek([
            "Toplam Borçlar", "Toplam Finansal Borçlar",
            "Toplam Yükümlülükler", "Financial Debt",
            "Kısa+Uzun Vadeli Borçlar", "Borçlanmalar"
        ])

        # Özkaynak
        ozkaynaklar = _tek([
            "Özkaynaklar", "Özkaynak", "Toplam Özkaynak",
            "Total Equity", "Equity"
        ])

        # Nakit
        nakit = _tek([
            "Nakit ve Nakit Benzerleri", "Nakit",
            "Cash", "Cash and Equivalents"
        ])

        # ─── Hesaplamalar ─────────────────────────────────────────
        net_kar_clean = [v for v in (net_kar_list or []) if v is not None]
        ciro_clean    = [v for v in (ciro_list    or []) if v is not None]
        favok_clean   = [v for v in (favok_list   or []) if v is not None]

        # Net Borç = Toplam Borç - Nakit
        net_borc = None
        if toplam_borc is not None and nakit is not None:
            net_borc = round(toplam_borc - nakit, 0)
        elif toplam_borc is not None:
            net_borc = toplam_borc

        # Net Borç / FAVÖK
        borc_favok = None
        son_favok = favok_clean[-1] if favok_clean else None
        if net_borc is not None and son_favok and son_favok > 0:
            borc_favok = round(net_borc / son_favok, 1)

        # ─── Kar Durumu ───────────────────────────────────────────
        son_kar  = net_kar_clean[-1] if net_kar_clean else None
        prev_kar = net_kar_clean[-2] if len(net_kar_clean) >= 2 else None

        if son_kar is None:
            kar_durumu = "belirsiz"
        elif son_kar < 0:
            kar_durumu = "zarar"
        elif prev_kar is not None and prev_kar != 0:
            buyume = (son_kar - prev_kar) / abs(prev_kar) * 100
            if buyume > 10:
                kar_durumu = "artiyor"
            elif buyume < -15:
                kar_durumu = "azaliyor"
            else:
                kar_durumu = "sabit"
        else:
            kar_durumu = "sabit"

        # ─── Temel Skor (0..4) ────────────────────────────────────
        temel_skor = 0
        uyarilar   = []

        # 1) Net Kar kontrolü
        if kar_durumu == "artiyor":
            temel_skor += 1
            uyarilar.append(f"✅ Kar Büyüyor: {_milyar(son_kar)}")
        elif kar_durumu == "zarar":
            temel_skor -= 2
            uyarilar.append(f"🚨 ŞİRKET ZARARDA: {_milyar(son_kar)}")
        elif kar_durumu == "azaliyor":
            temel_skor -= 1
            uyarilar.append(f"⚠ Kar Azalıyor: {_milyar(son_kar)}")
        elif kar_durumu == "sabit":
            uyarilar.append(f"➡ Kar Sabit: {_milyar(son_kar)}")
        else:
            uyarilar.append("Net Kar — veri yok")

        # 2) Net Borç / FAVÖK kontrolü
        if borc_favok is not None:
            if borc_favok > 10:
                temel_skor -= 2
                uyarilar.append(f"🚨 AŞ. BORÇLU: Net Borç/FAVÖK = {borc_favok:.1f}x")
            elif borc_favok > 5:
                temel_skor -= 1
                uyarilar.append(f"⚠ Yüksek Borç: Net Borç/FAVÖK = {borc_favok:.1f}x")
            elif borc_favok < 0:
                temel_skor += 1
                uyarilar.append(f"✅ Net Nakit Pozisyon (Borç/FAVÖK={borc_favok:.1f}x)")
            elif borc_favok < 2:
                temel_skor += 1
                uyarilar.append(f"✅ Düşük Borç: Net Borç/FAVÖK = {borc_favok:.1f}x")
            else:
                uyarilar.append(f"Borç/FAVÖK = {borc_favok:.1f}x")

        # 3) Borç/Özkaynak oranı
        if toplam_borc is not None and ozkaynaklar and ozkaynaklar > 0:
            boe = round(toplam_borc / ozkaynaklar, 2)
            if boe > 3:
                temel_skor -= 1
                uyarilar.append(f"⚠ Borç/Özkaynak Yüksek: {boe:.1f}x")
            elif boe < 0.5:
                temel_skor += 1
                uyarilar.append(f"✅ Güçlü Özkaynak: Borç/ÖK = {boe:.1f}x")
            else:
                uyarilar.append(f"Borç/Özkaynak: {boe:.1f}x")

        # 4) Ciro büyümesi
        if len(ciro_clean) >= 2 and ciro_clean[-2] and ciro_clean[-2] != 0:
            ciro_buy = (ciro_clean[-1] - ciro_clean[-2]) / abs(ciro_clean[-2]) * 100
            if ciro_buy > 20:
                temel_skor += 1
                uyarilar.append(f"✅ Ciro Büyüyor +{ciro_buy:.0f}%: {_milyar(ciro_clean[-1])}")
            elif ciro_buy > 0:
                uyarilar.append(f"Ciro +{ciro_buy:.0f}%: {_milyar(ciro_clean[-1])}")
            else:
                uyarilar.append(f"⚠ Ciro Düşüyor {ciro_buy:.0f}%: {_milyar(ciro_clean[-1])}")

        temel_skor = max(-3, min(4, temel_skor))

        return {
            "veri_var":      True,
            "kaynak":        "isyatirimhisse",
            "sembol":        sym,
            "net_kar":       net_kar_clean,
            "ciro":          ciro_clean,
            "favok":         favok_clean,
            "toplam_borc":   toplam_borc,
            "ozkaynaklar":   ozkaynaklar,
            "net_borc":      net_borc,
            "borc_favok":    borc_favok,
            "kar_durumu":    kar_durumu,
            "temel_skor":    temel_skor,
            "uyarilar":      uyarilar,
            "yillar":        yillar,
            "ham_df":        df,
            "pe":            None,  # isyatirimhisse'de P/E yok
            "pb":            None,
        }

    except Exception as e:
        print(f"[ISY] Bilanço hata {sym}: {e}")
        return {**_BOSTA_BILANCO, "sembol": sym}


def _yf_bilanco(sym: str) -> dict:
    """yfinance fallback bilanço."""
    if not _HAS_YF:
        return {**_BOSTA_BILANCO, "sembol": sym}
    try:
        import io, sys
        old = sys.stderr; sys.stderr = io.StringIO()
        try:
            ticker = yf.Ticker(f"{sym}.IS")
            info   = ticker.info or {}
        finally:
            sys.stderr = old

        pe  = info.get("trailingPE")
        pb  = info.get("priceToBook")
        eg  = info.get("earningsGrowth")

        if eg is not None and eg > 0:
            kar_durumu = "artiyor"
        elif eg is not None and eg < -0.1:
            kar_durumu = "azaliyor"
        else:
            kar_durumu = "belirsiz"

        uyarilar = []
        temel_skor = 0

        if pe and pe > 0:
            if pe > 30: uyarilar.append(f"⚠ F/K Yüksek ({pe:.1f}x)")
            elif pe < 10:
                temel_skor += 1
                uyarilar.append(f"✅ F/K Ucuz ({pe:.1f}x)")
            else: uyarilar.append(f"F/K Normal ({pe:.1f}x)")

        de = info.get("debtToEquity")
        if de and de > 200:
            temel_skor -= 1
            uyarilar.append(f"🚨 Yüksek Borç D/E {de:.0f}%")
        elif de and de < 30:
            temel_skor += 1
            uyarilar.append(f"✅ Düşük Borç D/E {de:.0f}%")

        return {
            "veri_var":    bool(pe or pb),
            "kaynak":      "yfinance",
            "sembol":      sym,
            "net_kar":     [],
            "ciro":        [],
            "favok":       [],
            "toplam_borc": None,
            "ozkaynaklar": None,
            "net_borc":    None,
            "borc_favok":  None,
            "kar_durumu":  kar_durumu,
            "temel_skor":  temel_skor,
            "uyarilar":    uyarilar or ["yfinance bilanço (sınırlı)"],
            "yillar":      [],
            "ham_df":      None,
            "pe":          round(float(pe), 1) if pe and pe > 0 else None,
            "pb":          round(float(pb), 2) if pb and pb > 0 else None,
        }
    except Exception as e:
        print(f"[YF] Bilanço hata {sym}: {e}")
        return {**_BOSTA_BILANCO, "sembol": sym}


# ─── ENDEKS VERİSİ ───────────────────────────────────────────────
def endeks_al(endeks: str = "XU100") -> Optional[pd.DataFrame]:
    """Endeks verisi (isyatirimhisse → yfinance fallback)."""
    with _CACHE_LOCK:
        hit = _ENDEKS_CACHE.get(endeks)
        if hit and (time.time() - hit["ts"]) < _OHLCV_TTL:
            return hit["df"].copy()

    df = None
    if _HAS_ISY:
        try:
            start, end = _period_to_dates("5d")
            df = fetch_index_data(indices=endeks, start_date=start, end_date=end)
            if df is not None and not df.empty:
                df = df.reset_index()
                df.columns = [c.replace(f"{endeks}_", "") for c in df.columns]
                df = df.rename(columns={
                    "close": "Close", "open": "Open",
                    "high": "High",   "low": "Low",
                    "volume": "Volume", "date": "Date",
                })
                if "Date" in df.columns:
                    df["Date"] = pd.to_datetime(df["Date"])
                    df = df.set_index("Date")
                df = df.sort_index()
        except Exception as e:
            print(f"[ISY] Endeks hata: {e}")
            df = None

    if df is None and _HAS_YF:
        try:
            import io, sys
            old = sys.stderr; sys.stderr = io.StringIO()
            try:
                df = yf.download("XU100.IS", period="5d", interval="1d",
                                 progress=False, auto_adjust=True)
            finally:
                sys.stderr = old
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
        except Exception:
            df = None

    if df is not None and not df.empty:
        with _CACHE_LOCK:
            _ENDEKS_CACHE[endeks] = {"df": df.copy(), "ts": time.time()}

    return df


# ─── YARDIMCI FONKSİYONLAR ───────────────────────────────────────
def _milyar(deger: Optional[float]) -> str:
    """Sayıyı okunabilir biçimde formatla (milyar / milyon)."""
    if deger is None:
        return "?"
    if abs(deger) >= 1_000_000_000:
        return f"{deger/1_000_000_000:.1f}B₺"
    elif abs(deger) >= 1_000_000:
        return f"{deger/1_000_000:.0f}M₺"
    return f"{deger:.0f}₺"


# ─── ORANLAR (F/K, PD/DD, ROE) ──────────────────────────────────
def oranlar_al(sembol: str, fiyat: float = 0.0) -> dict:
    """
    F/K, PD/DD, ROE, Net Kar Marjı oranlarını hesaplar.
    isyatirimhisse finansal tablosundan türetilir.

    Returns: {
        pe: float|None,   pd_dd: float|None,  roe: float|None,
        net_marj: float|None,  kaynak: str,
        uyarilar: list[str],   skor: int  (-2..+2)
    }
    """
    sym = _sym_clean(sembol)
    _BOSTA = {"pe": None, "pd_dd": None, "roe": None,
              "net_marj": None, "kaynak": "yok",
              "uyarilar": ["Oran verisi bulunamadı"], "skor": 0,
              "yatirimlik": False}

    if not _HAS_ISY and not _HAS_YF:
        return _BOSTA

    try:
        b = bilanco_al(sym)
        if not b.get("veri_var"):
            return _BOSTA

        net_kar_list = b.get("net_kar", [])
        ciro_list    = b.get("ciro",    [])
        ozkaynaklar  = b.get("ozkaynaklar")

        son_kar  = net_kar_list[-1]  if net_kar_list else None
        son_ciro = ciro_list[-1]     if ciro_list    else None

        # ── Net Kar Marjı ────────────────────────────────────────
        net_marj = None
        if son_kar and son_ciro and son_ciro != 0:
            net_marj = round(son_kar / son_ciro * 100, 1)

        # ── ROE (Özsermaye Karlılığı) ────────────────────────────
        roe = None
        if son_kar and ozkaynaklar and ozkaynaklar > 0:
            roe = round(son_kar / ozkaynaklar * 100, 1)

        # ── P/E ve P/B (fiyat bilgisi yoksa None) ────────────────
        pe    = b.get("pe")   # isyatirimhisse'den geliyorsa
        pd_dd = b.get("pb")   # isyatirimhisse'den geliyorsa

        # ── Puanlama ─────────────────────────────────────────────
        skor     = 0
        uyarilar = []
        yatirimlik = False

        if pe and pe > 0:
            if pe > 30:    skor -= 1; uyarilar.append(f"⚠ F/K Pahalı: {pe:.1f}x")
            elif pe < 10:  skor += 1; uyarilar.append(f"✅ F/K Ucuz: {pe:.1f}x")
            else:          uyarilar.append(f"F/K Normal: {pe:.1f}x")

        if pd_dd and pd_dd > 0:
            if pd_dd < 1.0:
                skor += 1
                uyarilar.append(f"✅ PD/DD < 1 ({pd_dd:.2f}x) — Defter değerinin altında!")
                yatirimlik = True   # KELEPİR adayı
            elif pd_dd < 1.5:
                skor += 1
                uyarilar.append(f"✅ PD/DD Değer: {pd_dd:.2f}x")
            elif pd_dd > 5:
                skor -= 1
                uyarilar.append(f"⚠ PD/DD Pahalı: {pd_dd:.2f}x")
            else:
                uyarilar.append(f"PD/DD Normal: {pd_dd:.2f}x")

        if roe is not None:
            if roe > 25:   skor += 1; uyarilar.append(f"✅ ROE Yüksek: %{roe:.1f}")
            elif roe > 15: uyarilar.append(f"ROE İyi: %{roe:.1f}")
            elif roe < 5:  skor -= 1; uyarilar.append(f"⚠ ROE Düşük: %{roe:.1f}")
            elif roe < 0:  skor -= 2; uyarilar.append(f"🚨 ROE Negatif: %{roe:.1f}")

        if net_marj is not None:
            if net_marj > 20:  uyarilar.append(f"✅ Net Kar Marjı: %{net_marj:.1f}")
            elif net_marj < 0: skor -= 1; uyarilar.append(f"🚨 Net Marj Negatif: %{net_marj:.1f}")
            else:              uyarilar.append(f"Net Marj: %{net_marj:.1f}")

        return {
            "pe": pe, "pd_dd": pd_dd, "roe": roe,
            "net_marj": net_marj,
            "kaynak": b.get("kaynak", "bilinmiyor"),
            "uyarilar": uyarilar,
            "skor": max(-3, min(3, skor)),
            "yatirimlik": yatirimlik,
        }

    except Exception as e:
        print(f"[ISY] Oranlar hata {sym}: {e}")
        return _BOSTA


# ─── %30 KAR DÜŞÜŞ FİLTRESİ ──────────────────────────────────────
def zayif_bilanc_kontrol(sembol: str) -> dict:
    """
    Net Dönem Karı son yıl bir önceki yıla göre %30'dan fazla düşmüş mü?
    veya şirket zararda mı?

    Returns: {
        risk: bool,
        etiket: str,    # "ZAYIF BİLANÇO: RİSKLİ" | ""
        sebep: str,
        dusus_pct: float | None
    }
    """
    sym = _sym_clean(sembol)
    _BOSTA = {"risk": False, "etiket": "", "sebep": "", "dusus_pct": None}

    try:
        b = bilanco_al(sym)
        if not b.get("veri_var"):
            return _BOSTA

        net_kar = b.get("net_kar", [])
        if len(net_kar) < 2:
            return _BOSTA

        son_kar  = net_kar[-1]
        prev_kar = net_kar[-2]

        # Zarar durumu
        if son_kar is not None and son_kar < 0:
            return {
                "risk":      True,
                "etiket":    "🚨 ZAYIF BİLANÇO: ŞİRKET ZARARDA",
                "sebep":     f"Son dönem net zarar: {_milyar(son_kar)}",
                "dusus_pct": None,
            }

        # %30+ düşüş
        if son_kar is not None and prev_kar and prev_kar > 0:
            dusus = (son_kar - prev_kar) / prev_kar * 100
            if dusus <= -30:
                return {
                    "risk":      True,
                    "etiket":    f"⚠ ZAYIF BİLANÇO: Kar -{abs(dusus):.0f}% düştü",
                    "sebep":     f"{_milyar(prev_kar)} → {_milyar(son_kar)}",
                    "dusus_pct": round(dusus, 1),
                }

        return _BOSTA

    except Exception as e:
        print(f"[ISY] Zayıf bilanço kontrol hata {sym}: {e}")
        return _BOSTA


def bilanco_ozet_json(sembol: str) -> dict:
    """
    Dashboard için bilanço + oran özet JSON'u.
    Grafik için yıllar + değerler listesi döndürür.
    """
    b = bilanco_al(sembol)
    r = oranlar_al(sembol)
    z = zayif_bilanc_kontrol(sembol)
    yillar = b.get("yillar", [])

    def _fmt_list(lst, yillar):
        return [{"yil": y, "deger": v, "fmt": _milyar(v)}
                for y, v in zip(yillar[-len(lst):], lst) if v is not None]

    return {
        "veri_var":       b["veri_var"],
        "kaynak":         b["kaynak"],
        "kar_durumu":     b["kar_durumu"],
        "temel_skor":     b["temel_skor"],
        "uyarilar":       b["uyarilar"],
        "borc_favok":     b["borc_favok"],
        "net_borc":       b["net_borc"],
        "net_kar_grafik": _fmt_list(b["net_kar"], yillar),
        "ciro_grafik":    _fmt_list(b["ciro"],    yillar),
        "favok_grafik":   _fmt_list(b["favok"],   yillar),
        # Oranlar
        "pe":        r.get("pe")    or b.get("pe"),
        "pb":        r.get("pd_dd") or b.get("pb"),
        "roe":       r.get("roe"),
        "net_marj":  r.get("net_marj"),
        "oran_uyarilar": r.get("uyarilar", []),
        "oran_skor":     r.get("skor", 0),
        "yatirimlik":    r.get("yatirimlik", False),
        # Zayıf bilanço uyarısı
        "zayif_bilanc": z["risk"],
        "zayif_bilanc_etiket": z["etiket"],
        "zayif_bilanc_sebep":  z["sebep"],
        "dusus_pct":           z["dusus_pct"],
    }


def durum_mesaji() -> str:
    """Hangi kütüphane aktif, durum mesajı."""
    if _HAS_ISY:
        return "isyatirimhisse ✅ aktif"
    elif _HAS_YF:
        return "yfinance fallback ⚠ aktif"
    return "Veri kaynağı yok ❌"


print(f"[ISY] Veri katmanı: {durum_mesaji()}")
