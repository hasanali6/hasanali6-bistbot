"""
gha_tarama.py — GitHub Actions BIST Sinyal Tarayıcı v2.0
══════════════════════════════════════════════════════════
Web dashboard ile AYNI algoritmayı kullanır:
  ✅ RSI + MACD + Bollinger + MA50/200 + Stochastic + SuperTrend
  ✅ Günlük (1d) + Haftalık (1wk) çift zaman dilimi
  ✅ Hacim onayı
  ✅ Portföy stop/hedef kontrolü
  ✅ 548 hisse
"""

import os, time, sys, io, warnings, json
from datetime import datetime
from typing import Optional
import requests
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MIN_PUAN         = 3   # Bu puanın üstündekiler raporda gösterilir

# Portföy — GitHub Secrets'tan oku
# Örnek değer: [{"sembol":"THYAO","alis":45.0,"stop":42.0,"hedef":52.0}]
PORTFOY_JSON = os.environ.get("PORTFOY", "[]")

# ── 548 Hisse Listesi ─────────────────────────────────────────────
_HISSELER = [
    "ACSEL","ADANA","ADEL","ADESE","ADNAC","AEFES","AFYON","AGESA",
    "AGHOL","AGROT","AGYO","AHGAZ","AKBNK","AKCNS","AKENR","AKFEN",
    "AKFGY","AKGRT","AKMGY","AKSA","AKSEN","AKSGY","ALARK","ALBRK",
    "ALCAR","ALCTL","ALFAS","ALGYO","ALKA","ALKIM","ALKLC","ALMAD",
    "ALNOS","ALTES","ALTINS","ALVES","ANACM","ANELE","ANER","ANERB",
    "ANHYT","ANJAS","ANKPA","ANSGR","ANTST","ARASE","ARCLK","ARDYZ",
    "ARENA","ARFYO","ARSAN","ARTMS","ARZUM","ASCEL","ASELS","ASGYO",
    "ASLAN","ASUZU","ATAGY","ATAKP","ATATP","ATEKS","ATLAS","ATPET",
    "AVGYO","AVHOL","AVISA","AVOD","AVTUR","AYCES","AYDEM","AYEN",
    "AYNES","AYRNT","AZTEK","BAGFS","BAHKM","BAKAB","BALAT","BALT",
    "BANVT","BARMA","BASCM","BASGZ","BAYRK","BERA","BEYAZ","BFREN",
    "BIENY","BIMAS","BINHO","BIOEN","BJKAS","BLCYT","BMEKS","BMELK",
    "BMSCH","BNTAS","BOLUC","BOSSA","BOYP","BRISA","BRKO","BRKVY",
    "BRMEN","BRSAN","BRSAS","BRYAT","BSOKE","BTCIM","BUCIM","BUMER",
    "BURCE","BURVA","BVSAN","BYDNR","CANTE","CATES","CBGYO","CCOLA",
    "CELHA","CEMAS","CEMTS","CEOEM","CGCAM","CIMSA","CLEBI","CLOUD",
    "CMBTN","CMENT","CONSE","COSMO","CRDFA","CRFSA","CUSAN","CVKMD",
    "CWENE","DAGHL","DAGI","DAPGM","DARDL","DATEGY","DENGE","DERHL",
    "DERIM","DESA","DESPC","DEVA","DGATE","DGGYO","DGKLB","DGNMO",
    "DIRI","DITAS","DMSAS","DNISI","DOAS","DOGUB","DOHOL","DOKTA",
    "DURDO","DYOBY","DZGYO","ECILC","ECZYT","EDATA","EDIP","EFORC",
    "EGEEN","EGGUB","EGPRO","EGSER","EKGYO","EKIZ","EKSUN","ELITE",
    "EMKEL","EMNIS","ENERY","ENFRA","ENGYO","ENJSA","ENKAI","EPLAS",
    "ERBOS","ERCAN","ERCB","EREGL","ERSU","ESCAR","ESCOM","ESEN",
    "ETILR","ETYAT","EUPWR","EUREN","EUYO","EVREN","FADCO","FENER",
    "FENR","FINBN","FLAP","FMIZP","FONET","FORMT","FORTE","FRIGO",
    "FROTO","FZLGY","GARAN","GARFA","GEDIK","GEDZA","GENIL","GENTS",
    "GEREL","GESAN","GIPTA","GLBMD","GLCVY","GLRYH","GLYHO","GMTAS",
    "GNGR","GOKNR","GOLTS","GOODY","GOZDE","GRSEL","GRTHO","GSDDE",
    "GSDHO","GSRAY","GUBRE","GUBRF","GUNDG","GUNSEL","GUSGR","GWIND",
    "HALKB","HATEK","HDFGS","HEDEF","HEKTS","HKTM","HLGYO","HRKET",
    "HTTBT","HUBVC","HUNER","HURGZ","HZGYO","ICBCT","IDGYO","IEYHO",
    "IHAAS","IHEVA","IHGZT","IHLAS","IHLGM","IHYAY","IMASM","INDES",
    "INTEM","INVEO","INVES","IPEKE","ISATR","ISBIR","ISCTR","ISFIN",
    "ISGSY","ISGYO","ISMEN","ISNET","ISYAT","IZENR","IZFAS","IZMDC",
    "IZOCM","JANTS","KAPLM","KAREL","KARSN","KARTN","KATMR","KAYSE",
    "KCHOL","KENT","KERVT","KFEIN","KGYO","KIPA","KLGYO","KLKIM",
    "KLMSN","KLNMA","KLRHO","KLSER","KLSYN","KMPUR","KNFRT","KONKA",
    "KONTR","KONYA","KOPOL","KORDS","KOZAA","KOZAL","KRDMA","KRDMB",
    "KRDMD","KRONT","KRPLS","KRSTL","KRTEK","KTLEV","KUYAS","KZBGY",
    "KZGYO","LCWGK","LIDER","LIDFA","LILAK","LINK","LKMNH","LOGO",
    "LRSHO","LUDOS","LUKSK","MAALT","MACKO","MAGEN","MAKIM","MAKTK",
    "MANAS","MAVI","MEDTR","MEGAP","MEGES","MEKAG","MERCN","MERIT",
    "MERKO","METRO","METUR","MGROS","MIATK","MIKRO","MIPAZ","MMCAS",
    "MNDRS","MNVRL","MOBTL","MOGAN","MONFL","MPARK","MRDIN","MRGYO",
    "MRSHL","MSGYO","MTRKS","MZHLD","NATEN","NETAS","NETRT","NIBAS",
    "NILYT","NKOMD","NTGAZ","NTHOL","NTTUR","NUGYO","NUHCM","OBAMS",
    "OBASE","ODAS","OFSYM","OGEN","OKCMD","ONCSM","ONRYT","ORCAY",
    "ORGE","ORKTK","OSSA","OSTIM","OTKAR","OYAKC","OYLUM","OYYAT",
    "OZKGY","OZRDN","OZSUB","PAGYO","PAPIL","PARSN","PASEU","PCILT",
    "PEKGY","PENGD","PENTA","PETKM","PETUN","PGSUS","PINSU","PKART",
    "PKENT","PLTUR","PNLSN","PNSUT","POLHO","POLTK","PRDGS","PRKAB",
    "PRKME","PRZMA","PSDTC","PTOFS","PWORK","QNBFB","QNBFL","RALYH",
    "RAYSG","RBALB","REEDR","RHEAG","RNPOL","RODRG","ROYDI","RTALB",
    "RUBNS","RYGYO","RYSAS","SAHOL","SAMAT","SANEL","SANFM","SARKY",
    "SASA","SAYAS","SDTTR","SEDEF","SEKFK","SEKUR","SELEC","SELGD",
    "SELMR","SENOL","SEYKM","SILVR","SISE","SKBAB","SKBNK","SNGYO",
    "SNICA","SNKRN","SNTKS","SODSN","SOKM","SONME","SRVGY","SUMAS",
    "SUNTK","SUWEN","TABGD","TAGGL","TATEN","TATGD","TAVHL","TBORG",
    "TCELL","TDGYO","TEKTU","TETMT","TEZOL","TGSAS","THYAO","TIRE",
    "TKFEN","TKNSA","TLMAN","TMNTR","TMPOL","TMSN","TOASO","TOFAS",
    "TRCAS","TRGYO","TRILC","TRKCM","TRKGY","TRNSK","TSGYO","TSKB",
    "TSPOR","TTKOM","TTRAK","TUCLK","TUKAS","TUMTK","TUPRS","TUREX",
    "TURGG","TURHM","TURSG","TZNGY","ULKER","ULUFA","ULUSE","UNLU",
    "UNYEC","USAK","USAS","USDTR","VAKBN","VAKFN","VAKKO","VANGD",
    "VBTS","VBTYZ","VERTU","VESBE","VESTL","VKFGY","VKFYO","VKGYO",
    "VKRYN","VRGYO","VSTR","YAPRK","YATAS","YAYLA","YBTAS","YESIL",
    "YGGYO","YGYO","YKBNK","YKRYO","YKSLN","YLGYO","YONGA","YUNSA",
    "ZBGYO","ZEDUR","ZOREN","ZRGYO",
]
_HISSELER = list(dict.fromkeys(_HISSELER))  # duplicate temizle


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
def telegram_gonder(mesaj: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       mesaj,
            "parse_mode": "HTML",
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM] Hata: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# VERİ — BATCH DOWNLOAD (TOPLU, HIZLI)
# ══════════════════════════════════════════════════════════════════
_BATCH_CACHE: dict = {}   # {period_interval: {sym: df}}

