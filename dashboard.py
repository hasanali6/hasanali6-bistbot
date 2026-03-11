"""
dashboard.py — BIST Sinyal Panosu v5.0 (FINAL)
Bloomberg Terminal Estetiği
Çalıştır: python dashboard.py  →  http://localhost:5000
"""

from flask import Flask, render_template_string, jsonify, request
import sqlite3, threading, time
from datetime import datetime
from bot_engine import zamansal_analiz, BIST_HISSELER, bist100_durumu, backtest
from alarm_bot import (db_alarm_init, db_alarm_ekle, db_alarm_sil,
                        db_alarm_listele, alarm_dongu, telegram_test,
                        sinyal_bildir, gunluk_ozet_gonder)
try:
    from telegram_komut import komut_dinle as _komut_dinle
    _HAS_KOMUT = True
except ImportError:
    _HAS_KOMUT = False

app    = Flask(__name__)
DB     = "portfolio.db"
LOCK   = threading.Lock()
_cache = {"data": [], "guncelleme": None, "yukleniyor": False}

# ─── VERİTABANI ───────────────────────────────────────────────────
def db_init():
    with sqlite3.connect(DB) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS portfoy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sembol TEXT NOT NULL, adet REAL NOT NULL,
            alis_fiyat REAL NOT NULL, alis_tarihi TEXT NOT NULL, notlar TEXT);
        CREATE TABLE IF NOT EXISTS islem_gecmisi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            islem_tipi TEXT, sembol TEXT, adet REAL,
            fiyat REAL, tarih TEXT, kar_zarar REAL);
        """)

def db_portfoy_al():
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in
                c.execute("SELECT * FROM portfoy ORDER BY alis_tarihi DESC").fetchall()]

def db_portfoy_ekle(sembol, adet, fiyat, notlar=""):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO portfoy (sembol,adet,alis_fiyat,alis_tarihi,notlar) VALUES (?,?,?,?,?)",
                  (sembol.upper(), adet, fiyat, now, notlar))
        c.execute("INSERT INTO islem_gecmisi (islem_tipi,sembol,adet,fiyat,tarih,kar_zarar) VALUES (?,?,?,?,?,?)",
                  ("ALIS", sembol.upper(), adet, fiyat, now, 0))

def db_portfoy_sat(poz_id, satis_fiyat):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        poz = c.execute("SELECT * FROM portfoy WHERE id=?", (poz_id,)).fetchone()
        if not poz: return False
        kz = round((satis_fiyat - poz["alis_fiyat"]) * poz["adet"], 2)
        c.execute("DELETE FROM portfoy WHERE id=?", (poz_id,))
        c.execute("INSERT INTO islem_gecmisi (islem_tipi,sembol,adet,fiyat,tarih,kar_zarar) VALUES (?,?,?,?,?,?)",
                  ("SATIS", poz["sembol"], poz["adet"], satis_fiyat,
                   datetime.now().strftime("%d.%m.%Y %H:%M"), kz))
    return kz

def db_gecmis_al():
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in
                c.execute("SELECT * FROM islem_gecmisi ORDER BY id DESC LIMIT 200").fetchall()]

# ─── TARAMA ───────────────────────────────────────────────────────
def tara():
    with LOCK: _cache["yukleniyor"] = True
    try:
        sonuclar = []
        for s in BIST_HISSELER:
            r = zamansal_analiz(s)
            if r: sonuclar.append(r)
        with LOCK:
            _cache["data"]       = sonuclar
            _cache["guncelleme"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        # Güçlü AL / SAT sinyallerini Telegram'a gönder
        try:
            sinyal_bildir(sonuclar)
        except Exception as _se:
            print(f"[BOT] sinyal_bildir hata: {_se}")
    finally:
        with LOCK: _cache["yukleniyor"] = False

def arkaplan_dongu():
    """Otomatik tarama döngüsü + sabah 09:05 günlük özet."""
    try:
        from config import TARAMA_DAKIKA as TM
    except Exception:
        TM = 30
    _son_ozet_gunu = None   # Bugün özet gönderildi mi?
    while True:
        tara()
        # Sabah 09:05–09:35 arası ilk tamamlanan taramada günlük özet gönder
        simdi = datetime.now()
        if (simdi.hour == 9 and 5 <= simdi.minute <= 35
                and _son_ozet_gunu != simdi.date()):
            try:
                with LOCK:
                    veri = list(_cache["data"])
                if veri:
                    gunluk_ozet_gonder(veri)
                    _son_ozet_gunu = simdi.date()
            except Exception as _oe:
                print(f"[BOT] Günlük özet hata: {_oe}")
        time.sleep(TM * 60)

# ─── HTML ─────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BIST Sinyal</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:     #0B0E17;
  --bg1:    #131720;
  --bg2:    #1A2030;
  --bg3:    #1E2636;
  --border: rgba(255,255,255,.06);
  --border2:rgba(255,255,255,.12);
  --green:  #00D68F;
  --green2: #00FFA3;
  --red:    #FF4D6D;
  --red2:   #FF8FA3;
  --amber:  #F9C74F;
  --blue:   #4CC9F0;
  --purple: #7B61FF;
  --text:   #E2EBF5;
  --muted:  #4A5568;
  --dim:    #2D3748;
  --fn:     'DM Sans',sans-serif;
  --fm:     'DM Mono',monospace;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-font-smoothing:antialiased}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--fn);font-size:14px}

/* ── HEADER ── */
.hdr{
  height:56px;background:var(--bg1);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 20px;gap:0;
  position:sticky;top:0;z-index:300;
  backdrop-filter:blur(12px);
}
.logo{
  font-family:var(--fm);font-size:.8rem;font-weight:500;
  color:var(--text);letter-spacing:.5px;
  display:flex;align-items:center;gap:8px;
  padding-right:20px;border-right:1px solid var(--border);
}
.logo-dot{
  width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 8px var(--green);
  animation:pulse 2s ease-in-out infinite;
}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.6;transform:scale(.85)}}
.hdr-chips{display:flex;gap:4px;padding:0 16px;border-right:1px solid var(--border)}
.chip{
  background:var(--bg2);border:1px solid var(--border);border-radius:20px;
  padding:4px 12px;font-size:.7rem;font-weight:500;color:var(--muted);
  display:flex;flex-direction:column;align-items:center;min-width:58px;
}
.chip .cv{font-size:.82rem;font-weight:600;color:var(--text);font-family:var(--fm)}
.chip.green .cv{color:var(--green)}
.chip.red   .cv{color:var(--red)}
.chip.amber .cv{color:var(--amber)}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:12px}
.hdr-endeks{
  font-family:var(--fm);font-size:.75rem;color:var(--muted);
  padding:4px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:20px;
}
.hdr-clock{font-family:var(--fm);font-size:.78rem;color:var(--muted)}
.scan-badge{
  background:rgba(0,214,143,.1);border:1px solid rgba(0,214,143,.25);
  border-radius:20px;padding:3px 10px;font-size:.65rem;color:var(--green);
  font-weight:500;display:none
}

/* ── NAV ── */
.nav{
  padding:10px 20px 0;background:var(--bg1);
  border-bottom:1px solid var(--border);
  display:flex;gap:2px;
}
.nav-item{
  padding:8px 16px;border-radius:8px 8px 0 0;font-size:.78rem;font-weight:500;
  color:var(--muted);cursor:pointer;transition:.15s;border:1px solid transparent;
  border-bottom:none;position:relative;
}
.nav-item:hover{color:var(--text);background:var(--bg2)}
.nav-item.on{
  color:var(--text);background:var(--bg);
  border-color:var(--border);border-bottom-color:var(--bg);
}
.nav-badge{
  display:inline-block;background:var(--green);color:#000;
  font-size:.55rem;font-weight:700;border-radius:10px;
  padding:1px 5px;margin-left:4px;vertical-align:middle;
}

/* ── PANELS ── */
.content{max-width:1900px;margin:0 auto;padding:16px 20px}
.panel{display:none}.panel.on{display:block}

/* ── TOOLBAR ── */
.toolbar{
  display:flex;gap:8px;align-items:center;flex-wrap:wrap;
  margin-bottom:14px;
}
.search-wrap{
  position:relative;flex:1;min-width:180px;max-width:260px;
}
.search-wrap::before{
  content:'⌕';position:absolute;left:11px;top:50%;transform:translateY(-50%);
  color:var(--muted);font-size:1rem;pointer-events:none;
}
.search-wrap input{
  width:100%;background:var(--bg1);border:1px solid var(--border);
  border-radius:8px;color:var(--text);padding:7px 10px 7px 32px;
  font-family:var(--fn);font-size:.8rem;outline:none;transition:.15s;
}
.search-wrap input:focus{border-color:var(--border2);background:var(--bg2)}
select{
  background:var(--bg1);border:1px solid var(--border);border-radius:8px;
  color:var(--text);padding:7px 10px;font-family:var(--fn);font-size:.78rem;
  outline:none;cursor:pointer;transition:.15s;
}
select:focus{border-color:var(--border2)}
.cnt-badge{
  font-size:.72rem;color:var(--muted);
  background:var(--bg1);border:1px solid var(--border);
  border-radius:6px;padding:5px 10px;
}
.btn{
  background:var(--bg2);border:1px solid var(--border);border-radius:8px;
  color:var(--text);padding:7px 16px;font-family:var(--fn);font-size:.78rem;
  font-weight:500;cursor:pointer;transition:.15s;
}
.btn:hover{border-color:var(--border2);background:var(--bg3)}
.btn.primary{
  background:linear-gradient(135deg,rgba(0,214,143,.15),rgba(0,214,143,.05));
  border-color:rgba(0,214,143,.35);color:var(--green);
}
.btn.primary:hover{background:linear-gradient(135deg,rgba(0,214,143,.22),rgba(0,214,143,.08));border-color:var(--green)}
.btn.danger{border-color:rgba(255,77,109,.35);color:var(--red)}
.btn.danger:hover{background:rgba(255,77,109,.1)}
.btn.sm{padding:4px 10px;font-size:.7rem;border-radius:6px}

/* ── BANNER ── */
.endeks-banner{
  background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.25);
  border-radius:8px;padding:8px 14px;font-size:.78rem;color:var(--red2);
  margin-bottom:12px;display:none;
}

/* ── STOCK TABLE ── */
.tbl-card{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;
  overflow:hidden;
}
table{width:100%;border-collapse:collapse}
thead th{
  background:var(--bg2);color:var(--muted);font-size:.65rem;font-weight:600;
  letter-spacing:.8px;text-transform:uppercase;padding:10px 12px;text-align:left;
  border-bottom:1px solid var(--border);white-space:nowrap;position:sticky;top:0;
}
tbody tr{border-bottom:1px solid var(--border);transition:.1s;cursor:pointer}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:rgba(255,255,255,.025)}
tbody td{padding:9px 12px;font-size:.8rem;white-space:nowrap}
/* Left accent border by signal */
tbody tr.sig-guclu_al{border-left:3px solid var(--green)}
tbody tr.sig-al{border-left:3px solid #9EF01A}
tbody tr.sig-zayif_al{border-left:3px solid var(--blue)}
tbody tr.sig-bekle{border-left:3px solid transparent}
tbody tr.sig-zayif_sat{border-left:3px solid #FFB347}
tbody tr.sig-sat{border-left:3px solid var(--red2)}
tbody tr.sig-guclu_sat{border-left:3px solid var(--red)}

.pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--muted)}

/* Signal pills */
.sig{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 9px;border-radius:20px;
  font-size:.65rem;font-weight:600;white-space:nowrap;
}
.sig::before{content:'';width:5px;height:5px;border-radius:50%}
.sig.guclu_al{background:rgba(0,214,143,.12);color:var(--green);border:1px solid rgba(0,214,143,.3)}
.sig.guclu_al::before{background:var(--green);box-shadow:0 0 5px var(--green)}
.sig.al{background:rgba(158,240,26,.1);color:#9EF01A;border:1px solid rgba(158,240,26,.25)}
.sig.al::before{background:#9EF01A}
.sig.zayif_al{background:rgba(76,201,240,.1);color:var(--blue);border:1px solid rgba(76,201,240,.25)}
.sig.zayif_al::before{background:var(--blue)}
.sig.bekle{background:var(--bg2);color:var(--muted);border:1px solid var(--border)}
.sig.bekle::before{background:var(--muted)}
.sig.zayif_sat{background:rgba(255,179,71,.1);color:#FFB347;border:1px solid rgba(255,179,71,.25)}
.sig.zayif_sat::before{background:#FFB347}
.sig.sat{background:rgba(255,143,163,.1);color:var(--red2);border:1px solid rgba(255,143,163,.25)}
.sig.sat::before{background:var(--red2)}
.sig.guclu_sat{background:rgba(255,77,109,.12);color:var(--red);border:1px solid rgba(255,77,109,.3)}
.sig.guclu_sat::before{background:var(--red);box-shadow:0 0 5px var(--red)}

/* Hisse sembol */
.sym-cell{display:flex;flex-direction:column;gap:1px}
.sym{font-family:var(--fm);font-size:.82rem;font-weight:600;color:var(--text)}
.sym-sub{font-size:.6rem;color:var(--muted)}

/* Fiyat */
.price-cell{font-family:var(--fm);font-weight:600;font-size:.85rem}

/* RSI bar */
.rsi-wrap{display:flex;align-items:center;gap:6px}
.rsi-bar{
  width:40px;height:4px;background:var(--bg3);border-radius:2px;overflow:hidden;
}
.rsi-fill{height:100%;border-radius:2px;transition:.3s}

/* Volume bar */
.vol-wrap{display:flex;align-items:center;gap:5px;font-size:.75rem}
.vol-pip{
  width:6px;height:6px;border-radius:1px;
  background:var(--muted);flex-shrink:0;
}
.vol-pip.on{background:var(--green)}

/* ── TOP 10 CARDS ── */
.cards-section{margin-bottom:20px}
.section-title{
  font-size:.7rem;font-weight:600;letter-spacing:1px;color:var(--muted);
  text-transform:uppercase;margin-bottom:10px;
  display:flex;align-items:center;gap:8px;
}
.section-title::after{content:'';flex:1;height:1px;background:var(--border)}
.cards-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;
}
.stk-card{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;
  padding:14px;cursor:pointer;transition:.2s;position:relative;overflow:hidden;
}
.stk-card::before{
  content:'';position:absolute;inset:0;opacity:0;transition:.2s;
  background:linear-gradient(135deg,rgba(255,255,255,.03),transparent);
}
.stk-card:hover{border-color:var(--border2);transform:translateY(-1px);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.stk-card:hover::before{opacity:1}
.stk-card-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}
.stk-sym{font-family:var(--fm);font-size:.9rem;font-weight:700}
.stk-price{font-family:var(--fm);font-size:1.3rem;font-weight:700;margin-bottom:6px}
.stk-chg{font-size:.72rem;font-weight:600}
.stk-row{display:flex;justify-content:space-between;align-items:center;margin-top:5px}
.stk-row .k{font-size:.65rem;color:var(--muted)}
.stk-row .v{font-family:var(--fm);font-size:.72rem;font-weight:500}
/* Card accent border */
.stk-card.al-card{border-top:2px solid var(--green)}
.stk-card.sat-card{border-top:2px solid var(--red)}

/* ── PORTFÖY ── */
.pf-summary{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;
  margin-bottom:16px;
}
.pf-box{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;
}
.pf-box .lbl{font-size:.65rem;color:var(--muted);font-weight:500;margin-bottom:4px}
.pf-box .val{font-family:var(--fm);font-size:1.1rem;font-weight:700}
.pf-form{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;
  padding:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;
  margin-bottom:14px;
}
.pf-form label{font-size:.65rem;color:var(--muted);display:block;margin-bottom:3px}
.pf-form input{
  background:var(--bg);border:1px solid var(--border);border-radius:8px;
  color:var(--text);padding:7px 10px;font-family:var(--fn);font-size:.8rem;
  outline:none;width:110px;transition:.15s;
}
.pf-form input:focus{border-color:var(--border2)}

/* ── ALARMLAR ── */
.alm-form{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;
  padding:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;
  margin-bottom:14px;
}
.alm-form label{font-size:.65rem;color:var(--muted);display:block;margin-bottom:3px}
.alm-form input,.alm-form select{
  background:var(--bg);border:1px solid var(--border);border-radius:8px;
  color:var(--text);padding:7px 10px;font-family:var(--fn);font-size:.8rem;
  outline:none;transition:.15s;
}
.alm-form input:focus,.alm-form select:focus{border-color:var(--border2)}

/* ── BACKTEST ── */
.bt-form{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;
  padding:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;
  margin-bottom:16px;
}
.bt-form label{font-size:.65rem;color:var(--muted);display:block;margin-bottom:3px}
.bt-form input{
  background:var(--bg);border:1px solid var(--border);border-radius:8px;
  color:var(--text);padding:7px 10px;font-family:var(--fn);font-size:.8rem;
  outline:none;width:100px;transition:.15s;
}
.bt-result{display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:560px}
.bt-box{
  background:var(--bg1);border:1px solid var(--border);border-radius:12px;padding:16px;
}
.bt-title{font-size:.65rem;font-weight:600;letter-spacing:.8px;color:var(--muted);text-transform:uppercase;margin-bottom:10px}
.bt-row{display:flex;justify-content:space-between;margin-bottom:6px;font-size:.78rem}
.bt-row .k{color:var(--muted)}.bt-row .v{font-family:var(--fm);font-weight:600}

/* ── MODAL ── */
.modal-overlay{
  position:fixed;inset:0;z-index:500;
  background:rgba(0,0,0,.7);backdrop-filter:blur(8px);
  display:flex;align-items:center;justify-content:center;
}
.modal-box{
  background:var(--bg1);border:1px solid var(--border2);border-radius:16px;
  width:min(680px,96vw);max-height:88vh;overflow-y:auto;
  box-shadow:0 32px 64px rgba(0,0,0,.8);
}
.modal-head{
  padding:16px 20px;border-bottom:1px solid var(--border);
  display:flex;justify-content:space-between;align-items:center;
  position:sticky;top:0;background:var(--bg1);z-index:1;border-radius:16px 16px 0 0;
}
.modal-close{
  background:var(--bg2);border:1px solid var(--border);border-radius:8px;
  color:var(--muted);padding:5px 10px;cursor:pointer;font-size:.8rem;
  transition:.15s;
}
.modal-close:hover{color:var(--text);border-color:var(--border2)}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--dim);border-radius:2px}
::-webkit-scrollbar-thumb:hover{background:var(--muted)}

/* ── LOADING SKELETON ── */
@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
.skeleton{
  background:linear-gradient(90deg,var(--bg2) 25%,var(--bg3) 50%,var(--bg2) 75%);
  background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:4px;
}

/* ── EMPTY STATE ── */
.empty-state{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:60px 20px;color:var(--muted);text-align:center;gap:10px;
}
.empty-state .icon{font-size:2.5rem;opacity:.4}
.empty-state .txt{font-size:.85rem}
.empty-state .sub{font-size:.72rem;opacity:.6}

/* ── GEÇMİŞ TABLE ── */
.his-badge{
  display:inline-block;padding:2px 8px;border-radius:20px;
  font-size:.65rem;font-weight:600;
}
.his-badge.alis{background:rgba(0,214,143,.12);color:var(--green);border:1px solid rgba(0,214,143,.25)}
.his-badge.satis{background:rgba(255,77,109,.1);color:var(--red);border:1px solid rgba(255,77,109,.2)}

/* Responsive */
@media(max-width:600px){
  .hdr-chips{display:none}
  .content{padding:12px}
  .cards-grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
}
</style>
</head>
<body>

<!-- HEADER -->
<div class="hdr">
  <div class="logo">
    <div class="logo-dot"></div>
    BIST SİNYAL
  </div>
  <div class="hdr-chips">
    <div class="chip amber">
      <span class="cv" id="h-adet">–</span>
      <span>hisse</span>
    </div>
    <div class="chip green">
      <span class="cv" id="h-gal">–</span>
      <span>güçlü al</span>
    </div>
    <div class="chip green">
      <span class="cv" id="h-al">–</span>
      <span>toplam al</span>
    </div>
    <div class="chip red">
      <span class="cv" id="h-sat">–</span>
      <span>sat</span>
    </div>
  </div>
  <div class="hdr-right">
    <div class="hdr-endeks" id="hdr-endeks">BIST-100 –</div>
    <span class="scan-badge" id="scan-badge">⟳ Taranıyor</span>
    <div class="hdr-clock" id="h-saat">00:00:00</div>
  </div>
</div>

<!-- NAV -->
<div class="nav">
  <div class="nav-item on" onclick="sekmeGec('market',this)">📈 Market</div>
  <div class="nav-item" onclick="sekmeGec('top10',this)">🏆 Top 10</div>
  <div class="nav-item" onclick="sekmeGec('portfoy',this)">💼 Portföy</div>
  <div class="nav-item" onclick="sekmeGec('alarmlar',this)">🔔 Alarmlar</div>
  <div class="nav-item" onclick="sekmeGec('gecmis',this)">📋 Geçmiş</div>
  <div class="nav-item" onclick="sekmeGec('backtest',this)">🔬 Backtest</div>
</div>

<div class="content">

<!-- ══ MARKET ══ -->
<div class="panel on" id="panel-market">
  <div class="endeks-banner" id="endeks-banner"></div>
  <div id="seans-banner" style="
    background:rgba(249,199,79,.06);border:1px solid rgba(249,199,79,.2);
    border-radius:8px;padding:8px 16px;margin-bottom:10px;display:none;
    font-size:.73rem;color:var(--amber)"></div>
  <div id="makro-banner" style="
    background:rgba(249,199,79,.07);border:1px solid rgba(249,199,79,.25);
    border-radius:8px;padding:10px 16px;margin-bottom:12px;display:none">
    <div style="font-size:.72rem;font-weight:600;color:var(--amber);margin-bottom:4px">
      🌍 MAKRO RİSK UYARISI</div>
    <div id="makro-ozet" style="font-size:.75rem;color:var(--text);line-height:1.6"></div>
    <div id="makro-riskler" style="font-size:.68rem;color:var(--muted);margin-top:5px"></div>
  </div>
  <div class="toolbar">
    <div class="search-wrap">
      <input id="ara" placeholder="Hisse ara... THYAO" oninput="filtrele()">
    </div>
    <select id="sinyal-filtre" onchange="filtrele()">
      <option value="">Tüm Sinyaller</option>
      <option value="guclu_al">🟢 Güçlü Al</option>
      <option value="al">🟡 Al</option>
      <option value="zayif_al">🔵 Zayıf Al</option>
      <option value="bekle">⏸ Bekle</option>
      <option value="zayif_sat">🟠 Zayıf Sat</option>
      <option value="sat">🔴 Sat</option>
      <option value="guclu_sat">🔴 Güçlü Sat</option>
    </select>
    <select id="siralama" onchange="filtrele()">
      <option value="puan">Puana Göre</option>
      <option value="degisim">Değişime Göre</option>
      <option value="rsi">RSI (Düşük)</option>
      <option value="hacim">Hacme Göre</option>
    </select>
    <select id="uyum-filtre" onchange="filtrele()">
      <option value="">Tüm Zamansal</option>
      <option value="uyumlu_al">✅ Uyumlu Al</option>
      <option value="uyumlu_sat">✅ Uyumlu Sat</option>
      <option value="cakisiyor">⚠ Çakışıyor</option>
    </select>
    <button class="btn primary" onclick="yeniTara()">⟳ Yeni Tara</button>
    <span class="cnt-badge" id="cnt">–</span>
  </div>
  <div class="tbl-card">
    <table>
      <thead>
        <tr>
          <th>Hisse</th>
          <th>Fiyat</th>
          <th>Değ%</th>
          <th>Sinyal</th>
          <th>Puan</th>
          <th>Zamansal</th>
          <th>Haber</th>
          <th>Analist</th>
          <th>F/K</th>
          <th>Hacim</th>
          <th>Hedef-1</th>
          <th>Stop</th>
          <th>R/K</th>
          <th>RSI</th>
          <th>Vade</th><th title="F/K + PD/DD + Kar">Temel</th><th title="F/K + PD/DD + Kar Büyümesi">Temel</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="tablo-body">
        <tr><td colspan="16">
          <div class="empty-state">
            <div class="icon">📊</div>
            <div class="txt">Henüz tarama yapılmadı</div>
            <div class="sub">Yeni Tara butonuna bas veya bekle</div>
          </div>
        </td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ══ TOP-10 ══ -->
<div class="panel" id="panel-top10">
  <div class="cards-section">
    <div class="section-title">🟢 En İyi Al Sinyalleri</div>
    <div class="cards-grid" id="top-al">
      <div class="empty-state" style="padding:30px"><div class="txt">Veri bekleniyor</div></div>
    </div>
  </div>
  <div class="cards-section">
    <div class="section-title">🔴 Sat Sinyalleri</div>
    <div class="cards-grid" id="top-sat">
      <div class="empty-state" style="padding:30px"><div class="txt">Veri bekleniyor</div></div>
    </div>
  </div>
</div>

<!-- ══ PORTFÖY ══ -->
<div class="panel" id="panel-portfoy">
  <div class="pf-summary">
    <div class="pf-box">
      <div class="lbl">Toplam Yatırım</div>
      <div class="val" id="pf-yatirim">–</div>
    </div>
    <div class="pf-box">
      <div class="lbl">Anlık Değer</div>
      <div class="val" id="pf-deger">–</div>
    </div>
    <div class="pf-box">
      <div class="lbl">Açık K/Z</div>
      <div class="val" id="pf-kz">–</div>
    </div>
    <div class="pf-box">
      <div class="lbl">Getiri %</div>
      <div class="val" id="pf-yuzde">–</div>
    </div>
    <div class="pf-box" style="border-left:2px solid rgba(0,214,143,.3)">
      <div class="lbl">✅ Realize K/Z</div>
      <div class="val" id="pf-realize">–</div>
    </div>
    <div class="pf-box" style="border-left:2px solid rgba(249,199,79,.4);background:rgba(249,199,79,.04)">
      <div class="lbl">🏆 Net Toplam</div>
      <div class="val" id="pf-net" style="font-size:1.1rem">–</div>
    </div>
  </div>
  <div class="pf-form">
    <div>
      <label>Hisse Kodu</label>
      <input id="pf-sembol" placeholder="THYAO" oninput="this.value=this.value.toUpperCase()">
    </div>
    <div>
      <label>Adet</label>
      <input id="pf-adet" placeholder="100" type="number" min="1">
    </div>
    <div>
      <label>Alış Fiyatı (₺)</label>
      <input id="pf-fiyat" placeholder="142.30" type="number" step="0.01">
    </div>
    <div>
      <label>Not (opsiyonel)</label>
      <input id="pf-notlar" placeholder="Opsiyonel not..." style="width:160px">
    </div>
    <button class="btn primary" onclick="portfoyEkle()">+ Ekle</button>
  </div>
  <div class="tbl-card">
    <table>
      <thead><tr>
        <th>Hisse</th><th>Adet</th><th>Alış</th><th>Anlık</th>
        <th>K/Z</th><th>K/Z %</th><th>Tarih</th><th>Not</th><th></th>
      </tr></thead>
      <tbody id="pf-body"></tbody>
    </table>
  </div>
</div>

<!-- ══ ALARMLAR ══ -->
<div class="panel" id="panel-alarmlar">
  <div class="alm-form">
    <div>
      <label>Hisse</label>
      <input id="alm-sembol" placeholder="THYAO" oninput="this.value=this.value.toUpperCase()">
    </div>
    <div>
      <label>Yön</label>
      <select id="alm-tip"><option value="asagi">⬇ Düşünce</option><option value="yukari">⬆ Çıkınca</option></select>
    </div>
    <div>
      <label>Hedef Fiyat</label>
      <input id="alm-fiyat" placeholder="135.00" type="number" step="0.01">
    </div>
    <div>
      <label>Not</label>
      <input id="alm-not" placeholder="Opsiyonel..." style="width:160px">
    </div>
    <button class="btn primary" onclick="alarmEkle()">+ Alarm Ekle</button>
    <button class="btn" onclick="telTest()">📱 Telegram Test</button>
  </div>
  <div class="tbl-card">
    <table>
      <thead><tr>
        <th>Hisse</th><th>Yön</th><th>Hedef</th><th>Not</th><th>Oluşturuldu</th><th></th>
      </tr></thead>
      <tbody id="alm-body"></tbody>
    </table>
  </div>
</div>

<!-- ══ GEÇMİŞ ══ -->
<div class="panel" id="panel-gecmis">
  <div class="tbl-card">
    <table>
      <thead><tr>
        <th>Tarih</th><th>İşlem</th><th>Hisse</th><th>Adet</th><th>Fiyat</th><th>K/Z</th>
      </tr></thead>
      <tbody id="gcm-body"></tbody>
    </table>
  </div>
</div>

<!-- ══ BACKTEST ══ -->
<div class="panel" id="panel-backtest">
  <div class="bt-form">
    <div>
      <label>Hisse Kodu</label>
      <input id="bt-sembol" placeholder="THYAO" oninput="this.value=this.value.toUpperCase()">
    </div>
    <div>
      <label>Gün Sayısı</label>
      <input id="bt-gun" placeholder="120" type="number" value="120" min="30" max="500">
    </div>
    <button class="btn primary" onclick="backtestCalistir()">▶ Çalıştır</button>
    <span id="bt-yukl" style="font-size:.75rem;color:var(--muted);display:none">⟳ Hesaplanıyor...</span>
  </div>
  <div id="bt-sonuc"></div>
</div>

</div><!-- /content -->

<script>
let tumData = [];
let son_endeks = {};

// ── CLOCK ──
function saatGuncelle(){
  document.getElementById('h-saat').textContent =
    new Date().toLocaleTimeString('tr-TR',{hour12:false,timeZone:'Europe/Istanbul'});
}
setInterval(saatGuncelle,1000); saatGuncelle();

// ── NAV ──
function sekmeGec(id,el){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.nav-item').forEach(t=>t.classList.remove('on'));
  document.getElementById('panel-'+id).classList.add('on');
  el.classList.add('on');
  if(id==='portfoy')  portfoyYukle();
  if(id==='gecmis')   gecmisYukle();
  if(id==='alarmlar') alarmlarYukle();
  if(id==='top10')    top10Render();
}

// ── VERİ YÜKLEme ──
async function veriYukle(){
  try{
    const r = await fetch('/api/data');
    const d = await r.json();
    tumData = Array.isArray(d.data)?d.data:[];

    document.getElementById('h-adet').textContent = tumData.length;
    document.getElementById('h-gal').textContent  = tumData.filter(x=>x.karar_kod==='guclu_al').length;
    document.getElementById('h-al').textContent   = tumData.filter(x=>['al','guclu_al'].includes(x.karar_kod)).length;
    document.getElementById('h-sat').textContent  = tumData.filter(x=>['sat','guclu_sat'].includes(x.karar_kod)).length;

    // Tarama badge
    const sb = document.getElementById('scan-badge');
    sb.style.display = d.yukleniyor?'block':'none';

    // Endeks
    son_endeks = d.endeks||{};
    const edeg = son_endeks.degisim||0;
    const ee = document.getElementById('hdr-endeks');
    if(son_endeks.fiyat){
      const sign = edeg>=0?'+':'';
      ee.textContent = `BIST-100  ${son_endeks.fiyat}  ${sign}${edeg}%`;
      ee.style.color = edeg<=-1?'var(--red)':edeg>=0.5?'var(--green)':'var(--muted)';
    }
    const banner = document.getElementById('endeks-banner');
    if(son_endeks.uyari){
      banner.textContent = `⚠ BIST-100 bugün ${edeg}% — Al sinyalleri otomatik zayıflatıldı`;
      banner.style.display='block';
    } else banner.style.display='none';

    // Seans uyarı banner
    const sb = document.getElementById('seans-banner');
    if(d.seans&&d.seans.durum==='volatil'&&sb){
      sb.textContent = d.seans.mesaj || '';
      sb.style.display='block';
    } else if(sb) sb.style.display='none';

    // Makro risk banner
    const mk = d.makro||{};
    const mb = document.getElementById('makro-banner');
    if(mk.risk_seviye && mk.risk_seviye !== 'NORMAL' && mb){
      document.getElementById('makro-ozet').textContent = mk.ozet||'';
      document.getElementById('makro-riskler').textContent =
        (mk.riskler||[]).slice(0,3).join('  |  ');
      mb.style.display = 'block';
      mb.style.borderColor = mk.risk_seviye==='YUKSEK'
        ? 'rgba(255,77,109,.4)' : 'rgba(249,199,79,.25)';
    } else if(mb) mb.style.display='none';

    filtrele();
  } catch(e){ console.error(e) }
}

// ── MARKET ──
function filtrele(){
  const ara    = (document.getElementById('ara').value||'').toUpperCase();
  const sinyal = document.getElementById('sinyal-filtre').value;
  const uyum   = document.getElementById('uyum-filtre').value;
  const sirala = document.getElementById('siralama').value;

  let f = tumData.filter(d=>{
    const s = d.sembol.replace('.IS','');
    if(ara    && !s.includes(ara))    return false;
    if(sinyal && d.karar_kod!==sinyal) return false;
    if(uyum   && d.uyum_kodu!==uyum) return false;
    return true;
  });
  if(sirala==='puan')    f.sort((a,b)=>{
    const aG=a.endeks_guc&&a.endeks_guc.endeksten_guclu?1:0;
    const bG=b.endeks_guc&&b.endeks_guc.endeksten_guclu?1:0;
    if(bG!==aG) return bG-aG;
    return b.toplam_puan-a.toplam_puan;
  });
  if(sirala==='degisim') f.sort((a,b)=>b.degisim-a.degisim);
  if(sirala==='rsi')     f.sort((a,b)=>a.rsi-b.rsi);
  if(sirala==='hacim')   f.sort((a,b)=>b.vol_oran-a.vol_oran);

  document.getElementById('cnt').textContent = `${f.length} hisse`;
  tabloRender(f);
}

function tabloRender(veri){
  if(!veri.length){
    document.getElementById('tablo-body').innerHTML =
      '<tr><td colspan="16"><div class="empty-state"><div class="icon">🔍</div><div class="txt">Sonuç yok</div></div></td></tr>';
    return;
  }

  const rows = veri.map(d=>{
    const sym  = d.sembol.replace('.IS','');
    const dCls = d.degisim>=0?'pos':'neg';
    const pCls = d.toplam_puan>0?'pos':d.toplam_puan<0?'neg':'neu';
    const ah   = d.araci_hedef;
    const te   = d.temel;
    // RSI bar
    const rsiPct = Math.min(100,Math.max(0,d.rsi));
    const rsiClr = d.rsi>70?'var(--red)':d.rsi<30?'var(--green)':'var(--amber)';
    // Volume pips (3 pips, fill based on vol_oran)
    const pips = [1,2,3].map(i=>`<div class="vol-pip ${d.vol_oran>=i?'on':''}"></div>`).join('');

    return `<tr class="sig-${d.karar_kod}" onclick="haberDetay('${d.sembol}')">
      <td title="${d.gap&&d.gap.aciklama?d.gap.aciklama:''} ${d.sektor&&d.sektor.etiket?'| '+d.sektor.etiket:''}">
        <div class="sym-cell">
          <span class="sym">${sym}</span>
          ${d.gap&&d.gap.mum?`<span style="font-size:.58rem;color:var(--amber)">${d.gap.mum}</span>`:''}
        </div></td>
      <td><span class="price-cell">${d.fiyat.toFixed(2)}<span style="font-size:.65rem;color:var(--muted)">₺</span></span></td>
      <td><span class="${dCls}" style="font-weight:600">${d.degisim>=0?'+':''}${d.degisim}%</span>
        ${d.endeks_guc&&d.endeks_guc.endeksten_guclu?`<div style="font-size:.55rem;color:var(--green);margin-top:1px">📈 Endeksten Güçlü</div>`:''}
        ${d.endeks_guc&&d.endeks_guc.puan<=-1?`<div style="font-size:.55rem;color:var(--muted);margin-top:1px">↘ Endeks Gerisinde</div>`:''}
      </td>
      <td><span class="sig ${d.karar_kod==='piyasa_riskli'?'guclu_sat':d.karar_kod}">${d.karar}</span>
        ${d.endeks_baskisi?`<div style="font-size:.58rem;color:var(--red);margin-top:2px">▼ Endeks</div>`:''}
        ${d.ma_trend==='alti'?`<div style="font-size:.58rem;color:var(--muted);margin-top:1px">MA200↓</div>`:''}
        ${d.riskli_haber?`<div style="font-size:.55rem;color:var(--red);margin-top:2px;font-weight:600">⛔ RİSKLİ HABER</div>`:''}
        ${d.sikisma&&d.sikisma.sikisma&&d.sikisma.puan>=2?`<div style="font-size:.55rem;color:#f9c74f;margin-top:1px">⏳ ZAMANSALLIK</div>`:''}
        ${d.st_yon===1?`<div style="font-size:.55rem;color:var(--green);margin-top:1px">ST 🟢</div>`:d.st_yon===-1?`<div style="font-size:.55rem;color:var(--red);margin-top:1px">ST 🔴</div>`:''}
        ${d.seans_uyari?`<div style="font-size:.55rem;color:var(--amber);margin-top:1px">⚡Volatil Seans</div>`:''}
      </td>
      <td><span class="${pCls}" style="font-family:var(--fm);font-weight:700">${d.toplam_puan>0?'+':''}${d.toplam_puan}</span></td>
      <td style="font-size:.72rem;color:var(--muted)">${d.uyum||'–'}</td>
      <td style="cursor:pointer" onclick="event.stopPropagation();haberDetay('${d.sembol}')">
        <span class="${(d.haber_skoru||0)>=1?'pos':(d.haber_skoru||0)<=-1?'neg':'neu'}"
              style="font-size:.72rem">${d.haber_etiketi||'–'}</span>
      </td>
      <td style="font-size:.72rem">
        ${ah&&ah.hedef_fiyat
          ?`<span style="color:var(--amber);font-weight:600">${ah.hedef_fiyat}₺</span>
            <div style="font-size:.6rem;color:var(--muted)">${ah.tavsiye||''}</div>`
          :`<span style="color:var(--dim)">–</span>`}
      </td>
      <td style="font-size:.75rem">
        ${te&&te.pe!=null
          ?`<span style="color:${te.pe>30?'var(--red)':te.pe<8?'var(--green)':'var(--text)'}">${te.pe}x</span>`
          :`<span style="color:var(--dim)">–</span>`}
      </td>
      <td><div class="vol-wrap">${pips}<span style="font-family:var(--fm)">${d.vol_oran}x</span></div></td>
      <td><span class="pos" style="font-family:var(--fm)">${d.hedef_1.toFixed(2)}₺</span></td>
      <td><span class="neg" style="font-family:var(--fm)">${d.stop_loss.toFixed(2)}₺</span></td>
      <td><span style="color:var(--amber);font-family:var(--fm)">${d.risk_getiri||0}</span></td>
      <td>
        <div class="rsi-wrap">
          <span style="font-family:var(--fm);font-size:.75rem;color:${rsiClr};min-width:28px">${d.rsi}</span>
          <div class="rsi-bar"><div class="rsi-fill" style="width:${rsiPct}%;background:${rsiClr}"></div></div>
        </div>
      </td>
      <td style="font-size:.68rem;color:var(--muted)">${d.vade_gun||'–'}</td>
      <td style="text-align:center">
        ${d.gunun_firsati?`<span title="Teknik + Temel 3/3 ✅" style="
          background:linear-gradient(135deg,#f9c74f,#f8961e);color:#0b0e17;
          font-size:.6rem;font-weight:700;padding:3px 7px;border-radius:20px;
          display:inline-block">🏆</span>`:`
        <span style="font-size:.72rem;color:${
          (d.temel_skor||0)>=3?'#f9c74f':
          (d.temel_skor||0)>=2?'var(--green)':
          (d.temel_skor||0)>=1?'var(--text)':'var(--muted)'
        };font-weight:600">${d.temel_skor!==undefined?d.temel_skor+'/3':'—'}</span>
        ${d.kar_durumu==='zarar'?`<div style="font-size:.55rem;color:var(--red)">ZARAR🚨</div>`:''}
        ${d.temel&&d.temel.pe?`<div style="font-size:.55rem;color:var(--muted)">F/K ${d.temel.pe}</div>`:''}
        `}
      </td>
      <td><button class="btn sm" onclick="event.stopPropagation();portfoyEkleModal('${d.sembol}',${d.fiyat})"
          title="Portföye ekle">+</button></td>
    </tr>`;
  });
  document.getElementById('tablo-body').innerHTML = rows.join('');
}

// ── TOP-10 ──
function top10Render(){
  const allar  = [...tumData].filter(d=>['guclu_al','al'].includes(d.karar_kod))
                              .sort((a,b)=>b.toplam_puan-a.toplam_puan).slice(0,10);
  const satlar = [...tumData].filter(d=>['guclu_sat','sat'].includes(d.karar_kod))
                              .sort((a,b)=>a.toplam_puan-b.toplam_puan).slice(0,10);

  function kart(d,tip){
    const sym=d.sembol.replace('.IS','');
    const chg=d.degisim>=0?'pos':'neg';
    return `<div class="stk-card ${tip}-card" onclick="haberDetay('${d.sembol}')">
      <div class="stk-card-top">
        <div>
          <div class="stk-sym" style="color:var(--text)">${sym}</div>
          <div style="font-size:.62rem;color:var(--muted);margin-top:2px">${d.vade_gun||'–'}</div>
        </div>
        <span class="sig ${d.karar_kod}">${d.karar}</span>
      </div>
      <div class="stk-price">${d.fiyat.toFixed(2)}<span style="font-size:.72rem;color:var(--muted)">₺</span>
        <span class="${chg}" style="font-size:.72rem;font-weight:600;margin-left:6px">${d.degisim>=0?'+':''}${d.degisim}%</span>
      </div>
      <div style="height:1px;background:var(--border);margin:8px 0"></div>
      <div class="stk-row"><span class="k">Puan</span>
        <span class="v ${d.toplam_puan>0?'pos':'neg'}">${d.toplam_puan>0?'+':''}${d.toplam_puan}</span></div>
      <div class="stk-row"><span class="k">RSI</span>
        <span class="v" style="color:${d.rsi>70?'var(--red)':d.rsi<30?'var(--green)':'var(--text)'}">${d.rsi}</span></div>
      <div class="stk-row"><span class="k">Hedef-1</span>
        <span class="v pos">${d.hedef_1.toFixed(2)}₺</span></div>
      <div class="stk-row"><span class="k">Stop</span>
        <span class="v neg">${d.stop_loss.toFixed(2)}₺</span></div>
      <div class="stk-row"><span class="k">R/K</span>
        <span class="v" style="color:var(--amber)">${d.risk_getiri}</span></div>
      ${d.haber_etiketi?`<div class="stk-row"><span class="k"></span>
        <span style="font-size:.62rem;color:var(--muted)">${d.haber_etiketi}</span></div>`:''}
    </div>`;
  }

  const emptyAl  = '<div class="empty-state" style="padding:30px;grid-column:1/-1"><div class="icon">📭</div><div class="txt">Al sinyali yok</div></div>';
  const emptySat = '<div class="empty-state" style="padding:30px;grid-column:1/-1"><div class="icon">📭</div><div class="txt">Sat sinyali yok</div></div>';
  document.getElementById('top-al').innerHTML  = allar.map(d=>kart(d,'al')).join('')  || emptyAl;
  document.getElementById('top-sat').innerHTML = satlar.map(d=>kart(d,'sat')).join('') || emptySat;
}

// ── PORTFÖY ──
async function portfoyYukle(){
  const [r1, r2] = await Promise.all([
    fetch('/api/portfoy'),
    fetch('/api/gecmis'),
  ]);
  const d1 = await r1.json();
  const d2 = await r2.json();
  const pozlar  = d1.pozlar||[];
  const islemler = d2.islemler||[];

  // Realize edilmiş K/Z toplamı (sadece SATIS işlemleri)
  const realizeKZ = islemler
    .filter(i=>i.islem_tipi==='SATIS')
    .reduce((acc,i)=>acc+(i.kar_zarar||0), 0);

  let topYat=0, topDeg=0, openKZ=0;

  const rows = pozlar.map(p=>{
    const guncel = (tumData.find(x=>x.sembol===p.sembol)?.fiyat)||p.alis_fiyat;
    const kz  = round2((guncel-p.alis_fiyat)*p.adet);
    const yuz = round2((guncel-p.alis_fiyat)/p.alis_fiyat*100);
    topYat += p.alis_fiyat*p.adet;
    topDeg += guncel*p.adet;
    openKZ += kz;
    const sl  = p.stop_loss || 0;
    const h1  = p.hedef_1   || 0;
    const slStr = sl>0?`<div style="font-size:.6rem;color:var(--muted);margin-top:1px">Stop: ${sl.toFixed(2)}₺</div>`:'';
    const h1Str = h1>0?`<div style="font-size:.6rem;color:var(--green);margin-top:1px">H1: ${h1.toFixed(2)}₺</div>`:'';
    return `<tr>
      <td>
        <span style="font-family:var(--fm);font-weight:600">${p.sembol.replace('.IS','')}</span>
        ${slStr}${h1Str}
      </td>
      <td>${p.adet}</td>
      <td style="font-family:var(--fm)">${p.alis_fiyat.toFixed(2)}₺</td>
      <td style="font-family:var(--fm)">${guncel.toFixed(2)}₺</td>
      <td class="${kz>=0?'pos':'neg'}" style="font-family:var(--fm);font-weight:600">${kz>=0?'+':''}${kz.toFixed(2)}₺</td>
      <td class="${yuz>=0?'pos':'neg'}" style="font-weight:600">${yuz>=0?'+':''}${yuz.toFixed(1)}%</td>
      <td style="font-size:.7rem;color:var(--muted)">${p.alis_tarihi}</td>
      <td style="font-size:.7rem;color:var(--muted)">${p.notlar||''}</td>
      <td><button class="btn sm danger" onclick="portfoySat(${p.id})">Sat</button></td>
    </tr>`;
  });

  document.getElementById('pf-body').innerHTML = rows.length?rows.join(''):
    '<tr><td colspan="9"><div class="empty-state" style="padding:30px"><div class="icon">💼</div><div class="txt">Portföyde hisse yok</div></div></td></tr>';

  const netKZ  = openKZ + realizeKZ;
  const topYuz = topYat>0?round2(openKZ/topYat*100):0;

  // Özet kutular
  document.getElementById('pf-yatirim').textContent = topYat.toFixed(2)+'₺';
  document.getElementById('pf-deger').textContent   = topDeg.toFixed(2)+'₺';

  const kzEl = document.getElementById('pf-kz');
  kzEl.textContent = (openKZ>=0?'+':'')+openKZ.toFixed(2)+'₺';
  kzEl.className   = 'val '+(openKZ>=0?'pos':'neg');

  const yzEl = document.getElementById('pf-yuzde');
  yzEl.textContent = (topYuz>=0?'+':'')+topYuz.toFixed(1)+'%';
  yzEl.className   = 'val '+(topYuz>=0?'pos':'neg');

  // Realize + Net kutuları güncelle (varsa)
  const rkzEl = document.getElementById('pf-realize');
  if(rkzEl){
    rkzEl.textContent = (realizeKZ>=0?'+':'')+realizeKZ.toFixed(2)+'₺';
    rkzEl.className   = 'val '+(realizeKZ>=0?'pos':'neg');
  }
  const netEl = document.getElementById('pf-net');
  if(netEl){
    netEl.textContent = (netKZ>=0?'+':'')+netKZ.toFixed(2)+'₺';
    netEl.className   = 'val '+(netKZ>=0?'pos':'neg');
  }
}

function portfoyEkleModal(sembol,fiyat){
  document.getElementById('pf-sembol').value = sembol.replace('.IS','');
  document.getElementById('pf-fiyat').value  = fiyat.toFixed(2);
  document.getElementById('pf-adet').value   = '';
  sekmeGec('portfoy',document.querySelectorAll('.nav-item')[2]);
  document.getElementById('pf-sembol').focus();
}

async function portfoyEkle(){
  const sembol = document.getElementById('pf-sembol').value.trim().toUpperCase();
  const adet   = parseFloat(document.getElementById('pf-adet').value);
  const fiyat  = parseFloat(document.getElementById('pf-fiyat').value);
  const notlar = document.getElementById('pf-notlar').value.trim();
  if(!sembol||isNaN(adet)||adet<=0||isNaN(fiyat)||fiyat<=0){alert('Sembol, adet ve fiyat girilmeli!');return;}
  const r = await fetch('/api/portfoy/al',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({sembol,adet,fiyat,notlar})});
  const d = await r.json();
  if(d.ok){['pf-sembol','pf-adet','pf-fiyat','pf-notlar'].forEach(id=>document.getElementById(id).value='');portfoyYukle();}
  else alert('Hata: '+(d.hata||'?'));
}

async function portfoySat(id){
  const fiyat = parseFloat(prompt('Satış fiyatı (₺)?'));
  if(!fiyat||fiyat<=0)return;
  const r = await fetch('/api/portfoy/sat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id,fiyat})});
  const d = await r.json();
  if(d.ok){alert(`İşlem tamam! K/Z: ${d.kar_zarar>=0?'+':''}${d.kar_zarar.toFixed(2)}₺`);portfoyYukle();gecmisYukle();}
  else alert('Hata: '+(d.hata||'?'));
}

// ── GEÇMİŞ ──
async function gecmisYukle(){
  const r = await fetch('/api/gecmis');
  const d = await r.json();
  const rows = (d.islemler||[]).map(i=>`<tr>
    <td style="font-size:.7rem;color:var(--muted)">${i.tarih||''}</td>
    <td><span class="his-badge ${i.islem_tipi==='ALIS'?'alis':'satis'}">${i.islem_tipi}</span></td>
    <td><span style="font-family:var(--fm);font-weight:600">${(i.sembol||'').replace('.IS','')}</span></td>
    <td>${i.adet}</td>
    <td style="font-family:var(--fm)">${(i.fiyat||0).toFixed(2)}₺</td>
    <td class="${(i.kar_zarar||0)>=0?'pos':'neg'}" style="font-family:var(--fm);font-weight:600">
      ${(i.kar_zarar||0)>=0?'+':''}${(i.kar_zarar||0).toFixed(2)}₺</td>
  </tr>`);
  document.getElementById('gcm-body').innerHTML = rows.length?rows.join(''):
    '<tr><td colspan="6"><div class="empty-state" style="padding:30px"><div class="icon">📋</div><div class="txt">İşlem geçmişi yok</div></div></td></tr>';
}

// ── ALARMLAR ──
async function alarmlarYukle(){
  const r = await fetch('/api/alarmlar');
  const d = await r.json();
  const rows = (d.alarmlar||[]).map(a=>`<tr>
    <td><span style="font-family:var(--fm);font-weight:600">${(a.sembol||'').replace('.IS','')}</span></td>
    <td style="color:${a.tip==='asagi'?'var(--red)':'var(--green)'}">${a.tip==='asagi'?'⬇ Düşünce':'⬆ Çıkınca'}</td>
    <td style="font-family:var(--fm);font-weight:600">${(a.hedef_fiyat||0).toFixed(2)}₺</td>
    <td style="font-size:.72rem;color:var(--muted)">${a.not_||'–'}</td>
    <td style="font-size:.7rem;color:var(--muted)">${a.olusturuldu||''}</td>
    <td><button class="btn sm danger" onclick="alarmSil(${a.id})">Sil</button></td>
  </tr>`);
  document.getElementById('alm-body').innerHTML = rows.length?rows.join(''):
    '<tr><td colspan="6"><div class="empty-state" style="padding:30px"><div class="icon">🔔</div><div class="txt">Aktif alarm yok</div></div></td></tr>';
}

async function alarmEkle(){
  const sembol = document.getElementById('alm-sembol').value.trim().toUpperCase();
  const tip    = document.getElementById('alm-tip').value;
  const fiyat  = parseFloat(document.getElementById('alm-fiyat').value);
  const not_   = document.getElementById('alm-not').value.trim();
  if(!sembol||isNaN(fiyat)||fiyat<=0){alert('Sembol ve fiyat girilmeli!');return;}
  const r = await fetch('/api/alarmlar/ekle',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({sembol,tip,fiyat,not_})});
  const d = await r.json();
  if(d.ok){['alm-sembol','alm-fiyat','alm-not'].forEach(id=>document.getElementById(id).value='');alarmlarYukle();}
  else alert('Hata: '+(d.hata||'?'));
}

async function alarmSil(id){
  await fetch('/api/alarmlar/sil',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  alarmlarYukle();
}

async function telTest(){
  const r = await fetch('/api/telegram/test');
  const d = await r.json();
  alert(d.mesaj||'Sonuç bilinmiyor');
}

// ── BACKTEST ──
async function backtestCalistir(){
  const sembol = document.getElementById('bt-sembol').value.trim().toUpperCase();
  const gun    = parseInt(document.getElementById('bt-gun').value)||120;
  if(!sembol){alert('Hisse kodu girilmeli!');return;}
  document.getElementById('bt-yukl').style.display='inline';
  document.getElementById('bt-sonuc').innerHTML='';
  try{
    const r = await fetch(`/api/backtest?sembol=${sembol}&gun=${gun}`);
    const d = await r.json();
    document.getElementById('bt-yukl').style.display='none';
    if(!d.ok||d.hata){
      document.getElementById('bt-sonuc').innerHTML=
        `<div class="empty-state"><div class="icon">⚠️</div><div class="txt">${d.hata||'Veri yok'}</div></div>`;
      return;
    }
    const s   = d.sonuc;
    const al  = s.al  || {};
    const sat = s.sat || {};
    const g   = s.gun || gun;

    // Başarı oranı rengi
    const alRenk  = (al.basari||0)  >= 55 ? 'var(--green)' : (al.basari||0)  >= 40 ? 'var(--amber)' : 'var(--red)';
    const satRenk = (sat.basari||0) >= 55 ? 'var(--green)' : (sat.basari||0) >= 40 ? 'var(--amber)' : 'var(--red)';

    // Yorum
    let yorum = '';
    if((al.basari||0) >= 60 && (al.ort||0) > 0){
      yorum = `<div style="background:rgba(0,214,143,.07);border:1px solid rgba(0,214,143,.2);border-radius:8px;padding:10px 14px;font-size:.75rem;color:var(--green)">
        ✅ <b>${sembol}</b> için AL sinyalleri son ${g} günde <b>%${al.basari} başarı</b> ve <b>${al.ort>0?'+':''}${al.ort}% ort. getiri</b> sağladı. Tarihsel performans güçlü.</div>`;
    } else if((al.basari||0) < 40){
      yorum = `<div style="background:rgba(255,77,109,.07);border:1px solid rgba(255,77,109,.2);border-radius:8px;padding:10px 14px;font-size:.75rem;color:var(--red)">
        ⚠ AL sinyalleri son ${g} günde zayıf performans (%${al.basari} başarı). Sinyale girmeden önce derinlik teyidi al.</div>`;
    } else {
      yorum = `<div style="background:rgba(249,199,79,.06);border:1px solid rgba(249,199,79,.2);border-radius:8px;padding:10px 14px;font-size:.75rem;color:var(--amber)">
        ⏸ Sinyal performansı orta düzeyde (%${al.basari||0} başarı). Sadece Güçlü AL + Zamansallık üçlüsünde gir.</div>`;
    }

    document.getElementById('bt-sonuc').innerHTML=`
      <div style="margin-bottom:12px;font-size:.72rem;color:var(--muted)">
        📅 Son <b style="color:var(--text)">${g} gün</b> analiz edildi — 5 günlük hedef bazlı test</div>
      ${yorum}
      <div class="bt-result">
        <div class="bt-box">
          <div class="bt-title">🟢 AL Sinyalleri</div>
          <div class="bt-row"><span class="k">Toplam Sinyal</span><span class="v">${al.n||0}</span></div>
          <div class="bt-row"><span class="k">Başarı Oranı</span>
            <span class="v" style="color:${alRenk};font-size:1.05rem;font-weight:700">%${al.basari||0}</span></div>
          <div class="bt-row"><span class="k">Ort. Getiri</span>
            <span class="v ${(al.ort||0)>=0?'pos':'neg'}">${(al.ort||0)>=0?'+':''}${al.ort||0}%</span></div>
          <div class="bt-row"><span class="k">En İyi</span>
            <span class="v pos">+${al.max||0}%</span></div>
          <div class="bt-row"><span class="k">En Kötü</span>
            <span class="v neg">${al.min||0}%</span></div>
        </div>
        <div class="bt-box">
          <div class="bt-title">🔴 SAT Sinyalleri</div>
          <div class="bt-row"><span class="k">Toplam Sinyal</span><span class="v">${sat.n||0}</span></div>
          <div class="bt-row"><span class="k">Başarı Oranı</span>
            <span class="v" style="color:${satRenk};font-size:1.05rem;font-weight:700">%${sat.basari||0}</span></div>
          <div class="bt-row"><span class="k">Ort. Getiri</span>
            <span class="v ${(sat.ort||0)>=0?'pos':'neg'}">${(sat.ort||0)>=0?'+':''}${sat.ort||0}%</span></div>
          <div class="bt-row"><span class="k">En İyi</span>
            <span class="v pos">+${sat.max||0}%</span></div>
          <div class="bt-row"><span class="k">En Kötü</span>
            <span class="v neg">${sat.min||0}%</span></div>
        </div>
      </div>
      <div style="margin-top:10px;padding:10px 14px;background:var(--bg2);border-radius:8px;
        font-size:.68rem;color:var(--muted);line-height:1.7">
        ⚠ <b>Uyarı:</b> Geçmiş performans gelecek garantisi değildir.
        Backtestte işlem maliyeti (komisyon, spread) dahil değildir.
        Gerçek işlemlerde her sinyali derinlik+SuperTrend+Zamansallık üçlüsüyle teyit et.
      </div>`;
  }catch(e){
    document.getElementById('bt-yukl').style.display='none';
    document.getElementById('bt-sonuc').innerHTML=
      `<div class="empty-state"><div class="icon">❌</div><div class="txt">Backtest hatası: ${e}</div></div>`;
  }
}

// ── HABER MODAL ──
function haberDetay(sembol){
  const d = tumData.find(x=>x.sembol===sembol);
  if(!d)return;
  const haberler = d.haberler||[];
  const ah = d.araci_hedef;

  const haberHTML = haberler.length
    ? haberler.map(h=>`
        <div style="padding:10px 0;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:4px">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:.65rem;color:var(--amber);font-weight:500">${h.kaynak||''}</span>
            ${h.tarih?`<span style="font-size:.62rem;color:var(--muted)">${h.tarih}</span>`:''}
            ${h.skor&&h.skor!==0?`<span style="font-size:.62rem;color:${h.skor>0?'var(--green)':'var(--red)'}">
              ${h.skor>0?'↑':'↓'} ${h.neden||''}</span>`:''}
          </div>
          <div style="font-size:.78rem;line-height:1.5">
            ${h.link?`<a href="${h.link}" target="_blank"
              style="color:var(--text);text-decoration:none;transition:.1s"
              onmouseover="this.style.color='var(--green)'" onmouseout="this.style.color='var(--text)'">${h.baslik}</a>`:h.baslik}
          </div>
        </div>`).join('')
    : '<div class="empty-state" style="padding:20px"><div class="txt">Haber bulunamadı</div></div>';

  const ahHTML = ah&&ah.hedef_fiyat?`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:14px">
      <div style="font-size:.62rem;font-weight:600;letter-spacing:.8px;color:var(--muted);text-transform:uppercase;margin-bottom:10px">Analist Tavsiyesi</div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end">
        <div><div style="font-size:.62rem;color:var(--muted);margin-bottom:2px">Hedef Fiyat</div>
             <b style="font-family:var(--fm);color:var(--amber);font-size:1.1rem">${ah.hedef_fiyat}₺</b></div>
        ${ah.dusuk_hedef?`<div><div style="font-size:.62rem;color:var(--muted)">Alt Hedef</div><span style="font-family:var(--fm)">${ah.dusuk_hedef}₺</span></div>`:''}
        ${ah.yuksek_hedef?`<div><div style="font-size:.62rem;color:var(--muted)">Üst Hedef</div><span style="font-family:var(--fm)">${ah.yuksek_hedef}₺</span></div>`:''}
        <div><div style="font-size:.62rem;color:var(--muted)">Tavsiye</div><b>${ah.tavsiye||'–'}</b></div>
        ${ah.analist_sayisi?`<div><div style="font-size:.62rem;color:var(--muted)">Analist Sayısı</div><span>${ah.analist_sayisi}</span></div>`:''}
      </div>
    </div>`:'' ;

  const te = d.temel||{};
  const teHTML = (te.pe||te.pb)?`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:14px;display:flex;gap:16px;flex-wrap:wrap">
      ${te.pe?`<div><div style="font-size:.62rem;color:var(--muted);margin-bottom:2px">F/K</div>
               <b style="font-family:var(--fm);color:${te.pe>30?'var(--red)':te.pe<8?'var(--green)':'var(--text)'}">${te.pe}x</b></div>`:''}
      ${te.pb?`<div><div style="font-size:.62rem;color:var(--muted);margin-bottom:2px">PD/DD</div>
               <b style="font-family:var(--fm);color:${te.pb>5?'var(--red)':te.pb<1?'var(--green)':'var(--text)'}">${te.pb}x</b></div>`:''}
      ${te.eps?`<div><div style="font-size:.62rem;color:var(--muted);margin-bottom:2px">HBK</div>
               <span style="font-family:var(--fm)">${te.eps}₺</span></div>`:''}
    </div>`:'';

  // Neden ozeti
  const nedenHTML = d.neden_ozeti&&d.neden_ozeti!=='Belirgin bir haber yok'?`
    <div style="background:rgba(0,214,143,.05);border:1px solid rgba(0,214,143,.15);
                border-radius:10px;padding:10px 14px;margin-bottom:14px">
      <div style="font-size:.62rem;font-weight:600;color:var(--green);margin-bottom:6px">📰 Haber Neden?</div>
      <div style="font-size:.74rem;color:var(--text);line-height:1.6;white-space:pre-line">${d.neden_ozeti}</div>
    </div>`:'';

  let modal = document.getElementById('haber-modal');
  if(!modal){
    modal = document.createElement('div');
    modal.id='haber-modal';
    modal.className='modal-overlay';
    modal.onclick=e=>{if(e.target===modal)modal.remove()};
    document.body.appendChild(modal);
  }
  const sym = sembol.replace('.IS','');
  modal.innerHTML=`
    <div class="modal-box">
      <div class="modal-head">
        <div style="display:flex;align-items:center;gap:12px">
          <span style="font-family:var(--fm);font-size:1rem;font-weight:700">${sym}</span>
          <span style="font-family:var(--fm);font-size:.85rem;color:var(--muted)">${d.fiyat.toFixed(2)}₺</span>
          <span class="${d.degisim>=0?'pos':'neg'}" style="font-size:.8rem;font-weight:600">${d.degisim>=0?'+':''}${d.degisim}%</span>
        </div>
        <button class="modal-close" onclick="document.getElementById('haber-modal').remove()">✕ Kapat</button>
      </div>
      <div style="padding:16px 20px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
          <span class="sig ${d.karar_kod}">${d.karar}</span>
          <span style="font-size:.72rem;color:var(--muted)">Teknik <b style="color:${d.g_puan>0?'var(--green)':'var(--red)'}">${d.g_puan>0?'+':''}${d.g_puan}</b></span>
          <span style="font-size:.72rem;color:var(--muted)">Haber <b style="color:${(d.haber_skoru||0)>0?'var(--green)':(d.haber_skoru||0)<0?'var(--red)':'var(--muted)'}">${(d.haber_skoru||0)>0?'+':''}${d.haber_skoru||0}</b></span>
          <span style="font-size:.72rem;color:var(--amber)">Birleşik <b>${d.toplam_puan>0?'+':''}${d.toplam_puan}</b></span>
          ${d.ai_ozet&&d.ai_ozet!=='keyword'?`<div style="font-size:.7rem;color:var(--muted);width:100%;margin-top:4px">🤖 ${d.ai_ozet}</div>`:''}
          ${d.gap&&d.gap.aciklama&&d.gap.aciklama!=='Normal seans'?`<div style="font-size:.7rem;color:var(--blue);width:100%;margin-top:2px">📊 ${d.gap.aciklama}</div>`:''}
          ${d.sektor&&d.sektor.etiket?`<div style="font-size:.7rem;color:${d.sektor.puan>0?'var(--green)':'var(--red)'};width:100%;margin-top:2px">🏭 ${d.sektor.sektor}: ${d.sektor.etiket} (${d.sektor.fark>0?'+':''}${d.sektor.fark}%)</div>`:''}
          ${d.ma200_uyari?`<div style="font-size:.7rem;color:var(--muted);width:100%;margin-top:2px">${d.ma200_uyari}</div>`:''}
          ${(d.temel&&(d.temel.pe||d.temel.pb||d.temel_skor))?`
            <div style="width:100%;margin-top:8px;padding:10px 12px;border-radius:8px;
              background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08)">
              <div style="font-size:.68rem;font-weight:600;color:var(--amber);margin-bottom:6px">
                📊 TEMEL ANALİZ SKORU: ${d.temel_skor||0}/3
                ${d.gunun_firsati?'🏆 GÜNÜN FIRSATI!':''}
              </div>
              <div style="display:flex;gap:16px;flex-wrap:wrap">
                <div style="font-size:.68rem">
                  <span style="color:var(--muted)">F/K: </span>
                  <span style="color:${!d.temel.pe?'var(--muted)':d.temel.pe<12?'var(--green)':d.temel.pe>30?'var(--red)':'var(--text)'}">
                    ${d.temel.pe||'—'}
                  </span>
                </div>
                <div style="font-size:.68rem">
                  <span style="color:var(--muted)">PD/DD: </span>
                  <span style="color:${!d.temel.pb?'var(--muted)':d.temel.pb<1.5?'var(--green)':d.temel.pb>5?'var(--red)':'var(--text)'}">
                    ${d.temel.pb||'—'}
                  </span>
                </div>
                <div style="font-size:.68rem">
                  <span style="color:var(--muted)">Kar: </span>
                  <span style="color:${d.kar_durumu==='artiyor'?'var(--green)':d.kar_durumu==='zarar'?'var(--red)':'var(--muted)'}">
                    ${d.kar_durumu==='artiyor'?'Büyüyor ✅':d.kar_durumu==='zarar'?'ZARARDA 🚨':d.kar_durumu==='azaliyor'?'Azalıyor ⚠':d.kar_durumu||'—'}
                    ${d.temel.net_kar_buyume!==null&&d.temel.net_kar_buyume!==undefined?'('+d.temel.net_kar_buyume+'%)':''}
                  </span>
                </div>
                <div style="font-size:.68rem">
                  <span style="color:var(--muted)">Tip: </span>
                  <span style="color:var(--text)">${d.hisse_tipi==='kucuk'?'Küçük 📌':d.hisse_tipi==='orta'?'Orta':'Büyük'}</span>
                </div>
                ${d.temel&&d.temel.borc_oz_orani!==null&&d.temel.borc_oz_orani!==undefined?`
                <div style="font-size:.68rem">
                  <span style="color:var(--muted)">D/E: </span>
                  <span style="color:${d.temel.borc_oz_orani>200?'var(--red)':d.temel.borc_oz_orani<30?'var(--green)':'var(--text)'}">
                    %${d.temel.borc_oz_orani}
                  </span>
                </div>`:''}
                ${d.temel&&d.temel.nakit_m!==null&&d.temel.nakit_m!==undefined?`
                <div style="font-size:.68rem">
                  <span style="color:var(--muted)">Nakit: </span>
                  <span style="color:${d.temel.nakit_m>0?'var(--green)':'var(--red)'}">
                    ${d.temel.nakit_m>0?'+':''}${d.temel.nakit_m}M$
                  </span>
                </div>`:''}
              </div>
              ${(d.temel.uyarilar||[]).filter(u=>u.includes('🚨')||u.includes('DİKKAT')).map(u=>`
                <div style="font-size:.65rem;color:var(--red);margin-top:4px">${u}</div>`).join('')}
            </div>`:''}
                    ${d.riskli_haber_uyari?`
            <div style="width:100%;margin-top:6px;padding:8px 12px;border-radius:8px;
              background:rgba(255,77,109,.1);border:1px solid rgba(255,77,109,.4)">
              <div style="font-size:.68rem;font-weight:700;color:var(--red)">
                ⛔ RİSKLİ HABER UYARISI — SİNYAL DURDURULDU</div>
              ${(d.risk_sebep||[]).map(s=>`<div style="font-size:.65rem;color:var(--text);margin-top:3px">${s}</div>`).join('')}
            </div>`:''}
          ${d.seans_uyari?`
            <div style="width:100%;margin-top:4px;padding:6px 12px;border-radius:6px;
              background:rgba(249,199,79,.06);border:1px solid rgba(249,199,79,.2);
              font-size:.68rem;color:var(--amber)">${d.seans_uyari}</div>`:''}
          ${d.sikisma&&d.sikisma.sikisma?`
            <div style="width:100%;margin-top:6px;padding:8px 12px;border-radius:8px;
              background:rgba(249,199,79,.07);border:1px solid rgba(249,199,79,.25)">
              <div style="font-size:.68rem;font-weight:600;color:var(--amber);margin-bottom:4px">
                ⏳ ZAMANSALLIK / SIKIŞMA TESPİT EDİLDİ</div>
              <div style="font-size:.7rem;color:var(--text)">${d.sikisma.etiket}</div>
              <div style="font-size:.65rem;color:var(--muted);margin-top:3px;display:flex;gap:12px;flex-wrap:wrap">
                <span>📏 Bant: %${d.sikisma.bant_oran}</span>
                <span>📅 ${d.sikisma.gun_sayisi} gün</span>
                ${d.sikisma.hacim_azalan?'<span>🔋 Hacim Azalıyor (Enerji Birikiyor)</span>':''}
                ${d.sikisma.bb_daralma?'<span>🎯 BB Daralmış</span>':''}
              </div>
              <div style="font-size:.68rem;margin-top:4px;color:${
                d.sikisma.kilis_yonu==='yukari'?'var(--green)':
                d.sikisma.kilis_yonu==='asagi'?'var(--red)':'var(--muted)'}">
                ${d.sikisma.kilis_yonu==='yukari'?'⬆ YUKARI KIRIŞ BEKLENİYOR':
                  d.sikisma.kilis_yonu==='asagi'?'⬇ AŞAĞI KIRIŞ RİSKİ':'↔ Yön Bekleniyor'}
              </div>
            </div>`:''}
          ${d.st_yon!==undefined&&d.st_yon!==0?`
            <div style="width:100%;margin-top:4px;padding:6px 12px;border-radius:6px;
              background:${d.st_yon===1?'rgba(0,214,143,.07)':'rgba(255,77,109,.07)'};
              border:1px solid ${d.st_yon===1?'rgba(0,214,143,.2)':'rgba(255,77,109,.2)'};
              font-size:.68rem;color:${d.st_yon===1?'var(--green)':'var(--red)'}">
              SuperTrend: ${d.st_yon===1?'🟢 AL Konumu — İşlem Onaylı':'🔴 SAT Konumu — Güçlü Al verilmez'}
              ${d.supertrend?` (${d.supertrend.toFixed(2)}₺)`:''}
            </div>`:''}
          ${d.divergence&&d.divergence.tip?`
            <div style="width:100%;margin-top:6px;padding:8px 10px;border-radius:8px;
              background:${d.divergence.tip==='pozitif'?'rgba(0,214,143,.08)':'rgba(255,77,109,.08)'};
              border:1px solid ${d.divergence.tip==='pozitif'?'rgba(0,214,143,.2)':'rgba(255,77,109,.2)'}">
              <div style="font-size:.68rem;font-weight:600;color:${d.divergence.tip==='pozitif'?'var(--green)':'var(--red)'};margin-bottom:4px">
                📊 RSI UYUMSUZLUĞU TESPİT EDİLDİ</div>
              <div style="font-size:.7rem;color:var(--text)">${d.divergence.etiket}</div>
              ${d.divergence.fiyat_dip1?`<div style="font-size:.65rem;color:var(--muted);margin-top:3px">
                Fiyat Dip: ${d.divergence.fiyat_dip1}₺ → ${d.divergence.fiyat_dip2}₺ (düşüş)
                &nbsp;|&nbsp; RSI Dip: ${d.divergence.rsi_dip1} → ${d.divergence.rsi_dip2} (yükseliş)</div>`:''}
              ${d.divergence.fiyat_tepe1?`<div style="font-size:.65rem;color:var(--muted);margin-top:3px">
                Fiyat Tepe: ${d.divergence.fiyat_tepe1}₺ → ${d.divergence.fiyat_tepe2}₺ (yükseliş)
                &nbsp;|&nbsp; RSI Tepe: ${d.divergence.rsi_tepe1} → ${d.divergence.rsi_tepe2} (düşüş)</div>`:''}
            </div>`:''}
        </div>
        ${nedenHTML}${ahHTML}${teHTML}
        <div style="font-size:.62rem;font-weight:600;letter-spacing:.8px;color:var(--muted);text-transform:uppercase;margin-bottom:10px">Son Haberler</div>
        ${haberHTML}
      </div>
    </div>`;
}

// ── HELPERS ──
function round2(n){return Math.round(n*100)/100}
async function yeniTara(){
  document.getElementById('scan-badge').style.display='block';
  await fetch('/api/tara');
  setTimeout(veriYukle,3000);
}

// ── BAŞLAT ──
veriYukle();
setInterval(veriYukle,60000);
</script>
</body>
</html>"""



