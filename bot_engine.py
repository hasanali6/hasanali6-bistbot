"""
bot_engine.py — BIST Sinyal Motoru v5.0 (FINAL)
════════════════════════════════════════════════
Düzeltmeler (v4→v5):
  ✅ Bellek sızıntısı giderildi (df artık döndürülmüyor)
  ✅ Blacklist bellekte de güncelleniyor
  ✅ Sadece gerçek delisting hataları blacklist'e gidiyor
  ✅ Ağırlıklar normalize edildi (toplam = 1.0)
  ✅ Duplikat ticker temizlendi
  ✅ Thread-safe endeks cache
"""

import time
import threading
import warnings
import os
import sys
import io
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─── İş Yatırım Veri Katmanı ─────────────────────────────────────
try:
    from isyatirim_veri import ohlcv_al as _ISY_OHLCV, bilanco_al as _ISY_BILANCO
    _HAS_ISY_VERI = True
    print("[BOT] ✅ isyatirim_veri modülü yüklendi")
except ImportError:
    _HAS_ISY_VERI = False
    print("[BOT] ⚠ isyatirim_veri bulunamadı")

# yfinance — sadece fallback ve intraday için
try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

# ─── yfinance STDERR SUSTUR ───────────────────────────────────────
# "possibly delisted; no price data found" mesajları terminalde görünmesin.
# Bunlar zaten blacklist mekanizmasıyla yakalanıyor.
@contextmanager
def _sessiz():
    """yfinance'in stderr çıktısını yakala, terminale bastırma."""
    old_err = sys.stderr
    old_out = sys.stdout
    try:
        sys.stderr = io.StringIO()
        yield
    finally:
        captured = sys.stderr.getvalue()
        sys.stderr = old_err
        # Sadece gerçek hatalar (blacklist dışı) loglan
        if captured and not any(k in captured for k in [
            "possibly delisted", "no price data", "No data found",
            "auto_adjust", "Delisted", "YFPricesMissingError",
            "Failed download", "1 Failed"
        ]):
            print(captured, file=old_err, end="")

DEBUG = os.environ.get("BIST_DEBUG", "0") == "1"
def _log(m):
    if DEBUG: print(f"[DEBUG] {m}")

# ─── BLACKLIST ────────────────────────────────────────────────────
BLACKLIST_FILE = "blacklist.txt"
_BL_LOCK = threading.RLock()
_BLACKLIST: set = set()

def _bl_yukle() -> set:
    try:
        with open(BLACKLIST_FILE) as f:
            return {l.strip() for l in f if l.strip()}
    except FileNotFoundError:
        return set()

def _bl_ekle(sembol: str):
    """Sembolü hem dosyaya hem belleğe ekle."""
    global _BLACKLIST
    with _BL_LOCK:
        if sembol in _BLACKLIST:
            return  # Zaten var
        _BLACKLIST.add(sembol)
        try:
            with open(BLACKLIST_FILE, "a") as f:
                f.write(sembol + "\n")
        except Exception:
            pass
    print(f"[BOT] ⛔ Blacklist: {sembol}")

def _is_delisting_error(err_str: str) -> bool:
    """Sadece gerçek delisting/no-data hatalarını yakala."""
    err = err_str.lower()
    return any(k in err for k in [
        "no data found", "no price data", "possibly delisted",
        "symbol may be delisted", "delisted", "no timezone found",
    ])

_BLACKLIST = _bl_yukle()

# ─── BIST HİSSE LİSTESİ ──────────────────────────────────────────
try:
    import requests as _req
    _HAS_REQ = True
except ImportError:
    _HAS_REQ = False

# Temiz hardcoded liste — 319 hisse, duplikatsız
_HC = [
    "ACSEL.IS","ADANA.IS","ADEL.IS","ADESE.IS","ADNAC.IS","AEFES.IS","AFYON.IS","AGESA.IS",
    "AGHOL.IS","AGROT.IS","AGYO.IS","AHGAZ.IS","AKBNK.IS","AKCNS.IS","AKENR.IS","AKFEN.IS",
    "AKFGY.IS","AKGRT.IS","AKMGY.IS","AKSA.IS","AKSEN.IS","AKSGY.IS","ALARK.IS","ALBRK.IS",
    "ALCAR.IS","ALCTL.IS","ALFAS.IS","ALGYO.IS","ALKA.IS","ALKIM.IS","ALKLC.IS","ALMAD.IS",
    "ALNOS.IS","ALTES.IS","ALTINS.IS","ALVES.IS","ANACM.IS","ANELE.IS","ANER.IS","ANERB.IS",
    "ANHYT.IS","ANJAS.IS","ANKPA.IS","ANSGR.IS","ANTST.IS","ARASE.IS","ARCLK.IS","ARDYZ.IS",
    "ARENA.IS","ARFYO.IS","ARSAN.IS","ARTMS.IS","ARZUM.IS","ASCEL.IS","ASELS.IS","ASGYO.IS",
    "ASLAN.IS","ASUZU.IS","ATAGY.IS","ATAKP.IS","ATATP.IS","ATEKS.IS","ATLAS.IS","ATPET.IS",
    "AVGYO.IS","AVHOL.IS","AVISA.IS","AVOD.IS","AVTUR.IS","AYCES.IS","AYDEM.IS","AYEN.IS",
    "AYNES.IS","AYRNT.IS","AZTEK.IS","BAGFS.IS","BAHKM.IS","BAKAB.IS","BALAT.IS","BALT.IS",
    "BANVT.IS","BARMA.IS","BASCM.IS","BASGZ.IS","BAYRK.IS","BERA.IS","BEYAZ.IS","BFREN.IS",
    "BIMAS.IS","BJKAS.IS","BLCYT.IS","BMEKS.IS","BMSCH.IS","BOLUC.IS","BOSSA.IS","BRISA.IS",
    "BRKO.IS","BRKVY.IS","BRMEN.IS","BRSAS.IS","BSOKE.IS","BTCIM.IS","BUCIM.IS","BURCE.IS",
    "BURVA.IS","BVSAN.IS","BYDNR.IS","CANTE.IS","CATES.IS","CBGYO.IS","CCOLA.IS","CELHA.IS",
    "CEMAS.IS","CEMTS.IS","CEOEM.IS","CGCAM.IS","CIMSA.IS","CLEBI.IS","CLOUD.IS","CMBTN.IS",
    "CMENT.IS","CONSE.IS","COSMO.IS","CRDFA.IS","CRFSA.IS","CUSAN.IS","CVKMD.IS","CWENE.IS",
    "DAGHL.IS","DAGI.IS","DAPGM.IS","DARDL.IS","DATEGY.IS","DENGE.IS","DERHL.IS","DERIM.IS",
    "DESA.IS","DESPC.IS","DEVA.IS","DGATE.IS","DGKLB.IS","DGNMO.IS","DIRI.IS","DITAS.IS",
    "DMSAS.IS","DOAS.IS","DOGUB.IS","DOHOL.IS","DOKTA.IS","DURDO.IS","DYOBY.IS","DZGYO.IS",
    "ECILC.IS","ECZYT.IS","EDATA.IS","EDIP.IS","EFORC.IS","EGEEN.IS","EGGUB.IS","EGPRO.IS",
    "EGSER.IS","EKGYO.IS","EKSUN.IS","ELITE.IS","EMKEL.IS","EMNIS.IS","ENERY.IS","ENFRA.IS",
    "ENGYO.IS","ENJSA.IS","ENKAI.IS","EPLAS.IS","ERCAN.IS","ERCB.IS","EREGL.IS","ERSU.IS",
    "ESCAR.IS","ESCOM.IS","ESEN.IS","ETILR.IS","ETYAT.IS","EUREN.IS","EUYO.IS","EVREN.IS",
    "FADCO.IS","FENER.IS","FENR.IS","FLAP.IS","FMIZP.IS","FONET.IS","FORMT.IS","FORTE.IS",
    "FRIGO.IS","FROTO.IS","FZLGY.IS","GARAN.IS","GARFA.IS","GEDZA.IS","GENIL.IS","GENTS.IS",
    "GEREL.IS","GESAN.IS","GIPTA.IS","GLBMD.IS","GLCVY.IS","GLRYH.IS","GLYHO.IS","GMTAS.IS",
    "GOKNR.IS","GOLTS.IS","GOODY.IS","GOZDE.IS","GRSEL.IS","GRTHO.IS","GSDDE.IS","GSDHO.IS",
    "GSRAY.IS","GUBRE.IS","GUBRF.IS","GUNDG.IS","GUSGR.IS","GWIND.IS","HALKB.IS","HATEK.IS",
    "HEDEF.IS","HEKTS.IS","HLGYO.IS","HRKET.IS","HTTBT.IS","HUBVC.IS","HUNER.IS","HURGZ.IS",
    "ICBCT.IS","IEYHO.IS","IHAAS.IS","IHEVA.IS","IHGZT.IS","IHLAS.IS","IHLGM.IS","IHYAY.IS",
    "IMASM.IS","INDES.IS","INTEM.IS","INVES.IS","IPEKE.IS","ISBIR.IS","ISCTR.IS","ISFIN.IS",
    "ISGSY.IS","ISGYO.IS","ISMEN.IS","ISYAT.IS","IZFAS.IS","IZMDC.IS","IZOCM.IS","JANTS.IS",
    "KAPLM.IS","KAREL.IS","KARSN.IS","KARTN.IS","KCHOL.IS","KERVT.IS","KFEIN.IS","KIPA.IS",
    "KLGYO.IS","KLKIM.IS","KLMSN.IS","KLNMA.IS","KLRHO.IS","KLSER.IS","KLSYN.IS","KMPUR.IS",
    "KNFRT.IS","KONKA.IS","KONTR.IS","KONYA.IS","KOPOL.IS","KORDS.IS","KOZAA.IS","KOZAL.IS",
    "KRDMA.IS","KRDMB.IS","KRDMD.IS","KRPLS.IS","KRSTL.IS","KRTEK.IS","KUYAS.IS","KZBGY.IS",
    "LCWGK.IS","LIDER.IS","LILAK.IS","LINK.IS","LKMNH.IS","LOGO.IS","LRSHO.IS","LUKSK.IS",
    "MAALT.IS","MACKO.IS","MAGEN.IS","MAKIM.IS","MAKTK.IS","MANAS.IS","MAVI.IS","MEDTR.IS",
    "MEGAP.IS","MEKAG.IS","MERKO.IS","METRO.IS","METUR.IS","MGROS.IS","MIPAZ.IS","MMCAS.IS",
    "MNDRS.IS","MNVRL.IS","MOBTL.IS","MOGAN.IS","MONFL.IS","MPARK.IS","MRGYO.IS","MRSHL.IS",
    "MSGYO.IS","MTRKS.IS","MZHLD.IS","NATEN.IS","NETAS.IS","NIBAS.IS","NILYT.IS","NKOMD.IS",
    "NTHOL.IS","NTTUR.IS","NUGYO.IS","NUHCM.IS","OBAMS.IS","ODAS.IS","OFSYM.IS","OKCMD.IS",
    "ONCSM.IS","ONRYT.IS","ORCAY.IS","ORGE.IS","ORKTK.IS","OSSA.IS","OSTIM.IS","OTKAR.IS",
    "OYAKC.IS","OYYAT.IS","OZKGY.IS","OZRDN.IS","OZSUB.IS","PAGYO.IS","PAPIL.IS","PARSN.IS",
    "PASEU.IS","PEKGY.IS","PENGD.IS","PENTA.IS","PETKM.IS","PETUN.IS","PGSUS.IS","PKART.IS",
    "PKENT.IS","PLTUR.IS","PNLSN.IS","POLHO.IS","POLTK.IS","PRDGS.IS","PRZMA.IS","PSDTC.IS",
    "PTOFS.IS","PWORK.IS","QNBFB.IS","QNBFL.IS","RALYH.IS","RAYSG.IS","RBALB.IS","RYGYO.IS",
    "SAHOL.IS","SAMAT.IS","SANEL.IS","SANFM.IS","SARKY.IS","SASA.IS","SAYAS.IS","SDTTR.IS",
    "SEDEF.IS","SEKFK.IS","SEKUR.IS","SELEC.IS","SELMR.IS","SENOL.IS","SEYKM.IS","SILVR.IS",
    "SISE.IS","SKBNK.IS","SNGYO.IS","SNICA.IS","SNKRN.IS","SNTKS.IS","SODSN.IS","SOKM.IS",
    "SONME.IS","SRVGY.IS","SUMAS.IS","SUWEN.IS","TAGGL.IS","TATGD.IS","TAVHL.IS","TCELL.IS",
    "TDGYO.IS","TEZOL.IS","TGSAS.IS","THYAO.IS","TKFEN.IS","TKNSA.IS","TLMAN.IS","TMPOL.IS",
    "TMSN.IS","TOASO.IS","TOFAS.IS","TRGYO.IS","TRKCM.IS","TRNSK.IS","TSGYO.IS","TSKB.IS",
    "TSPOR.IS","TTKOM.IS","TTRAK.IS","TUCLK.IS","TUMTK.IS","TUPRS.IS","TUREX.IS","TURGG.IS",
    "TURSG.IS","ULKER.IS","ULUFA.IS","ULUSE.IS","UNLU.IS","USAK.IS","USDTR.IS","VAKBN.IS",
    "VAKFN.IS","VAKKO.IS","VBTYZ.IS","VESBE.IS","VESTL.IS","VKFYO.IS","VKGYO.IS","VKRYN.IS",
    "VRGYO.IS","YAPRK.IS","YATAS.IS","YBTAS.IS","YESIL.IS","YGGYO.IS","YKBNK.IS","YKRYO.IS",
    "YUNSA.IS","ZEDUR.IS","ZRGYO.IS",
]

