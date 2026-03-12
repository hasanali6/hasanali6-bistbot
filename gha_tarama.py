"""
gha_tarama.py — GitHub Actions BIST Sinyal Tarayıcı
"""

import os, time, requests, warnings
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore")

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MAX_HISSE        = 200
MIN_PUAN         = 3

_HISSELER = [
    "THYAO","AKBNK","GARAN","ISCTR","YKBNK","VAKBN","HALKB","SISE",
    "KCHOL","SAHOL","TUPRS","EREGL","FROTO","TOASO","ARCLK","ASELS",
    "BIMAS","MGROS","SOKM","TAVHL","PGSUS","TCELL","TTKOM","SASA",
    "KOZAL","KOZA1","ENKAI","EKGYO","ISGYO","ALGYO","TRGYO","MAVI",
    "LOGO","NETAS","DOAS","OTKAR","BRISA","PETKIM","AGHOL","TKFEN",
    "ULAS","ULKER","BFREN","CIMSA","AKCNS","NUHCM","ADANA","ADNAC",
    "AFYON","SKBNK","ALARK","ALBRK","ALCAR","ALCTL","ALFAS","ALKA",
    "ALKIM","ALMAD","ALVES","ALYAG","ANACM","ANGEN","ANHYT","ANSGR",
    "ARASE","ARENA","ARSAN","ARTMS","ASLAN","ATATP","ATEKS","ATLAS",
    "AVHOL","AVOD","AYEN","AYCES","AYDEM","AYGAZ","AZTEK","BAGFS",
    "BAKAB","BALAT","BANVT","BARMA","BASGZ","BATAN","BAYRK","BEGYO",
    "BEYAZ","BIENY","BIGCH","BINHO","BIOEN","BIOPAS","BIZIM","BJKAS",
    "BLCYT","BMSCH","BNTAS","BOBET","BOSSA","BRKO","BRKSN","BRLSM",
    "BRMEN","BSOKE","BTCIM","BUCIM","BURCE","BURVA","BVSAN","CANTE",
    "CASA","CCOLA","CELHA","CEMAS","CEMTS","CEOEM","CLEBI","CLNMA",
    "CMBTN","COMDO","COSMO","CRDFA","CRFSA","CUSAN","CVKMD","CWENE",
    "DAGI","DAPGM","DARDL","DENGE","DESA","DERIM","DERHL","DEVA",
    "DGATE","DGNMO","DIRAS","DISKL","DITAS","DMRGD","DMSAS","DNISI",
    "DOGUB","DOHOL","DURDO","DYOBY","DZGYO","ECILC","ECZYT","EDATA",
    "EDIP","EGEEN","EGEPO","EGPRO","EGSER","EKSUN","ELITE","EMKEL",
    "EMNIS","ENERY","ENTRA","ERCB","ERSU","ESCAR","ESCOM","ESEN",
    "ETILR","ETYAK","EUHOL","EUREN","EUPWR","EVYAP","FADE","FENER",
    "FMIZP","FONET","FPEN","FZLGY","GARFA","GEDIK","GEDZA","GENIL",
    "GENTS","GEREL","GESAN","GIPTA","GLBMD","GLYHO","GMTAS","GOKNR",
    "GOLTS","GOODY","GOZDE","GRNYO","GRSEL","GRTRK","GSDDE","GSDHO",
    "GSRAY","GUBRF","GWIND","GZGYO","HDFGS","HEDEF","HEKTS","HLGYO",
    "HTTBT","HUNER","HURGZ","ICBCT","IEYHO","IHLGM","IHEVA","IHLAS",
    "IHYAY","IMASM","INDES","INFO","INGRM","INTEM","INVEO","IPEKE",
    "ISATR","ISBIR","ISFIN","ISGSY","ISKPL","ISYAT","ITTFH","IZFAS",
    "IZINV","IZMDC","JANTS","KAPLM","KARSN","KARYE","KATMR","KAYSE",
    "KCAER","KENT","KERVT","KFEIN","KLGYO","KLKIM","KLMSN","KLNMA",
    "KMPUR","KNFRT","KONTR","KONYA","KOPOL","KORDS","KOZAA","KRDMA",
    "KRDMB","KRPLS","KRSTL","KRTEK","KSTUR","KTLEV","KUTPO","LIDER",
    "LIDFA","LILAK","LINK","LKMNH","LRSHO","LYDHO","MAALT","MACKO",
    "MAKIM","MANAS","MARKA","MEDTR","MEGAP","MEKAG","MERIO","MERIT",
    "MERKO","METRO","MIPAZ","MNDRS","MNDTR","MOBTL","MPARK","MRGYO",
    "NATEN","NIBAS","NTGAZ","NUGYO","OBASE","ODAS","OFSYM","ONCSM",
    "ORCAY","ORGE","ORMA","OSTIM","OYAKC","OYAYO","OYLUM","OZGYO",
]
_HISSELER = list(dict.fromkeys(_HISSELER))[:MAX_HISSE]


