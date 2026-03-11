"""
alarm_bot.py — Telegram Alarm & Sinyal Bildirim Sistemi v2.0
═════════════════════════════════════════════════════════════
YENİ (v2.0):
  ✅ Zengin sinyal kartı — tüm indikatörler tek mesajda
  ✅ Derinlik kontrol linki (@ucretsizderinlikbot)
  ✅ Sinyal tekrarını önleme (aynı hisse 4 saat içinde tekrar gelmez)
  ✅ Güçlü AL / Güçlü SAT / Günlük özet bildirimleri
  ✅ Fiyat alarmları (eskisi gibi çalışıyor)
"""

import sqlite3, threading, time, requests
from datetime import datetime, timedelta
from typing import Optional
from bot_engine import anlik_fiyat

DB   = "portfolio.db"
LOCK = threading.Lock()

# ─── SON BİLDİRİM CACHE (spam önleme) ────────────────────────────
# { "THYAO.IS_guclu_al": datetime }
_son_bildirim: dict = {}
_SB_LOCK = threading.Lock()
_TEKRAR_SURESI_SAAT = 4   # Aynı sinyal 4 saat içinde tekrar gelmez

def _bildirim_gonder_mi(sembol: str, karar_kod: str) -> bool:
    """Bu sinyali şimdi göndermeli miyiz? Spam önleme."""
    anahtar = f"{sembol}_{karar_kod}"
    simdi = datetime.now()
    with _SB_LOCK:
        son = _son_bildirim.get(anahtar)
        if son and (simdi - son) < timedelta(hours=_TEKRAR_SURESI_SAAT):
            return False
        _son_bildirim[anahtar] = simdi
        return True

# ─── TELEGRAM ─────────────────────────────────────────────────────
def telegram_gonder(mesaj: str, parse_mode: str = "HTML") -> bool:
    try:
        from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[ALARM] ⚠ config.py'de TOKEN/CHAT_ID boş!")
            return False
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       mesaj,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[ALARM] Telegram hata: {e}")
        return False

def telegram_test() -> dict:
    ok = telegram_gonder(
        "✅ <b>BIST BOT — Bağlantı Testi</b>\n\n"
        "🚀 Bot çalışıyor ve sinyaller geliyor!\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        "📊 Sinyal gelince tam analiz kartı buraya düşecek.\n"
        "🔍 Derinlik kontrol: @ucretsizderinlikbot"
    )
    return {
        "ok":    ok,
        "mesaj": "✅ Telegram'a test mesajı gönderildi!" if ok
                 else "❌ Hata! Token/Chat ID kontrol et.",
    }