def _nosyapi_list(api_key: str) -> list:
    if not _HAS_REQ:
        return []
    try:
        r = _req.get(
            f"https://www.nosyapi.com/apiv2/service/economy/bist/list?apiKey={api_key}",
            timeout=15)
        d = r.json()
        if d.get("status") == "success":
            codes = [x["code"].strip() + ".IS"
                     for x in d.get("data", []) if x.get("code")]
            print(f"[BOT] ✅ NosyAPI: {len(codes)} hisse yüklendi")
            return codes
    except Exception as e:
        print(f"[BOT] NosyAPI hata: {e}")
    return []

def _bist_listesi_yukle() -> list:
    try:
        from config import NOSYAPI_KEY
        if NOSYAPI_KEY and NOSYAPI_KEY.strip():
            lst = _nosyapi_list(NOSYAPI_KEY.strip())
            if lst:
                return lst
    except (ImportError, AttributeError):
        pass
    print(f"[BOT] Dahili liste: {len(_HC)} hisse")
    return list(_HC)

BIST_HISSELER: list = []

def _init_hisse_listesi():
    global BIST_HISSELER
    raw = _bist_listesi_yukle()
    # Blacklist'teki hisseleri çıkar, duplikat kaldır
    seen: set = set()
    clean: list = []
    for t in raw:
        if t not in seen and t not in _BLACKLIST:
            seen.add(t)
            clean.append(t)
    BIST_HISSELER = clean
    print(f"[BOT] Aktif liste: {len(BIST_HISSELER)} hisse")

_init_hisse_listesi()

# ─── VERİ ARAÇLARI ───────────────────────────────────────────────
def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    return df

