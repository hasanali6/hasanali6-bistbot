"""
telegram_komut.py — Telegram Komut Terminali v1.0
══════════════════════════════════════════════════
Desteklenen Komutlar:
  /tara          → Tüm BIST'i tara, güçlü sinyalleri gönder
  /top10         → En yüksek puanlı 10 hisse
  /hisse THYAO   → Tek hisse analizi
  /portfoy       → Açık pozisyonlar + kâr/zarar
  /alarm THYAO 150 yukari  → Fiyat alarmı kur
  /alarmlar      → Aktif alarmlar listesi
  /alarmsil 3    → Alarm ID'yi sil
  /backtest THYAO → Geçmiş sinyal başarı oranı
  /makro         → Makro risk analizi
  /yardim        → Komut listesi
"""

import threading
import time
import requests
from datetime import datetime
from typing import Optional

# ─── UPDATE POLLING ───────────────────────────────────────────────
_son_update_id: int = 0
_KOMUT_LOCK = threading.Lock()
_calisiyor  = False

def _telegram_get_updates(token: str, offset: int = 0,
                           timeout: int = 30) -> list:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": timeout,
                    "allowed_updates": ["message"]},
            timeout=timeout + 5,
        )
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        print(f"[KOMUT] getUpdates hata: {e}")
    return []

def _telegram_yaz(token: str, chat_id: str, mesaj: str,
                  parse_mode: str = "HTML") -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": mesaj,
                  "parse_mode": parse_mode,
                  "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


# ─── KOMUT İŞLEYİCİLER ───────────────────────────────────────────

def _cmd_yardim() -> str:
    return (
        "🤖 <b>BIST BOT — Komutlar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>Analiz:</b>\n"
        "  /tara — Tüm BIST taraması (yavaş)\n"
        "  /top10 — En iyi 10 sinyal\n"
        "  /hisse THYAO — Tek hisse detay\n"
        "  /backtest THYAO — Geçmiş başarı\n"
        "  /makro — Makro risk durumu\n\n"
        "💼 <b>Portföy:</b>\n"
        "  /portfoy — Pozisyonlarım + K/Z\n"
        "  /gecmis — İşlem geçmişi\n\n"
        "🔔 <b>Alarmlar:</b>\n"
        "  /alarm THYAO 150 yukari\n"
        "  /alarm THYAO 140 asagi\n"
        "  /alarmlar — Aktif alarmlar\n"
        "  /alarmsil 3 — ID sil\n\n"
        "ℹ️ <b>Diğer:</b>\n"
        "  /yardim — Bu liste\n"
        "  /durum — Bot durumu"
    )


def _cmd_durum() -> str:
    from bot_engine import bist100_durumu, makro_risk_analizi
    try:
        endeks = bist100_durumu()
        makro  = makro_risk_analizi()
        xu  = endeks.get("degisim", 0)
        sev = makro.get("risk_seviye", "NORMAL")
        uyari = endeks.get("uyari", False)
        return (
            f"✅ <b>Bot Çalışıyor</b>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📊 BIST-100: <b>{xu:+.2f}%</b>"
            f"  {'🔴 RİSKLİ' if uyari else '🟢 Normal'}\n"
            f"🌍 Makro Risk: <b>{sev}</b>\n\n"
            f"Komutlar için: /yardim"
        )
    except Exception as e:
        return f"✅ Bot çalışıyor\n⚠ Veri çekilemedi: {e}"