# ─── API ENDPOINTS ────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/data")
def api_data():
    with LOCK:
        from bot_engine import makro_risk_analizi
        return jsonify({
            "data":       _cache["data"],
            "guncelleme": _cache["guncelleme"],
            "yukleniyor": _cache["yukleniyor"],
            "endeks":     bist100_durumu(),
            "makro":      makro_risk_analizi(),
        })

@app.route("/api/tara")
def api_tara():
    with LOCK:
        busy = _cache["yukleniyor"]
    if not busy:
        threading.Thread(target=tara, daemon=True).start()
    return jsonify({"ok": True, "busy": busy})

@app.route("/api/portfoy")
def api_portfoy():
    return jsonify({"pozlar": db_portfoy_al()})

@app.route("/api/portfoy/al", methods=["POST"])
def api_portfoy_al_route():
    try:
        d = request.get_json(silent=True) or {}
        sembol = str(d.get("sembol", "")).strip().upper()
        adet   = float(d.get("adet", 0))
        fiyat  = float(d.get("fiyat", 0))
        notlar = str(d.get("notlar", ""))
        if not sembol or adet <= 0 or fiyat <= 0:
            return jsonify({"ok": False, "hata": "Sembol, adet ve fiyat zorunlu"}), 400
        db_portfoy_ekle(sembol, adet, fiyat, notlar)
        return jsonify({"ok": True})
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "hata": str(e)}), 400

