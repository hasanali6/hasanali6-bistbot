"""
haber_analiz.py — Haber & Sentiment Motoru v2.0
══════════════════════════════════════════════════
YENİ (v2.0):
  ✅ "Neden olumlu/olumsuz" açıklaması — hangi başlık, hangi kelime
  ✅ Her haberin kendi skoru ayrı hesaplanıyor
  ✅ En etkili 3 haber öne çıkarılıyor (Telegram'a gönderilecek)
  ✅ Keyword match highlight
"""

import re, time, json, threading
from datetime import datetime
from typing import Optional
import xml.etree.ElementTree as ET

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

# ─── KEYWORD SÖZLÜĞÜ ─────────────────────────────────────────────
# (kelime, puan, kategori)
_POZ = [
    ("kâr açıkladı",      2.0, "kâr"),
    ("beklenti üstü",     2.0, "kâr"),
    ("rekor kâr",         2.0, "kâr"),
    ("net kâr arttı",     2.0, "kâr"),
    ("temettü",           1.5, "temettü"),
    ("temettü artışı",    2.0, "temettü"),
    ("sözleşme imzaladı", 1.5, "büyüme"),
    ("ihale kazandı",     1.5, "büyüme"),
    ("sipariş aldı",      1.5, "büyüme"),
    ("yatırım",           1.0, "büyüme"),
    ("kapasite artışı",   1.0, "büyüme"),
    ("ihracat",           1.0, "büyüme"),
    ("satın alma",        1.0, "büyüme"),
    ("ortaklık",          1.0, "büyüme"),
    ("büyüme",            1.0, "büyüme"),
    ("güçlü al",          1.5, "analist"),
    ("hedef yükseldi",    1.5, "analist"),
    ("al tavsiyesi",      1.5, "analist"),
    ("kâr",               0.5, "kâr"),
    ("kar",               0.5, "kâr"),
    ("artış",             0.5, "büyüme"),
    ("yükseliş",          0.5, "piyasa"),
    ("anlaşma",           0.5, "büyüme"),
    ("pozitif",           0.5, "genel"),
    ("olumlu",            0.5, "genel"),
]

_NEG = [
    ("zarar açıkladı",    2.0, "zarar"),
    ("beklenti altı",     2.0, "zarar"),
    ("net zarar",         2.0, "zarar"),
    ("zararı arttı",      2.0, "zarar"),
    ("dava açıldı",       1.5, "hukuki"),
    ("soruşturma",        1.5, "hukuki"),
    ("para cezası",       1.5, "hukuki"),
    ("iflas",             2.0, "hukuki"),
    ("toplu işten çıkarma", 1.5, "yönetim"),
    ("yönetim değişikliği", 1.0, "yönetim"),
    ("kâr uyarısı",       2.0, "zarar"),
    ("hedef düşürüldü",   1.5, "analist"),
    ("sat tavsiyesi",     1.5, "analist"),
    ("satış baskısı",     1.0, "piyasa"),
    ("borç",              1.0, "finans"),
    ("kayıp",             0.5, "zarar"),
    ("zarar",             0.5, "zarar"),
    ("düşüş",             0.5, "piyasa"),
    ("gerileme",          0.5, "piyasa"),
    ("olumsuz",           0.5, "genel"),
    ("risk",              0.3, "genel"),
    ("endişe",            0.3, "genel"),
]

# ─── KRİTİK RİSK KELİMELERİ ──────────────────────────────────────
# Bu kelimeler tespit edilirse sinyal "RİSKLİ HABER: BEKLE"ye döner
_KRITIK_RISKLER = [
    # Hukuki / Düzenleyici
    ("hapis",         "hukuki",    4),
    ("tutuklama",     "hukuki",    4),
    ("iflas",         "hukuki",    4),
    ("konkordato",    "hukuki",    4),
    ("haciz",         "hukuki",    3),
    ("vergi kaçakçı", "hukuki",    4),
    ("yolsuzluk",     "hukuki",    4),
    ("manipülasyon",  "hukuki",    4),
    ("spp soruşturma","hukuki",    4),  # SPK
    ("spk inceleme",  "hukuki",    3),
    ("bddk ceza",     "hukuki",    3),
    ("soruşturma",    "hukuki",    3),
    ("dava açıldı",   "hukuki",    3),
    ("para cezası",   "hukuki",    2),
    ("ceza kesildi",  "hukuki",    3),
    # Yönetim / Şeffaflık
    ("genel kurul iptal","yönetim",3),
    ("yönetim istifa","yönetim",   3),
    ("ceo istifa",    "yönetim",   3),
    ("ortaklık satışı","yönetim",  2),
    ("hisse satışı",  "yönetim",   2),  # büyük ortak satıyor
    ("bedelsiz iptal","yönetim",   3),
    # Operasyonel
    ("üretim durdu",  "operasyon", 3),
    ("fabrika yangın","operasyon", 3),
    ("grev",          "operasyon", 2),
    ("ihracat yasağı","operasyon", 3),
    ("lisans iptal",  "operasyon", 4),
    # Finansal
    ("sermaye erozyonu","finans",  4),
    ("özkaynak negatif","finans",  4),
    ("bono ödeyemedi","finans",    4),
    ("kredi notu düşürüldü","finans",3),
]