# ─── ZENGİN SİNYAL KARTI ─────────────────────────────────────────
def _sinyal_karti_olustur(r: dict) -> str:
    """
    Tarama sonucundan zengin Telegram mesajı üretir.
    r = zamansal_analiz() çıktısı
    """
    sym  = r["sembol"].replace(".IS", "")
    kk   = r.get("karar_kod", "")
    kar  = r.get("karar", "?")

    # Başlık emoji + renk
    BASLIK = {
        "guclu_al":  "🟢 GÜÇLÜ AL SİNYALİ",
        "al":        "🟡 AL SİNYALİ",
        "zayif_al":  "🔵 ZAYIF AL",
        "guclu_sat": "🔴 GÜÇLÜ SAT SİNYALİ",
        "sat":       "🟠 SAT SİNYALİ",
        "zayif_sat": "🟤 ZAYIF SAT",
    }
    baslik = BASLIK.get(kk, kar)

    fiyat   = r.get("fiyat", 0)
    degisim = r.get("degisim", 0)
    puan    = r.get("toplam_puan", 0)
    gp      = r.get("g_puan", 0)
    hp      = r.get("h_puan", 0)
    hs      = r.get("haber_skoru", 0) or 0
    rsi_v   = r.get("rsi", 0)
    stoch_v = r.get("stoch_k", 0)
    atr_o   = r.get("atr_oran", 0)
    vol_o   = r.get("vol_oran", 1)
    h_onay  = r.get("hacim_onay", False)
    sl      = r.get("stop_loss", 0)
    h1      = r.get("hedef_1", 0)
    h2      = r.get("hedef_2", 0)
    rk      = r.get("risk_getiri", 0)
    vade    = r.get("vade_gun", "–")
    uyum    = r.get("uyum", "–")
    sinyaller = r.get("sinyaller", [])
    ep      = r.get("endeks_baskisi", "")
    ah      = r.get("araci_hedef") or {}
    te      = r.get("temel") or {}
    ai_ozet = r.get("ai_ozet", "")

    # Değişim oku
    deg_ok = "📈" if degisim >= 0 else "📉"
    deg_str = f"+{degisim:.2f}%" if degisim >= 0 else f"{degisim:.2f}%"

    # Puan rengi (metin)
    puan_str = f"+{puan}" if puan > 0 else str(puan)

    # Hedef yüzdeleri
    def yuzde(hedef):
        if fiyat > 0:
            return f"({((hedef-fiyat)/fiyat*100):+.1f}%)"
        return ""

    # Sinyaller özeti (ilk 3)
    sin_str = ""
    if sinyaller:
        sin_str = "  •  ".join(sinyaller[:3])

    # Hacim
    vol_str = f"{vol_o}x {'✅' if h_onay else '⚠'}"

    # Analist hedef
    ah_str = ""
    if ah and ah.get("hedef_fiyat"):
        ah_str = (f"\n🏦 <b>Analist Hedef:</b> {ah['hedef_fiyat']}₺"
                  f"  <i>{ah.get('tavsiye','')}</i>")

    # Temel
    te_str = ""
    pe = te.get("pe")
    pb = te.get("pb")
    if pe or pb:
        parts = []
        if pe: parts.append(f"F/K {pe}x")
        if pb: parts.append(f"PD/DD {pb}x")
        te_str = f"\n📋 <b>Temel:</b>  " + "  |  ".join(parts)

    # Endeks uyarısı
    ep_str = f"\n⚠️ <i>{ep}</i>" if ep else ""

    # Haber neden açıklaması
    neden_ozeti = r.get("neden_ozeti", "")
    haber_neden_str = ""
    if neden_ozeti and neden_ozeti != "Belirgin bir haber yok":
        satirlar = neden_ozeti.split("\n   ")
        fmt = "\n   ".join(f"<i>{s}</i>" for s in satirlar[:3])
        haber_neden_str = f"\n📰 <b>Haber Nedeni:</b>\n   {fmt}"

    # AI özet (haber nedeni yoksa göster)
    ai_str = ""
    if ai_ozet and ai_ozet != "keyword" and not haber_neden_str:
        ai_str = f"\n🤖 <i>{ai_ozet}</i>"

    # Derinlik linki — işlem kararında kullan
    derinlik = (
        f"\n\n{'─'*28}\n"
        f"🔍 <b>Derinliği kontrol et:</b>\n"
        f"👉 @ucretsizderinlikbot uygulamasını aç\n"
        f"✏️ <code>{sym}</code> yaz ve derinliğe bak\n"
        f"✅ Derinlik de destekliyorsa → <b>EMİR AÇ</b>"
    )

    mesaj = (
        f"{'━'*28}\n"
        f"<b>{baslik} — {sym}</b>\n"
        f"{'━'*28}\n\n"
        f"💰 <b>Fiyat:</b>  {fiyat:.2f}₺  {deg_ok} {deg_str}\n"
        f"📊 <b>Birleşik Puan:</b>  <b>{puan_str}</b>\n"
        f"   ├ Teknik (G):  {gp:+d}   Haftalık:  {hp:+d}\n"
        f"   └ Haber:  {hs:+.1f}   Uyum: {uyum}\n\n"
        f"📉 <b>İndikatörler:</b>\n"
        f"   RSI: {rsi_v:.1f}   Stoch: {stoch_v:.0f}   ATR%: {atr_o:.1f}\n"
        f"   Hacim: {vol_str}\n"
    )

    if sin_str:
        mesaj += f"   <i>↳ {sin_str}</i>\n"

    mesaj += (
        f"\n🎯 <b>Hedefler:</b>\n"
        f"   Hedef-1: <b>{h1:.2f}₺</b>  {yuzde(h1)}\n"
        f"   Hedef-2: <b>{h2:.2f}₺</b>  {yuzde(h2)}\n"
        f"   Stop:    <b>{sl:.2f}₺</b>  {yuzde(sl)}\n"
        f"   R/K Oranı: <b>1 : {rk}</b>   Vade: {vade}\n"
    )

    mesaj += ah_str + te_str + ep_str + haber_neden_str + ai_str + derinlik

    mesaj += (
        f"\n\n<i>🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>"
    )

    return mesaj