def telegram_gonder(mesaj: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mesaj,
            "parse_mode": "HTML",
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram hata: {e}")
        return False


def veri_al(sym: str):
    try:
        import io, sys
        old = sys.stderr; sys.stderr = io.StringIO()
        df = yf.download(f"{sym}.IS", period="6mo", interval="1d",
                         progress=False, auto_adjust=True)
        sys.stderr = old
        if df is None or df.empty or len(df) < 30:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
        return df[["Open","High","Low","Close","Volume"]].astype(float).dropna()
    except Exception:
        return None


def rsi(s: pd.Series, n=14) -> float:
    d = s.diff().dropna()
    g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return float((100 - 100/(1+rs)).iloc[-1])

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def supertrend(df: pd.DataFrame, per=10, mult=3.0):
    hl2 = (df["High"] + df["Low"]) / 2
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"]  - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=per, adjust=False).mean()
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    st = pd.Series(np.nan, index=df.index)
    trend = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df["Close"].iloc[i] > upper.iloc[i-1]:
            trend.iloc[i] = 1
        elif df["Close"].iloc[i] < lower.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]
        st.iloc[i] = lower.iloc[i] if trend.iloc[i] == 1 else upper.iloc[i]
    return trend, st

def hacim_artis(df: pd.DataFrame) -> bool:
    try:
        son5   = df["Volume"].iloc[-5:].mean()
        once20 = df["Volume"].iloc[-25:-5].mean()
        return son5 > once20 * 1.5 if once20 > 0 else False
    except:
        return False


def sinyal_hesapla(sym: str):
    df = veri_al(sym)
    if df is None or len(df) < 50:
        return None
    close  = df["Close"]
    fiyat  = float(close.iloc[-1])
    rsi_val = rsi(close)
    e20    = float(ema(close, 20).iloc[-1])
    e50    = float(ema(close, 50).iloc[-1])
    e200   = float(ema(close, 200).iloc[-1]) if len(df) >= 200 else None
    trend, st = supertrend(df)
    st_yukari = int(trend.iloc[-1]) == 1
    degisim = float((close.iloc[-1]/close.iloc[-2]-1)*100) if len(close) > 1 else 0
    hacim_yuksek = hacim_artis(df)

    puan = 0; sinyaller = []
    if rsi_val < 35:   puan += 2; sinyaller.append(f"📉 RSI Aşırı Satım ({rsi_val:.0f})")
    elif rsi_val < 45: puan += 1; sinyaller.append(f"RSI Düşük ({rsi_val:.0f})")
    elif rsi_val > 70: puan -= 1
    if fiyat > e20 > e50: puan += 2; sinyaller.append("📈 EMA Yükseliş")
    elif fiyat > e20:     puan += 1; sinyaller.append("EMA20 üstünde")
    if e200 and fiyat > e200: puan += 1; sinyaller.append("EMA200 üstünde")
    if st_yukari: puan += 2; sinyaller.append("🟢 SuperTrend AL")
    else:         puan -= 1
    if hacim_yuksek: puan += 1; sinyaller.append("📊 Hacim Artışı")
    if puan < MIN_PUAN: return None

    atr_son = float(abs(df["High"].iloc[-1] - df["Low"].iloc[-1]))
    hedef = round(fiyat + atr_son * 2.5, 2)
    stop  = round(fiyat - atr_son * 1.5, 2)
    rr    = round((hedef-fiyat)/(fiyat-stop), 2) if fiyat > stop else 0
    return {"sembol":sym,"fiyat":fiyat,"puan":puan,"degisim":degisim,
            "rsi":rsi_val,"st_yukari":st_yukari,"sinyaller":sinyaller,
            "hedef":hedef,"stop":stop,"rr":rr}