# ─── CACHE ────────────────────────────────────────────────────────
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL  = 3600  # 1 saat

def _cache_get(key: str) -> Optional[dict]:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item and (time.time() - item["ts"]) < _CACHE_TTL:
            return item["data"]
    return None

def _cache_set(key: str, data: dict):
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "ts": time.time()}

# ─── RSS ──────────────────────────────────────────────────────────
def _rss_cek(url: str, timeout: int = 8) -> list:
    if not _HAS_REQ:
        return []
    try:
        r = _req.get(url, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 BISTBot/2.0"})
        root = ET.fromstring(r.content)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate","").strip()
            if title:
                items.append({"baslik": title, "link": link, "tarih": pub})
        return items
    except Exception:
        return []

def kap_haberleri(sembol: str) -> list:
    kod = sembol.replace(".IS", "").upper()
    tum = _rss_cek("https://www.kap.org.tr/tr/rss", timeout=10)
    return [h for h in tum if kod in h["baslik"].upper()][:5]

def yahoo_haberleri(sembol: str) -> list:
    if not _HAS_YF:
        return []
    try:
        news = _yf.Ticker(sembol).news or []
        return [
            {
                "baslik": n.get("title", ""),
                "link":   n.get("link", ""),
                "tarih":  datetime.fromtimestamp(
                              n.get("providerPublishTime", 0)
                          ).strftime("%d.%m.%Y %H:%M")
                          if n.get("providerPublishTime") else "",
                "kaynak": n.get("publisher", "Yahoo Finance"),
            }
            for n in news[:6] if n.get("title")
        ]
    except Exception:
        return []

def google_news_haberleri(sembol: str) -> list:
    kod = sembol.replace(".IS", "")
    url = (f"https://news.google.com/rss/search"
           f"?q={kod}+borsa+hisse&hl=tr&gl=TR&ceid=TR:tr")
    return [dict(h, kaynak="Google News") for h in _rss_cek(url, timeout=6)[:5]]

_YEREL_RSS = {
    "KAP":         "https://www.kap.org.tr/tr/rss",
    "Bloomberg HT":"https://www.bloomberght.com/rss",
    "Ekonomim":    "https://www.ekonomim.com/rss",
    "Dünya":       "https://www.dunya.com/rss/haberler.xml",
}

def yerel_haberler(sembol: str) -> list:
    kod = sembol.replace(".IS", "").upper()
    sonuclar = []
    for kaynak, url in _YEREL_RSS.items():
        try:
            items = _rss_cek(url, timeout=6)
            for h in items:
                if kod in h["baslik"].upper():
                    sonuclar.append(dict(h, kaynak=kaynak))
        except Exception:
            continue
    return sonuclar[:6]

# ─── ANICI KURUM HEDEFİ ──────────────────────────────────────────
def araci_hedef(sembol: str) -> Optional[dict]:
    if not _HAS_YF:
        return None
    try:
        info = _yf.Ticker(sembol).info or {}
        hedef = info.get("targetMeanPrice")
        if not hedef:
            return None
        TAV = {
            "strong_buy":  "💚 GÜÇLÜ AL",
            "buy":         "🟢 AL",
            "hold":        "🟡 TUT",
            "sell":        "🟠 SAT",
            "strong_sell": "🔴 GÜÇLÜ SAT",
        }
        tk = info.get("recommendationKey", "")
        return {
            "hedef_fiyat":    round(float(hedef), 2),
            "dusuk_hedef":    round(float(info["targetLowPrice"]),  2) if info.get("targetLowPrice")  else None,
            "yuksek_hedef":   round(float(info["targetHighPrice"]), 2) if info.get("targetHighPrice") else None,
            "tavsiye":        TAV.get(tk, tk.upper() if tk else "–"),
            "tavsiye_kodu":   tk,
            "analist_sayisi": info.get("numberOfAnalystOpinions", 0),
        }
    except Exception:
        return None

# ─── TEK HABER SKORU + NEDEN ─────────────────────────────────────
def _haber_skor_ve_neden(baslik: str) -> tuple:
    """
    Bir başlık için (skor, neden_str, kategori) döndürür.
    neden_str → Telegram'da gösterilecek açıklama
    """
    bl = baslik.lower()
    poz_eslesme = []
    neg_eslesme = []

    for kelime, puan, kat in _POZ:
        if kelime in bl:
            poz_eslesme.append((kelime, puan, kat))

    for kelime, puan, kat in _NEG:
        if kelime in bl:
            neg_eslesme.append((kelime, puan, kat))

    poz_toplam = sum(p for _, p, _ in poz_eslesme)
    neg_toplam = sum(p for _, p, _ in neg_eslesme)
    net = poz_toplam - neg_toplam

    # Neden metni
    neden_parcalar = []
    for kelime, _, kat in (poz_eslesme + neg_eslesme)[:2]:
        neden_parcalar.append(f'"{kelime}" ({kat})')
    neden = " | ".join(neden_parcalar) if neden_parcalar else ""

    # Kategori: en yüksek puanlı
    if poz_eslesme and (not neg_eslesme or poz_toplam >= neg_toplam):
        kat = sorted(poz_eslesme, key=lambda x: x[1], reverse=True)[0][2]
    elif neg_eslesme:
        kat = sorted(neg_eslesme, key=lambda x: x[1], reverse=True)[0][2]
    else:
        kat = "genel"

    return round(net * 0.5, 1), neden, kat

# ─── KEYWORD TOPLAM SKOR ─────────────────────────────────────────
def keyword_skor(basliklar: list) -> float:
    if not basliklar:
        return 0.0
    toplam = sum(_haber_skor_ve_neden(b)[0] for b in basliklar)
    return max(-4.0, min(4.0, round(toplam, 1)))

# ─── CLAUDE AI SENTIMENT ─────────────────────────────────────────
def ai_skor(sembol: str, basliklar: list) -> tuple:
    """(skor, ozet) döndürür. API yoksa keyword fallback."""
    if not basliklar:
        return 0.0, ""
    try:
        from config import CLAUDE_API_KEY
        if not CLAUDE_API_KEY or not CLAUDE_API_KEY.strip():
            raise ValueError("no key")
    except (ImportError, ValueError, AttributeError):
        return keyword_skor(basliklar), ""

    if not _HAS_REQ:
        return keyword_skor(basliklar), ""

    kod = sembol.replace(".IS", "")
    baslik_metni = "\n".join(f"- {b}" for b in basliklar[:8])
    prompt = f"""Aşağıdaki {kod} hissesiyle ilgili haber başlıklarını analiz et.
{baslik_metni}

SADECE JSON döndür (başka hiçbir şey yazma):
{{"skor":<-4 ile +4 arası sayı>,"ozet":"<tek cümle, max 80 karakter>","neden":"<1-2 kelimelik ana tema>"}}"""

    try:
        r = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_API_KEY.strip(),
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001",
                  "max_tokens": 120,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=12,
        )
        text = r.json()["content"][0]["text"].strip()
        text = re.sub(r"```json|```", "", text).strip()
        parsed = json.loads(text)
        skor  = max(-4.0, min(4.0, float(parsed.get("skor", 0))))
        ozet  = str(parsed.get("ozet", ""))[:100]
        return round(skor, 1), ozet
    except Exception:
        return keyword_skor(basliklar), ""