# ─── TARAMA SONRASI SİNYAL BİLDİRİMLERİ ─────────────────────────
def sinyal_bildir(sonuclar: list,
                  min_puan: float = 3.0,
                  sadece_guclu: bool = True) -> int:
    """
    Tarama bittikten sonra çağrılır.
    Güçlü AL/SAT sinyallerini Telegram'a gönderir.
    
    Parametreler:
        sonuclar    : zamansal_analiz() listesi
        min_puan    : minimum birleşik puan eşiği
        sadece_guclu: True = sadece guclu_al/guclu_sat
    
    Döndürür: gönderilen bildirim sayısı
    """
    gonderilen = 0

    # Puanlara göre sırala, en güçlü önce
    al_sinyalleri  = sorted(
        [r for r in sonuclar if r.get("karar_kod") == "guclu_al"
         and r.get("toplam_puan", 0) >= min_puan],
        key=lambda x: x.get("toplam_puan", 0), reverse=True
    )
    sat_sinyalleri = sorted(
        [r for r in sonuclar if r.get("karar_kod") == "guclu_sat"
         and r.get("toplam_puan", 0) <= -min_puan],
        key=lambda x: x.get("toplam_puan", 0)
    )

    if not sadece_guclu:
        al_sinyalleri  += sorted(
            [r for r in sonuclar if r.get("karar_kod") == "al"
             and r.get("toplam_puan", 0) >= min_puan],
            key=lambda x: x.get("toplam_puan", 0), reverse=True
        )
        sat_sinyalleri += sorted(
            [r for r in sonuclar if r.get("karar_kod") == "sat"
             and r.get("toplam_puan", 0) <= -min_puan],
            key=lambda x: x.get("toplam_puan", 0)
        )

    for r in (al_sinyalleri + sat_sinyalleri):
        sembol   = r.get("sembol", "")
        karar_kod = r.get("karar_kod", "")

        if not _bildirim_gonder_mi(sembol, karar_kod):
            continue  # 4 saat içinde zaten gönderilmiş

        kart = _sinyal_karti_olustur(r)
        if telegram_gonder(kart):
            gonderilen += 1
            print(f"[SİNYAL] 📨 {sembol} → {karar_kod} gönderildi")
        time.sleep(0.5)  # Telegram rate limit

    if gonderilen > 0:
        print(f"[SİNYAL] Toplam {gonderilen} sinyal bildirimi gönderildi")

    return gonderilen