def mesaj_olustur(sinyaller: list) -> str:
    simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
    guclu = [s for s in sinyaller if s["puan"] >= 5]
    diger = [s for s in sinyaller if s["puan"] < 5]
    mesaj = f"🤖 <b>BIST SİNYAL RAPORU</b>\n📅 {simdi} | {len(sinyaller)} sinyal\n" + "─"*30 + "\n\n"
    if guclu:
        mesaj += f"🔥 <b>GÜÇLÜ AL ({len(guclu)} hisse)</b>\n\n"
        for s in sorted(guclu, key=lambda x: -x["puan"])[:10]:
            i = "+" if s["degisim"] >= 0 else ""
            mesaj += (f"<b>{s['sembol']}</b> — {s['fiyat']:.2f}₺ ({i}{s['degisim']:.1f}%)\n"
                      f"  📊 Puan:{s['puan']} RSI:{s['rsi']:.0f} ⚖️R/R:{s['rr']}x\n"
                      f"  🎯{s['hedef']}₺ ⛔{s['stop']}₺\n"
                      f"  {' | '.join(s['sinyaller'][:3])}\n\n")
    if diger:
        mesaj += f"📌 <b>DİĞER ({len(diger)})</b>\n"
        for s in sorted(diger, key=lambda x: -x["puan"])[:8]:
            i = "+" if s["degisim"] >= 0 else ""
            mesaj += f"• <b>{s['sembol']}</b> {s['fiyat']:.2f}₺ ({i}{s['degisim']:.1f}%) Puan:{s['puan']} 🎯{s['hedef']}₺ ⛔{s['stop']}₺\n"
    mesaj += "\n🔗 Dashboard: PC açıkken http://localhost:5000"
    return mesaj


def main():
    simdi = datetime.now()
    print(f"[{simdi.strftime('%H:%M')}] Tarama başlıyor — {len(_HISSELER)} hisse")
    telegram_gonder(f"🔄 <b>BIST Tarama Başladı</b>\n⏰ {simdi.strftime('%d.%m.%Y %H:%M')}\n📋 {len(_HISSELER)} hisse taranıyor...")
    bulunan = []
    for i, sym in enumerate(_HISSELER):
        try:
            sonuc = sinyal_hesapla(sym)
            if sonuc:
                bulunan.append(sonuc)
                print(f"  ✅ {sym}: puan={sonuc['puan']}")
            if i % 20 == 0 and i > 0:
                print(f"  [{i}/{len(_HISSELER)}]...")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ {sym}: {e}")
    print(f"\nBitti: {len(bulunan)} sinyal")
    if bulunan:
        telegram_gonder(mesaj_olustur(bulunan))
        print("✅ Telegram gönderildi")
    else:
        telegram_gonder(f"📊 <b>Tarama Tamamlandı</b>\n⏰ {simdi.strftime('%H:%M')}\nℹ️ Kritik sinyal yok ({len(_HISSELER)} hisse tarandı)")

if __name__ == "__main__":
    main()