def _kritik_risk_tara(basliklar: list) -> dict:
    """
    Kritik risk kelimelerini tarar.
    Bulursa: riskli=True, sebep listesi, en ağır kategori.
    
    Returns:
        {riskli: bool, sebep: list[str], kategori: str, agirlik: int}
    """
    sebep    = []
    max_agir = 0
    kat_list = []

    for baslik in basliklar:
        bl = baslik.lower()
        for kelime, kat, agirlik in _KRITIK_RISKLER:
            if kelime in bl:
                snippet = baslik[:80].strip()
                entry   = f"⛔ {snippet}  [{kat}]"
                if entry not in sebep:
                    sebep.append(entry)
                    kat_list.append(kat)
                    max_agir = max(max_agir, agirlik)

    return {
        "riskli":   len(sebep) > 0,
        "sebep":    sebep[:3],
        "kategori": kat_list[0] if kat_list else "",
        "agirlik":  max_agir,   # 2=dikkat, 3=ciddi, 4=acil
    }


# ─── ANA FONKSİYON ───────────────────────────────────────────────
def haber_analizi(sembol: str) -> dict:
    """
    Tüm kaynakları tarar, skorlar, NEDEN açıklaması üretir.
    
    Çıktı:
        haber_skoru   : -4..+4
        haberler      : list — her item'da 'neden' ve 'skor' alanı var
        etkili_haberler: en güçlü 3 haber (Telegram'a gönderilir)
        araci_hedef   : dict | None
        ai_ozet       : str
        neden_ozeti   : str — "Neden olumlu/olumsuz?" açıklaması
    """
    cache_key = f"haber_{sembol}_{datetime.now().strftime('%Y%m%d%H')}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    tum_haberler = []
    basliklar    = []

    # Haber toplama
    for h in kap_haberleri(sembol):
        tum_haberler.append(dict(h, kaynak="📋 KAP", onem="yuksek"))
        basliklar.append(h["baslik"])

    for h in yahoo_haberleri(sembol):
        tum_haberler.append(dict(h, onem="normal"))
        basliklar.append(h["baslik"])

    for h in google_news_haberleri(sembol):
        tum_haberler.append(dict(h, onem="normal"))
        basliklar.append(h["baslik"])

    for h in yerel_haberler(sembol):
        tum_haberler.append(dict(h, onem="normal"))
        basliklar.append(h["baslik"])

    # Her habere ayrı skor + neden ekle
    for h in tum_haberler:
        s, neden, kat = _haber_skor_ve_neden(h.get("baslik", ""))
        h["skor"]     = s
        h["neden"]    = neden
        h["kategori"] = kat

    # Aracı kurum hedefi
    ah = araci_hedef(sembol)

    # AI / keyword skor
    skor, ozet = ai_skor(sembol, basliklar)

    # Aracı kurum puanı
    temel_skor = 0.0
    if ah:
        tk = ah.get("tavsiye_kodu", "")
        temel_skor = {"strong_buy": 2.0, "buy": 1.0, "hold": 0.0,
                      "sell": -1.0, "strong_sell": -2.0}.get(tk, 0.0)

    birlesik = round(skor * 0.7 + temel_skor * 0.3, 1)
    birlesik  = max(-4.0, min(4.0, birlesik))

    # Kritik risk taraması
    risk_v = _kritik_risk_tara(basliklar)
    # Kritik risk varsa skoru daha da aşağı çek
    if risk_v["riskli"]:
        birlesik = min(birlesik, -risk_v["agirlik"] * 0.5)

    # En etkili 3 haber (mutlak skor büyükten küçüğe)
    etkili = sorted(
        [h for h in tum_haberler if h.get("skor", 0) != 0],
        key=lambda x: abs(x.get("skor", 0)), reverse=True
    )[:3]

    # "Neden olumlu/olumsuz?" özet metni
    neden_ozeti = _neden_metni_olustur(birlesik, etkili, ozet, ah)

    sonuc = {
        "sembol":          sembol,
        "haber_skoru":     birlesik,
        "haberler":        tum_haberler[:10],
        "etkili_haberler": etkili,
        "araci_hedef":     ah,
        "ai_ozet":         ozet,
        "neden_ozeti":     neden_ozeti,
        "kaynak_sayisi":   len(set(h.get("kaynak", "") for h in tum_haberler)),
        "baslik_sayisi":   len(basliklar),
        "guncelleme":      datetime.now().strftime("%H:%M"),
        # Kritik risk
        "riskli_haber":    risk_v["riskli"],
        "risk_sebep":      risk_v["sebep"],
        "risk_kategori":   risk_v["kategori"],
        "risk_agirlik":    risk_v["agirlik"],
    }

    _cache_set(cache_key, sonuc)
    return sonuc