@app.route("/api/portfoy/sat", methods=["POST"])
def api_portfoy_sat_route():
    try:
        d      = request.get_json(silent=True) or {}
        poz_id = int(d.get("id", 0))
        fiyat  = float(d.get("fiyat", 0))
        if poz_id <= 0 or fiyat <= 0:
            return jsonify({"ok": False, "hata": "Geçersiz id veya fiyat"}), 400
        kz = db_portfoy_sat(poz_id, fiyat)
        return jsonify({"ok": kz is not False, "kar_zarar": float(kz) if kz is not False else 0})
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "hata": str(e)}), 400

@app.route("/api/gecmis")
def api_gecmis():
    return jsonify({"islemler": db_gecmis_al()})

@app.route("/api/alarmlar")
def api_alarmlar():
    return jsonify({"alarmlar": db_alarm_listele(sadece_aktif=True)})

@app.route("/api/alarmlar/ekle", methods=["POST"])
def api_alarm_ekle():
    try:
        d      = request.get_json(silent=True) or {}
        sembol = str(d.get("sembol", "")).strip().upper()
        tip    = str(d.get("tip", "asagi"))
        hedef  = float(d.get("hedef_fiyat", 0))
        not_   = str(d.get("not_", ""))
        if not sembol or hedef <= 0 or tip not in ("asagi", "yukari"):
            return jsonify({"ok": False, "hata": "Geçersiz veri"}), 400
        if not sembol.endswith(".IS"):
            sembol += ".IS"
        aid = db_alarm_ekle(sembol, tip, hedef, not_)
        return jsonify({"ok": True, "id": aid})
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "hata": str(e)}), 400