# ─── GÜNLÜK ÖZET ─────────────────────────────────────────────────
def gunluk_ozet_gonder(sonuclar: list) -> bool:
    """
    Günlük piyasa özeti — sabah otomatik gönderilir.
    """
    if not sonuclar:
        return False

    gal  = [r for r in sonuclar if r.get("karar_kod") == "guclu_al"]
    al   = [r for r in sonuclar if r.get("karar_kod") == "al"]
    gsat = [r for r in sonuclar if r.get("karar_kod") == "guclu_sat"]
    sat  = [r for r in sonuclar if r.get("karar_kod") == "sat"]
    bkl  = [r for r in sonuclar if r.get("karar_kod") == "bekle"]

    # En iyi 5 AL
    top_al = sorted(gal + al,
                    key=lambda x: x.get("toplam_puan", 0),
                    reverse=True)[:5]
    top_al_str = ""
    for r in top_al:
        sym = r["sembol"].replace(".IS", "")
        top_al_str += (f"  • <b>{sym}</b>  {r['fiyat']:.2f}₺  "
                       f"({r['degisim']:+.1f}%)  "
                       f"Puan: {r['toplam_puan']:+.1f}\n")

    # En iyi 3 SAT
    top_sat = sorted(gsat + sat,
                     key=lambda x: x.get("toplam_puan", 0))[:3]
    top_sat_str = ""
    for r in top_sat:
        sym = r["sembol"].replace(".IS", "")
        top_sat_str += (f"  • <b>{sym}</b>  {r['fiyat']:.2f}₺  "
                        f"({r['degisim']:+.1f}%)  "
                        f"Puan: {r['toplam_puan']:+.1f}\n")

    mesaj = (
        f"📊 <b>GÜNLÜK PİYASA ÖZETİ</b>\n"
        f"{'━'*28}\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🟢 Güçlü AL: <b>{len(gal)}</b>   "
        f"🟡 AL: <b>{len(al)}</b>   "
        f"🔴 Güçlü SAT: <b>{len(gsat)}</b>   "
        f"🟠 SAT: <b>{len(sat)}</b>   "
        f"⏸ Bekle: <b>{len(bkl)}</b>\n\n"
    )

    if top_al_str:
        mesaj += f"🏆 <b>En İyi AL Sinyalleri:</b>\n{top_al_str}\n"
    if top_sat_str:
        mesaj += f"⚠️ <b>SAT Sinyalleri:</b>\n{top_sat_str}\n"

    mesaj += (
        f"\n🔍 Detay için @ucretsizderinlikbot'ta\n"
        f"hisse kodunu yaz ve derinliğe bak."
    )

    return telegram_gonder(mesaj)