def _neden_metni_olustur(skor: float, etkili: list,
                          ai_ozet: str, ah: Optional[dict]) -> str:
    """Telegram'da gösterilecek 'Neden olumlu?' açıklaması."""
    if skor == 0 and not etkili:
        return "Belirgin bir haber yok"

    parcalar = []

    # AI özeti varsa önce o
    if ai_ozet and ai_ozet != "keyword":
        parcalar.append(f"🤖 {ai_ozet}")

    # En etkili haberler
    for h in etkili[:2]:
        baslik = h.get("baslik", "")[:70]
        kaynak = h.get("kaynak", "")
        neden  = h.get("neden", "")
        yon    = "↑" if h.get("skor", 0) > 0 else "↓"
        if neden:
            parcalar.append(f"{yon} {baslik}  [{neden}] — {kaynak}")
        else:
            parcalar.append(f"{yon} {baslik} — {kaynak}")

    # Analist hedefi
    if ah and ah.get("hedef_fiyat"):
        parcalar.append(
            f"🏦 Analist hedef: {ah['hedef_fiyat']}₺  {ah.get('tavsiye','')}"
        )

    return "\n   ".join(parcalar) if parcalar else "Haber yok"

# ─── SKOR ETİKETİ ─────────────────────────────────────────────────
def haber_skor_etiketi(skor: float) -> str:
    if   skor >= 2:    return "🟢 ÇOK OLUMLU"
    elif skor >= 1:    return "🟢 OLUMLU"
    elif skor >= 0.5:  return "🔵 Hafif +"
    elif skor > -0.5:  return "⚪ Nötr"
    elif skor > -1:    return "🔴 Hafif −"
    elif skor > -2:    return "🔴 OLUMSUZ"
    else:              return "🔴 ÇOK OLUMSUZ"
