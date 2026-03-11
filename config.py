"""
config.py — BIST BOT Ayarları v2.0
════════════════════════════════════
Railway/bulutta çalışırken environment variable'dan okur.
Lokalda çalışırken direkt buraya yaz.

Railway'de ayarlamak için:
  Dashboard → Proje → Variables → Add Variable
"""

import os

def _env(key: str, default: str = "") -> str:
    """Önce environment variable bak, yoksa default döndür."""
    return os.environ.get(key, default).strip()

# ═══════════════════════════════════════════════════════
#  TELEGRAM
#  Railway Variables: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
# ═══════════════════════════════════════════════════════
TELEGRAM_TOKEN   = _env("TELEGRAM_TOKEN",   "")  # Buraya da yazabilirsin
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")

# ═══════════════════════════════════════════════════════
#  NOSYAPI — 636 hisse (ücretsiz)
#  Railway Variable: NOSYAPI_KEY
# ═══════════════════════════════════════════════════════
NOSYAPI_KEY = _env("NOSYAPI_KEY", "")

# ═══════════════════════════════════════════════════════
#  CLAUDE AI — Haber yorumlama (opsiyonel)
#  Railway Variable: CLAUDE_API_KEY
# ═══════════════════════════════════════════════════════
CLAUDE_API_KEY = _env("CLAUDE_API_KEY", "")

# ═══════════════════════════════════════════════════════
#  ZAMANLAMA
# ═══════════════════════════════════════════════════════
TARAMA_DAKIKA        = int(_env("TARAMA_DAKIKA",        "30"))
ALARM_KONTROL_DAKIKA = int(_env("ALARM_KONTROL_DAKIKA", "2"))

# ═══════════════════════════════════════════════════════
#  SUNUCU
#  Railway PORT'u otomatik atar — değiştirme!
# ═══════════════════════════════════════════════════════
PORT  = int(_env("PORT", "5000"))  # Railway bunu otomatik set eder
DEBUG = _env("DEBUG", "false").lower() == "true"