@app.route("/api/alarmlar/sil", methods=["POST"])
def api_alarm_sil():
    try:
        d   = request.get_json(silent=True) or {}
        aid = int(d.get("id", 0))
        if aid <= 0: return jsonify({"ok": False}), 400
        db_alarm_sil(aid)
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False}), 400

@app.route("/api/telegram/test")
def api_telegram_test():
    return jsonify(telegram_test())

@app.route("/api/backtest")
def api_backtest():
    try:
        sembol = request.args.get("sembol", "").strip().upper()
        gun    = int(request.args.get("gun", 120))
        if not sembol:
            return jsonify({"ok": False, "hata": "Sembol gerekli"}), 400
        if not sembol.endswith(".IS"):
            sembol += ".IS"
        gun = max(30, min(500, gun))
        sonuc = backtest(sembol, gun)
        if not sonuc:
            return jsonify({"ok": False, "hata": f"{sembol} için yeterli veri yok veya hisse bulunamadı"})
        return jsonify({"ok": True, "sonuc": sonuc})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 400

# ─── BAŞLAT ───────────────────────────────────────────────────────
if __name__ == "__main__":
    db_init()
    db_alarm_init()

    try:
        from config import ALARM_KONTROL_DAKIKA as AKD, PORT
    except Exception:
        AKD = 2; PORT = 5000

    # İlk tarama hemen başlasın
    threading.Thread(target=tara, daemon=True).start()
    # Otomatik tarama döngüsü
    threading.Thread(target=arkaplan_dongu, daemon=True).start()
    # Alarm döngüsü
    threading.Thread(target=alarm_dongu, args=(AKD,), daemon=True).start()

    # Telegram komut terminali
    if _HAS_KOMUT:
        try:
            from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
            if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
                threading.Thread(
                    target=_komut_dinle,
                    args=(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID),
                    daemon=True
                ).start()
                print("[KOMUT] 🤖 Telegram komut terminali aktif")
                print("[KOMUT] Telegram'dan /yardim yaz")
        except Exception as _ke:
            print(f"[KOMUT] Telegram terminali başlatılamadı: {_ke}")

    print("""
╔══════════════════════════════════════════════════════════════╗
║  🖥  BIST TERMINAL v8.0 — ÇALIŞIYOR                          ║
╠══════════════════════════════════════════════════════════════╣
║  Tarayıcıda aç  →  http://localhost:5000                     ║
║  Telegram bot   →  /yardim yaz                               ║
║  Durdurmak      →  Ctrl+C                                    ║
╚══════════════════════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", debug=False, port=PORT, threaded=True)