def _cmd_hisse(sembol_raw: str, token: str, chat_id: str):
    """Tek hisse analizi — uzun sürebilir, önce 'analiz ediliyor' yaz."""
    sembol = sembol_raw.upper().strip()
    if not sembol.endswith(".IS"):
        sembol += ".IS"

    _telegram_yaz(token, chat_id,
                  f"🔍 <b>{sembol_raw.upper()}</b> analiz ediliyor...\n"
                  f"⏳ 10-20 saniye sürebilir.")

    try:
        from bot_engine import zamansal_analiz
        r = zamansal_analiz(sembol)
        if not r:
            return f"❌ {sembol_raw.upper()} için veri bulunamadı.\nBlacklist'te veya borsadan silinmiş olabilir."

        sym  = sembol.replace(".IS", "")
        kk   = r.get("karar_kod", "bekle")
        kar  = r.get("karar", "BEKLE")
        fiy  = r.get("fiyat", 0)
        deg  = r.get("degisim", 0)
        puan = r.get("toplam_puan", 0)
        rsi  = r.get("rsi", 0)
        sl   = r.get("stop_loss", 0)
        h1   = r.get("hedef_1", 0)
        h2   = r.get("hedef_2", 0)
        vade = r.get("vade_gun", "–")
        ma200 = r.get("ma200", 0)
        ma_trend = r.get("ma_trend", "")
        st_yon = r.get("st_yon", 0)
        sik   = r.get("sikisma", {})
        div_v = r.get("divergence", {})
        te    = r.get("temel") or {}
        sek   = r.get("sektor", {})
        eg    = r.get("endeks_guc", {})

        deg_ok = "📈" if deg >= 0 else "📉"

        # SuperTrend
        st_str = "🟢 AL" if st_yon == 1 else ("🔴 SAT" if st_yon == -1 else "–")

        # Zamansallık
        sik_str = ""
        if sik.get("sikisma"):
            sik_str = f"\n⏳ Zamansallık: {sik.get('etiket','')}"

        # Divergence
        div_str = ""
        if div_v.get("tip"):
            div_str = f"\n🔀 RSI Uyumsuzluk: {div_v.get('etiket','')}"

        # Riskli haber
        riskli_str = ""
        if r.get("riskli_haber"):
            riskli_str = f"\n⛔ <b>RİSKLİ HABER VAR!</b>"

        mesaj = (
            f"{'━'*28}\n"
            f"<b>{kar} — {sym}</b>\n"
            f"{'━'*28}\n\n"
            f"💰 {fiy:.2f}₺  {deg_ok} {deg:+.2f}%\n"
            f"📊 Birleşik Puan: <b>{puan:+.1f}</b>\n\n"
            f"📉 RSI: {rsi:.1f}   "
            f"SuperTrend: {st_str}   "
            f"MA200: {'✅' if ma_trend == 'ustunde' else '⚠↓'}\n"
            f"🏭 Sektör: {sek.get('etiket','–')}\n"
            f"📈 Endeks: {eg.get('etiket','–')}\n"
            f"{sik_str}{div_str}{riskli_str}\n\n"
            f"🎯 <b>Hedefler:</b>\n"
            f"   H1: {h1:.2f}₺  ({(h1-fiy)/fiy*100:+.1f}%)\n"
            f"   H2: {h2:.2f}₺  ({(h2-fiy)/fiy*100:+.1f}%)\n"
            f"   Stop: {sl:.2f}₺  ({(sl-fiy)/fiy*100:+.1f}%)\n"
            f"   Vade: {vade}\n"
        )

        # Temel
        pe = te.get("pe"); pb = te.get("pb")
        temel_skor = te.get("temel_skor", 0)
        if pe or pb:
            mesaj += (
                f"\n📋 Temel Skor: {temel_skor}/3"
                f"{'  🏆 GÜNÜN FIRSATI!' if r.get('gunun_firsati') else ''}\n"
            )
            if pe: mesaj += f"   F/K: {pe}x"
            if pb: mesaj += f"   PD/DD: {pb}x"
            mesaj += "\n"

        mesaj += (
            f"\n🔍 @ucretsizderinlikbot → <code>{sym}</code>\n"
            f"<i>🕐 {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        return mesaj

    except Exception as e:
        return f"❌ Hata: {e}"


def _cmd_top10(token: str, chat_id: str):
    """Cache'den en iyi 10 sinyali döndür."""
    _telegram_yaz(token, chat_id, "⏳ Top 10 hazırlanıyor...")
    try:
        # Dashboard cache'ini oku
        import requests as _r
        try:
            from config import PORT as _PORT
        except Exception:
            _PORT = 5000
        try:
            resp = _r.get(f"http://localhost:{_PORT}/api/data", timeout=5)
            data = resp.json().get("data", [])
        except Exception:
            from bot_engine import zamansal_analiz, BIST_HISSELER
            _telegram_yaz(token, chat_id,
                          "⚠ Dashboard kapalı, hızlı tarama yapıyorum (30 hisse)...")
            data = []
            for s in BIST_HISSELER[:30]:
                r = zamansal_analiz(s)
                if r:
                    data.append(r)

        if not data:
            return "❌ Veri yok. /tara komutuyla tarama başlat."

        # En iyi AL sinyalleri
        top = sorted(
            [r for r in data if "al" in r.get("karar_kod", "")],
            key=lambda x: x.get("toplam_puan", 0), reverse=True
        )[:10]

        if not top:
            return "📊 Şu an güçlü AL sinyali yok.\nPiyasa bekle modunda olabilir."

        satirlar = []
        for i, r in enumerate(top, 1):
            sym = r["sembol"].replace(".IS", "")
            kk  = r.get("karar_kod", "")
            p   = r.get("toplam_puan", 0)
            f   = r.get("fiyat", 0)
            d   = r.get("degisim", 0)
            st  = "🟢" if r.get("st_yon") == 1 else ""
            sik = "⏳" if r.get("sikisma", {}).get("sikisma") else ""
            kk_emoji = "🟢" if kk == "guclu_al" else "🟡"
            satirlar.append(
                f"{i}. {kk_emoji} <b>{sym}</b>  {f:.2f}₺  {d:+.1f}%"
                f"  Puan:{p:+.1f}  {st}{sik}"
            )

        mesaj = (
            f"🏆 <b>TOP 10 AL SİNYALİ</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(satirlar)
            + "\n\n🟢=Güçlü AL  🟡=AL  🟢ST=SuperTrend  ⏳=Zamansallık"
            + "\n\nDetay için: /hisse THYAO"
        )
        return mesaj

    except Exception as e:
        return f"❌ Hata: {e}"


def _cmd_tara(token: str, chat_id: str):
    """Tam tarama — uzun sürer, arka planda çalışır."""
    _telegram_yaz(token, chat_id,
                  "🔍 <b>Tam BIST Taraması Başladı</b>\n\n"
                  "⏳ Bu işlem 10-30 dakika sürebilir.\n"
                  "Güçlü sinyaller bulunca otomatik bildirim gelecek.\n\n"
                  "Dashboard'u açık bırak: bot zaten arkaplanda tarıyor.")

    def _tara_arkaplanda():
        try:
            from bot_engine import zamansal_analiz, BIST_HISSELER
            from alarm_bot import sinyal_bildir
            sonuclar = []
            for i, s in enumerate(BIST_HISSELER):
                r = zamansal_analiz(s)
                if r:
                    sonuclar.append(r)
                if i % 50 == 0 and i > 0:
                    _telegram_yaz(token, chat_id,
                                  f"⏳ Tarama: {i}/{len(BIST_HISSELER)} hisse işlendi...")
                time.sleep(0.1)
            sinyal_bildir(sonuclar)
            _telegram_yaz(token, chat_id,
                          f"✅ Tarama tamamlandı!\n"
                          f"📊 {len(sonuclar)} hisse analiz edildi.\n"
                          f"Güçlü sinyaller yukarı gönderildi.")
        except Exception as e:
            _telegram_yaz(token, chat_id, f"❌ Tarama hatası: {e}")

    t = threading.Thread(target=_tara_arkaplanda, daemon=True)
    t.start()
    return None  # Yanıt zaten arka planda gönderilecek


def _cmd_portfoy(token: str, chat_id: str):
    """Açık pozisyonlar + anlık K/Z."""
    try:
        from bot_engine import anlik_fiyat
        import sqlite3
        DB = "portfolio.db"

        with sqlite3.connect(DB) as c:
            c.row_factory = sqlite3.Row
            pozlar = [dict(r) for r in
                      c.execute("SELECT * FROM portfoy ORDER BY alis_tarihi DESC").fetchall()]

            # Toplam K/Z (kapalı işlemler)
            gecmis = c.execute(
                "SELECT SUM(kar_zarar) as toplam FROM islem_gecmisi WHERE islem_tipi='SATIS'"
            ).fetchone()
            realized_kz = float(gecmis["toplam"] or 0)

        if not pozlar:
            return (
                "💼 <b>Portföyünüz Boş</b>\n\n"
                "Dashboard'dan hisse ekleyebilirsin.\n"
                f"📈 Realize edilmiş K/Z: <b>{realized_kz:+.2f}₺</b>"
            )

        satirlar = []
        toplam_maliyet  = 0.0
        toplam_deger    = 0.0
        unrealized_kz   = 0.0

        for p in pozlar:
            sym   = p["sembol"].replace(".IS", "")
            adet  = p["adet"]
            alis  = p["alis_fiyat"]
            maliyet = adet * alis

            # Anlık fiyat çek
            son_f = anlik_fiyat(p["sembol"])
            if son_f:
                kz     = (son_f - alis) * adet
                kz_yuz = (son_f - alis) / alis * 100
                deger  = adet * son_f
                yon    = "📈" if kz >= 0 else "📉"
                kz_str = f"{kz:+.2f}₺ ({kz_yuz:+.1f}%)"
                unrealized_kz  += kz
                toplam_deger   += deger
            else:
                yon    = "–"
                kz_str = "fiyat alınamadı"
                deger  = maliyet
                toplam_deger += maliyet

            toplam_maliyet += maliyet
            satirlar.append(
                f"{yon} <b>{sym}</b>  {adet:.0f} lot\n"
                f"   Alış: {alis:.2f}₺  |  Maliyet: {maliyet:.2f}₺\n"
                f"   Şu an: {son_f:.2f}₺  |  K/Z: <b>{kz_str}</b>"
            )

        toplam_kz = unrealized_kz + realized_kz
        ozet = (
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 Maliyet:      <b>{toplam_maliyet:.2f}₺</b>\n"
            f"📊 Güncel Değer: <b>{toplam_deger:.2f}₺</b>\n"
            f"📈 Açık K/Z:     <b>{unrealized_kz:+.2f}₺</b>\n"
            f"✅ Realize K/Z:  <b>{realized_kz:+.2f}₺</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Net Toplam:   <b>{toplam_kz:+.2f}₺</b>"
        )

        mesaj = (
            f"💼 <b>PORTFÖY DURUMU</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n\n".join(satirlar)
            + ozet
        )
        return mesaj

    except Exception as e:
        return f"❌ Portföy hatası: {e}"


def _cmd_alarm_ekle(parcalar: list) -> str:
    """
    /alarm THYAO 150 yukari
    /alarm THYAO 140 asagi
    """
    if len(parcalar) < 3:
        return (
            "❌ Yanlış format.\n\n"
            "Doğru kullanım:\n"
            "  /alarm THYAO 150 yukari\n"
            "  /alarm THYAO 140 asagi"
        )
    sembol = parcalar[0].upper()
    if not sembol.endswith(".IS"):
        sembol += ".IS"
    try:
        hedef = float(parcalar[1].replace(",", "."))
    except ValueError:
        return "❌ Fiyat rakam olmalı. Örnek: /alarm THYAO 150 yukari"

    tip = parcalar[2].lower()
    if tip not in ("yukari", "asagi", "üstü", "altı"):
        return "❌ Yön 'yukari' veya 'asagi' olmalı."
    if tip in ("üstü",): tip = "yukari"
    if tip in ("altı",):  tip = "asagi"

    from alarm_bot import db_alarm_ekle
    alarm_id = db_alarm_ekle(sembol, tip, hedef)

    yon_str = "yükselirse" if tip == "yukari" else "düşerse"
    return (
        f"✅ <b>Alarm Kuruldu!</b>  #{alarm_id}\n\n"
        f"📌 {sembol.replace('.IS','')}  →  {hedef:.2f}₺'ye {yon_str} bildirim gelecek\n"
        f"🔔 Alarm ID: <b>{alarm_id}</b> (silmek için /alarmsil {alarm_id})"
    )


def _cmd_alarmlar() -> str:
    from alarm_bot import db_alarm_listele
    alarmlar = db_alarm_listele(sadece_aktif=True)
    if not alarmlar:
        return "🔕 Aktif alarm yok.\n\nAlarm kurmak için:\n/alarm THYAO 150 yukari"
    satirlar = []
    for a in alarmlar:
        sym = a["sembol"].replace(".IS", "")
        yon = "⬆" if a["tip"] == "yukari" else "⬇"
        satirlar.append(
            f"#{a['id']}  {yon} <b>{sym}</b>  →  {a['hedef_fiyat']:.2f}₺\n"
            f"   Oluşturuldu: {a['olusturuldu']}"
        )
    return (
        f"🔔 <b>Aktif Alarmlar ({len(alarmlar)})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(satirlar)
        + "\n\nSilmek için: /alarmsil [ID]"
    )


def _cmd_alarmsil(alarm_id_str: str) -> str:
    try:
        alarm_id = int(alarm_id_str.strip())
    except ValueError:
        return "❌ Geçersiz ID. Örnek: /alarmsil 3"
    from alarm_bot import db_alarm_sil
    db_alarm_sil(alarm_id)
    return f"✅ Alarm #{alarm_id} silindi."


def _cmd_backtest(sembol_raw: str, token: str, chat_id: str):
    sembol = sembol_raw.upper().strip()
    if not sembol.endswith(".IS"):
        sembol += ".IS"

    _telegram_yaz(token, chat_id,
                  f"⏳ <b>{sembol_raw.upper()}</b> backtest çalışıyor...")
    try:
        from bot_engine import backtest
        bt = backtest(sembol, gun=120)
        if not bt:
            return f"❌ {sembol_raw.upper()} için backtest verisi yok."

        al  = bt.get("al",  {})
        sat = bt.get("sat", {})

        def fmt(d):
            if not d or d.get("n", 0) == 0:
                return "  Sinyal yok\n"
            return (
                f"  Sinyal: {d['n']}  |  Başarı: %{d['basari']}\n"
                f"  Ort. getiri: {d['ort']:+.2f}%\n"
                f"  En iyi: {d['max']:+.2f}%  |  En kötü: {d['min']:+.2f}%\n"
            )

        return (
            f"📊 <b>BACKTEST — {sembol.replace('.IS','')}</b>\n"
            f"Son {bt['gun']} gün (5 günlük hedef)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 <b>AL Sinyalleri:</b>\n{fmt(al)}\n"
            f"🔴 <b>SAT Sinyalleri:</b>\n{fmt(sat)}\n"
            f"<i>⚠ Geçmiş performans gelecek garantisi değildir.</i>"
        )
    except Exception as e:
        return f"❌ Backtest hatası: {e}"


def _cmd_makro() -> str:
    try:
        from bot_engine import makro_risk_analizi
        mk = makro_risk_analizi()
        sev   = mk.get("risk_seviye", "NORMAL")
        skor  = mk.get("risk_skoru", 0)
        ozet  = mk.get("ozet", "")
        riskler = mk.get("riskler", [])
        gunc  = mk.get("guncelleme", "")

        sev_emoji = {"YUKSEK": "🚨", "ORTA": "⚠", "DUSUK": "🟡", "NORMAL": "✅"}
        mesaj = (
            f"🌍 <b>MAKRO RİSK ANALİZİ</b>\n"
            f"🕐 {gunc}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Seviye: {sev_emoji.get(sev,'?')} <b>{sev}</b>  (Skor: {skor}/10)\n"
        )
        if ozet:
            mesaj += f"\n{ozet}\n"
        if riskler:
            mesaj += "\n<b>Tespit Edilen Riskler:</b>\n"
            for r in riskler[:4]:
                mesaj += f"  {r}\n"
        if sev == "NORMAL":
            mesaj += "\n✅ Belirgin makro risk tespit edilmedi."
        return mesaj
    except Exception as e:
        return f"❌ Makro analiz hatası: {e}"


def _cmd_gecmis() -> str:
    """Son 10 işlem + toplam K/Z."""
    try:
        import sqlite3
        DB = "portfolio.db"
        with sqlite3.connect(DB) as c:
            c.row_factory = sqlite3.Row
            islemler = [dict(r) for r in c.execute(
                "SELECT * FROM islem_gecmisi ORDER BY tarih DESC LIMIT 10"
            ).fetchall()]
            toplam = c.execute(
                "SELECT SUM(kar_zarar) FROM islem_gecmisi WHERE islem_tipi='SATIS'"
            ).fetchone()[0] or 0

        if not islemler:
            return "📋 İşlem geçmişi boş."

        satirlar = []
        for i in islemler:
            sym = str(i.get("sembol","")).replace(".IS","")
            tip = i.get("islem_tipi","")
            fiy = i.get("fiyat", 0)
            adet = i.get("adet", 0)
            kz  = i.get("kar_zarar", 0)
            emoji = "🟢" if tip == "ALIS" else "🔴"
            kz_str = f"  K/Z: <b>{kz:+.2f}₺</b>" if tip == "SATIS" else ""
            satirlar.append(
                f"{emoji} {tip}  <b>{sym}</b>  {adet:.0f}×{fiy:.2f}₺{kz_str}\n"
                f"   {i.get('tarih','')}"
            )

        return (
            f"📋 <b>SON 10 İŞLEM</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n\n".join(satirlar)
            + f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Toplam Realize K/Z: <b>{toplam:+.2f}₺</b>"
        )
    except Exception as e:
        return f"❌ Hata: {e}"


# ─── ANA KOMUT DÖNGÜSÜ ───────────────────────────────────────────
def _komut_isle(update: dict, token: str, chat_id_izin: str):
    """Gelen Telegram update'i işle."""
    global _son_update_id

    update_id = update.get("update_id", 0)
    msg       = update.get("message", {})
    metin     = (msg.get("text") or "").strip()
    chat_id   = str(msg.get("chat", {}).get("id", ""))

    if not metin or not chat_id:
        return

    # Güvenlik: sadece izinli chat'ten kabul et
    if chat_id_izin and chat_id != str(chat_id_izin):
        print(f"[KOMUT] ⛔ Yetkisiz chat: {chat_id}")
        return

    # Komut parse
    parcalar = metin.split()
    komut    = parcalar[0].lower().lstrip("/").split("@")[0]
    args     = parcalar[1:]

    print(f"[KOMUT] /{komut} {' '.join(args)}")

    yanit = None

    if komut == "yardim" or komut == "start":
        yanit = _cmd_yardim()

    elif komut == "durum":
        yanit = _cmd_durum()

    elif komut == "hisse":
        if not args:
            yanit = "❌ Hisse kodu gir. Örnek: /hisse THYAO"
        else:
            yanit = _cmd_hisse(args[0], token, chat_id)

    elif komut == "top10":
        yanit = _cmd_top10(token, chat_id)

    elif komut == "tara":
        _cmd_tara(token, chat_id)
        return  # Arka planda çalışıyor

    elif komut == "portfoy":
        yanit = _cmd_portfoy(token, chat_id)

    elif komut == "gecmis":
        yanit = _cmd_gecmis()

    elif komut == "alarm":
        yanit = _cmd_alarm_ekle(args)

    elif komut == "alarmlar":
        yanit = _cmd_alarmlar()

    elif komut == "alarmsil":
        if not args:
            yanit = "❌ ID gir. Örnek: /alarmsil 3"
        else:
            yanit = _cmd_alarmsil(args[0])

    elif komut == "backtest":
        if not args:
            yanit = "❌ Hisse gir. Örnek: /backtest THYAO"
        else:
            yanit = _cmd_backtest(args[0], token, chat_id)

    elif komut == "makro":
        yanit = _cmd_makro()

    else:
        yanit = f"❓ Bilinmeyen komut: /{komut}\n\nKomutlar için: /yardim"

    if yanit:
        _telegram_yaz(token, chat_id, yanit)


def komut_dinle(token: str, chat_id: str):
    """
    Telegram'dan gelen komutları dinler (long-polling).
    Dashboard'dan thread olarak başlatılır.
    
    Kullanım:
        import threading
        from telegram_komut import komut_dinle
        t = threading.Thread(target=komut_dinle, args=(TOKEN, CHAT_ID), daemon=True)
        t.start()
    """
    global _son_update_id, _calisiyor

    with _KOMUT_LOCK:
        if _calisiyor:
            print("[KOMUT] Zaten çalışıyor.")
            return
        _calisiyor = True

    print(f"[KOMUT] 🤖 Telegram komut terminali başladı")
    print(f"[KOMUT] Chat ID: {chat_id}")
    print(f"[KOMUT] Komutlar: /yardim /tara /top10 /hisse /portfoy /alarm /backtest")

    # Botun adını al
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe",
                          timeout=5).json()
        bot_adi = me.get("result", {}).get("username", "bot")
        print(f"[KOMUT] Bot: @{bot_adi}")
    except Exception:
        pass

    while True:
        try:
            updates = _telegram_get_updates(token, _son_update_id + 1)
            for upd in updates:
                _son_update_id = max(_son_update_id, upd.get("update_id", 0))
                _komut_isle(upd, token, chat_id)
        except Exception as e:
            print(f"[KOMUT] Döngü hatası: {e}")
            time.sleep(5)
        time.sleep(1)