# ─── VERİTABANI ───────────────────────────────────────────────────
def db_alarm_init():
    with sqlite3.connect(DB) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS alarmlar (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sembol       TEXT    NOT NULL,
                tip          TEXT    NOT NULL,
                hedef_fiyat  REAL    NOT NULL,
                not_         TEXT,
                olusturuldu  TEXT    NOT NULL,
                aktif        INTEGER DEFAULT 1,
                tetiklendi_f REAL,
                tetiklendi_t TEXT
            )""")
        c.commit()

def db_alarm_ekle(sembol: str, tip: str, hedef: float, not_: str = "") -> int:
    with sqlite3.connect(DB) as c:
        cur = c.execute(
            "INSERT INTO alarmlar (sembol,tip,hedef_fiyat,not_,olusturuldu) VALUES (?,?,?,?,?)",
            (sembol.upper(), tip, hedef, not_,
             datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        c.commit()
        return cur.lastrowid

def db_alarm_sil(alarm_id: int):
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE alarmlar SET aktif=0 WHERE id=?", (alarm_id,))
        c.commit()

def db_alarm_listele(sadece_aktif: bool = True) -> list:
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        q = "SELECT * FROM alarmlar"
        if sadece_aktif:
            q += " WHERE aktif=1"
        q += " ORDER BY id DESC"
        return [dict(r) for r in c.execute(q).fetchall()]

def db_alarm_tetiklendi(alarm_id: int, son_fiyat: float):
    with sqlite3.connect(DB) as c:
        c.execute(
            "UPDATE alarmlar SET aktif=0,tetiklendi_f=?,tetiklendi_t=? WHERE id=?",
            (son_fiyat, datetime.now().strftime("%d.%m.%Y %H:%M:%S"), alarm_id)
        )
        c.commit()

# ─── FİYAT ALARM DÖNGÜSÜ ─────────────────────────────────────────
def _alarm_kontrol_bir_kez():
    alarmlar = db_alarm_listele(sadece_aktif=True)
    if not alarmlar:
        return

    fiyat_cache: dict = {}
    for alarm in alarmlar:
        sembol = alarm["sembol"]
        if sembol not in fiyat_cache:
            fiyat_cache[sembol] = anlik_fiyat(sembol)

        son_f = fiyat_cache.get(sembol)
        if son_f is None:
            continue

        tetiklendi = False
        mesaj = ""

        if alarm["tip"] == "asagi" and son_f <= alarm["hedef_fiyat"]:
            tetiklendi = True
            mesaj = (
                f"🔴 <b>FİYAT ALARMI — DÜŞTÜ!</b>\n\n"
                f"📌 <b>{sembol.replace('.IS','')}</b>\n"
                f"💰 Anlık: <b>{son_f:.2f}₺</b>\n"
                f"🎯 Hedef: {alarm['hedef_fiyat']:.2f}₺  (⬇ aşağı)\n"
                f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )

        elif alarm["tip"] == "yukari" and son_f >= alarm["hedef_fiyat"]:
            tetiklendi = True
            mesaj = (
                f"🟢 <b>FİYAT ALARMI — YÜKSELDİ!</b>\n\n"
                f"📌 <b>{sembol.replace('.IS','')}</b>\n"
                f"💰 Anlık: <b>{son_f:.2f}₺</b>\n"
                f"🎯 Hedef: {alarm['hedef_fiyat']:.2f}₺  (⬆ yukarı)\n"
                f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )

        if tetiklendi:
            if alarm.get("not_"):
                mesaj += f"\n📝 {alarm['not_']}"
            mesaj += (
                f"\n\n🔍 Derinlik: @ucretsizderinlikbot\n"
                f"✏️ <code>{sembol.replace('.IS','')}</code> yaz"
            )
            telegram_gonder(mesaj)
            db_alarm_tetiklendi(alarm["id"], son_f)
            print(f"[ALARM] ✅ Tetiklendi: {sembol} @ {son_f:.2f}₺")

def alarm_dongu(dakika: int = 2):
    print(f"[ALARM] Servis başladı — her {dakika} dk kontrol")
    while True:
        try:
            _alarm_kontrol_bir_kez()
        except Exception as e:
            print(f"[ALARM] Hata: {e}")
        try:
            _pozisyon_kontrol()
        except Exception as e:
            print(f"[POZ] Hata: {e}")
        time.sleep(dakika * 60)

# ─── POZİSYON TAKİP SİSTEMİ ──────────────────────────────────────
# Açık pozisyonları takip et: hedef-1'e ulaşınca / stop'a düşünce bildir
# { sembol: {"alis": float, "stop": float, "h1": float, "h2": float,
#             "h1_gecti": bool, "bildirildi_stop": bool} }
_POZISYONLAR: dict = {}
_POZ_LOCK = threading.Lock()

def pozisyon_ekle(sembol: str, alis_fiyat: float,
                  stop: float, h1: float, h2: float):
    """
    Açık bir pozisyonu takip listesine ekle.
    Dashboard'dan portföye hisse eklenince otomatik çağrılabilir.
    """
    with _POZ_LOCK:
        _POZISYONLAR[sembol.upper()] = {
            "alis":            alis_fiyat,
            "stop":            stop,
            "h1":              h1,
            "h2":              h2,
            "h1_gecti":        False,
            "bildirildi_stop": False,
            "bildirildi_h1":   False,
            "bildirildi_h2":   False,
        }
    print(f"[POZ] 📌 Takibe alındı: {sembol} @ {alis_fiyat:.2f}₺  "
          f"Stop:{stop:.2f}  H1:{h1:.2f}  H2:{h2:.2f}")

def pozisyon_sil(sembol: str):
    with _POZ_LOCK:
        _POZISYONLAR.pop(sembol.upper(), None)

def _pozisyon_kontrol():
    """Takipteki pozisyonları fiyat alarmlarıyla karşılaştır."""
    with _POZ_LOCK:
        pozlar = dict(_POZISYONLAR)

    for sembol, poz in pozlar.items():
        fiyat = anlik_fiyat(sembol)
        if fiyat is None:
            continue
        sym = sembol.replace(".IS", "")
        alis = poz["alis"]
        kar_yuz = (fiyat - alis) / alis * 100

        # ── STOP tetiklendi ───────────────────────────────────────
        if fiyat <= poz["stop"] and not poz["bildirildi_stop"]:
            mesaj = (
                f"🛑 <b>STOP LOSS TETİKLENDİ — {sym}</b>\n\n"
                f"💰 Anlık:  <b>{fiyat:.2f}₺</b>\n"
                f"📉 Değişim: {kar_yuz:+.1f}% (alıştan)\n"
                f"🛑 Stop:   {poz['stop']:.2f}₺\n\n"
                f"⚠️ <b>POZİSYONU KAPAT!</b>  Zararı büyütme.\n"
                f"🔍 @ucretsizderinlikbot → <code>{sym}</code>"
            )
            telegram_gonder(mesaj)
            with _POZ_LOCK:
                if sembol in _POZISYONLAR:
                    _POZISYONLAR[sembol]["bildirildi_stop"] = True
            print(f"[POZ] 🛑 Stop tetiklendi: {sembol} @ {fiyat:.2f}")

        # ── HEDEF-1 ulaşıldı ─────────────────────────────────────
        elif fiyat >= poz["h1"] and not poz["bildirildi_h1"]:
            mesaj = (
                f"🎯 <b>HEDEF-1 ULAŞILDI — {sym}</b>\n\n"
                f"💰 Anlık:   <b>{fiyat:.2f}₺</b>\n"
                f"📈 Kâr:      <b>+{kar_yuz:.1f}%</b> 🎉\n"
                f"🎯 Hedef-1:  {poz['h1']:.2f}₺  ✅\n"
                f"🎯 Hedef-2:  {poz['h2']:.2f}₺\n\n"
                f"💡 <b>Öneri:</b>\n"
                f"   • Yarı pozisyonu sat → kâr realize et\n"
                f"   • Stop'u alış fiyatına çek ({alis:.2f}₺)\n"
                f"   • Kalan yarı için H2'yi bekle\n\n"
                f"🔍 @ucretsizderinlikbot → <code>{sym}</code>"
            )
            telegram_gonder(mesaj)
            with _POZ_LOCK:
                if sembol in _POZISYONLAR:
                    _POZISYONLAR[sembol]["bildirildi_h1"] = True
                    _POZISYONLAR[sembol]["h1_gecti"]      = True
            print(f"[POZ] 🎯 Hedef-1: {sembol} @ {fiyat:.2f}")

        # ── HEDEF-2 ulaşıldı ─────────────────────────────────────
        elif fiyat >= poz["h2"] and poz["h1_gecti"] and not poz["bildirildi_h2"]:
            mesaj = (
                f"🚀 <b>HEDEF-2 ULAŞILDI — {sym}</b>\n\n"
                f"💰 Anlık:   <b>{fiyat:.2f}₺</b>\n"
                f"📈 Kâr:      <b>+{kar_yuz:.1f}%</b> 🔥\n"
                f"🎯 Hedef-2:  {poz['h2']:.2f}₺  ✅\n\n"
                f"💡 <b>Öneri:</b> Kalan pozisyonu kapat.\n"
                f"   Harika iş! Kâr tamamlandı. 💰\n\n"
                f"🔍 @ucretsizderinlikbot → <code>{sym}</code>"
            )
            telegram_gonder(mesaj)
            with _POZ_LOCK:
                if sembol in _POZISYONLAR:
                    _POZISYONLAR[sembol]["bildirildi_h2"] = True
            print(f"[POZ] 🚀 Hedef-2: {sembol} @ {fiyat:.2f}")

        # ── H1 geçti ama geri döndü, stop = maliyet ──────────────
        elif (poz["h1_gecti"] and fiyat <= alis * 1.005
              and not poz["bildirildi_stop"]):
            mesaj = (
                f"⚠️ <b>UYARI — {sym} MALİYETE DÖNDÜ</b>\n\n"
                f"💰 Anlık: <b>{fiyat:.2f}₺</b>\n"
                f"📉 H1 geçmişti ama fiyat düştü!\n\n"
                f"💡 Stop'unu <b>{alis:.2f}₺</b>'ye çek — kaybetme!"
            )
            telegram_gonder(mesaj)
            with _POZ_LOCK:
                if sembol in _POZISYONLAR:
                    _POZISYONLAR[sembol]["bildirildi_stop"] = True