def _sessiz_indir(tickers, period, interval):
    """yfinance hata mesajlarını gizleyerek indir."""
    old = sys.stderr; sys.stderr = io.StringIO()
    try:
        df = yf.download(
            tickers, period=period, interval=interval,
            progress=False, auto_adjust=True, group_by="ticker",
        )
    except Exception:
        df = None
    finally:
        sys.stderr = old
    return df


def _df_temizle(df) -> Optional[pd.DataFrame]:
    """DataFrame'i standart OHLCV formatına getir."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    gerekli = [c for c in ["Open","High","Low","Close","Volume"] if c in df.columns]
    if "Close" not in gerekli:
        return None
    df = df[gerekli].astype(float).dropna()
    return df if len(df) >= 30 else None


def batch_yukle(period: str, interval: str) -> dict:
    """Tüm hisseleri 50'şer grupla toplu yükle. {sym: df} döndür."""
    anahtar = f"{period}_{interval}"
    if anahtar in _BATCH_CACHE:
        return _BATCH_CACHE[anahtar]

    sonuc = {}
    gruplar = [_HISSELER[i:i+50] for i in range(0, len(_HISSELER), 50)]
    print(f"[VERİ] {interval} verisi yükleniyor ({len(gruplar)} grup)...")

    for g_idx, grup in enumerate(gruplar):
        tickers = [f"{s}.IS" for s in grup]
        df_batch = _sessiz_indir(tickers, period, interval)
        if df_batch is None or df_batch.empty:
            continue
        for sym in grup:
            try:
                ticker = f"{sym}.IS"
                lvl0 = df_batch.columns.get_level_values(0)
                if ticker not in lvl0:
                    continue
                df = df_batch[ticker].copy()
                df = _df_temizle(df)
                if df is not None:
                    sonuc[sym] = df
            except Exception:
                continue
        print(f"  Grup {g_idx+1}/{len(gruplar)}: {len(sonuc)} hisse yüklendi")
        time.sleep(0.5)

    _BATCH_CACHE[anahtar] = sonuc
    print(f"[VERİ] {interval} tamamlandı: {len(sonuc)}/{len(_HISSELER)} hisse")
    return sonuc