def _indir(sembol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """
    Veri indir — isyatirimhisse önce (günlük), yfinance fallback.
    Sadece gerçek delisting hatalarında blacklist'e ekle.
    """
    try:
        # isyatirim_veri modülü varsa kullan (günlük veriler için)
        if _HAS_ISY_VERI and interval == "1d":
            df = _ISY_OHLCV(sembol.replace(".IS", ""), period=period, interval="1d")
            if df is not None and not df.empty:
                needed = {"Open", "High", "Low", "Close", "Volume"}
                if needed.issubset(df.columns):
                    _log(f"_indir({sembol}): isyatirimhisse ✅")
                    return df

        # yfinance fallback (intraday veya isyatirimhisse başarısız)
        if not _HAS_YF:
            return None
        with _sessiz():
            df = yf.download(sembol, period=period, interval=interval,
                             progress=False, auto_adjust=True)
        if df is None or df.empty:
            _bl_ekle(sembol)
            return None
        df = _flatten(df)
        needed = {"Open", "High", "Low", "Close", "Volume"}
        if not needed.issubset(df.columns):
            _bl_ekle(sembol)
            return None
        return df
    except Exception as e:
        err = str(e)
        if _is_delisting_error(err):
            _bl_ekle(sembol)
        else:
            _log(f"_indir({sembol}): {err}")
        return None

# ─── TEKNİK İNDİKATÖRLER ─────────────────────────────────────────
def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    s = s.squeeze()
    d = s.diff()
    g = d.clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n - 1, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def _macd(s: pd.Series):
    s = s.squeeze()
    e12 = s.ewm(span=12, adjust=False).mean()
    e26 = s.ewm(span=26, adjust=False).mean()
    m = e12 - e26
    sig = m.ewm(span=9, adjust=False).mean()
    return m, sig, m - sig

def _bollinger(s: pd.Series, n: int = 20):
    s = s.squeeze()
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    return mid + 2 * std, mid, mid - 2 * std

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h = df["High"].squeeze()
    lo = df["Low"].squeeze()
    c = df["Close"].squeeze()
    tr = pd.concat(
        [(h - lo), (h - c.shift()).abs(), (lo - c.shift()).abs()],
        axis=1
    ).max(axis=1)
    return tr.ewm(com=n - 1, adjust=False).mean()

def _stochastic(df: pd.DataFrame, k: int = 14, d: int = 3):
    lo = df["Low"].squeeze()
    hi = df["High"].squeeze()
    cl = df["Close"].squeeze()
    lmin = lo.rolling(k).min()
    hmax = hi.rolling(k).max()
    denom = (hmax - lmin).replace(0, np.nan)
    kl = 100 * (cl - lmin) / denom
    dl = kl.rolling(d).mean()
    return kl, dl


def _supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    """
    SuperTrend indikatörü.
    Returns: (supertrend_series, direction_series)
      direction: +1 = AL (yeşil, fiyat ST üstünde)
                -1 = SAT (kırmızı, fiyat ST altında)

    Tamer Güler mantığı: Sadece direction=+1 (yeşil) iken işlem onaylanır.
    """
    _bos_st  = pd.Series(np.nan, index=df.index)
    _bos_dir = pd.Series(0,      index=df.index)
    try:
        hi  = df["High"].squeeze()
        lo  = df["Low"].squeeze()
        cl  = df["Close"].squeeze()
        atr = _atr(df, period)

        hl2   = (hi + lo) / 2
        upper = hl2 + mult * atr
        lower = hl2 - mult * atr

        # numpy array kullan → pandas CoW uyarısı yok, daha hızlı
        n      = len(cl)
        st_arr = np.full(n, np.nan)
        di_arr = np.ones(n, dtype=int)

        cl_v = cl.values
        up_v = upper.values
        lo_v = lower.values

        for i in range(1, n):
            if lo_v[i] > lo_v[i-1] or cl_v[i-1] < st_arr[i-1]:
                final_lower = lo_v[i]
            else:
                final_lower = lo_v[i-1]

            if up_v[i] < up_v[i-1] or cl_v[i-1] > st_arr[i-1]:
                final_upper = up_v[i]
            else:
                final_upper = up_v[i-1]

            if np.isnan(st_arr[i-1]):
                st_arr[i] = final_lower;  di_arr[i] = 1
            elif st_arr[i-1] == up_v[i-1]:
                if cl_v[i] <= final_upper:
                    st_arr[i] = final_upper; di_arr[i] = -1
                else:
                    st_arr[i] = final_lower; di_arr[i] = 1
            else:
                if cl_v[i] >= final_lower:
                    st_arr[i] = final_lower; di_arr[i] = 1
                else:
                    st_arr[i] = final_upper; di_arr[i] = -1

        return pd.Series(st_arr, index=cl.index), pd.Series(di_arr, index=cl.index)
    except Exception as e:
        _log(f"_supertrend hata: {e}")
        return _bos_st, _bos_dir


def zamansallik_sikisma(df: pd.DataFrame,
                         gun: int = 20,
                         bant_esik: float = 0.05) -> dict:
    """
    Tamer Güler'in 'Zamansallık / Sıkışma' tekniği:
    
    Son `gun` günde fiyat dar bir bantta sıkışmışsa
    (max-min farkı ≤ bant_esik = %5) → patlama hazır!
    
    Ek kontroller:
    - Hacim sıkışma süresince azalıyorsa (enerji birikiyor) → daha güçlü
    - Bollinger Band daralması → sıkışmayı teyit eder
    - Kırılış yönü: Son fiyat üst banda yakınsa yukarı, alt banda yakınsa aşağı
    
    Returns:
        {
          sikisma:      bool,
          bant_oran:    float,   # % sıkışma genişliği
          gun_sayisi:   int,     # kaç gündür sıkışıyor
          hacim_azalan: bool,    # enerji birikiyor mu?
          bb_daralma:   bool,    # Bollinger daralmış mı?
          kilis_yonu:   "yukari"|"asagi"|"belirsiz",
          puan:         int,     # 0..3
          etiket:       str,
        }
    """
    bos = {"sikisma": False, "bant_oran": 0.0, "gun_sayisi": 0,
           "hacim_azalan": False, "bb_daralma": False,
           "kilis_yonu": "belirsiz", "puan": 0, "etiket": ""}

    if len(df) < gun + 5:
        return bos

    son_df    = df.iloc[-gun:]
    cl        = son_df["Close"].squeeze()
    vol       = son_df["Volume"].squeeze()

    yuksek    = float(cl.max())
    dusuk     = float(cl.min())
    orta      = (yuksek + dusuk) / 2

    if orta <= 0:
        return bos

    bant_oran = (yuksek - dusuk) / orta   # % genişlik

    if bant_oran > bant_esik:
        # Sıkışma yok — ama kaç gündür sıkışıyor bul
        return {**bos, "bant_oran": round(bant_oran * 100, 2)}

    # ── Kaç gündür sıkışıyor? ─────────────────────────────────────
    # Geriye giderek dar bandın başladığı noktayı bul
    gun_sayisi = gun
    for g in range(gun, min(60, len(df))):
        pencere   = df["Close"].squeeze().iloc[-g:]
        p_yuksek  = float(pencere.max())
        p_dusuk   = float(pencere.min())
        p_orta    = (p_yuksek + p_dusuk) / 2
        if p_orta > 0 and (p_yuksek - p_dusuk) / p_orta <= bant_esik * 1.1:
            gun_sayisi = g
        else:
            break

    # ── Hacim analizi — azalıyor mu? ──────────────────────────────
    # Sıkışma döneminde hacim azalıyorsa enerji birikiyordur
    vol_ilk_yari  = float(vol.iloc[:gun//2].mean())
    vol_son_yari  = float(vol.iloc[gun//2:].mean())
    hacim_azalan  = vol_son_yari < vol_ilk_yari * 0.85

    # ── Bollinger Band Daralması ──────────────────────────────────
    bb_daralma = False
    try:
        tum_cl    = df["Close"].squeeze()
        bb_std    = tum_cl.rolling(20).std()
        # Son değer tarihin alt %20'sindeyse → daralmış
        son_std   = float(bb_std.iloc[-1])
        hist_std  = bb_std.dropna()
        if len(hist_std) >= 20:
            esik = float(hist_std.quantile(0.20))
            bb_daralma = son_std <= esik
    except Exception:
        pass

    # ── Kırılış yönü tahmini ──────────────────────────────────────
    son_fiyat = float(cl.iloc[-1])
    ust_mesafe = yuksek - son_fiyat
    alt_mesafe = son_fiyat - dusuk
    if ust_mesafe < alt_mesafe * 0.5:
        kilis_yonu = "yukari"    # Üst banda yakın → yukarı kırılış
    elif alt_mesafe < ust_mesafe * 0.5:
        kilis_yonu = "asagi"
    else:
        kilis_yonu = "belirsiz"

    # ── Puanlama ──────────────────────────────────────────────────
    puan = 1  # Temel sıkışma = 1 puan
    if hacim_azalan:  puan += 1   # Enerji birikiyor
    if bb_daralma:    puan += 1   # BB teyit ediyor

    # Uzun süreli sıkışma daha değerli
    if gun_sayisi >= 30: puan = min(puan + 1, 3)

    etiket_yön = {
        "yukari":   "⬆ Yukarı Kırılış Bekleniyor",
        "asagi":    "⬇ Aşağı Kırılış Riski",
        "belirsiz": "↔ Yön Belirsiz",
    }.get(kilis_yonu, "")

    if puan >= 3:
        etiket = f"🎯 ZAMANSALLIK ONAYLI {etiket_yön} ({gun_sayisi}g)"
    elif puan == 2:
        etiket = f"⏳ Sıkışma Tespit Edildi {etiket_yön} ({gun_sayisi}g)"
    else:
        etiket = f"↔ Sıkışma ({bant_oran*100:.1f}% bant, {gun_sayisi}g)"

    return {
        "sikisma":      True,
        "bant_oran":    round(bant_oran * 100, 2),
        "gun_sayisi":   gun_sayisi,
        "hacim_azalan": hacim_azalan,
        "bb_daralma":   bb_daralma,
        "kilis_yonu":   kilis_yonu,
        "puan":         puan,
        "etiket":       etiket,
    }

# ─── RSI UYUMSUZLUĞU (DIVERGENCE) DEDEKTÖRü ─────────────────────
def rsi_divergence(close_s: pd.Series, rsi_s: pd.Series,
                   lookback: int = 60, min_aralik: int = 5) -> dict:
    """
    Son `lookback` barda Pozitif ve Negatif RSI Uyumsuzluğu arar.

    Pozitif (Bullish) Divergence:
        Fiyat → yeni dip (düşük dip)
        RSI   → yükselen dip   ← büyük oyuncular dipten alıyor
        Sonuç → Güçlü AL sinyali

    Negatif (Bearish) Divergence:
        Fiyat → yeni zirve (yüksek tepe)
        RSI   → düşen tepe    ← momentum zayıflıyor
        Sonuç → Güçlü SAT sinyali

    Returns:
        {
          "tip":    "pozitif" | "negatif" | None,
          "puan":   int  (-3..+3),
          "guc":    "guclu" | "zayif" | None,
          "etiket": str,
          "fiyat_dip1", "fiyat_dip2",   # Pozitif için
          "rsi_dip1",   "rsi_dip2",
          "bar_aralik":  int,
        }
    """
    bos = {"tip": None, "puan": 0, "guc": None,
           "etiket": "", "bar_aralik": 0}

    close = close_s.squeeze().values
    rsi   = rsi_s.squeeze().values

    if len(close) < lookback + 5:
        return bos

    c = close[-lookback:]
    r = rsi[-lookback:]
    n = len(c)

    # ── Dip tespiti (local minimum) ───────────────────────────────
    def dip_bul(seri, pencere=3):
        """seri içinde local minimum indekslerini döndür."""
        dipler = []
        for i in range(pencere, len(seri) - pencere):
            blok = seri[i-pencere:i+pencere+1]
            if seri[i] == min(blok):
                dipler.append(i)
        return dipler

    def tepe_bul(seri, pencere=3):
        tepeler = []
        for i in range(pencere, len(seri) - pencere):
            blok = seri[i-pencere:i+pencere+1]
            if seri[i] == max(blok):
                tepeler.append(i)
        return tepeler

    # ── POZİTİF UYUMSUZLUK (Bullish Divergence) ──────────────────
    fiyat_dipler = dip_bul(c)
    rsi_dipler   = dip_bul(r)

    en_iyi_poz = None
    en_iyi_poz_guc = 0

    if len(fiyat_dipler) >= 2:
        # Son iki dipi al
        d2_idx = fiyat_dipler[-1]   # son dip
        for d1_idx in reversed(fiyat_dipler[:-1]):
            aralik = d2_idx - d1_idx
            if aralik < min_aralik:
                continue

            # Fiyat yeni dip yapıyor mu? (d2 < d1)
            if c[d2_idx] >= c[d1_idx]:
                continue

            # RSI'da bu bölgeye karşılık gelen dipler var mı?
            # d1 ve d2 etrafındaki RSI diplerini ara
            r1_bolgesi = [i for i in rsi_dipler
                          if abs(i - d1_idx) <= 4]
            r2_bolgesi = [i for i in rsi_dipler
                          if abs(i - d2_idx) <= 4]

            if not r1_bolgesi or not r2_bolgesi:
                continue

            r1_idx = min(r1_bolgesi, key=lambda x: abs(x - d1_idx))
            r2_idx = min(r2_bolgesi, key=lambda x: abs(x - d2_idx))

            # RSI yükselen dip yapıyor mu? (r2 > r1) — uyumsuzluk!
            if r[r2_idx] <= r[r1_idx]:
                continue

            # Uyumsuzluk gücü: fiyat farkı ve RSI farkı ne kadar belirgin?
            fiyat_fark = (c[d1_idx] - c[d2_idx]) / c[d1_idx] * 100  # % düşüş
            rsi_fark   = r[r2_idx] - r[r1_idx]                       # RSI artışı

            guc_skoru  = fiyat_fark * 0.5 + rsi_fark * 0.5
            if guc_skoru > en_iyi_poz_guc:
                en_iyi_poz_guc = guc_skoru
                en_iyi_poz = {
                    "fiyat_dip1":  round(float(c[d1_idx]), 2),
                    "fiyat_dip2":  round(float(c[d2_idx]), 2),
                    "rsi_dip1":    round(float(r[r1_idx]), 1),
                    "rsi_dip2":    round(float(r[r2_idx]), 1),
                    "fiyat_fark":  round(fiyat_fark, 1),
                    "rsi_fark":    round(rsi_fark, 1),
                    "bar_aralik":  aralik,
                    "guc_skoru":   round(guc_skoru, 1),
                }
            break   # en yakın çift yeterli

    if en_iyi_poz:
        gs = en_iyi_poz["guc_skoru"]
        if gs >= 8:
            guc   = "guclu"
            puan  = 3
            etiket = f"🎯 GÜÇLÜ POZİTİF UYUMSUZLUK (+{en_iyi_poz['rsi_fark']:.1f} RSI)"
        elif gs >= 4:
            guc   = "guclu"
            puan  = 2
            etiket = f"📈 Pozitif RSI Uyumsuzluğu (+{en_iyi_poz['rsi_fark']:.1f} RSI)"
        else:
            guc   = "zayif"
            puan  = 1
            etiket = f"↗ Zayıf Pozitif Uyumsuzluk"

        return {
            "tip":        "pozitif",
            "puan":       puan,
            "guc":        guc,
            "etiket":     etiket,
            "bar_aralik": en_iyi_poz["bar_aralik"],
            **en_iyi_poz,
        }

    # ── NEGATİF UYUMSUZLUK (Bearish Divergence) ──────────────────
    fiyat_tepeler = tepe_bul(c)
    rsi_tepeler   = tepe_bul(r)

    en_iyi_neg = None
    en_iyi_neg_guc = 0

    if len(fiyat_tepeler) >= 2:
        t2_idx = fiyat_tepeler[-1]
        for t1_idx in reversed(fiyat_tepeler[:-1]):
            aralik = t2_idx - t1_idx
            if aralik < min_aralik:
                continue

            # Fiyat yeni tepe yapıyor mu? (t2 > t1)
            if c[t2_idx] <= c[t1_idx]:
                continue

            r1_bolgesi = [i for i in rsi_tepeler
                          if abs(i - t1_idx) <= 4]
            r2_bolgesi = [i for i in rsi_tepeler
                          if abs(i - t2_idx) <= 4]

            if not r1_bolgesi or not r2_bolgesi:
                continue

            r1_idx = min(r1_bolgesi, key=lambda x: abs(x - t1_idx))
            r2_idx = min(r2_bolgesi, key=lambda x: abs(x - t2_idx))

            # RSI düşen tepe yapıyor mu? (r2 < r1) — negatif uyumsuzluk!
            if r[r2_idx] >= r[r1_idx]:
                continue

            fiyat_fark = (c[t2_idx] - c[t1_idx]) / c[t1_idx] * 100
            rsi_fark   = r[r1_idx] - r[r2_idx]
            guc_skoru  = fiyat_fark * 0.5 + rsi_fark * 0.5

            if guc_skoru > en_iyi_neg_guc:
                en_iyi_neg_guc = guc_skoru
                en_iyi_neg = {
                    "fiyat_tepe1": round(float(c[t1_idx]), 2),
                    "fiyat_tepe2": round(float(c[t2_idx]), 2),
                    "rsi_tepe1":   round(float(r[r1_idx]), 1),
                    "rsi_tepe2":   round(float(r[r2_idx]), 1),
                    "fiyat_fark":  round(fiyat_fark, 1),
                    "rsi_fark":    round(rsi_fark, 1),
                    "bar_aralik":  aralik,
                    "guc_skoru":   round(guc_skoru, 1),
                }
            break

    if en_iyi_neg:
        gs = en_iyi_neg["guc_skoru"]
        if gs >= 8:
            guc    = "guclu"
            puan   = -3
            etiket = f"🚨 GÜÇLÜ NEGATİF UYUMSUZLUK (-{en_iyi_neg['rsi_fark']:.1f} RSI)"
        elif gs >= 4:
            guc    = "guclu"
            puan   = -2
            etiket = f"📉 Negatif RSI Uyumsuzluğu (-{en_iyi_neg['rsi_fark']:.1f} RSI)"
        else:
            guc    = "zayif"
            puan   = -1
            etiket = f"↘ Zayıf Negatif Uyumsuzluk"

        return {
            "tip":        "negatif",
            "puan":       puan,
            "guc":        guc,
            "etiket":     etiket,
            "bar_aralik": en_iyi_neg["bar_aralik"],
            **en_iyi_neg,
        }

    return bos


# ─── TEK ZAMAN DİLİMİ ANALİZİ ────────────────────────────────────
def analiz_et(sembol: str, interval: str = "1d", period: str = "2y") -> Optional[dict]:
    """
    Tek zaman dilimine göre teknik analiz yapar.
    DataFrame'i DÖNDÜRMEZ — sadece sayısal sonuçları döndürür.
    """
    if sembol in _BLACKLIST:
        return None
    try:
        df = _indir(sembol, period, interval)
        if df is None:
            return None

        close = df["Close"].squeeze()
        vol   = df["Volume"].squeeze()
        df["RSI"]     = _rsi(close)
        m, s, h       = _macd(close)
        df["MACD"]    = m; df["SIG"] = s; df["HIST"] = h
        bu, bm, bl    = _bollinger(close)
        df["BB_U"]    = bu; df["BB_M"] = bm; df["BB_L"] = bl
        df["MA20"]    = close.rolling(20).mean()
        df["MA50"]    = close.rolling(50).mean()
        df["MA200"]   = close.rolling(200).mean()
        df["ATR"]     = _atr(df)
        sk, sd        = _stochastic(df)
        df["STOCH_K"] = sk; df["STOCH_D"] = sd
        st_val, st_dir = _supertrend(df)
        df["ST"]      = st_val
        df["ST_DIR"]  = st_dir
        df = df.dropna()

        min_required = 40 if interval in ("5m", "15m", "1h") else 60
        if len(df) < min_required:
            return None

        son  = df.iloc[-1]
        prev = df.iloc[-2]

        fiyat     = float(son["Close"])
        prev_close = float(prev["Close"])
        if fiyat <= 0:
            return None

        # ── Hacim analizi ────────────────────────────────────────
        vol_ort20   = float(vol.rolling(20).mean().iloc[-1]) if len(df) >= 20 else 0.0
        vol_son     = float(son["Volume"])
        vol_oran    = round(vol_son / vol_ort20, 2) if vol_ort20 > 0 else 1.0
        hacim_onay  = vol_oran >= 1.5

        # ── Sinyal puanlama ──────────────────────────────────────
        puan = 0
        sinyaller = []

        # RSI
        rv = float(son["RSI"])
        if rv < 30:    puan += 2; sinyaller.append("RSI Aşırı Satım")
        elif rv < 40:  puan += 1; sinyaller.append("RSI Düşük")
        elif rv > 70:  puan -= 2; sinyaller.append("RSI Aşırı Alım")
        elif rv > 60:  puan -= 1; sinyaller.append("RSI Yüksek")

        # MACD
        mac_up = float(prev["MACD"]) < float(prev["SIG"]) and \
                 float(son["MACD"])  > float(son["SIG"])
        mac_dn = float(prev["MACD"]) > float(prev["SIG"]) and \
                 float(son["MACD"])  < float(son["SIG"])
        if mac_up:              puan += 2; sinyaller.append("MACD ↑ Kesişim")
        elif mac_dn:            puan -= 2; sinyaller.append("MACD ↓ Kesişim")
        elif float(son["HIST"]) > 0: puan += 1
        elif float(son["HIST"]) < 0: puan -= 1

        # Bollinger
        if fiyat < float(son["BB_L"]):  puan += 1; sinyaller.append("BB Alt Band")
        elif fiyat > float(son["BB_U"]): puan -= 1; sinyaller.append("BB Üst Band")

        # MA
        ma50 = float(son["MA50"]); ma200 = float(son["MA200"])
        if ma50 > ma200: puan += 1; sinyaller.append("Golden Cross ✓")
        else:            puan -= 1; sinyaller.append("Death Cross")

        # Stochastic
        skv = float(son["STOCH_K"]); sdv = float(son["STOCH_D"])
        if skv < 20 and skv > sdv:    puan += 1; sinyaller.append("Stoch Aşırı Satım")
        elif skv > 80 and skv < sdv:  puan -= 1; sinyaller.append("Stoch Aşırı Alım")

        # SuperTrend
        st_yon = int(son["ST_DIR"]) if not pd.isna(son["ST_DIR"]) else 0
        st_fiy = float(son["ST"])   if not pd.isna(son["ST"])     else 0.0
        if st_yon == 1:
            puan += 2; sinyaller.append("SuperTrend 🟢 AL")
        elif st_yon == -1:
            puan -= 2; sinyaller.append("SuperTrend 🔴 SAT")

        # Hacim onayı (bonus/ceza)
        if hacim_onay and puan > 0:
            puan += 1; sinyaller.append(f"Hacim Onayı {vol_oran}x ✓")
        elif not hacim_onay and puan >= 3:
            puan -= 1; sinyaller.append(f"Hacim Yetersiz {vol_oran}x")

        # ── RSI Uyumsuzluğu (Divergence) ─────────────────────────
        div = rsi_divergence(close, df["RSI"])
        if div["tip"]:
            puan += div["puan"]
            sinyaller.append(div["etiket"])

        return {
            "sembol":     sembol,
            "interval":   interval,
            "fiyat":      fiyat,
            "prev_close": prev_close,
            "rsi":        round(rv, 1),
            "macd_v":     round(float(son["MACD"]), 4),
            "macd_s":     round(float(son["SIG"]),  4),
            "bb_u":       round(float(son["BB_U"]), 2),
            "bb_l":       round(float(son["BB_L"]), 2),
            "ma20":       round(float(son["MA20"]),  2),
            "ma50":       round(ma50,               2),
            "ma200":      round(ma200,              2),
            "atr":        round(float(son["ATR"]),   2),
            "stoch_k":    round(skv, 1),
            "stoch_d":    round(sdv, 1),
            "vol_oran":   vol_oran,
            "hacim_onay": hacim_onay,
            "supertrend": st_fiy,
            "st_yon":     st_yon,   # +1=AL, -1=SAT, 0=belirsiz
            "puan":       puan,
            "sinyaller":  sinyaller,
            "divergence": div,   # ham divergence verisi (zamansal_analiz_v6'da kullanılır)
        }
    except Exception as e:
        _log(f"analiz_et({sembol},{interval}): {e}")
        return None

# ─── BIST-100 ENDEKS DURUMU ───────────────────────────────────────
_endeks_cache: dict = {"data": None, "ts": 0.0}
_ENDEKS_LOCK  = threading.Lock()
_ENDEKS_TTL   = 900  # 15 dk

def bist100_durumu() -> dict:
    _BOSTA = {"fiyat": 0, "degisim": 0.0, "uyari": False, "zayif": False}
    now = time.time()
    with _ENDEKS_LOCK:
        if _endeks_cache["data"] and (now - _endeks_cache["ts"]) < _ENDEKS_TTL:
            return _endeks_cache["data"]
    try:
        df = None
        # isyatirim_veri modülü varsa endeks verisini oradan al
        if _HAS_ISY_VERI:
            try:
                from isyatirim_veri import endeks_al
                df = endeks_al("XU100")
            except Exception:
                df = None

        # yfinance fallback
        if (df is None or df.empty) and _HAS_YF:
            with _sessiz():
                df = yf.download("XU100.IS", period="5d", interval="1d",
                                 progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                df = _flatten(df)

        if df is None or df.empty:
            return _BOSTA
        cl = df["Close"].squeeze()
        if len(cl) < 2:
            return _BOSTA
        son  = float(cl.iloc[-1])
        prev = float(cl.iloc[-2])
        degis = round((son - prev) / prev * 100, 2) if prev != 0 else 0.0
        sonuc = {
            "fiyat":   round(son, 1),
            "degisim": degis,
            "uyari":   degis <= -1.0,
            "zayif":   -1.0 < degis <= -0.5,
        }
        with _ENDEKS_LOCK:
            _endeks_cache["data"] = sonuc
            _endeks_cache["ts"]   = now
        return sonuc
    except Exception as e:
        _log(f"bist100_durumu: {e}")
        return _BOSTA

# ─── SEANS SAATİ FİLTRESİ ────────────────────────────────────────
def seans_filtresi() -> dict:
    """
    Borsa İstanbul seans saatlerine göre risk uyarısı üretir.
    
    Yüksek volatilite pencereleri:
      10:00-10:30 — Açılış saati (sert hareketler, algo emirleri)
      17:30-18:00 — Kapanış saati (pozisyon kapatmalar)
      12:30-13:00 — Öğlen seansı açılışı
    
    Returns:
        {
          durum: "normal"|"volatil"|"seans_disi"
          mesaj: str
          islem_onerisi: "normal"|"dikkat"|"bekle"
        }
    """
    now  = datetime.now()
    saat = now.hour
    dak  = now.minute
    gun  = now.weekday()   # 0=Pazartesi, 5=Cmt, 6=Pzt

    # Hafta sonu — borsa kapalı
    if gun >= 5:
        return {
            "durum": "seans_disi",
            "mesaj": "🔴 Borsa Kapalı (Hafta Sonu)",
            "islem_onerisi": "bekle",
        }

    # Saat 10:00 öncesi — pre-market, borsa açılmadı
    if saat < 10:
        return {
            "durum": "seans_disi",
            "mesaj": f"⏰ Borsa Henüz Açılmadı (Açılış: 10:00)",
            "islem_onerisi": "bekle",
        }

    # Saat 18:00 sonrası — kapandı
    if saat >= 18:
        return {
            "durum": "seans_disi",
            "mesaj": "🔴 Borsa Kapandı (18:00)",
            "islem_onerisi": "bekle",
        }

    # Yüksek volatilite pencereleri
    t = saat * 100 + dak   # ör. 10:15 → 1015

    if 1000 <= t <= 1030:
        return {
            "durum": "volatil",
            "mesaj": "⚠ AÇILIŞ SAATİ (10:00-10:30) — Algo emirleri aktif, sert hareket riski",
            "islem_onerisi": "dikkat",
        }
    if 1230 <= t <= 1300:
        return {
            "durum": "volatil",
            "mesaj": "⚠ ÖĞLEN AÇILIŞI (12:30-13:00) — Kısa volatilite penceresi",
            "islem_onerisi": "dikkat",
        }
    if 1730 <= t <= 1800:
        return {
            "durum": "volatil",
            "mesaj": "⚠ KAPANIS SAATİ (17:30-18:00) — Pozisyon kapatmalar, sert kapanış riski",
            "islem_onerisi": "dikkat",
        }

    return {
        "durum": "normal",
        "mesaj": "",
        "islem_onerisi": "normal",
    }


# ─── ENDEKS'E GÖRE RÖLATIF GÜÇ ──────────────────────────────────
def endeks_guc_skoru(hisse_degisim: float) -> dict:
    """
    Hisseyi BIST-100 endeksine göre kıyaslar.
    "Endeksten güçlü" olanlar sıralamada üste çıkar.
    
    Returns:
        {
          xu100_degisim: float,
          fark: float,          # hisse - endeks
          puan: int,            # -2..+2
          etiket: str,
          endeksten_guclu: bool
        }
    """
    endeks = bist100_durumu()
    xu100  = endeks.get("degisim", 0.0)
    fark   = round(hisse_degisim - xu100, 2)

    if   fark >= 3.0:  puan = 2;  etiket = "🚀 Endeksten Çok Güçlü"
    elif fark >= 1.0:  puan = 1;  etiket = "📈 Endeksten Güçlü"
    elif fark <= -3.0: puan = -2; etiket = "📉 Endeksten Çok Zayıf"
    elif fark <= -1.0: puan = -1; etiket = "↘ Endeksin Gerisinde"
    else:              puan = 0;  etiket = "≈ Endeksle Uyumlu"

    return {
        "xu100_degisim":  xu100,
        "fark":           fark,
        "puan":           puan,
        "etiket":         etiket,
        "endeksten_guclu": fark >= 1.0,
    }


# ─── TARİHSEL GETİRİ ─────────────────────────────────────────────
def _tarihsel_getiri(sembol: str) -> dict:
    """
    1 ay, 3 ay, 6 ay, 1 yıl, 3 yıl geriye dönük yüzde getiri hesapla.
    yfinance üzerinden çeker. Hata varsa None döner.
    """
    bos = {"1a": None, "3a": None, "6a": None, "1y": None, "3y": None}
    if not _HAS_YF:
        return bos
    try:
        with _yf_quiet():
            df = yf.download(sembol, period="3y", interval="1d",
                             auto_adjust=True, progress=False)
        if df is None or df.empty or len(df) < 20:
            return bos
        close = df["Close"].squeeze()
        if hasattr(close, "columns"):          # MultiIndex fallback
            close = close.iloc[:, 0]
        close = close.dropna()
        if len(close) < 20:
            return bos

        son  = float(close.iloc[-1])
        n    = len(close)

        def _get(gun: int):
            idx = n - gun - 1
            if idx < 0:
                return None
            bas = float(close.iloc[idx])
            if bas <= 0:
                return None
            return round((son - bas) / bas * 100, 2)

        return {
            "1a":  _get(21),    # ~1 ay
            "3a":  _get(63),    # ~3 ay
            "6a":  _get(126),   # ~6 ay
            "1y":  _get(252),   # ~1 yıl
            "3y":  _get(756),   # ~3 yıl
        }
    except Exception:
        return bos


# ─── TEMEL ANALİZ v3.0 — isyatirimhisse + yfinance fallback ─────
def temel_analiz(sembol: str) -> dict:
    """
    Gerçek KAP/İş Yatırım bilanço verisini kullanır.
    isyatirimhisse → yfinance fallback
    
    Returns:
        pe, pb                          — oran
        net_kar_buyume                  — % (None=yok)
        kar_durumu                      — "artiyor"|"azaliyor"|"zarar"|"belirsiz"
        temel_skor                      — 0..4
        pahali_puan                     — -2..+2 (uyumluluk)
        uyarilar                        — liste
        gunun_firsati                   — bool
        bilanco                         — ham bilanço dict
    """
    _BOSTA = {
        "pe": None, "pb": None, "eps": None,
        "net_kar_buyume": None, "kar_durumu": "belirsiz",
        "piyasa_degeri_m": None, "hisse_tipi": "belirsiz",
        "temel_skor": 0, "pahali_puan": 0,
        "uyarilar": [], "gunun_firsati": False,
        "bilanco": None,
        "borc_oz_orani": None, "nakit_m": None,
    }

    try:
        # ── isyatirimhisse bilanço verisi ─────────────────────────
        if _HAS_ISY_VERI:
            bilanco = _ISY_BILANCO(sembol.replace(".IS", ""))
        else:
            bilanco = {"veri_var": False, "kaynak": "yok"}

        # Fallback: yfinance ile mevcut mantığı koru
        if not bilanco.get("veri_var") and _HAS_YF:
            try:
                ticker = yf.Ticker(sembol)
                info   = ticker.info or {}
            except Exception:
                info = {}

            pe  = info.get("trailingPE")
            pb  = info.get("priceToBook")
            eg  = info.get("earningsGrowth")
            de  = info.get("debtToEquity")

            kar_durumu = "belirsiz"
            if eg is not None:
                if eg > 0: kar_durumu = "artiyor"
                elif eg < -0.1: kar_durumu = "azaliyor"

            uyarilar   = []
            temel_skor = 0
            pahali_puan = 0

            if pe and pe > 0:
                if pe > 30:   pahali_puan -= 1; uyarilar.append(f"⚠ F/K Yüksek ({pe:.1f}x)")
                elif pe < 12: temel_skor += 1; pahali_puan += 1; uyarilar.append(f"✅ F/K Ucuz ({pe:.1f}x)")
                else:         uyarilar.append(f"F/K Normal ({pe:.1f}x)")

            if kar_durumu == "artiyor":   temel_skor += 1; pahali_puan += 1
            elif kar_durumu == "zarar":   temel_skor -= 2; pahali_puan -= 1; uyarilar.append("🚨 Zararda")
            elif kar_durumu == "azaliyor":pahali_puan -= 1; uyarilar.append("⚠ Kar Azalıyor")

            if de and de > 200: pahali_puan -= 1; uyarilar.append(f"🚨 Yüksek Borç D/E {de:.0f}%")
            elif de and de < 30: pahali_puan += 1; uyarilar.append(f"✅ Düşük Borç D/E {de:.0f}%")

            return {
                "pe": round(float(pe), 1) if pe and pe > 0 else None,
                "pb": round(float(pb), 2) if pb and pb > 0 else None,
                "eps": None,
                "net_kar_buyume": round(eg * 100, 1) if eg else None,
                "kar_durumu": kar_durumu,
                "piyasa_degeri_m": None, "hisse_tipi": "belirsiz",
                "temel_skor": max(0, min(3, temel_skor)),
                "pahali_puan": pahali_puan,
                "uyarilar": uyarilar,
                "gunun_firsati": temel_skor >= 3,
                "bilanco": None,
                "borc_oz_orani": de,
                "nakit_m": None,
            }

        # ── isyatirimhisse verisi ile temel skor hesapla ──────────
        temel_skor  = bilanco.get("temel_skor", 0)
        kar_durumu  = bilanco.get("kar_durumu", "belirsiz")
        uyarilar    = bilanco.get("uyarilar", [])

        # pahali_puan uyumluluk (eski kod ile uyumlu)
        pahali_puan = 0
        if kar_durumu == "artiyor":    pahali_puan += 1
        elif kar_durumu == "zarar":    pahali_puan -= 2
        elif kar_durumu == "azaliyor": pahali_puan -= 1

        borc_favok = bilanco.get("borc_favok")
        if borc_favok is not None:
            if borc_favok > 10:   pahali_puan -= 2
            elif borc_favok > 5:  pahali_puan -= 1
            elif borc_favok < 2:  pahali_puan += 1

        # Günün fırsatı: temel skor >= 3
        gunun_firsati = (temel_skor >= 3)

        return {
            "pe":              bilanco.get("pe"),
            "pb":              bilanco.get("pb"),
            "eps":             None,
            "net_kar_buyume":  None,
            "kar_durumu":      kar_durumu,
            "piyasa_degeri_m": None,
            "hisse_tipi":      "belirsiz",
            "temel_skor":      max(-3, min(4, temel_skor)),
            "pahali_puan":     max(-3, min(3, pahali_puan)),
            "uyarilar":        uyarilar,
            "gunun_firsati":   gunun_firsati,
            "bilanco":         bilanco,        # ham bilanço objesi
            "borc_oz_orani":   None,
            "nakit_m":         None,
        }

    except Exception as e:
        _log(f"temel_analiz({sembol}): {e}")
        return _BOSTA
def zamansal_analiz(sembol: str) -> Optional[dict]:
    """
    Günlük + Haftalık + Haber + Temel analizi birleştirip karar üretir.
    Ağırlıklar: Günlük 0.55 + Haftalık 0.25 + Haber 0.15 + Temel 0.05 = 1.00
    """
    if sembol in _BLACKLIST:
        return None
    try:
        gunluk   = analiz_et(sembol, "1d", "2y")
        haftalik = analiz_et(sembol, "1wk", "5y")
        if not gunluk:
            return None

        gp    = gunluk["puan"]
        hp    = haftalik["puan"] if haftalik else 0
        fiyat = gunluk["fiyat"]
        atr_v = gunluk["atr"]

        # ── Temel analiz ─────────────────────────────────────────
        temel     = temel_analiz(sembol)
        t_puan    = temel["pahali_puan"]   # -2..+1

        # ── Haber analizi ────────────────────────────────────────
        haber_v = {
            "haber_skoru":   0.0,
            "haberler":      [],
            "araci_hedef":   None,
            "ai_ozet":       "",
            "haber_etiketi": "",
        }
        haber_skor = 0.0
        try:
            from haber_analiz import haber_analizi, haber_skor_etiketi
            hv = haber_analizi(sembol)
            haber_skor = hv.get("haber_skoru", 0.0)
            haber_v = {
                "haber_skoru":   haber_skor,
                "haberler":      hv.get("haberler", []),
                "araci_hedef":   hv.get("araci_hedef"),
                "ai_ozet":       hv.get("ai_ozet", ""),
                "haber_etiketi": haber_skor_etiketi(haber_skor),
            }
        except Exception as _he:
            _log(f"haber: {_he}")

        # ── Zamansal uyum ────────────────────────────────────────
        if   gp > 0 and hp > 0:   uk = "uyumlu_al"
        elif gp < 0 and hp < 0:   uk = "uyumlu_sat"
        elif gp * hp < 0:         uk = "cakisiyor"
        else:                     uk = "notr"

        # ── Birleşik puan (TOPLAM AĞIRLIK = 1.00) ────────────────
        toplam = round(
            gp         * 0.55 +
            hp         * 0.25 +
            haber_skor * 0.15 +
            t_puan     * 0.05,
            1
        )

        # ── BIST-100 endeks filtresi ──────────────────────────────
        endeks = bist100_durumu()
        endeks_baskisi = ""
        if endeks["uyari"] and toplam > 0:
            toplam = round(toplam * 0.5, 1)
            endeks_baskisi = f"⚠ BIST-100 {endeks['degisim']}% — sinyaller zayıflatıldı"
        elif endeks["zayif"] and toplam >= 3:
            toplam = round(toplam * 0.75, 1)
            endeks_baskisi = f"BIST-100 {endeks['degisim']}%"

        # ── Karar ────────────────────────────────────────────────
        if   toplam >= 3 and uk == "uyumlu_al":    kk = "guclu_al"
        elif toplam >= 2:                           kk = "al"
        elif toplam >= 1:                           kk = "zayif_al"
        elif toplam <= -3 and uk == "uyumlu_sat":  kk = "guclu_sat"
        elif toplam <= -2:                          kk = "sat"
        elif toplam <= -1:                          kk = "zayif_sat"
        else:                                       kk = "bekle"

        # Pahalı hisseye Güçlü Al verilmez
        if t_puan < -1 and kk == "guclu_al":
            kk = "al"
        # Hacim onayı olmadan Güçlü Al verilmez
        if kk == "guclu_al" and not gunluk["hacim_onay"]:
            kk = "al"

        # ── ATR bazlı stop/hedef ─────────────────────────────────
        atr_oran = (atr_v / fiyat * 100) if fiyat > 0 else 2.0
        if "al" in kk:
            if   atr_oran > 3:    vg, vt, va = "3-5 gün",    "KISA", "Yüksek volatilite"
            elif atr_oran > 1.5:  vg, vt, va = "1-3 hafta",  "ORTA", "Devam sinyali"
            else:                 vg, vt, va = "1-3 ay",     "UZUN", "Düşük volatilite"
            sl = round(fiyat - 1.5 * atr_v, 2)
            h1 = round(fiyat + 1.5 * atr_v, 2)   # ATR x1.5 (garanti)
            h2 = round(fiyat + 3.0 * atr_v, 2)   # ATR x3.0
            p  = fiyat - sl
            rg = round((h1 - fiyat) / p, 2) if p > 0 else 0.0
        elif "sat" in kk:
            vg = vt = va = "-"
            sl = round(fiyat + 1.5 * atr_v, 2)
            h1 = round(fiyat - 2.0 * atr_v, 2)
            h2 = round(fiyat - 3.5 * atr_v, 2)
            p  = sl - fiyat
            rg = round((fiyat - h1) / p, 2) if p > 0 else 0.0
        else:
            vg = vt = va = "-"; sl = h1 = h2 = fiyat; rg = 0.0

        # ── Günlük değişim ───────────────────────────────────────
        prev_f  = gunluk["prev_close"]
        degisim = round((fiyat - prev_f) / prev_f * 100, 2) if prev_f > 0 else 0.0

        KE = {
            "guclu_al":  "🟢 GÜÇLÜ AL",
            "al":        "🟡 AL",
            "zayif_al":  "🔵 ZAYIF AL",
            "bekle":     "⏸ BEKLE",
            "zayif_sat": "🟤 ZAYIF SAT",
            "sat":       "🟠 SAT",
            "guclu_sat": "🔴 GÜÇLÜ SAT",
        }
        UE = {
            "uyumlu_al":  "✅ UYUMLU",
            "uyumlu_sat": "✅ UYUMLU",
            "cakisiyor":  "⚠ ÇAKIŞIYOR",
            "notr":       "➡ NÖTR",
        }

        return {
            # Kimlik
            "sembol":          sembol,
            "fiyat":           fiyat,
            "degisim":         degisim,
            # Karar
            "karar":           KE.get(kk, kk),
            "karar_kod":       kk,
            "toplam_puan":     toplam,
            # Alt puanlar
            "g_puan":          gp,
            "h_puan":          hp,
            "uyum":            UE.get(uk, uk),
            "uyum_kodu":       uk,
            # Teknik
            "rsi":             gunluk["rsi"],
            "stoch_k":         gunluk["stoch_k"],
            "atr":             atr_v,
            "atr_oran":        round(atr_oran, 2),
            "vol_oran":        gunluk["vol_oran"],
            "hacim_onay":      gunluk["hacim_onay"],
            "ma20":            gunluk["ma20"],
            "ma50":            gunluk["ma50"],
            "ma200":           gunluk["ma200"],
            "sinyaller":       gunluk["sinyaller"],
            # Stop/hedef
            "stop_loss":       sl,
            "hedef_1":         h1,
            "hedef_2":         h2,
            "risk_getiri":     rg,
            "vade_gun":        vg,
            "vade_tip":        vt,
            "vade_acik":       va,
            # Temel
            "temel":           temel,
            "pahali_uyari":    temel["uyarilar"],
            # Endeks
            "endeks_baskisi":  endeks_baskisi,
            # Güncelleme
            "guncelleme":      datetime.now().strftime("%H:%M:%S"),
            # Haber (dict unpack)
            **haber_v,
        }
    except Exception as e:
        _log(f"zamansal_analiz({sembol}): {e}")
        return None

# ─── ANLИК FİYAT (TradingView önce, yfinance fallback) ───────────
def anlik_fiyat(sembol: str) -> Optional[float]:
    """
    Önce TradingView Scanner'dan dener (hızlı, 15dk gecikme),
    başarısız olursa yfinance'e düşer.
    """
    # 1) TradingView
    try:
        from veri_kaynagi import fiyat_al
        f = fiyat_al(sembol.replace(".IS",""))
        if f and f > 0:
            return f
    except ImportError:
        pass
    # 2) yfinance fallback
    try:
        with _sessiz():
            df = yf.download(sembol, period="1d", interval="1m",
                             progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            return float(_flatten(df)["Close"].iloc[-1])
    except Exception:
        pass
    return None

# ─── BACKTEST ─────────────────────────────────────────────────────
def backtest(sembol: str, gun: int = 120) -> Optional[dict]:
    """
    Son N günde Al/Sat sinyallerinin gerçekleşme başarısını hesaplar.
    Her sinyal 5 gün sonraki kapanışla kıyaslanır.
    """
    if sembol in _BLACKLIST:
        return None
    try:
        df = _indir(sembol, "3y", "1d")
        if df is None:
            return None
        close = df["Close"].squeeze()
        df["RSI"]     = _rsi(close)
        m, s, _       = _macd(close)
        df["MACD"]    = m; df["SIG"] = s
        bu, _, bl     = _bollinger(close)
        df["BB_U"]    = bu; df["BB_L"] = bl
        df["MA50"]    = close.rolling(50).mean()
        df["MA200"]   = close.rolling(200).mean()
        df["ATR"]     = _atr(df)
        sk, sd        = _stochastic(df)
        df["STOCH_K"] = sk; df["STOCH_D"] = sd
        df = df.dropna().tail(gun + 10)
        if len(df) < gun + 6:
            return None

        al_ret: list = []
        sat_ret: list = []

        for i in range(1, len(df) - 5):
            son  = df.iloc[i]
            prev = df.iloc[i - 1]
            p    = 0

            rv = float(son["RSI"])
            if rv < 30:   p += 2
            elif rv > 70: p -= 2

            if (float(prev["MACD"]) < float(prev["SIG"]) and
                    float(son["MACD"]) > float(son["SIG"])):
                p += 2
            elif (float(prev["MACD"]) > float(prev["SIG"]) and
                      float(son["MACD"]) < float(son["SIG"])):
                p -= 2

            cv = float(son["Close"])
            if cv < float(son["BB_L"]):  p += 1
            elif cv > float(son["BB_U"]): p -= 1

            if float(son["MA50"]) > float(son["MA200"]): p += 1
            else:                                        p -= 1

            if float(son["STOCH_K"]) < 20: p += 1
            elif float(son["STOCH_K"]) > 80: p -= 1

            g = float(son["Close"])
            if g <= 0:
                continue
            c   = float(df.iloc[i + 5]["Close"])
            ret = (c - g) / g * 100

            if p >= 3:
                al_ret.append(ret)
            elif p <= -3:
                sat_ret.append(-ret)  # SAT sinyalinde düşüş = kâr

        def istatistik(lst: list) -> dict:
            if not lst:
                return {"n": 0, "basari": 0, "ort": 0.0, "max": 0.0, "min": 0.0}
            b = sum(1 for x in lst if x > 0)
            return {
                "n":      len(lst),
                "basari": round(b / len(lst) * 100, 1),
                "ort":    round(float(np.mean(lst)),  2),
                "max":    round(max(lst),              2),
                "min":    round(min(lst),              2),
            }

        return {
            "sembol": sembol,
            "al":     istatistik(al_ret),
            "sat":    istatistik(sat_ret),
            "gun":    gun,
        }
    except Exception as e:
        _log(f"backtest({sembol}): {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  v6.0 EKLENTİLERİ
#  ✅ MA200 Trend Filtresi
#  ✅ Gap & Mum Analizi (Kaçış Boşluğu)
#  ✅ Sektörel Kıyaslama (Pozitif Ayrışma)
#  ✅ Piyasa Riskli modu (%1 altı endeks)
#  ✅ Makro Risk Analizi (savaş/seçim/kriz)
#  ✅ Dinamik vade (RSI + volatilite bazlı)
# ══════════════════════════════════════════════════════════════════

# ─── SEKTÖR HARİTASI ─────────────────────────────────────────────
# Her hisse → sektör ETF veya büyük hisse grubu
_SEKTOR_MAP: dict = {
    # Bankacılık
    "AKBNK.IS":"BANKA","GARAN.IS":"BANKA","YKBNK.IS":"BANKA","ISCTR.IS":"BANKA",
    "HALKB.IS":"BANKA","VAKBN.IS":"BANKA","TSKB.IS":"BANKA","SKBNK.IS":"BANKA",
    "QNBFB.IS":"BANKA","ALBRK.IS":"BANKA","FINBN.IS":"BANKA","ICBCT.IS":"BANKA",
    # Holding
    "KCHOL.IS":"HOLDING","SAHOL.IS":"HOLDING","DOHOL.IS":"HOLDING","GLYHO.IS":"HOLDING",
    "NTHOL.IS":"HOLDING","POLHO.IS":"HOLDING","GSDHO.IS":"HOLDING","AVHOL.IS":"HOLDING",
    # Sanayi / Otomotiv
    "FROTO.IS":"OTOMOTIV","TOASO.IS":"OTOMOTIV","ASUZU.IS":"OTOMOTIV","TTRAK.IS":"OTOMOTIV",
    "OTKAR.IS":"OTOMOTIV","DOAS.IS":"OTOMOTIV",
    # Kimya / Petrokimya
    "SASA.IS":"KIMYA","PETKM.IS":"KIMYA","ALKIM.IS":"KIMYA","GUBRF.IS":"KIMYA",
    "HEKTS.IS":"KIMYA","BAGFS.IS":"KIMYA",
    # Demir-Çelik
    "EREGL.IS":"DEMIR","KRDMD.IS":"DEMIR","KRDMB.IS":"DEMIR","IZMDC.IS":"DEMIR",
    # Enerji
    "AKSEN.IS":"ENERJI","ODAS.IS":"ENERJI","AKENR.IS":"ENERJI","GWIND.IS":"ENERJI",
    "ENJSA.IS":"ENERJI","ZOREN.IS":"ENERJI","EUPWR.IS":"ENERJI",
    # Perakende / Gıda
    "BIMAS.IS":"PERAKENDE","MGROS.IS":"PERAKENDE","SOKM.IS":"PERAKENDE",
    "ULKER.IS":"GIDA","TATGD.IS":"GIDA","CCOLA.IS":"GIDA","AEFES.IS":"GIDA",
    # Havacılık / Ulaşım
    "THYAO.IS":"UCUS","PGSUS.IS":"UCUS","TAVHL.IS":"UCUS","USAS.IS":"UCUS",
    # Telecom
    "TCELL.IS":"TELEKOM","TTKOM.IS":"TELEKOM",
    # Savunma / Teknoloji
    "ASELS.IS":"SAVUNMA","LOGO.IS":"TEKNO","INDES.IS":"TEKNO","NETAS.IS":"TEKNO",
    "KAREL.IS":"TEKNO","ARDYZ.IS":"TEKNO","DGATE.IS":"TEKNO",
    # Çimento / İnşaat
    "AKCNS.IS":"CIMENTO","CIMSA.IS":"CIMENTO","NUHCM.IS":"CIMENTO","TRKCM.IS":"CIMENTO",
    "BOLUC.IS":"CIMENTO","ANACM.IS":"CIMENTO","BSOKE.IS":"CIMENTO",
    # GYO
    "EKGYO.IS":"GYO","TRGYO.IS":"GYO","SNGYO.IS":"GYO","ISGYO.IS":"GYO",
    "DGGYO.IS":"GYO","ALGYO.IS":"GYO",
    # Turizm
    "BRYAT.IS":"TURIZM","TURSG.IS":"TURIZM","MERIT.IS":"TURIZM",
}

# Sektör bazında referans hisseler (kıyaslama için en likit 3 hisse)
_SEKTOR_REFERANS: dict = {
    "BANKA":    ["GARAN.IS","AKBNK.IS","ISCTR.IS"],
    "HOLDING":  ["KCHOL.IS","SAHOL.IS","DOHOL.IS"],
    "OTOMOTIV": ["FROTO.IS","TOASO.IS","TTRAK.IS"],
    "KIMYA":    ["SASA.IS","PETKM.IS","ALKIM.IS"],
    "DEMIR":    ["EREGL.IS","KRDMD.IS","IZMDC.IS"],
    "ENERJI":   ["AKSEN.IS","ODAS.IS","AKENR.IS"],
    "PERAKENDE":["BIMAS.IS","MGROS.IS","SOKM.IS"],
    "UCUS":     ["THYAO.IS","PGSUS.IS","TAVHL.IS"],
    "TELEKOM":  ["TCELL.IS","TTKOM.IS"],
    "SAVUNMA":  ["ASELS.IS"],
    "TEKNO":    ["LOGO.IS","INDES.IS","ARDYZ.IS"],
    "CIMENTO":  ["AKCNS.IS","CIMSA.IS","NUHCM.IS"],
    "GYO":      ["EKGYO.IS","TRGYO.IS","SNGYO.IS"],
    "TURIZM":   ["BRYAT.IS","TURSG.IS"],
    "GIDA":     ["ULKER.IS","CCOLA.IS","AEFES.IS"],
}

# Sektör değişim cache (30 dk TTL)
_SEKTOR_CACHE: dict = {}
_SEKTOR_LOCK  = threading.Lock()
_SEKTOR_TTL   = 1800

def _sektor_degisim(sektor: str) -> Optional[float]:
    """Sektörün ortalama günlük değişimini hesapla."""
    now = time.time()
    with _SEKTOR_LOCK:
        hit = _SEKTOR_CACHE.get(sektor)
        if hit and (now - hit["ts"]) < _SEKTOR_TTL:
            return hit["v"]

    refs = _SEKTOR_REFERANS.get(sektor, [])
    if not refs:
        return None

    degisimler = []
    for sym in refs:
        try:
            with _sessiz():
                df = yf.download(sym, period="3d", interval="1d",
                                 progress=False, auto_adjust=True)
            if df is None or df.empty:
                continue
            df = _flatten(df)
            cl = df["Close"].squeeze()
            if len(cl) >= 2:
                d = (float(cl.iloc[-1]) - float(cl.iloc[-2])) / float(cl.iloc[-2]) * 100
                degisimler.append(d)
        except Exception:
            continue

    if not degisimler:
        return None

    ort = round(sum(degisimler) / len(degisimler), 2)
    with _SEKTOR_LOCK:
        _SEKTOR_CACHE[sektor] = {"v": ort, "ts": now}
    return ort


def sektor_karsilastirma(sembol: str, hisse_degisim: float) -> dict:
    """
    Hisseyi sektör ortalamasıyla karşılaştır.
    Returns: {
        sektor: str,
        sektor_degisim: float,
        fark: float,          # hisse - sektör
        puan: int,            # -2..+2
        etiket: str
    }
    """
    _bos = {"sektor": "–", "sektor_degisim": 0.0,
            "fark": 0.0, "puan": 0, "etiket": ""}
    try:
        sektor = _SEKTOR_MAP.get(sembol)
        if not sektor:
            return _bos

        sek_d = _sektor_degisim(sektor)
        if sek_d is None:
            return {**_bos, "sektor": sektor}

        fark = round(hisse_degisim - sek_d, 2)
        puan = 0
        etiket = ""

        if   fark >= 3.0:  puan = 2;  etiket = "🚀 Güçlü Ayrışma"
        elif fark >= 1.5:  puan = 1;  etiket = "📈 Pozitif Ayrışma"
        elif fark <= -3.0: puan = -2; etiket = "⬇ Sektörden Kötü (-)"
        elif fark <= -1.5: puan = -1; etiket = "↘ Sektör Gerisinde"
        elif abs(fark) < 0.5: etiket = "≈ Sektörle Uyumlu"

        return {
            "sektor":         sektor,
            "sektor_degisim": sek_d,
            "fark":           fark,
            "puan":           puan,
            "etiket":         etiket,
        }
    except Exception as e:
        _log(f"sektor_karsilastirma({sembol}): {e}")
        return _bos


# ─── GAP & MUM ANALİZİ ───────────────────────────────────────────
def gap_mum_analizi(sembol: str) -> dict:
    """
    Son 3 günün fiyat verisiyle:
    - Boşluk (gap) tespiti
    - Mum formasyonu (Hammer, Engulfing, Doji, Morning Star)
    
    Returns: {
        gap_tipi: str,    # "kacis", "tukenmis", "normal", "asagi_gap"
        gap_oran: float,  # % boşluk
        mum: str,         # formasyon adı
        puan: int,        # -2..+3
        aciklama: str
    }
    """
    bos = {"gap_tipi": "normal", "gap_oran": 0.0,
           "mum": "", "puan": 0, "aciklama": ""}
    try:
        df = _indir(sembol, "5d", "1d")
        if df is None or len(df) < 3:
            return bos

        puan     = 0
        aciklama = []

        son   = df.iloc[-1]
        prev  = df.iloc[-2]
        prev2 = df.iloc[-3]

        o  = float(son["Open"]);   c  = float(son["Close"])
        h  = float(son["High"]);   lo = float(son["Low"])
        po = float(prev["Open"]);  pc = float(prev["Close"])
        ph = float(prev["High"]);  pl = float(prev["Low"])
        p2c = float(prev2["Close"])

        body      = abs(c - o)
        rng       = h - lo if (h - lo) > 0 else 0.001
        body_oran = body / rng       # 0..1
        ust_fitil = (h - max(o, c)) / rng
        alt_fitil = (min(o, c) - lo) / rng

        # ── GAP tespiti ───────────────────────────────────────────
        gap_oran = (o - pc) / pc * 100 if pc > 0 else 0.0
        gap_tipi = "normal"

        if gap_oran >= 2.0:
            gap_tipi = "kacis"
            vol_son  = float(son["Volume"])
            vol_ort  = float(df["Volume"].rolling(10).mean().iloc[-1])
            if vol_son >= vol_ort * 1.5:
                puan += 3
                aciklama.append(f"🚀 Kaçış Boşluğu +{gap_oran:.1f}% (Hacimli ✓)")
            else:
                puan += 1
                aciklama.append(f"⬆ Yukarı Gap +{gap_oran:.1f}% (Hacim zayıf)")
        elif gap_oran <= -2.0:
            gap_tipi = "asagi_gap"
            puan -= 2
            aciklama.append(f"⬇ Aşağı Boşluk {gap_oran:.1f}%")
        elif -0.3 <= gap_oran <= 0.3:
            gap_tipi = "normal"

        # Tükenmiş boşluk: çok büyük ama gün içi geri döndü
        if gap_oran >= 3.0 and c < o:
            gap_tipi = "tukenmis"
            puan    -= 1
            aciklama.append("⚠ Tükenmiş Boşluk (gün içi geri döndü)")

        # ── MUM FORMASYONLARI ─────────────────────────────────────
        mum = ""

        # Çekiç (Hammer) — alt fitil uzun, gövde küçük, alt trendde
        if (alt_fitil >= 0.55 and body_oran <= 0.30
                and (p2c > pc)):          # son 2 gün düşüş
            mum = "🔨 Çekiç"
            puan += 2
            aciklama.append("🔨 Çekiç Formasyonu (dip sinyali)")

        # Ters Çekiç (Inverted Hammer)
        elif (ust_fitil >= 0.55 and body_oran <= 0.30
              and c > o and p2c > pc):
            mum = "↕ Ters Çekiç"
            puan += 1
            aciklama.append("↕ Ters Çekiç (zayıf dip)")

        # Yutan Boğa (Bullish Engulfing)
        elif (c > o and pc < po          # bugün yeşil, dün kırmızı
              and c > po and o < pc      # bugün dünü yutuyor
              and body_oran >= 0.60):
            mum = "🟢 Boğa Yutma"
            puan += 2
            aciklama.append("🟢 Boğa Yutma (güçlü dönüş)")

        # Yutan Ayı (Bearish Engulfing)
        elif (c < o and pc > po
              and c < po and o > pc
              and body_oran >= 0.60):
            mum = "🔴 Ayı Yutma"
            puan -= 2
            aciklama.append("🔴 Ayı Yutma (düşüş dönüşü)")

        # Doji — belirsizlik
        elif body_oran <= 0.10:
            mum = "〰 Doji"
            aciklama.append("〰 Doji (belirsizlik, yön bekleniyor)")

        # Sabah Yıldızı (Morning Star) — 3 mum
        ms_cond = (
            p2c < float(prev2["Open"])          # mum1: kırmızı
            and body_oran <= 0.35               # mum2: küçük gövde (yıldız)
            and c > o                           # mum3: yeşil
            and c > (float(prev2["Open"]) + float(prev2["Close"])) / 2
        )
        if ms_cond:
            mum   = "⭐ Sabah Yıldızı"
            puan += 3
            aciklama.append("⭐ Sabah Yıldızı (güçlü dönüş)")

        return {
            "gap_tipi":  gap_tipi,
            "gap_oran":  round(gap_oran, 2),
            "mum":       mum,
            "puan":      max(-3, min(3, puan)),
            "aciklama":  " | ".join(aciklama) if aciklama else "Normal seans",
        }
    except Exception as e:
        _log(f"gap_mum_analizi({sembol}): {e}")
        return bos


# ─── MAKRO RİSK ANALİZİ ──────────────────────────────────────────
# Haftalık makro risk cache — ağır işlem
_MAKRO_CACHE: dict = {"data": None, "ts": 0.0}
_MAKRO_LOCK  = threading.Lock()
_MAKRO_TTL   = 3600 * 6  # 6 saat

# Risk kelimeleri — Türkçe + İngilizce
_MAKRO_RISKLER = [
    # Jeopolitik
    ("savaş",    3, "jeopolitik"), ("war",      3, "jeopolitik"),
    ("çatışma",  2, "jeopolitik"), ("conflict", 2, "jeopolitik"),
    ("saldırı",  2, "jeopolitik"), ("attack",   2, "jeopolitik"),
    ("gerilim",  1, "jeopolitik"), ("tension",  1, "jeopolitik"),
    ("ambargo",  2, "ticaret"),    ("embargo",  2, "ticaret"),
    # Sağlık
    ("pandemi",  3, "sağlık"),     ("pandemic", 3, "sağlık"),
    ("salgın",   3, "sağlık"),     ("epidemic", 3, "sağlık"),
    ("virüs",    2, "sağlık"),     ("virus",    2, "sağlık"),
    # Finans / Ekonomi
    ("kriz",     2, "ekonomi"),    ("crisis",   2, "ekonomi"),
    ("iflas",    2, "ekonomi"),    ("bankrupt", 2, "ekonomi"),
    ("çöküş",    3, "ekonomi"),    ("crash",    3, "ekonomi"),
    ("durgunluk",2, "ekonomi"),    ("recession",2, "ekonomi"),
    # Türkiye özel
    ("deprem",   2, "doğal afet"), ("earthquake",2,"doğal afet"),
    ("sel",      1, "doğal afet"), ("flood",    1, "doğal afet"),
    ("seçim",    1, "siyasi"),     ("election", 1, "siyasi"),
    ("faiz",     1, "merkez bankası"), ("interest rate",1,"merkez bankası"),
    ("enflasyon",1, "ekonomi"),    ("inflation",1, "ekonomi"),
    ("dolar",    1, "kur"),        ("usd/try",  1, "kur"),
    ("kur",      1, "kur"),
]

def makro_risk_analizi() -> dict:
    """
    Google News + ekonomi kaynaklarından BIST'i etkileyebilecek
    makro riskleri tespit eder.
    
    Returns: {
        risk_seviye: "YUKSEK" | "ORTA" | "DUSUK" | "NORMAL"
        risk_skoru:  int (0..10)
        riskler:     list[str]   — tespit edilen riskler
        ozet:        str         — "Bu hafta işlem önermem" tarzı mesaj
        kaynaklar:   list[str]
    }
    """
    now = time.time()
    with _MAKRO_LOCK:
        if _MAKRO_CACHE["data"] and (now - _MAKRO_CACHE["ts"]) < _MAKRO_TTL:
            return _MAKRO_CACHE["data"]

    bos = {"risk_seviye": "NORMAL", "risk_skoru": 0,
           "riskler": [], "ozet": "", "kaynaklar": []}

    if not _HAS_REQ:
        return bos

    import xml.etree.ElementTree as ET

    KAYNAKLAR = [
        ("Bloomberg HT", "https://www.bloomberght.com/rss"),
        ("Dünya",        "https://www.dunya.com/rss/haberler.xml"),
        ("Google TR",    "https://news.google.com/rss/search?q=borsa+ekonomi+kriz&hl=tr&gl=TR&ceid=TR:tr"),
        ("Google EN",    "https://news.google.com/rss/search?q=turkey+stock+market+risk&hl=en&gl=US&ceid=US:en"),
    ]

    basliklar   = []
    kaynak_list = []

    for kaynak_adi, url in KAYNAKLAR:
        try:
            r = _req.get(url, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0 BISTBot/2.0"})
            root = ET.fromstring(r.content)
            for item in root.iter("item"):
                t = item.findtext("title", "").strip()
                if t:
                    basliklar.append(t.lower())
            kaynak_list.append(kaynak_adi)
        except Exception:
            continue

    if not basliklar:
        return bos

    # Risk tespiti
    bulunan_riskler  = []
    kategori_toplam  = {}
    toplam_skor      = 0

    for baslik in basliklar[:30]:
        for kelime, agirlik, kat in _MAKRO_RISKLER:
            if kelime in baslik and kat not in kategori_toplam:
                kategori_toplam[kat] = agirlik
                toplam_skor += agirlik
                # Başlıktan anlamlı kısım al
                idx = baslik.find(kelime)
                snippet = baslik[max(0, idx-20):idx+40].strip().title()
                bulunan_riskler.append(
                    f"{'⚠' if agirlik>=2 else '•'} {snippet}  [{kat}]"
                )

    # Seviye belirleme
    if   toplam_skor >= 7:  seviye = "YUKSEK"
    elif toplam_skor >= 4:  seviye = "ORTA"
    elif toplam_skor >= 2:  seviye = "DUSUK"
    else:                   seviye = "NORMAL"

    # Özet mesaj
    if seviye == "YUKSEK":
        ozet = ("🚨 Makro Risk YÜKSEK — Bu hafta yeni pozisyon açmanı önermem!\n"
                "   Mevcut pozisyonlarda stop'larını sıkılaştır.")
    elif seviye == "ORTA":
        ozet = ("⚠ Makro Risk ORTA — Dikkatli ol, pozisyon büyüklüğünü küçült.\n"
                "   Sadece çok güçlü sinyallerde işlem aç.")
    elif seviye == "DUSUK":
        ozet = "🟡 Hafif Makro Risk — Normal işlem yapılabilir, haberleri takip et."
    else:
        ozet = ""

    sonuc = {
        "risk_seviye": seviye,
        "risk_skoru":  min(10, toplam_skor),
        "riskler":     bulunan_riskler[:5],
        "ozet":        ozet,
        "kaynaklar":   kaynak_list,
        "guncelleme":  datetime.now().strftime("%d.%m %H:%M"),
    }

    with _MAKRO_LOCK:
        _MAKRO_CACHE["data"] = sonuc
        _MAKRO_CACHE["ts"]   = now

    return sonuc


# ─── DİNAMİK VADE HESAPLAMA ──────────────────────────────────────
def dinamik_vade(atr_oran: float, rsi: float, uyum_kodu: str,
                 ma_trend: str) -> tuple:
    """
    ATR oranı + RSI + zamansal uyum + MA trendi baz alarak
    dinamik vade hesaplar.
    Returns: (vade_str, vade_tip, vade_aciklama)
    """
    # Baz vade ATR'dan
    if   atr_oran > 4.0:  baz = 0   # çok yüksek volatilite → günlük
    elif atr_oran > 2.5:  baz = 1   # yüksek → kısa vade
    elif atr_oran > 1.5:  baz = 2   # orta
    elif atr_oran > 0.8:  baz = 3   # düşük → orta vade
    else:                 baz = 4   # çok düşük → uzun vade

    # RSI ayarı — aşırı satımda vade uzar (daha fazla toparlanma zamanı)
    if rsi < 25:          baz = min(baz + 1, 4)
    elif rsi > 75:        baz = max(baz - 1, 0)

    # Zamansal uyum — uyumluysa vade uzar
    if uyum_kodu == "uyumlu_al":  baz = min(baz + 1, 4)
    elif uyum_kodu == "cakisiyor": baz = max(baz - 1, 0)

    # MA200 altında vade kısalır (riskli bölge)
    if ma_trend == "alti":        baz = max(baz - 1, 0)

    VADE_TABLOSU = [
        ("1-3 gün",   "SKALP",   "Çok kısa vadeli, gün içi çık"),
        ("3-7 gün",   "KISA",    "Kısa vadeli, haftalık hedef"),
        ("1-2 hafta", "ORTA",    "Orta vadeli, trend devamı"),
        ("2-4 hafta", "SWING",   "Swing trade, trend ile devam"),
        ("1-3 ay",    "UZUN",    "Uzun vadeli, güçlü trend"),
    ]

    vg, vt, va = VADE_TABLOSU[baz]
    return vg, vt, va


# ─── YENİ zamansal_analiz (v6.0) ─────────────────────────────────
def zamansal_analiz_v6(sembol: str) -> Optional[dict]:
    """
    v5 zamansal_analiz'in yerini alır:
    + MA200 filtresi ("Fiyat MA200 altında → Güçlü Al yok")
    + Gap & Mum analizi (kaçış boşluğu, çekiç vb.)
    + Sektörel kıyaslama (Pozitif Ayrışma puanı)
    + Piyasa Riskli modu (%1 altı endeks → karar override)
    + Makro risk uyarısı
    + Dinamik vade
    """
    if sembol in _BLACKLIST:
        return None
    try:
        gunluk   = analiz_et(sembol, "1d", "2y")
        haftalik = analiz_et(sembol, "1wk", "5y")
        if not gunluk:
            return None

        gp    = gunluk["puan"]
        hp    = haftalik["puan"] if haftalik else 0
        fiyat = gunluk["fiyat"]
        atr_v = gunluk["atr"]

        # ── Temel analiz ─────────────────────────────────────────
        temel  = temel_analiz(sembol)
        t_puan = temel["pahali_puan"]

        # ── Haber analizi ────────────────────────────────────────
        haber_v = {
            "haber_skoru":   0.0, "haberler":      [],
            "araci_hedef":   None,"ai_ozet":        "",
            "haber_etiketi": "","neden_ozeti":     "",
            "etkili_haberler": [],
        }
        haber_skor = 0.0
        riskli_haber    = False
        risk_sebep      = []
        # Tarihsel getiri — hata olursa bos dict
        try:
            _tg = _tarihsel_getiri(sembol)
        except Exception:
            _tg = {"1a": None, "3a": None, "6a": None, "1y": None, "3y": None}
        try:
            from haber_analiz import haber_analizi, haber_skor_etiketi
            hv = haber_analizi(sembol)
            haber_skor      = hv.get("haber_skoru", 0.0)
            riskli_haber    = hv.get("riskli_haber", False)
            risk_sebep      = hv.get("risk_sebep", [])
            haber_v = {
                "haber_skoru":     haber_skor,
                "haberler":        hv.get("haberler", []),
                "etkili_haberler": hv.get("etkili_haberler", []),
                "araci_hedef":     hv.get("araci_hedef"),
                "ai_ozet":         hv.get("ai_ozet", ""),
                "haber_etiketi":   haber_skor_etiketi(haber_skor),
                "neden_ozeti":     hv.get("neden_ozeti", ""),
                "riskli_haber":    riskli_haber,
                "risk_sebep":      risk_sebep,
                "risk_agirlik":    hv.get("risk_agirlik", 0),
            }
        except Exception as _he:
            _log(f"haber: {_he}")

        # ── MA200 trend tespiti ───────────────────────────────────
        ma200    = gunluk["ma200"]
        ma_trend = "ustunde" if fiyat >= ma200 * 0.98 else "alti"
        ma200_uyari = ""
        if ma_trend == "alti":
            ma200_uyari = f"⚠ Fiyat MA200 altında ({ma200:.2f}₺) — Uzun trend ayı"

        # ── Gap & Mum ────────────────────────────────────────────
        gap_v  = gap_mum_analizi(sembol)
        gap_p  = gap_v["puan"]

        # ── Zamansallık / Sıkışma (Tamer Güler tekniği) ──────────
        try:
            _df_sikisma = _indir(sembol, "3mo", "1d")
            sik_v = zamansallik_sikisma(_df_sikisma) if _df_sikisma is not None else \
                    {"sikisma": False, "puan": 0, "etiket": "", "kilis_yonu": "belirsiz",
                     "bant_oran": 0.0, "gun_sayisi": 0, "hacim_azalan": False, "bb_daralma": False}
        except Exception:
            sik_v = {"sikisma": False, "puan": 0, "etiket": "", "kilis_yonu": "belirsiz",
                     "bant_oran": 0.0, "gun_sayisi": 0, "hacim_azalan": False, "bb_daralma": False}
        sik_p = sik_v["puan"] if sik_v["sikisma"] else 0

        # ── RSI Divergence bilgisini günlükten al ─────────────────
        div_v  = gunluk.get("divergence", {"tip": None, "puan": 0,
                                            "guc": None, "etiket": ""})
        div_p  = div_v["puan"]   # zaten analiz_et'te puana eklendi,
        # ama v6 kendi toplam puanını hesapladığı için burada da dahil ediyoruz

        # ── Zamansal uyum ────────────────────────────────────────
        if   gp > 0 and hp > 0:  uk = "uyumlu_al"
        elif gp < 0 and hp < 0:  uk = "uyumlu_sat"
        elif gp * hp < 0:        uk = "cakisiyor"
        else:                    uk = "notr"

        # ── Günlük değişim ───────────────────────────────────────
        prev_f  = gunluk["prev_close"]
        degisim = round((fiyat - prev_f) / prev_f * 100, 2) if prev_f > 0 else 0.0

        # ── Seans Saati Filtresi ──────────────────────────────────
        seans_v = seans_filtresi()

        # ── Endeks'e Göre Rölatif Güç ────────────────────────────
        eguc_v  = endeks_guc_skoru(degisim)
        eguc_p  = eguc_v["puan"]   # -2..+2

        # ── Sektörel kıyaslama ───────────────────────────────────
        sek_v = sektor_karsilastirma(sembol, degisim)
        sek_p = sek_v["puan"]

        # ── Birleşik puan ─────────────────────────────────────────
        # SuperTrend zaten gp içinde (analiz_et'te eklendi)
        # Günlük 0.40 + Haftalık 0.18 + Haber 0.11 + Temel 0.05 +
        # Gap 0.06 + Sektör 0.03 + Divergence 0.05 + EndeksGüç 0.04 +
        # Sıkışma 0.08 = 1.00
        toplam = round(
            gp         * 0.40 +
            hp         * 0.18 +
            haber_skor * 0.11 +
            t_puan     * 0.05 +
            gap_p      * 0.06 +
            sek_p      * 0.03 +
            div_p      * 0.05 +
            eguc_p     * 0.04 +
            sik_p      * 0.08,
            1
        )

        # ── BIST-100 endeks filtresi ──────────────────────────────
        endeks = bist100_durumu()
        endeks_baskisi = ""
        piyasa_riskli  = False

        if endeks["uyari"]:
            # -%1 altı → Piyasa Riskli modu
            if toplam > 0:
                toplam = round(toplam * 0.5, 1)
            endeks_baskisi = f"⚠ BIST-100 {endeks['degisim']}% — sinyaller zayıflatıldı"
            if endeks["degisim"] <= -1.5:
                piyasa_riskli = True
        elif endeks["zayif"] and toplam >= 3:
            toplam = round(toplam * 0.75, 1)
            endeks_baskisi = f"BIST-100 {endeks['degisim']}%"

        # ── MA200 kısıtlaması ─────────────────────────────────────
        # Fiyat MA200 altında → puanı cezalandır
        if ma_trend == "alti" and toplam > 0:
            toplam = round(toplam * 0.7, 1)

        # ── Karar ────────────────────────────────────────────────
        if piyasa_riskli:
            kk = "piyasa_riskli"
        elif toplam >= 3 and uk == "uyumlu_al" and ma_trend == "ustunde":
            kk = "guclu_al"
        elif toplam >= 2:
            kk = "al"
        elif toplam >= 1:
            kk = "zayif_al"
        elif toplam <= -3 and uk == "uyumlu_sat":
            kk = "guclu_sat"
        elif toplam <= -2:
            kk = "sat"
        elif toplam <= -1:
            kk = "zayif_sat"
        else:
            kk = "bekle"

        # Pahalı hisseye Güçlü Al yok
        if t_puan < -1 and kk == "guclu_al":
            kk = "al"
        # Zararda şirkete Güçlü Al yok — sadece "AL (TEPKİ)" ver
        kar_durumu = temel.get("kar_durumu", "belirsiz")
        if kar_durumu in ("zarar", "azaliyor") and kk == "guclu_al":
            kk = "al"
        # Hacim onayı olmadan Güçlü Al yok
        if kk == "guclu_al" and not gunluk["hacim_onay"]:
            kk = "al"
        # MA200 altında Güçlü Al yok
        if kk == "guclu_al" and ma_trend == "alti":
            kk = "al"

        # ── Günün Fırsatı tespiti ─────────────────────────────────
        # Teknik Güçlü Al + Temel 3/3 + MA200 üstü = altın fırsat
        gunun_firsati = (
            kk == "guclu_al"
            and temel.get("temel_skor", 0) >= 3
            and ma_trend == "ustunde"
        )

        # ── RİSKLİ HABER override ────────────────────────────────
        # Dava/soruşturma/iflas gibi kritik haber → "RİSKLİ HABER: BEKLE"
        riskli_haber_uyari = ""
        if riskli_haber and "al" in kk and kk != "piyasa_riskli":
            riskli_haber_uyari = (
                f"⛔ RİSKLİ HABER: {risk_sebep[0][:60] if risk_sebep else 'Kritik haber var'}"
            )
            kk = "bekle"   # Tüm AL sinyallerini durdur

        # ── Seans Volatilite notu ─────────────────────────────────
        # Seans açılış/kapanış saatlerinde "Volatilite Yüksek" notu
        seans_uyari = seans_v.get("mesaj", "") if seans_v["durum"] == "volatil" else ""

        # Kaçış Boşluğu onaylı sinyal
        gap_onay = ""
        if gap_v["gap_tipi"] == "kacis" and "al" in kk:
            gap_onay = "GAP ONAYLI"
            if kk == "al":
                kk = "guclu_al"

        # RSI Pozitif Uyumsuzluk override
        div_onay = ""
        if div_v["tip"] == "pozitif" and div_v["guc"] == "guclu":
            div_onay = "POZİTİF UYUMSUZLUK ONAYLI"
            # AL → GÜÇLÜ AL terfi (piyasa riskli değilse)
            if kk == "al" and not piyasa_riskli:
                kk = "guclu_al"
            # BEKLE ama güçlü divergence → en azından ZAYIF AL
            elif kk == "bekle" and not piyasa_riskli:
                kk = "zayif_al"
        elif div_v["tip"] == "negatif" and div_v["guc"] == "guclu":
            div_onay = "NEGATİF UYUMSUZLUK ONAYLI"
            # AL → BEKLE'ye düşür (tehlike!)
            if kk in ("al", "zayif_al"):
                kk = "bekle"
            # BEKLE → ZAYIF SAT
            elif kk == "bekle":
                kk = "zayif_sat"

        # ── Stop / Hedef — ATR x1.5 Hedef-1 ────────────────────
        # Hedef-1 = ATR x 1.5 (daha garanti)
        # Hedef-2 = ATR x 3.0 (potansiyel üst hedef)
        atr_oran = (atr_v / fiyat * 100) if fiyat > 0 else 2.0
        if "al" in kk and kk != "piyasa_riskli":
            sl = round(fiyat - 1.5 * atr_v, 2)
            h1 = round(fiyat + 1.5 * atr_v, 2)   # ← ATR x1.5 (daha yakın, daha güvenli)
            h2 = round(fiyat + 3.0 * atr_v, 2)   # ← ATR x3.0
            p  = fiyat - sl
            rg = round((h1 - fiyat) / p, 2) if p > 0 else 0.0
        elif "sat" in kk:
            sl = round(fiyat + 1.5 * atr_v, 2)
            h1 = round(fiyat - 1.5 * atr_v, 2)
            h2 = round(fiyat - 3.0 * atr_v, 2)
            p  = sl - fiyat
            rg = round((fiyat - h1) / p, 2) if p > 0 else 0.0
        else:
            sl = h1 = h2 = fiyat; rg = 0.0

        # ── Dinamik vade ─────────────────────────────────────────
        vg, vt, va = dinamik_vade(atr_oran, gunluk["rsi"], uk, ma_trend)

        # ── ZAYIF BİLANÇO Kontrolü ───────────────────────────────
        zayif_bilanc      = False
        zayif_bilanc_uyari = ""
        try:
            from isyatirim_veri import zayif_bilanc_kontrol
            zb = zayif_bilanc_kontrol(sembol.replace(".IS", ""))
            if zb["risk"]:
                zayif_bilanc       = True
                zayif_bilanc_uyari = zb["etiket"]
                # AL sinyallerini düşür ama tamamen engelleme
                if kk == "guclu_al":
                    kk = "al"
                tum_sinyaller_ekleme = zb["etiket"]
            else:
                tum_sinyaller_ekleme = ""
        except Exception:
            tum_sinyaller_ekleme = ""

        # ── TAVAN/POMPA Koruması (%9.5+) ─────────────────────────
        tavan_uyari = ""
        if abs(degisim) >= 9.5:
            if degisim >= 9.5:
                tavan_uyari = f"🚨 DİKKAT: TAVAN FİYAT ({degisim:+.1f}%) — DÜZELTME RİSKİ"
                if kk in ("guclu_al", "al"):
                    kk = "zayif_al"   # Tavanda alım yapma!
            else:
                tavan_uyari = f"⚠ DİP FİYAT ({degisim:+.1f}%) — Satış baskısı çok yüksek"

        # ── YATIRIMLıK / KELEPİR Tespiti ─────────────────────────
        # PD/DD < 1.0 + Pozitif Uyumsuzluk → KELEPİR adayı
        yatirimlik = False
        yatirimlik_etiket = ""
        try:
            from isyatirim_veri import oranlar_al
            oran_v = oranlar_al(sembol.replace(".IS", ""))
            pd_dd  = oran_v.get("pd_dd")
            if (pd_dd and pd_dd < 1.0
                    and div_v.get("tip") == "pozitif"
                    and ma_trend == "ustunde"):
                yatirimlik = True
                yatirimlik_etiket = f"💎 YATIRIMLIK/KELEPİR (PD/DD={pd_dd:.2f}x)"
                # Sinyali terfi et
                if kk == "al":
                    kk = "guclu_al"
                elif kk == "zayif_al":
                    kk = "al"
        except Exception:
            oran_v = {}

        # ── MA200 ALTI → TEPKİ YÜKSELİŞİ Etiketi ────────────────
        # MA200 altında AL yerine "TEPKİ YÜKSELİŞİ BEKLENTİSİ" yaz
        tepki_modu = False
        if ma_trend == "alti" and kk in ("guclu_al", "al", "zayif_al"):
            tepki_modu = True

        KE = {
            "guclu_al":       "🟢 GÜÇLÜ AL",
            "al":             "🟡 AL",
            "zayif_al":       "🔵 ZAYIF AL",
            "bekle":          "⏸ BEKLE",
            "zayif_sat":      "🟤 ZAYIF SAT",
            "sat":            "🟠 SAT",
            "guclu_sat":      "🔴 GÜÇLÜ SAT",
            "piyasa_riskli":  "🚨 PİYASA RİSKLİ",
        }
        UE = {
            "uyumlu_al":  "✅ UYUMLU",
            "uyumlu_sat": "✅ UYUMLU",
            "cakisiyor":  "⚠ ÇAKIŞIYOR",
            "notr":       "➡ NÖTR",
        }

        # Sinyaller listesine gap & sektör ekle
        tum_sinyaller = list(gunluk["sinyaller"])
        if gap_v["aciklama"] and gap_v["aciklama"] != "Normal seans":
            tum_sinyaller.append(gap_v["aciklama"])
        if sek_v["etiket"]:
            tum_sinyaller.append(f"Sektör({sek_v['sektor']}): {sek_v['etiket']}")
        if ma200_uyari:
            tum_sinyaller.append(ma200_uyari)
        if tum_sinyaller_ekleme:
            tum_sinyaller.append(tum_sinyaller_ekleme)
        if tavan_uyari:
            tum_sinyaller.append(tavan_uyari)
        if yatirimlik_etiket:
            tum_sinyaller.append(yatirimlik_etiket)

        # Birleşik karar etiketi
        _onaylar = " | ".join(x for x in [gap_onay, div_onay] if x)

        # Zamansallık sıkışma onayı — kırılış yukarıysa Güçlü Al'ı terfi et
        sik_onay = ""
        if sik_v["sikisma"] and sik_v["kilis_yonu"] == "yukari" and sik_v["puan"] >= 2:
            sik_onay = "ZAMANSALLIK ONAYLI"
            if kk == "al" and not piyasa_riskli and not zayif_bilanc and not tavan_uyari:
                kk = "guclu_al"
        elif sik_v["sikisma"] and sik_v["kilis_yonu"] == "asagi":
            if kk in ("al", "zayif_al"):
                kk = "bekle"   # Aşağı kırılış bekleniyor, alma

        if sik_onay:
            _onaylar = " | ".join(x for x in [_onaylar, sik_onay] if x)

        # SuperTrend SAT konumunda Güçlü Al verme
        st_yon_gunluk = gunluk.get("st_yon", 0)
        if st_yon_gunluk == -1 and kk == "guclu_al":
            kk = "al"   # SuperTrend kırmızı → terfi yok

        # Temel karar etiketi
        _base_label = KE.get(kk, kk)

        # MA200 altında → TEPKİ YÜKSELİŞİ BEKLENTİSİ ekle
        if tepki_modu:
            _base_label = _base_label + " ⚡TEPKİ YÜKSELİŞİ BEKLENTİSİ"

        # Zayıf bilanço uyarısı ekle
        if zayif_bilanc_uyari:
            _base_label = _base_label + f" | {zayif_bilanc_uyari}"

        # Tavan uyarısı ekle
        if tavan_uyari:
            _base_label = _base_label + f" | 🚨TAVAN"

        # Yatırımlık etiketi ekle
        if yatirimlik:
            _base_label = _base_label + " | 💎KELEPİR"

        karar_etiketi = _base_label + (f" ⚡{_onaylar}" if _onaylar else "")

        return {
            "sembol":           sembol,
            "fiyat":            fiyat,
            "degisim":          degisim,
            "karar":            karar_etiketi,
            "karar_kod":        kk,
            "toplam_puan":      toplam,
            "g_puan":           gp,
            "h_puan":           hp,
            "uyum":             UE.get(uk, uk),
            "uyum_kodu":        uk,
            "rsi":              gunluk["rsi"],
            "stoch_k":          gunluk["stoch_k"],
            "atr":              atr_v,
            "atr_oran":         round(atr_oran, 2),
            "vol_oran":         gunluk["vol_oran"],
            "hacim_onay":       gunluk["hacim_onay"],
            "ma20":             gunluk["ma20"],
            "ma50":             gunluk["ma50"],
            "ma200":            ma200,
            "ma_trend":         ma_trend,
            "ma200_uyari":      ma200_uyari,
            "gap":              gap_v,
            "sektor":           sek_v,
            "divergence":       div_v,
            "sikisma":          sik_v,
            "supertrend":       gunluk.get("supertrend", 0.0),
            "st_yon":           st_yon_gunluk,  # +1=AL(yeşil), -1=SAT(kırmızı)
            "sinyaller":        tum_sinyaller,
            "stop_loss":        sl,
            "hedef_1":          h1,
            "hedef_2":          h2,
            "risk_getiri":      rg,
            "vade_gun":         vg,
            "vade_tip":         vt,
            "vade_acik":        va,
            "temel":            temel,
            "temel_skor":       temel.get("temel_skor", 0),
            "gunun_firsati":    gunun_firsati,
            "kar_durumu":       kar_durumu,
            "hisse_tipi":       temel.get("hisse_tipi", "belirsiz"),
            "pahali_uyari":     temel["uyarilar"],
            "endeks_baskisi":   endeks_baskisi,
            "piyasa_riskli":    piyasa_riskli,
            "riskli_haber":     riskli_haber,
            "riskli_haber_uyari": riskli_haber_uyari,
            "zayif_bilanc":     zayif_bilanc,
            "zayif_bilanc_uyari": zayif_bilanc_uyari,
            "tavan_uyari":      tavan_uyari,
            "yatirimlik":       yatirimlik,
            "yatirimlik_etiket": yatirimlik_etiket,
            "tepki_modu":       tepki_modu,
            "seans":            seans_v,
            "seans_uyari":      seans_uyari,
            "endeks_guc":       eguc_v,
            "tarihsel_getiri": _tg,
            "guncelleme":       datetime.now().strftime("%H:%M:%S"),
            **haber_v,
        }
    except Exception as e:
        _log(f"zamansal_analiz_v6({sembol}): {e}")
        return None

# v6 varsayılan olarak kullanılsın
zamansal_analiz = zamansal_analiz_v6