def veri_al(sym: str, period="2y", interval="1d") -> Optional[pd.DataFrame]:
    """Önce batch cache'e bak, yoksa tek çek."""
    anahtar = f"{period}_{interval}"
    if anahtar in _BATCH_CACHE:
        df = _BATCH_CACHE[anahtar].get(sym)
        if df is not None:
            return df.copy()
    # Cache yoksa tek çek
    old = sys.stderr; sys.stderr = io.StringIO()
    try:
        df = yf.download(f"{sym}.IS", period=period, interval=interval,
                         progress=False, auto_adjust=True)
    except Exception:
        df = None
    finally:
        sys.stderr = old
    return _df_temizle(df)


# ══════════════════════════════════════════════════════════════════
# TEKNİK İNDİKATÖRLER — BOT_ENGINE İLE AYNI
# ══════════════════════════════════════════════════════════════════
def _rsi(close: pd.Series, n=14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd(close: pd.Series):
    e12 = close.ewm(span=12, adjust=False).mean()
    e26 = close.ewm(span=26, adjust=False).mean()
    m   = e12 - e26
    s   = m.ewm(span=9, adjust=False).mean()
    return m, s, m - s


def _bollinger(close: pd.Series, n=20, k=2):
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    return mid + k*std, mid, mid - k*std


def _atr(df: pd.DataFrame, n=14) -> pd.Series:
    hi = df["High"]; lo = df["Low"]; cl = df["Close"]
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def _stochastic(df: pd.DataFrame, k=14, d=3):
    lo_min = df["Low"].rolling(k).min()
    hi_max = df["High"].rolling(k).max()
    sk = 100 * (df["Close"] - lo_min) / (hi_max - lo_min + 1e-10)
    sd = sk.rolling(d).mean()
    return sk, sd


def _supertrend(df: pd.DataFrame, per=10, mult=3.0):
    hi = df["High"]; lo = df["Low"]; cl = df["Close"]
    hl2  = (hi + lo) / 2
    atr  = _atr(df, per)
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    n   = len(cl)
    st  = np.full(n, np.nan)
    di  = np.ones(n, dtype=int)
    clv = cl.values; upv = upper.values; lov = lower.values
    for i in range(1, n):
        fl = lov[i] if (lov[i] > lov[i-1] or clv[i-1] < st[i-1]) else lov[i-1]
        fu = upv[i] if (upv[i] < upv[i-1] or clv[i-1] > st[i-1]) else upv[i-1]
        if np.isnan(st[i-1]):
            st[i] = fl; di[i] = 1
        elif st[i-1] == upv[i-1]:
            st[i] = fu if clv[i] <= fu else fl
            di[i] = -1 if clv[i] <= fu else 1
        else:
            st[i] = fl if clv[i] >= fl else fu
            di[i] = 1  if clv[i] >= fl else -1
    return pd.Series(st, index=cl.index), pd.Series(di, index=cl.index)


# ══════════════════════════════════════════════════════════════════
# ANALİZ — BOT_ENGINE analiz_et() ile AYNI MANTIK
# ══════════════════════════════════════════════════════════════════
def analiz_et(sym: str, interval="1d", period="2y") -> Optional[dict]:
    """Tek zaman dilimine tam teknik analiz — bot_engine ile aynı."""
    df = veri_al(sym, period, interval)
    if df is None:
        return None

    close = df["Close"]
    vol   = df["Volume"]

    # İndikatörler
    rsi_s               = _rsi(close)
    macd_s, sig_s, hist = _macd(close)
    bb_u, bb_m, bb_l    = _bollinger(close)
    ma50  = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    atr_s = _atr(df)
    sk, sd              = _stochastic(df)
    st_val, st_dir      = _supertrend(df)

    # NaN temizle
    df2 = pd.DataFrame({
        "Close": close, "Volume": vol,
        "High": df["High"], "Low": df["Low"],
        "RSI": rsi_s, "MACD": macd_s, "SIG": sig_s, "HIST": hist,
        "BB_U": bb_u, "BB_L": bb_l,
        "MA50": ma50, "MA200": ma200,
        "ATR": atr_s, "SK": sk, "SD": sd,
        "ST": st_val, "ST_DIR": st_dir,
    }).dropna()

    if len(df2) < 60:
        return None

    son  = df2.iloc[-1]
    prev = df2.iloc[-2]

    fiyat = float(son["Close"])
    if fiyat <= 0:
        return None

    # Hacim
    vol_ort = float(vol.rolling(20).mean().iloc[-1]) if len(df2) >= 20 else 1.0
    vol_son = float(son["Volume"])
    vol_oran = round(vol_son / vol_ort, 2) if vol_ort > 0 else 1.0
    hacim_onay = vol_oran >= 1.5

    # Puan hesapla
    puan = 0
    sinyaller = []

    # RSI
    rv = float(son["RSI"])
    if   rv < 30: puan += 2; sinyaller.append(f"RSI Aşırı Satım({rv:.0f})")
    elif rv < 40: puan += 1; sinyaller.append(f"RSI Düşük({rv:.0f})")
    elif rv > 70: puan -= 2; sinyaller.append(f"RSI Aşırı Alım({rv:.0f})")
    elif rv > 60: puan -= 1

    # MACD
    mac_up = float(prev["MACD"]) < float(prev["SIG"]) and float(son["MACD"]) > float(son["SIG"])
    mac_dn = float(prev["MACD"]) > float(prev["SIG"]) and float(son["MACD"]) < float(son["SIG"])
    if   mac_up:             puan += 2; sinyaller.append("MACD ↑ Kesişim")
    elif mac_dn:             puan -= 2; sinyaller.append("MACD ↓ Kesişim")
    elif float(son["HIST"]) > 0: puan += 1
    elif float(son["HIST"]) < 0: puan -= 1

    # Bollinger
    if   fiyat < float(son["BB_L"]): puan += 1; sinyaller.append("BB Alt Band")
    elif fiyat > float(son["BB_U"]): puan -= 1; sinyaller.append("BB Üst Band")

    # MA Golden/Death Cross
    ma50v  = float(son["MA50"])
    ma200v = float(son["MA200"])
    if   ma50v > ma200v: puan += 1; sinyaller.append("Golden Cross ✓")
    else:                puan -= 1; sinyaller.append("Death Cross")

    # Stochastic
    skv = float(son["SK"]); sdv = float(son["SD"])
    if   skv < 20 and skv > sdv: puan += 1; sinyaller.append("Stoch Aşırı Satım")
    elif skv > 80 and skv < sdv: puan -= 1; sinyaller.append("Stoch Aşırı Alım")

    # SuperTrend
    st_yon = int(son["ST_DIR"]) if not pd.isna(son["ST_DIR"]) else 0
    if   st_yon ==  1: puan += 2; sinyaller.append("SuperTrend 🟢 AL")
    elif st_yon == -1: puan -= 2; sinyaller.append("SuperTrend 🔴 SAT")

    # Hacim onayı
    if hacim_onay and puan > 0:
        puan += 1; sinyaller.append(f"Hacim Onayı {vol_oran}x ✓")
    elif not hacim_onay and puan >= 3:
        puan -= 1; sinyaller.append(f"Hacim Yetersiz {vol_oran}x")

    return {
        "puan": puan, "sinyaller": sinyaller,
        "fiyat": fiyat,
        "rsi": round(rv, 1),
        "atr": round(float(son["ATR"]), 2),
        "ma50": round(ma50v, 2), "ma200": round(ma200v, 2),
        "st_yon": st_yon,
        "vol_oran": vol_oran,
        "prev_close": float(prev["Close"]),
    }


def zamansal_analiz(sym: str) -> Optional[dict]:
    """
    Günlük + Haftalık birleşik analiz — bot_engine zamansal_analiz() ile AYNI.
    Ağırlıklar: Günlük 0.55 + Haftalık 0.25 = 0.80 (haber/temel GHA'da yok)
    """
    gunluk   = analiz_et(sym, "1d", "2y")
    haftalik = analiz_et(sym, "1wk", "5y")

    if not gunluk:
        return None

    gp = gunluk["puan"]
    hp = haftalik["puan"] if haftalik else 0

    # Zamansal uyum
    if   gp > 0 and hp > 0: uk = "uyumlu_al"
    elif gp < 0 and hp < 0: uk = "uyumlu_sat"
    elif gp * hp < 0:        uk = "cakisiyor"
    else:                    uk = "notr"

    # Birleşik puan
    # Not: GHA'da haber/temel analizi yok → ağırlıklar normalize edildi
    toplam = round(gp * 0.69 + hp * 0.31, 1)

    if toplam < MIN_PUAN:
        return None

    fiyat      = gunluk["fiyat"]
    prev_close = gunluk["prev_close"]
    degisim    = round((fiyat / prev_close - 1) * 100, 2) if prev_close > 0 else 0.0
    atr        = gunluk["atr"]

    # Hedef & Stop (ATR bazlı)
    hedef   = round(fiyat + atr * 2.5, 2)
    stop    = round(fiyat - atr * 1.5, 2)
    rr      = round((hedef - fiyat) / (fiyat - stop), 2) if fiyat > stop else 0

    # Sinyal etiketi
    if   toplam >= 6: sinyal = "🟢 GÜÇLÜ AL"
    elif toplam >= 4: sinyal = "🟡 AL"
    elif toplam >= 2: sinyal = "⚪ ZAYIF AL"
    elif toplam <= -6: sinyal = "🔴 GÜÇLÜ SAT"
    elif toplam <= -4: sinyal = "🟠 SAT"
    else:              sinyal = "⚪ Nötr"

    return {
        "sembol":    sym,
        "fiyat":     fiyat,
        "degisim":   degisim,
        "puan":      toplam,
        "sinyal":    sinyal,
        "zamansal":  uk,
        "rsi":       gunluk["rsi"],
        "st_yon":    gunluk["st_yon"],
        "hedef":     hedef,
        "stop":      stop,
        "rr":        rr,
        "sinyaller": gunluk["sinyaller"],
        "gunluk_p":  gp,
        "haftalik_p": hp,
    }


# ══════════════════════════════════════════════════════════════════
# MESAJ FORMATLAMA
# ══════════════════════════════════════════════════════════════════
def mesaj_olustur(sinyaller: list) -> str:
    simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
    guclu = [s for s in sinyaller if s["puan"] >= 5]
    diger = [s for s in sinyaller if s["puan"] < 5]

    mesaj  = f"🤖 <b>BIST SİNYAL RAPORU</b>\n"
    mesaj += f"📅 {simdi} | {len(sinyaller)} sinyal\n"
    mesaj += "─" * 30 + "\n\n"

    if guclu:
        mesaj += f"🔥 <b>GÜÇLÜ AL ({len(guclu)} hisse)</b>\n\n"
        for s in sorted(guclu, key=lambda x: -x["puan"])[:10]:
            isaret = "+" if s["degisim"] >= 0 else ""
            mesaj += (
                f"<b>{s['sembol']}</b> — {s['fiyat']:.2f}₺ "
                f"({isaret}{s['degisim']:.1f}%)\n"
                f"  📊 Puan: {s['puan']} | RSI: {s['rsi']:.0f} | {s['sinyal']}\n"
                f"  🎯 Hedef: {s['hedef']}₺ | ⛔ Stop: {s['stop']}₺ | R/R: {s['rr']}x\n"
                f"  {' | '.join(s['sinyaller'][:3])}\n\n"
            )

    if diger:
        mesaj += f"📌 <b>DİĞER SİNYALLER ({len(diger)})</b>\n"
        for s in sorted(diger, key=lambda x: -x["puan"])[:8]:
            isaret = "+" if s["degisim"] >= 0 else ""
            mesaj += (
                f"• <b>{s['sembol']}</b> {s['fiyat']:.2f}₺ "
                f"({isaret}{s['degisim']:.1f}%) | "
                f"Puan:{s['puan']} RSI:{s['rsi']:.0f} "
                f"🎯{s['hedef']}₺ ⛔{s['stop']}₺\n"
            )

    mesaj += "\n🔗 Dashboard: PC açıkken http://localhost:5000"
    return mesaj


# ══════════════════════════════════════════════════════════════════
# PORTFÖY STOP / HEDEF KONTROLÜ
# ══════════════════════════════════════════════════════════════════
def portfoy_kontrol():
    """GitHub Secrets'taki PORTFOY değişkeninden hisse listesini okur."""
    try:
        portfoy = json.loads(PORTFOY_JSON)
        if not portfoy:
            print("ℹ️ Portföy boş, kontrol atlandı")
            return

        print(f"\n[PORTFÖY] {len(portfoy)} hisse kontrol ediliyor...")
        uyarilar = []

        for p in portfoy:
            try:
                sym   = str(p.get("sembol","")).upper().strip()
                alis  = float(p.get("alis",  0))
                stop  = float(p.get("stop",  0))
                hedef = float(p.get("hedef", 0))
                if not sym or not alis:
                    continue

                df = veri_al(sym, period="5d", interval="1d")
                if df is None or df.empty:
                    print(f"  ⚠ {sym}: veri yok")
                    continue

                fiyat   = float(df["Close"].iloc[-1])
                kar_pct = round((fiyat - alis) / alis * 100, 2)
                isaret  = "+" if kar_pct >= 0 else ""

                if stop and fiyat <= stop:
                    uyarilar.append(
                        f"🔴 <b>STOP!</b> {sym}\n"
                        f"  Fiyat: {fiyat:.2f}₺ | Stop: {stop:.2f}₺\n"
                        f"  Kar/Zarar: {isaret}{kar_pct}%"
                    )
                    print(f"  🔴 {sym} STOP — {fiyat:.2f} ≤ {stop:.2f}")
                elif hedef and fiyat >= hedef:
                    uyarilar.append(
                        f"🟢 <b>HEDEF!</b> {sym}\n"
                        f"  Fiyat: {fiyat:.2f}₺ | Hedef: {hedef:.2f}₺\n"
                        f"  Kar: +{kar_pct}%"
                    )
                    print(f"  🟢 {sym} HEDEF — {fiyat:.2f} ≥ {hedef:.2f}")
                else:
                    print(f"  ✅ {sym}: {fiyat:.2f}₺ ({isaret}{kar_pct}%)")

            except Exception as e:
                print(f"  ❌ {p}: {e}")

        if uyarilar:
            mesaj = "⚠️ <b>PORTFÖY UYARISI</b>\n\n" + "\n\n".join(uyarilar)
            telegram_gonder(mesaj)
            print(f"✅ {len(uyarilar)} portföy uyarısı gönderildi")
        else:
            print("✅ Portföy normal, uyarı yok")

    except json.JSONDecodeError:
        print("[PORTFÖY] PORTFOY secret JSON formatı hatalı!")
    except Exception as e:
        print(f"[PORTFÖY] Hata: {e}")


# ══════════════════════════════════════════════════════════════════
# ANA TARAMA
# ══════════════════════════════════════════════════════════════════
def main():
    simdi = datetime.now()
    print(f"[{simdi.strftime('%H:%M')}] BIST tarama başlıyor — {len(_HISSELER)} hisse")
    print(f"Algoritma: RSI + MACD + Bollinger + MA50/200 + Stoch + SuperTrend + Haftalık")

    telegram_gonder(
        f"🔄 <b>BIST Tarama Başladı</b>\n"
        f"⏰ {simdi.strftime('%d.%m.%Y %H:%M')}\n"
        f"📋 {len(_HISSELER)} hisse taranıyor..."
    )

    # Batch download — tüm hisseleri toplu çek
    batch_yukle("2y",  "1d")
    batch_yukle("5y",  "1wk")

    # Tarama
    bulunan = []
    for i, sym in enumerate(_HISSELER):
        try:
            sonuc = zamansal_analiz(sym)
            if sonuc:
                bulunan.append(sonuc)
                print(f"  ✅ {sym}: puan={sonuc['puan']} | {sonuc['sinyal']}")
            if (i+1) % 50 == 0:
                print(f"  [{i+1}/{len(_HISSELER)}] devam ediyor... ({len(bulunan)} sinyal)")
        except Exception as e:
            print(f"  ❌ {sym}: {e}")

    print(f"\nTarama bitti: {len(bulunan)} sinyal bulundu")

    if bulunan:
        telegram_gonder(mesaj_olustur(bulunan))
        print("✅ Telegram bildirimi gönderildi")
    else:
        telegram_gonder(
            f"📊 <b>BIST Tarama Tamamlandı</b>\n"
            f"⏰ {simdi.strftime('%H:%M')}\n"
            f"ℹ️ Şu an kritik sinyal yok ({len(_HISSELER)} hisse tarandı)"
        )
        print("ℹ️ Sinyal bulunamadı")

    # Portföy kontrolü
    portfoy_kontrol()


if __name__ == "__main__":
    main()
