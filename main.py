import asyncio
import copy
import time
import aiohttp
import base64
import glob
import hashlib
import io
import logging
from datetime import datetime, timedelta, timezone, date
import json
import os
import random
import re
import threading
from collections import OrderedDict
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    AuthKeyDuplicatedError,
    UserDeactivatedError,
    SessionPasswordNeededError,
)

# ================= ASOSIY SOZLAMALAR =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8817958511:AAF6VJWPiwjSlsy9nefL2SbqVXGvpq5PG1I")

API_ID = int(os.environ.get("API_ID", 27309538))
API_HASH = os.environ.get("API_HASH", "a728b10f5fe73b9d2eec290147f7c74c")

CARD_NUMBER = "9860606758705960"
CARD_OWNER = "Muxiddinova V"

ADMIN_ID = 8488328091

# Toshkent vaqt zonasi (+5 soat)
TASHKENT_TZ = timezone(timedelta(hours=5))

DAYS_OF_WEEK_UZ = {
    0: "dushanba",
    1: "seshanba",
    2: "chorshanba",
    3: "payshanba",
    4: "juma",
    5: "shanba",
    6: "yakshanba"
}

# Murojaat / yordam
ADMIN_USERNAME = "soatbotSUPPORT"
DEV_USERNAME = "mrCODERRR"

# Premium (custom) emoji ID lari. Bo'sh qoldirilsa, oddiy emoji ishlatiladi.
# Misol: PREMIUM_EMOJI = {"clock": "5368324170671202286", "gift": "..."}
PREMIUM_EMOJI = {}
# =======================================================

os.makedirs("sessions", exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip().strip('"').strip("'")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "isaqjonovabdulloh59-svg/REPO_NOMI")
# To'liq havola (https://github.com/user/repo) yoki ".git" yozilgan bo'lsa ham, "user/repo" ko'rinishiga keltiriladi
GITHUB_REPO = re.sub(r"^(https?://)?(www\.)?github\.com/", "", GITHUB_REPO.strip()).strip("/").removesuffix(".git")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

DB_FILE = "users_db.json"
PROMO_FILE = "promos_db.json"

db_lock = threading.Lock()


def pe(name, fallback):
    """Premium emoji (agar ID berilgan bo'lsa), aks holda oddiy emoji. HTML parse_mode uchun."""
    eid = PREMIUM_EMOJI.get(name)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if eid else fallback


_BTN_FIELDS = InlineKeyboardButton.model_fields


def ibtn(text, callback_data=None, url=None, style=None, icon=None):
    """Inline tugma. aiogram yangi bo'lsa rangli (style) va premium ikonka (icon) qo'llanadi,
    eski bo'lsa jimgina oddiy tugma bo'ladi. style: 'primary' | 'success' | 'danger'."""
    kw = {"text": text}
    if callback_data:
        kw["callback_data"] = callback_data
    if url:
        kw["url"] = url
    if style and "style" in _BTN_FIELDS:
        kw["style"] = style
    if icon and "icon_custom_emoji_id" in _BTN_FIELDS:
        kw["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(**kw)


def strip_clock(name):
    """Faqat boshidagi eski soat emojisini (🕐–🕧) olib tashlaydi. Bo'sh bo'lsa '' qaytaradi."""
    name = re.sub(r"^[\U0001F550-\U0001F567\s]+", "", name or "")
    return name if name.strip() else ""


def clean_first_name(name):
    return strip_clock(name) or "User"


async def current_first_name(user_id, u_data):
    """Odamning HOZIRGI ismini Telegram'dan o'qiydi (u o'zgartirgan bo'lsa ham). Topilmasa — saqlangan ismni."""
    conn_id = u_data.get("biz_connection_id")
    fresh = ""
    if conn_id:
        try:
            conn = await bot.get_business_connection(business_connection_id=conn_id)
            fresh = strip_clock(conn.user.first_name)
        except Exception:
            fresh = ""
    if fresh:
        if u_data.get("biz_first_name") != fresh:
            u_data["biz_first_name"] = fresh
            save_db(db)
        return fresh
    return clean_first_name(u_data.get("biz_first_name"))


# Render port xatosi va HEAD so'rovlar uchun mini server
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running successfully!")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()


def load_db():
    with db_lock:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


def save_db(data):
    with db_lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    request_backup()


def load_promos():
    if os.path.exists(PROMO_FILE):
        try:
            with open(PROMO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {"DEFAULTPROMO": {"amount": 2000, "uses": 10}}


def save_promos(data):
    with open(PROMO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    request_backup()


db = load_db()
promos_db = load_promos()

# ---------- Zaxira ----------
# Telegramga backup.json yuborish O'CHIRILGAN (adminga hech narsa kelmaydi, pin ham qilinmaydi).
# Faqat GITHUB_TOKEN berilgan bo'lsagina baza GitHub'ga jimgina yangilanadi.
_backup_scheduled = False


def request_backup():
    global _backup_scheduled
    if not GITHUB_TOKEN or _backup_scheduled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _backup_scheduled = True
    loop.create_task(_delayed_github_push())


async def _delayed_github_push(delay=5):
    global _backup_scheduled
    await asyncio.sleep(delay)
    _backup_scheduled = False
    await push_to_github()

_github_lock = asyncio.Lock()

_last_pushed_fp = None     # GitHub'ga oxirgi muvaffaqiyatli yozilgan bazaning "barmoq izi"
_github_fail_count = 0


def _db_fingerprint():
    raw = json.dumps([db, promos_db], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _github_explain(status):
    if status == 401:
        return "TOKEN yaroqsiz yoki muddati tugagan (401). Yangi GITHUB_TOKEN yarating va Render'ga qo'ying."
    if status == 403:
        return "Token ruxsati yetmaydi yoki limit tugagan (403). Token 'Contents: Read and write' ruxsatiga ega bo'lsin."
    if status == 404:
        return f"Repo/branch topilmadi yoki token reponi ko'rmaydi (404). GITHUB_REPO={GITHUB_REPO}, GITHUB_BRANCH={GITHUB_BRANCH}"
    return f"HTTP {status}"


async def _github_put_file(session, path, content: bytes, message):
    """Faylni GitHub'ga yozadi. Vaqtincha xatolarda (409/422/5xx/tarmoq) 4 martagacha qayta urinadi. True/False qaytaradi."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    for attempt in range(4):
        try:
            sha = None
            async with session.get(url, headers=headers, params={"ref": GITHUB_BRANCH}) as r:
                if r.status == 200:
                    sha = (await r.json()).get("sha")
                elif r.status in (401, 403):
                    logging.error(f"GitHub {path}: {_github_explain(r.status)}")
                    return False
            body = {
                "message": message,
                "content": base64.b64encode(content).decode("ascii"),
                "branch": GITHUB_BRANCH,
            }
            if sha:
                body["sha"] = sha
            async with session.put(url, headers=headers, json=body) as r:
                if r.status in (200, 201):
                    return True
                text = await r.text()
                if r.status in (401, 403, 404):
                    logging.error(f"GitHub {path} yozilmadi: {_github_explain(r.status)}")
                    return False
                logging.error(f"GitHub {path} yozilmadi (urinish {attempt + 1}/4): {r.status} {text[:200]}")
        except Exception as e:
            logging.error(f"GitHub {path} tarmoq xatosi (urinish {attempt + 1}/4): {e}")
        await asyncio.sleep(2 * (attempt + 1))
    return False


async def push_to_github():
    """users_db.json va promos_db.json ni GitHub'ga yangilaydi. Muvaffaqiyatli bo'lsa True."""
    global _last_synced, _last_pushed_fp, _github_fail_count
    if not GITHUB_TOKEN:
        return False
    async with _github_lock:
        try:
            now = datetime.now(TASHKENT_TZ).strftime("%Y-%m-%d %H:%M:%S")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as session:
                remote = await fetch_remote_db(session)          # userbot yozgan o'zgarishlarni yo'qotmaslik uchun
                if remote is None:
                    logging.error("GitHub bazasini o'qib bo'lmadi — zaxira eski nusxa ustiga yozilmaydi (keyingi urinishda qayta uriniladi)")
                    _github_fail_count += 1
                    return False
                banned = merge_remote(remote)
                if banned:
                    await kick_banned(banned)
                fp = _db_fingerprint()
                users_bytes = json.dumps(db, ensure_ascii=False, indent=4).encode("utf-8")
                promos_bytes = json.dumps(promos_db, ensure_ascii=False, indent=4).encode("utf-8")
                ok1 = await _github_put_file(session, "users_db.json", users_bytes, f"Auto backup {now} [skip render] [skip ci]")
                ok2 = await _github_put_file(session, "promos_db.json", promos_bytes, f"Auto backup {now} [skip render] [skip ci]")
            if ok1 and ok2:
                _last_synced = copy.deepcopy(db)
                _last_pushed_fp = fp
                _github_fail_count = 0
                return True
            _github_fail_count += 1
            return False
        except Exception as e:
            logging.error(f"GitHub push xatosi: {e}")
            _github_fail_count += 1
            return False


async def github_autosave_loop():
    """Baza o'zgargan bo'lsa (kim nima o'rnatgan bo'lsa ham) GitHub'ga o'zi yozadi. Xato bo'lsa qayta uriniladi."""
    await asyncio.sleep(15)
    while True:
        try:
            if GITHUB_TOKEN and not _github_lock.locked() and _db_fingerprint() != _last_pushed_fp:
                await push_to_github()
        except Exception as e:
            logging.error(f"Avto-saqlash xatosi: {e}")
        # Xato ketma-ket bo'lsa, kutish uzayadi (30s -> 5 daqiqagacha), lekin to'xtamaydi
        await asyncio.sleep(min(30 * (2 ** min(_github_fail_count, 4)), 300) if _github_fail_count else 30)


_last_synced = {}   # str_id -> GitHub'dagi oxirgi ma'lum holat (3 tomonlama birlashtirish uchun asos)


async def fetch_remote_db(session):
    """GitHub'dagi users_db.json ni o'qiydi. Xato bo'lsa None."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/users_db.json"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.raw+json"}
    try:
        async with session.get(url, headers=headers, params={"ref": GITHUB_BRANCH}) as r:
            if r.status == 404:
                logging.error(f"GitHub: users_db.json topilmadi yoki repo/token noto'g'ri (404). GITHUB_REPO={GITHUB_REPO}")
                return {}
            if r.status != 200:
                logging.error(f"GitHub baza o'qilmadi: HTTP {r.status} — {_github_explain(r.status)}")
                return None
            data = json.loads(await r.text())
            return data if isinstance(data, dict) else None
    except Exception as e:
        logging.error(f"GitHub baza o'qilmadi: {e}")
        return None


def merge_remote(remote):
    """Tashqarida (userbot orqali) o'zgargan maydonlarni xotiradagi db ga qo'shadi.
    Faqat GitHub'da asosdan farq qilgan maydonlar olinadi; balans — farq (delta) sifatida qo'shiladi.
    -> yangi bloklangan foydalanuvchilar ro'yxati"""
    newly_banned = []
    for uid, r in remote.items():
        if not isinstance(r, dict):
            continue
        cur = db.get(uid)
        if cur is None:
            db[uid] = copy.deepcopy(r)
            continue
        base = _last_synced.get(uid)
        if base is None:
            continue
        for k, rv in r.items():
            if rv == base.get(k):
                continue
            if k == "balance" and isinstance(rv, (int, float)) and isinstance(base.get(k, 0), (int, float)):
                cur[k] = (cur.get(k, 0) or 0) + (rv - (base.get(k, 0) or 0))
            elif k == "banned" or cur.get(k) == base.get(k):
                if k == "banned" and rv and not cur.get("banned"):
                    newly_banned.append(uid)
                cur[k] = copy.deepcopy(rv)
    return newly_banned


async def kick_banned(uids):
    """Bloklanganlarning soatini to'xtatadi (aylanalar active_* dan chiqib ketadi)."""
    for uid in uids:
        try:
            i = int(uid)
        except ValueError:
            continue
        active_biz_clocks.pop(i, None)
        cl = active_clocks.pop(i, None)
        u = db.get(uid, {})
        u["clock_active"] = False
        u["biz_active"] = False
        u["antidelete_active"] = False
        if cl is not None:
            try:
                await cl.disconnect()
            except Exception:
                pass
        print(f"BLOKLANDI: {uid} — soat to'xtatildi")


async def sync_remote_loop():
    """Har 60 soniyada GitHub'dagi o'zgarishlarni (userbot amallarini) olib turadi."""
    global _last_synced
    while True:
        await asyncio.sleep(60)
        if not GITHUB_TOKEN or _github_lock.locked():
            continue
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                remote = await fetch_remote_db(session)
            if remote is None:
                continue
            banned = merge_remote(remote)
            _last_synced = copy.deepcopy(remote)
            if banned:
                await kick_banned(banned)
            with db_lock:
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"Sinxron xatosi: {e}")


_ban_notice_at = {}


def ban_notice_text(reason=None):
    r = f"\n\n📝 <b>Sabab:</b> {esc(reason)}" if reason else ""
    return (
        "🚫 <b>Siz bloklangansiz!</b>"
        f"{r}\n\n"
        "Agar buni xato deb hisoblasangiz, to'lov chekingiz yoki muammo <b>skrinshotini</b> "
        f"@{ADMIN_USERNAME} ga yuboring — admin ko'rib chiqadi."
    )


def ban_notice_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("📞 Support", url=f"https://t.me/{ADMIN_USERNAME}", style="primary")]
    ])


class BanMiddleware(BaseMiddleware):
    """banned=true bo'lgan foydalanuvchiga 'Siz bloklangansiz' + Support tugmasi ko'rsatiladi (admin bundan mustasno)."""
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and user.id != ADMIN_ID and db.get(str(user.id), {}).get("banned"):
            if isinstance(event, types.CallbackQuery):
                try:
                    await event.answer(f"🚫 Siz bloklangansiz! Support: @{ADMIN_USERNAME}", show_alert=True)
                except Exception:
                    pass
            else:
                now = time.time()
                if now - _ban_notice_at.get(user.id, 0) > 30:   # spam bo'lmasligi uchun 30 soniyada 1 marta
                    _ban_notice_at[user.id] = now
                    try:
                        await bot.send_message(
                            user.id,
                            ban_notice_text(db.get(str(user.id), {}).get("banned_reason")),
                            reply_markup=ban_notice_kb(), parse_mode="HTML",
                        )
                    except Exception:
                        pass
            return
        return await handler(event, data)


def _apply_backup(data):
    """Zaxira ma'lumotini xotiraga va diskka (sessiyalar bilan) tiklaydi."""
    db.clear(); db.update(data.get("db", {}))
    promos_db.clear(); promos_db.update(data.get("promos", {}))
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)
    with open(PROMO_FILE, "w", encoding="utf-8") as f:
        json.dump(promos_db, f, ensure_ascii=False, indent=4)
    os.makedirs("sessions", exist_ok=True)
    count = 0
    for name, b64 in data.get("sessions", {}).items():
        safe = os.path.basename(name)
        if not safe.endswith(".session"):
            continue
        with open(os.path.join("sessions", safe), "wb") as f:
            f.write(base64.b64decode(b64))
        count += 1
    return count

user_sessions = {}
active_clocks = {}
active_biz_clocks = {}  # user_id -> True, biznes (Telegram Business) usuli orqali ishlayotgan soatlar
biz_conn_to_user = {}  # business_connection_id -> owner user_id (tez qidirish uchun)
business_msg_cache = OrderedDict()  # (connection_id, chat_id, message_id) -> {"text", "sender", "chat_title"}
BUSINESS_CACHE_LIMIT = 3000


def get_user_data(user_id):
    str_id = str(user_id)
    if str_id not in db:
        db[str_id] = {
            "balance": 0,
            "plan": "Free",
            "joined_date": datetime.now(TASHKENT_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "clock_active": False,
            "nick_clock": True,
            "bio_clock": False,
            "bio_type": "oddiy",
            "online_mode": False,
            "referrals_count": 0,
            "clock_installed_referrals": 0,
            "used_promos": [],
            "birthday_date": "12-25",
            "plan_expire": "Mavjud emas",
            "plan_start": None,
            "font_style": "Default",
            "saved_pubg_id": None,
            "setup_method": None,
            "biz_connection_id": None,
            "biz_active": False,
            "biz_can_name": False,
            "biz_can_bio": False,
            "biz_can_msg": False,
            "biz_base_bio": "",
            "antidelete_active": False,
            "biz_first_name": "",
        }
        save_db(db)
    return db[str_id]


def apply_font(text, font_style):
    if font_style == "Monospace":
        trans = str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")
        return text.translate(trans)
    elif font_style == "Bold":
        trans = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")
        return text.translate(trans)
    elif font_style == "Double Struck":
        trans = str.maketrans("0123456789", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡")
        return text.translate(trans)
    elif font_style == "Circle":
        trans = str.maketrans("0123456789", "⓪①②③④⑤⑥⑦⑧⑨")
        return text.translate(trans)
    elif font_style == "SuperScript":
        trans = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
        return text.translate(trans)
    elif font_style == "SubScript":
        trans = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        return text.translate(trans)
    elif font_style == "Strike-Through":
        return "".join([c + "\u0336" if c.isdigit() else c for c in text])
    elif font_style == "Bold Serif":
        trans = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")
        return text.translate(trans)
    elif font_style == "Double Circle":
        trans = str.maketrans("0123456789", "⓪①②③④⑤⑥⑦⑧⑨")
        return text.translate(trans)
    elif font_style == "Dark Circle":
        trans = str.maketrans("0123456789", "⓪①②③④⑤⑥⑦⑧⑨")
        return text.translate(trans)
    elif font_style == "Crazify":
        styles = ["Default", "Monospace", "Bold", "Double Struck", "Circle"]
        chosen = random.choice(styles)
        if chosen != "Crazify":
            return apply_font(text, chosen)
    return text


FREE_BIO_TAG = "✨ Soat @tmclock_bot orqali qo'yildi"
BIO_MAX = 70


def effective_font(u_data):
    """Font faqat Premium tarifida ishlaydi. Boshqalarda doim oddiy (Default) shrift."""
    if u_data.get("plan") == "Premium":
        return u_data.get("font_style", "Default")
    return "Default"


def biz_should_set_bio(u_data):
    """Business usulida bioni yangilash kerakmi? Free'da doim (yozuv o'chirilsa qayta chiqadi)."""
    if not u_data.get("biz_can_bio", False):
        return False
    plan = u_data.get("plan")
    if plan == "Free":
        u_data["biz_tag_set"] = True
        return True
    if u_data.get("bio_clock", False) and plan in BIO_PLANS:
        u_data["biz_tag_set"] = True      # bioga soat yozildi - o'chirilganda tozalash kerak bo'ladi
        return True
    if u_data.get("biz_tag_set", False):  # bio o'chirilgan / tarif tugagan: eski yozuvni BIR MARTA tozalaymiz
        u_data["biz_tag_set"] = False
        return True
    return False


def get_hijri_qurbon_hayiti(year):
    qurbon_dates = {
        2025: (datetime(2025, 6, 6, tzinfo=TASHKENT_TZ), "05:30"),
        2026: (datetime(2026, 5, 27, tzinfo=TASHKENT_TZ), "05:30"),
        2027: (datetime(2027, 5, 17, tzinfo=TASHKENT_TZ), "05:30"),
        2028: (datetime(2028, 5, 6, tzinfo=TASHKENT_TZ), "05:30"),
    }
    target_dt = qurbon_dates.get(year, (datetime(year, 6, 1, tzinfo=TASHKENT_TZ), "05:30"))
    return target_dt


# ================= BIO: PLANLAR, HISOBLAGICHLAR, NAMOZ VAQTLARI =================
# Bio funksiyalari qaysi tariflarda ishlaydi (Standard, Plus va Premium).
BIO_PLANS = ["Standard", "Plus", "Premium"]
BIO_PLANS_TEXT = "Standard ⏰, Plus ✨ va Premium ⭐️"



def fmt_dur(seconds):
    """Soniyani '15 kun 4 soat 15 min' ko'rinishiga o'tkazadi (nol birliklar tushirib qoldiriladi)."""
    total_min = max(int(seconds) // 60, 0)
    days, rem = divmod(total_min, 1440)
    hours, mins = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} kun")
    if days or hours:
        parts.append(f"{hours} soat")
    parts.append(f"{mins} min")
    return " ".join(parts)


def _minute_floor(dt):
    return dt.replace(second=0, microsecond=0)


def countdown_line(emoji, title, month, day, now_dt, today_text, show_wday=True):
    """Aniq sanagacha (har yili 00:00 da boshlanadi) qancha vaqt qolganini hisoblaydi."""
    now_m = _minute_floor(now_dt)
    if now_m.month == month and now_m.day == day:
        return today_text
    target = datetime(now_m.year, month, day, 0, 0, tzinfo=TASHKENT_TZ)
    if target <= now_m:
        target = datetime(now_m.year + 1, month, day, 0, 0, tzinfo=TASHKENT_TZ)
    left = fmt_dur((target - now_m).total_seconds())
    wd = f" ({DAYS_OF_WEEK_UZ[target.weekday()]})" if show_wday else ""
    return f"{emoji} {title} {left} qoldi{wd}"


# ---------- Namoz vaqtlari (shaharlar bo'yicha) ----------
# key: (ko'rsatiladigan nom, kenglik, uzunlik, praytime.uz region_id, namoz-vaqti.uz slug variantlari)
NAMOZ_CITIES = {
    "toshkent":  ("Toshkent",  41.2995, 69.2401, 1,   ["toshkent-shahri", "toshkent"]),
    "fargona":   ("Farg'ona",  40.3842, 71.7843, 77,  ["fargona-shahri", "fargona"]),
    "qoqon":     ("Qo'qon",    40.5286, 70.9425, 78,  ["qoqon-shahri", "qoqon"]),
    "namangan":  ("Namangan",  40.9983, 71.6726, 149, ["namangan-shahri", "namangan"]),
    "andijon":   ("Andijon",   40.7821, 72.3442, 17,  ["andijon-shahri", "andijon"]),
    "samarqand": ("Samarqand", 39.6542, 66.9597, 47,  ["samarqand-shahri", "samarqand"]),
    "buxoro":    ("Buxoro",    39.7747, 64.4286, 34,  ["buxoro-shahri", "buxoro"]),
    "navoiy":    ("Navoiy",    40.0844, 65.3792, 136, ["navoiy-shahri", "navoiy"]),
    "jizzax":    ("Jizzax",    40.1158, 67.8422, 107, ["jizzax-shahri", "jizzax"]),
    "guliston":  ("Guliston",  40.4897, 68.7842, 67,  ["guliston-shahri", "guliston"]),
    "qarshi":    ("Qarshi",    38.8606, 65.7891, 121, ["qarshi-shahri", "qarshi"]),
    "termiz":    ("Termiz",    37.2242, 67.2783, 162, ["termiz-shahri", "termiz"]),
    "urganch":   ("Urganch",   41.5500, 60.6333, 96,  ["urganch-shahri", "urganch"]),
    "nukus":     ("Nukus",     42.4531, 59.6103, 176, ["nukus-shahri", "nukus"]),
}
DEFAULT_CITY = "toshkent"
PRAYER_NAMES = {"bomdod": "Bomdod", "peshin": "Peshin", "asr": "Asr", "shom": "Shom", "xufton": "Xufton"}


def city_of(u_data):
    c = (u_data or {}).get("prayer_city", DEFAULT_CITY)
    return c if c in NAMOZ_CITIES else DEFAULT_CITY


def city_name(key):
    return NAMOZ_CITIES.get(key, NAMOZ_CITIES[DEFAULT_CITY])[0]


def calc_prayer_local(d, city=DEFAULT_CITY):
    """Internet bo'lmasa ishlatiladigan zaxira hisob (astronomik formula). Taxminiy: bir necha daqiqa xato."""
    import math
    _, lat, lng, _, _ = NAMOZ_CITIES.get(city, NAMOZ_CITIES[DEFAULT_CITY])
    tz = 5
    y, m, dd = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + dd + (2 - A + A // 4) - 1524.5
    jd -= lng / (15 * 24.0)
    D = jd + 0.5 - 2451545.0
    g = math.radians((357.529 + 0.98560028 * D) % 360)
    q = (280.459 + 0.98564736 * D) % 360
    L = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    e = math.radians(23.439 - 0.00000036 * D)
    RA = (math.degrees(math.atan2(math.cos(e) * math.sin(L), math.cos(L))) / 15.0) % 24
    decl = math.asin(math.sin(e) * math.sin(L))
    eqt = q / 15.0 - RA
    while eqt > 12:
        eqt -= 24
    while eqt < -12:
        eqt += 24
    la = math.radians(lat)
    noon = 12 + tz - lng / 15.0 - eqt

    def hour_angle(sin_alt):
        x = (sin_alt - math.sin(decl) * math.sin(la)) / (math.cos(decl) * math.cos(la))
        return math.degrees(math.acos(max(-1.0, min(1.0, x)))) / 15.0

    alt_asr = math.atan(1.0 / (2 + math.tan(abs(la - decl))))   # Hanafiy asr (soya 2 barobar)
    vals = {
        "bomdod": noon - hour_angle(-math.sin(math.radians(16.0))),
        "quyosh": noon - hour_angle(-math.sin(math.radians(0.833))),
        "peshin": noon + 1 / 60.0,
        "asr": noon + hour_angle(math.sin(alt_asr)),
        "shom": noon + hour_angle(-math.sin(math.radians(0.833))) + 3 / 60.0,
        "xufton": noon + hour_angle(-math.sin(math.radians(15.0))),
    }
    base = datetime(d.year, d.month, d.day, tzinfo=TASHKENT_TZ)
    return {k: base + timedelta(hours=v) for k, v in vals.items()}


PRAYER_FILE = "prayer_cache.json"
PRAYER_CACHE = {}          # shahar -> {sana -> {"bomdod": datetime, ...}}  (faqat RASMIY manbalardan)
PRAYER_SOURCE = {}         # shahar -> {sana -> manba nomi}
PRAYER_KEYS = ["bomdod", "quyosh", "peshin", "asr", "shom", "xufton"]
UZ_MONTHS = {"yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
             "iyul": 7, "avgust": 8, "sentabr": 9, "oktabr": 10, "noyabr": 11, "dekabr": 12}
PRAYER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}


def _norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _hhmm_to_dt(d, s):
    m = re.search(r"(\d{1,2}):(\d{2})", str(s))
    if not m:
        raise ValueError(f"vaqt formati xato: {s}")
    return datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)), tzinfo=TASHKENT_TZ)


def _times_from_strings(d, t):
    return {k: _hhmm_to_dt(d, t[k]) for k in PRAYER_KEYS}


def _valid_day(times, d, city=DEFAULT_CITY):
    """Vaqtlar tartibli va hisob-kitobdan 25 daqiqadan ortiq farq qilmasligini tekshiradi (xato ma'lumotni rad etadi)."""
    try:
        seq = [times[k] for k in PRAYER_KEYS]
    except KeyError:
        return False
    if any(seq[i] >= seq[i + 1] for i in range(len(seq) - 1)):
        return False
    ref = calc_prayer_local(d, city)
    return all(abs((times[k] - ref[k]).total_seconds()) <= 25 * 60 for k in PRAYER_KEYS)


async def _http_get(session, url, as_json=False):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        if as_json:
            return await r.json(content_type=None)
        return await r.text()


def _parse_month_json(data, city=DEFAULT_CITY):
    """namoz-vaqti.uz JSON (Musulmonlar idorasi / Din ishlari qo'mitasi ma'lumotlari). Shahar nomi tekshiriladi."""
    try:
        reg = data["meta"]["region"]
        label = _norm(f"{reg.get('name', '')}{reg.get('slug', '')}")
        if label and _norm(city_name(city)) not in label:
            return {}          # boshqa shahar ma'lumoti keldi - rad etamiz
    except Exception:
        pass
    days = {}
    for row in (data.get("period_table") or []):
        try:
            dd, mm, yy = row["date"].split(".")
            d = date(int(yy), int(mm), int(dd))
            t = _times_from_strings(d, row["times"])
            if _valid_day(t, d, city):
                days[d] = t
        except Exception:
            continue
    try:
        y, m, dd = data["meta"]["date"].split("-")
        d = date(int(y), int(m), int(dd))
        t = _times_from_strings(d, data["today"]["times"])
        if _valid_day(t, d, city):
            days.setdefault(d, t)
    except Exception:
        pass
    return days


def _parse_month_html(text, city=DEFAULT_CITY):
    """Oylik jadval HTML sahifasi (zaxira usul): 'DD.MM.YYYY | 05:52 | 07:15 | ...' qatorlari."""
    tm = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    if tm and _norm(city_name(city)) not in _norm(tm.group(1)):
        return {}
    plain = re.sub(r"<[^>]+>", " ", text)
    days = {}
    for m in re.finditer(r"(\d{2})\.(\d{2})\.(\d{4})((?:\s*\|?\s*\d{1,2}:\d{2}){6})", plain):
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            hh = re.findall(r"\d{1,2}:\d{2}", m.group(4))
            t = _times_from_strings(d, dict(zip(PRAYER_KEYS, hh)))
            if _valid_day(t, d, city):
                days[d] = t
        except Exception:
            continue
    return days


async def _fetch_month(session, city, y, mth):
    ym = f"{y}-{mth:02d}"
    slugs = NAMOZ_CITIES[city][4]
    for slug in slugs:          # 1) JSON API
        try:
            data = await _http_get(
                session, f"https://namoz-vaqti.uz/index.php?format=json&lang=en&period={ym}&region={slug}", True)
            days = _parse_month_json(data, city)
            if days:
                return days
        except Exception as e:
            print(f"namoz-vaqti.uz JSON xatosi ({slug}):", e)
    for slug in slugs:          # 2) shu saytning HTML jadvali
        try:
            html = await _http_get(session, f"https://namoz-vaqti.uz/en/namoz-vaqtlari/{slug}/oylik/{ym}")
            days = _parse_month_html(html, city)
            if days:
                return days
        except Exception as e:
            print(f"namoz-vaqti.uz HTML xatosi ({slug}):", e)
    return {}


async def _fetch_praytime_today(session, city, today):
    """praytime.uz (Muftiyat taqvimi) - faqat bugun uchun zaxira manba."""
    try:
        rid = NAMOZ_CITIES[city][3]
        html = await _http_get(session, f"https://praytime.uz/?region_id={rid}&lng=uz")
        plain = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        plain = re.sub(r"<[^>]+>", " ", plain)
        dm = re.search(r"(\d{1,2})-(" + "|".join(UZ_MONTHS) + ")", plain, re.I)
        if not dm or int(dm.group(1)) != today.day or UZ_MONTHS[dm.group(2).lower()] != today.month:
            print("praytime.uz: sahifa sanasi bugungi sanaga mos emas")
            return {}
        times = re.findall(r"(?<![\d:])(\d{2}:\d{2})(?![\d:])", plain[dm.end():])
        if len(times) < 7:
            return {}
        t = {"bomdod": times[0], "quyosh": times[1], "peshin": times[3],
             "asr": times[4], "shom": times[5], "xufton": times[6]}
        parsed = _times_from_strings(today, t)
        return {today: parsed} if _valid_day(parsed, today, city) else {}
    except Exception as e:
        print("praytime.uz xatosi:", e)
        return {}


def _save_prayer_cache():
    try:
        today = datetime.now(TASHKENT_TZ).date()
        out = {}
        for city, days in PRAYER_CACHE.items():
            out[city] = {d.isoformat(): {k: v[k].strftime("%H:%M") for k in PRAYER_KEYS}
                         for d, v in days.items() if d >= today - timedelta(days=3)}
        with open(PRAYER_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception as e:
        print("Namoz keshini saqlashda xato:", e)


def _load_prayer_cache():
    """Bot qayta ishga tushganda (internet vaqtincha yo'q bo'lsa ham) oxirgi rasmiy vaqtlar tiklanadi."""
    try:
        if not os.path.exists(PRAYER_FILE):
            return
        with open(PRAYER_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for city, days in raw.items():
            if city not in NAMOZ_CITIES:
                continue
            for k, v in days.items():
                d = date.fromisoformat(k)
                t = _times_from_strings(d, v)
                if _valid_day(t, d, city):
                    PRAYER_CACHE.setdefault(city, {})[d] = t
                    PRAYER_SOURCE.setdefault(city, {}).setdefault(d, "kesh")
    except Exception as e:
        print("Namoz keshini o'qishda xato:", e)


def used_prayer_cities():
    """Foydalanuvchilar tanlagan shaharlar (+ Toshkent har doim)."""
    cities = {DEFAULT_CITY}
    try:
        for u in list(db.values()):
            if isinstance(u, dict) and u.get("bio_type") == "namoz":
                cities.add(city_of(u))
    except Exception:
        pass
    return cities


def prayer_data_ok(cities=None):
    """Bugun va ertaga uchun rasmiy (yangi) ma'lumot bormi?"""
    today = datetime.now(TASHKENT_TZ).date()
    for c in (cities or used_prayer_cities()):
        src = PRAYER_SOURCE.get(c, {})
        if not all(src.get(d) in ("namoz-vaqti.uz", "praytime.uz") for d in (today, today + timedelta(days=1))):
            return False
    return True


async def refresh_prayer_cache(cities=None):
    """Rasmiy manbalardan vaqtlarni yangilaydi. Vaqtlar o'zgargan bo'lsa, eskisi ustiga yoziladi."""
    today = datetime.now(TASHKENT_TZ).date()
    months = sorted({(d.year, d.month) for d in (today - timedelta(days=1), today, today + timedelta(days=1))})
    changed = False
    async with aiohttp.ClientSession(headers=PRAYER_HEADERS) as session:
        for city in (cities or used_prayer_cities()):
            cache = PRAYER_CACHE.setdefault(city, {})
            srcs = PRAYER_SOURCE.setdefault(city, {})
            for (y, mth) in months:
                days = await _fetch_month(session, city, y, mth)
                for d, t in days.items():
                    if cache.get(d) != t:
                        changed = True
                    cache[d] = t
                    srcs[d] = "namoz-vaqti.uz"
            if srcs.get(today) != "namoz-vaqti.uz":
                for d, t in (await _fetch_praytime_today(session, city, today)).items():
                    if cache.get(d) != t:
                        changed = True
                    cache[d] = t
                    srcs[d] = "praytime.uz"
            for d in list(cache):
                if d < today - timedelta(days=3):
                    cache.pop(d, None)
                    srcs.pop(d, None)
            print(f"Namoz vaqtlari ({city_name(city)}): manba = {srcs.get(today, 'hisob')}")
    if changed:
        _save_prayer_cache()


async def prayer_refresh_loop():
    _load_prayer_cache()
    while True:
        try:
            await refresh_prayer_cache()
        except Exception as e:
            print("Namoz yangilash sikli xatosi:", e)
        # Rasmiy ma'lumot yo'q bo'lsa 10 daqiqada, bo'lsa 2 soatda qayta tekshiradi (o'zgarishlar avtomatik olinadi)
        await asyncio.sleep(600 if not prayer_data_ok() else 7200)


def get_prayer_times(d, city=DEFAULT_CITY):
    """Rasmiy vaqt bo'lsa — o'sha. Bo'lmasa: eng yaqin rasmiy kunning farqi (siljishi) bilan to'g'rilangan hisob."""
    cache = PRAYER_CACHE.get(city) or {}
    if d in cache:
        return cache[d]
    local = calc_prayer_local(d, city)
    if cache:
        ref_d = min(cache, key=lambda x: abs((x - d).days))
        if abs((ref_d - d).days) <= 45:
            ref_local = calc_prayer_local(ref_d, city)
            off = {k: cache[ref_d][k] - ref_local[k] for k in PRAYER_KEYS}
            return {k: local[k] + off[k] for k in PRAYER_KEYS}
    return local


def prayer_line(now_dt, city=DEFAULT_CITY):
    """Hozirgi namoz: qachon kirdi/qachon chiqadi va necha soat-daqiqa qolgani. Chiqqach keyingisigacha."""
    now_m = _minute_floor(now_dt)
    today = now_m.date()
    windows = []
    for off in (-1, 0, 1):
        d = today + timedelta(days=off)
        t = get_prayer_times(d, city)
        nxt = get_prayer_times(d + timedelta(days=1), city)
        windows += [
            ("bomdod", t["bomdod"], t["quyosh"]),
            ("peshin", t["peshin"], t["asr"]),
            ("asr", t["asr"], t["shom"]),
            ("shom", t["shom"], t["xufton"]),
            ("xufton", t["xufton"], nxt["bomdod"]),
        ]
    windows.sort(key=lambda w: w[1])
    for name, start, end in windows:
        if start <= now_m < end:
            left = fmt_dur((end - now_m).total_seconds())
            return (f"🕌 {PRAYER_NAMES[name]} {start.strftime('%H:%M')}-{end.strftime('%H:%M')} "
                    f"| chiqishiga {left} qoldi")
    for name, start, end in windows:
        if start > now_m:   # Quyosh chiqqandan Peshingacha bo'lgan oraliq
            left = fmt_dur((start - now_m).total_seconds())
            return f"🕌 {PRAYER_NAMES[name]} {start.strftime('%H:%M')} da kiradi | {left} qoldi"
    return "🕌 Namoz vaqti"


def build_bio_extra(u_data, now_dt, now_str):
    """Bio uchun qo'shimcha matn (bio tipiga qarab). Ikkala soat usuli (telefon va Business) shundan foydalanadi."""
    extra = []
    if not (u_data.get("bio_clock", False) and u_data.get("plan") in BIO_PLANS):
        return extra
    b_type = u_data.get("bio_type", "oddiy")
    if b_type == "oddiy":
        extra.append(f"🕒 {now_str}")
    elif b_type == "salomlashish":
        hour = now_dt.hour
        if 5 <= hour < 12:
            extra.append("Good morning ☀️")
        elif 12 <= hour < 17:
            extra.append("Good afternoon 🌤")
        elif 17 <= hour < 22:
            extra.append("Good evening 🌙")
        else:
            extra.append("Good night 🌠")
    elif b_type == "tugilgan_kun":
        try:
            b_month, b_day = map(int, u_data.get("birthday_date", "12-25").split("-"))
            extra.append(countdown_line("🎂", "Tug'ilgan kunga", b_month, b_day, now_dt, "🎂 Bugun tug'ilgan kun! 🎉"))
        except Exception:
            extra.append("🎂 Tug'ilgan kun")
    elif b_type == "yangi_yil":
        extra.append(countdown_line("🎄", "Yangi yilga", 1, 1, now_dt, "🎄 Yangi yil muborak! 🎉", show_wday=False))
    elif b_type == "vatan_himoyachilari":
        extra.append(countdown_line("🎖", "14-yanvarga", 1, 14, now_dt, "🎖 Bugun Vatan himoyachilari kuni!"))
    elif b_type == "sakkiz_mart":
        extra.append(countdown_line("🌷", "8-martga", 3, 8, now_dt, "🌷 Bugun 8-mart bayrami!"))
    elif b_type == "namoz":
        extra.append(prayer_line(now_dt, city_of(u_data)))
    elif b_type == "qurbon_hayiti":
        qh_dt, namoz_time = get_hijri_qurbon_hayiti(now_dt.year)
        if qh_dt.date() < now_dt.date():
            qh_dt, namoz_time = get_hijri_qurbon_hayiti(now_dt.year + 1)
        if qh_dt.date() == now_dt.date():
            extra.append(f"🕌 Bugun Qurbon hayiti! Namoz: {namoz_time}")
        else:
            left = fmt_dur((qh_dt - _minute_floor(now_dt)).total_seconds())
            extra.append(f"🕌 Qurbon hayitiga {left} qoldi ({DAYS_OF_WEEK_UZ[qh_dt.weekday()]})")
    return extra


def build_final_bio(clean_bio, extra_bio, is_free):
    """Free tarifda reklama yozuvi doim qoladi. Boshqalarda soat matni DOIM sig'adi:
    kerak bo'lsa foydalanuvchining o'z bio matni qisqartiriladi (soat kesilib qolmaydi)."""
    if is_free:
        room = max(BIO_MAX - len(FREE_BIO_TAG) - 1, 0)
        base = clean_bio[:room].rstrip()
        return f"{base} {FREE_BIO_TAG}".strip()
    if not extra_bio:
        return clean_bio[:BIO_MAX]
    extra = " | ".join(extra_bio)[:BIO_MAX]
    room = BIO_MAX - len(extra) - 3
    if room <= 0 or not clean_bio:
        return extra
    return f"{clean_bio[:room].rstrip()} | {extra}"[:BIO_MAX]
# =================================================================================


class ClockSetup(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()
    waiting_for_birthday = State()


class PaymentState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_receipt = State()


class PromoState(StatesGroup):
    waiting_for_promo = State()


class NickGenState(StatesGroup):
    waiting_for_name = State()
    waiting_for_choice = State()


class PubgState(StatesGroup):
    waiting_for_pubg_id = State()
    waiting_for_new_pubg_id = State()


class AdminBroadcast(StatesGroup):
    composing = State()


main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Soat Sozlamalari ⚙️"),
            KeyboardButton(text="Mening Hisobim 👤"),
        ],
        [
            KeyboardButton(text="PUBG UC 🎮"),
        ],
        [
            KeyboardButton(text="Hisobni To'ldirish 💰"),
            KeyboardButton(text="Tariflar 🛍"),
        ],
        [
            KeyboardButton(text="Referral 💸"),
            KeyboardButton(text="Promokod 🎟"),
        ],
        [
            KeyboardButton(text="Savollar (FAQ) ❓"),
            KeyboardButton(text="Nik yaratish 🤩"),
        ],
        [
            KeyboardButton(text="Avto javob 🤖"),
            KeyboardButton(text="Chat nazorati 💬"),
        ],
    ],
    resize_keyboard=True,
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Bekor qilish")]], resize_keyboard=True
)

phone_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📞 Telefon raqamni jo'natish", request_contact=True)],
        [KeyboardButton(text="⬅️ Bekor qilish")],
    ],
    resize_keyboard=True,
)


def online_status_text(u_data):
    """Online rejim holati. Premium bo'lmasa, eskirib qolgan 'yoniq' belgisi avtomatik o'chiriladi."""
    if u_data.get("online_mode", False) and u_data.get("plan") != "Premium":
        u_data["online_mode"] = False
        save_db(db)
    return "Yoniq 🟢" if u_data.get("online_mode", False) else "O'chiq 🔴"


async def keep_online_loop(user_id, client):
    """Online rejim yoqilgan bo'lsa, profilni doimo 'online' holatda ushlab turadi (har 10 soniyada).
    Ulanish uzilsa avtomatik qayta ulanadi, FloodWait bo'lsa kutadi, sessiya o'lsa to'xtaydi."""
    from telethon.errors import FloodWaitError
    fails = 0
    while user_id in active_clocks:
        delay = 10
        try:
            u = get_user_data(user_id)
            if u.get("plan") == "Premium" and u.get("online_mode", False):
                if not client.is_connected():
                    await client.connect()
                await client(functions.account.UpdateStatusRequest(offline=False))
                fails = 0
        except FloodWaitError as fw:
            delay = min(int(getattr(fw, "seconds", 30)) + 1, 120)
            print(f"Online holat FloodWait ({user_id}): {delay}s")
        except (AuthKeyDuplicatedError, UserDeactivatedError) as e:
            print(f"Online holat: sessiya yaroqsiz ({user_id}):", e)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            fails += 1
            print(f"Online holat xatosi ({user_id}) [{fails}]:", e)
            if fails >= 3:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                try:
                    await client.connect()
                except Exception:
                    pass
                fails = 0
        await asyncio.sleep(delay)


online_tasks = {}


def ensure_online_task(user_id):
    """Telefon (Telethon) sessiyasi bor bo'lsa, online-ushlagich ishlab turganiga ishonch hosil qiladi."""
    client = active_clocks.get(user_id)
    if client is None:
        return False
    t = online_tasks.get(user_id)
    if t is None or t.done():
        online_tasks[user_id] = asyncio.create_task(keep_online_loop(user_id, client))
    return True


def compute_clock_name_and_bio(user_id, u_data, base_bio_text):
    """Joriy vaqt asosida yangi last_name va bio matnini hisoblaydi.
    base_bio_text — foydalanuvchining soat qo'shilmagan "toza" bio matni."""
    now_dt = datetime.now(TASHKENT_TZ)
    now_raw = now_dt.strftime("%H:%M")
    font_style = effective_font(u_data)
    now = apply_font(now_raw, font_style)

    new_last_name = now if u_data.get("nick_clock", True) else ""

    about_text = base_bio_text or ""
    if "|" in about_text:
        clean_bio = about_text.split("|")[0].strip()
    else:
        clean_bio = about_text
    clean_bio = re.sub(r"(🕒|⏳|🎂|🎄|✨|🕌|Soat @tmclock_bot|Good|Tug'ilgan|Yangi|Vatan|Qurbon|8-mart).*$", "", clean_bio).strip()

    extra_bio = build_bio_extra(u_data, now_dt, now)
    final_bio = build_final_bio(clean_bio, extra_bio, u_data.get("plan") == "Free")
    return new_last_name, final_bio


async def apply_business_clock_now(user_id):
    """Soat/bio'ni kutmasdan darhol yangilaydi ('Avtomatik o'rnatish' va qayta tekshirish uchun)."""
    try:
        u_data = get_user_data(user_id)
        conn_id = u_data.get("biz_connection_id")
        if not conn_id:
            return
        new_last_name, final_bio = compute_clock_name_and_bio(user_id, u_data, u_data.get("biz_base_bio", ""))
        if u_data.get("biz_can_name", False):
            await bot.set_business_account_name(
                business_connection_id=conn_id,
                first_name=await current_first_name(user_id, u_data),
                last_name=new_last_name,
            )
        if biz_should_set_bio(u_data):
            await bot.set_business_account_bio(business_connection_id=conn_id, bio=final_bio)
    except Exception as e:
        print(f"Darhol soat yangilash xatosi ({user_id}):", e)


async def start_business_clock(user_id):
    """Telegram Business ulanishi orqali (kodsiz) ism/bio'ni har daqiqada yangilab turadi."""
    while user_id in active_biz_clocks:
        try:
            u_data = get_user_data(user_id)
            conn_id = u_data.get("biz_connection_id")
            if not conn_id:
                break

            if u_data.get("plan") != "Free" and u_data.get("plan_expire") != "Mavjud emas":
                try:
                    exp_dt = datetime.strptime(u_data.get("plan_expire"), "%Y-%m-%d %H:%M:%S")
                    exp_dt = exp_dt.replace(tzinfo=TASHKENT_TZ)
                    if datetime.now(TASHKENT_TZ) > exp_dt:
                        u_data["plan"] = "Free"
                        u_data["plan_expire"] = "Mavjud emas"
                        save_db(db)
                except Exception:
                    pass

            new_last_name, final_bio = compute_clock_name_and_bio(user_id, u_data, u_data.get("biz_base_bio", ""))

            if u_data.get("biz_can_name", False):
                try:
                    await bot.set_business_account_name(
                        business_connection_id=conn_id,
                        first_name=await current_first_name(user_id, u_data),
                        last_name=new_last_name,
                    )
                except Exception as e:
                    print(f"Biznes ism yangilash xatosi ({user_id}):", e)

            if biz_should_set_bio(u_data):
                try:
                    await bot.set_business_account_bio(business_connection_id=conn_id, bio=final_bio)
                except Exception as e:
                    print(f"Biznes bio yangilash xatosi ({user_id}):", e)

        except Exception as err:
            msg = str(err).lower()
            if "business" in msg and ("not found" in msg or "connection" in msg):
                active_biz_clocks.pop(user_id, None)
                u_data = get_user_data(user_id)
                u_data["biz_active"] = False
                save_db(db)
                try:
                    await bot.send_message(user_id, "⚠️ Telegram Business ulanishi uzildi. Soatni qaytadan ulang.")
                except Exception:
                    pass
                break
            else:
                print(f"Biznes soat xatosi ({user_id}):", err)

        now_sec = datetime.now(TASHKENT_TZ).second
        sleep_time = 60 - now_sec
        if sleep_time <= 0:
            sleep_time = 60
        await asyncio.sleep(sleep_time)


async def start_user_clock(user_id, client):
    # Soat qayta ishga tushsa, eski online-ushlagich takrorlanib qolmasligi uchun almashtiramiz
    old_task = online_tasks.get(user_id)
    if old_task and not old_task.done():
        old_task.cancel()
    online_tasks[user_id] = asyncio.create_task(keep_online_loop(user_id, client))
    persist_session(user_id, client)
    while user_id in active_clocks:
        try:
            u_data = get_user_data(user_id)
            if u_data.get("online_mode", False):
                ensure_online_task(user_id)   # online-ushlagich to'xtab qolgan bo'lsa, qayta ishga tushiradi
            
            if u_data.get("plan") != "Free" and u_data.get("plan_expire") != "Mavjud emas":
                try:
                    exp_dt = datetime.strptime(u_data.get("plan_expire"), "%Y-%m-%d %H:%M:%S")
                    exp_dt = exp_dt.replace(tzinfo=TASHKENT_TZ)
                    if datetime.now(TASHKENT_TZ) > exp_dt:
                        u_data["plan"] = "Free"
                        u_data["plan_expire"] = "Mavjud emas"
                        u_data["online_mode"] = False
                        save_db(db)
                except Exception:
                    pass

            now_dt = datetime.now(TASHKENT_TZ)
            now_raw = now_dt.strftime("%H:%M")
            font_style = effective_font(u_data)
            now = apply_font(now_raw, font_style)
            
            me = await client.get_me()
            full_user = await client(functions.users.GetFullUserRequest(id=me))
            
            about_text = ""
            if hasattr(full_user, "about"):
                about_text = full_user.about or ""
            elif hasattr(full_user, "full_user") and hasattr(full_user.full_user, "about"):
                about_text = full_user.full_user.about or ""

            # Faqat Premium tarifidagilar uchun Online rejim
            if u_data.get("plan") == "Premium" and u_data.get("online_mode", False):
                try:
                    await client(functions.account.UpdateStatusRequest(offline=False))
                except Exception:
                    pass

            first_name = clean_first_name(me.first_name)
            
            if u_data.get("nick_clock", True):
                new_last_name = now
            else:
                new_last_name = ""

            if "|" in about_text:
                clean_bio = about_text.split("|")[0].strip()
            else:
                clean_bio = about_text
            
            clean_bio = re.sub(r"(🕒|⏳|🎂|🎄|✨|🕌|Soat @tmclock_bot|Good|Tug'ilgan|Yangi|Vatan|Qurbon|8-mart).*$", "", clean_bio).strip()
            
            extra_bio = build_bio_extra(u_data, now_dt, now)
            final_bio = build_final_bio(clean_bio, extra_bio, u_data.get("plan") == "Free")

            await client(
                functions.account.UpdateProfileRequest(
                    first_name=first_name, last_name=new_last_name, about=final_bio[:70]
                )
            )

        except (AuthKeyDuplicatedError, UserDeactivatedError, Exception) as err:
            if "authorization" in str(err).lower() or "session" in str(err).lower() or isinstance(err, (AuthKeyDuplicatedError, UserDeactivatedError)):
                active_clocks.pop(user_id, None)
                u_data = get_user_data(user_id)
                u_data["clock_active"] = False
                save_db(db)
                try:
                    await bot.send_message(user_id, "Siz botni profilingizdan chiqarib yubordingiz, iltimos qaytadan urinib ko'ring")
                except Exception:
                    pass
                break
            else:
                print(f"Soat yangilash xatosi ({user_id}):", err)

        now_sec = datetime.now(TASHKENT_TZ).second
        sleep_time = 60 - now_sec
        if sleep_time <= 0:
            sleep_time = 60
        await asyncio.sleep(sleep_time)


async def process_business_connection(business_connection: types.BusinessConnection, manual_recheck=False):
    """business_connection event kelganda HAM, qo'lda 'qayta tekshirish' bosilganda HAM shu funksiya ishlaydi.
    Telefon orqali ulangan soat bor bo'lsa yoki ism huquqi berilmagan bo'lsa — bu ulanish FAQAT chat nazorati
    va avto javob uchun ishlatiladi (soat/ism huquqi talab qilinmaydi)."""
    user_id = business_connection.user.id
    u_data = get_user_data(user_id)
    if u_data.get("banned"):
        return
    rights = business_connection.rights

    if not business_connection.is_enabled:
        # Kech kelgan eski "o'chirildi" xabari yangi ulanishni buzmasligi uchun haqiqiy holatni Telegram'dan so'raymiz
        try:
            fresh = await bot.get_business_connection(business_connection_id=business_connection.id)
            if fresh and fresh.is_enabled:
                business_connection = fresh
                rights = fresh.rights
        except Exception:
            pass

    if not business_connection.is_enabled:
        stored = u_data.get("biz_connection_id")
        if stored and stored != business_connection.id:
            return   # bu boshqa (eski) ulanish haqida — hozirgisini tegmaymiz
        biz_conn_to_user.pop(stored, None)
        active_biz_clocks.pop(user_id, None)
        u_data["biz_active"] = False
        u_data["biz_connection_id"] = None
        u_data["antidelete_active"] = False
        save_db(db)
        try:
            await bot.send_message(user_id, "🔴✨ Telegram Business ulanishi o'chirildi — chat nazorati va avto javob to'xtatildi.")
        except Exception:
            pass
        return

    can_name = bool(getattr(rights, "can_edit_name", False)) if rights else False
    can_bio = bool(getattr(rights, "can_edit_bio", False)) if rights else False
    can_msg = bool(getattr(rights, "can_reply", False)) if rights else False

    was_new = u_data.get("biz_connection_id") != business_connection.id
    u_data["biz_first_name"] = strip_clock(business_connection.user.first_name) or u_data.get("biz_first_name", "")
    u_data["biz_can_read"] = chatctl_can_read(business_connection, user_id)
    u_data["biz_connection_id"] = business_connection.id
    u_data["biz_can_name"] = can_name
    u_data["biz_can_bio"] = can_bio
    u_data["biz_can_msg"] = can_msg
    biz_conn_to_user[business_connection.id] = user_id

    if u_data.get("clock_active") and user_id not in active_clocks:
        if not await restore_phone_clock(user_id):
            u_data["clock_active"] = False     # sessiya yo'q — soat aslida ishlamayapti
    phone_clock = user_id in active_clocks

    # ---------- Faqat chat nazorati / avto javob ulanishi ----------
    if phone_clock or not can_name:
        active_biz_clocks.pop(user_id, None)
        u_data["biz_active"] = False
        if was_new:
            u_data["antidelete_active"] = True      # yangi ulanganda chat nazorati avtomatik yoqiladi
        save_db(db)
        lines = ["💬✅ <b>Chat nazorati ulandi!</b> ✅💬", "━━━━━━━━━━━━━━━"]
        if phone_clock:
            lines.append("🕒 Soat telefon orqali ishlashda davom etadi.")
        lines.append("📡 Chat nazorati yoqildi: o'chirilgan 🗑 va tahrirlangan ✏️ xabarlarni sizga yuboraman.")
        lines.append("🤖 Avto javob uchun menyudagi «Avto javob 🤖» bo'limiga kiring.")
        if not can_msg:
            lines.append("\nℹ️ Avto javob ishlashi uchun Chatbots'da «Xabarlarga javob berish» ruxsatini ham yoqing.")
        if not phone_clock:
            lines.append("\nℹ️ Soatni Business orqali ishlatmoqchi bo'lsangiz «Ism va bio» ruxsatini ham bering va "
                         "«Soat Sozlamalari» dagi 🔄 tugmani bosing (ixtiyoriy).")
        try:
            await bot.send_message(user_id, "\n".join(lines), reply_markup=main_menu, parse_mode="HTML")
        except Exception:
            pass
        return

    # ---------- Soat Business orqali ----------
    if not u_data.get("biz_base_bio"):
        try:
            chat = await bot.get_chat(user_id)
            u_data["biz_base_bio"] = getattr(chat, "bio", None) or ""
        except Exception:
            pass

    u_data["biz_active"] = True
    u_data["setup_method"] = "business"
    save_db(db)

    if user_id not in active_biz_clocks:
        active_biz_clocks[user_id] = True
        asyncio.create_task(start_business_clock(user_id))
    else:
        await apply_business_clock_now(user_id)

    bio_note = "" if can_bio else "\nℹ️ Bio huquqi berilmagan — faqat ismdagi soat ishlaydi."
    msg_note = (
        "\n💬 Chat nazorati va 🤖 Avto javob ham mavjud — asosiy menyudan boshqaring."
        if can_msg
        else ""
    )
    title = "🔄✅ <b>Qayta tekshirildi — hammasi joyida!</b> ✅🔄" if manual_recheck else "🎉✅ <b>Soat bot muvaffaqiyatli qo'shildi!</b> ✅🎉"
    try:
        await bot.send_message(
            user_id,
            f"{title}\n"
            "━━━━━━━━━━━━━━━\n"
            "💼 Ulanish usuli: <b>Telegram Business</b>\n\n"
            "🕒 Soat 1 daqiqa ichida ismingizda avtomatik ko'rinadi!"
            f"{bio_note}{msg_note}",
            reply_markup=main_menu,
            parse_mode="HTML",
        )
    except Exception:
        pass


@dp.business_connection()
async def handle_business_connection(business_connection: types.BusinessConnection):
    """Foydalanuvchi botni Sozlamalar → Telegram Business → Chatbots orqali ulasa/uzsa shu yerga keladi."""
    await process_business_connection(business_connection, manual_recheck=False)


@dp.callback_query(F.data == "recheck_business")
async def recheck_business_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    conn_id = u_data.get("biz_connection_id")
    if not conn_id:
        await call.answer(
            "⚠️ Hali ulanish topilmadi. Avval botni Sozlamalar → Telegram Business → Chatbots orqali qo'shing.",
            show_alert=True,
        )
        return
    await call.answer("🔄 Tekshirilmoqda...")
    try:
        fresh_connection = await bot.get_business_connection(business_connection_id=conn_id)
        await process_business_connection(fresh_connection, manual_recheck=True)
    except Exception as e:
        try:
            await call.message.answer(f"❌ Tekshirishda xatolik: {e}\n\nBotni Chatbots ro'yxatidan o'chirib, qaytadan qo'shib ko'ring.")
        except Exception:
            pass


def extract_msg_content(message):
    """(matn, tur, file_id) qaytaradi."""
    caption = message.caption or ""
    if message.text:
        return message.text, "text", None
    if message.photo:
        return caption or "[rasm]", "photo", message.photo[-1].file_id
    if message.video:
        return caption or "[video]", "video", message.video.file_id
    if message.voice:
        return caption or "[ovozli xabar]", "voice", message.voice.file_id
    if message.video_note:
        return "[dumaloq video]", "video_note", message.video_note.file_id
    if message.audio:
        return caption or "[audio]", "audio", message.audio.file_id
    if message.animation:
        return caption or "[GIF]", "animation", message.animation.file_id
    if message.document:
        return caption or "[fayl]", "document", message.document.file_id
    if message.sticker:
        return "[stiker]", "sticker", message.sticker.file_id
    return "[boshqa turdagi xabar]", "other", None


KIND_LABEL = {
    "text": "💬 Matn", "photo": "🖼 Rasm", "video": "🎬 Video", "voice": "🎤 Ovozli xabar",
    "video_note": "⭕️ Dumaloq video", "audio": "🎵 Audio", "animation": "🎞 GIF",
    "document": "📎 Fayl", "sticker": "😀 Stiker", "other": "📦 Xabar",
}


async def resend_cached_media(owner_id, cached, caption):
    kind, fid = cached.get("kind"), cached.get("file_id")
    if not fid:
        return
    sender = {
        "photo": bot.send_photo, "video": bot.send_video, "voice": bot.send_voice,
        "video_note": bot.send_video_note, "audio": bot.send_audio,
        "animation": bot.send_animation, "document": bot.send_document, "sticker": bot.send_sticker,
    }.get(kind)
    if not sender:
        return
    param = {"photo": "photo", "video": "video", "voice": "voice", "video_note": "video_note",
             "audio": "audio", "animation": "animation", "document": "document", "sticker": "sticker"}[kind]
    kwargs = {"chat_id": owner_id, param: fid}
    if kind not in ("video_note", "sticker"):
        kwargs["caption"] = caption
        kwargs["parse_mode"] = "HTML"
    await sender(**kwargs)


def esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def person_line(user_id, username):
    """Odamning @username'i, bo'lmasa — chatiga kiruvchi havola."""
    if username:
        return f"🔗 Username: @{esc(username)}\n"
    if user_id:
        return f'🔗 Username: yo\'q — <a href="tg://user?id={user_id}">chatga kirish</a>\n'
    return ""


async def resolve_owner(conn_id):
    """business_connection_id -> egasining ID si. Bot qayta ishga tushib xotira/baza yo'qolgan bo'lsa ham,
    Telegram'dan so'rab, ulanishni qayta tiklaydi (shuning uchun 'o'rnatmadingiz' xatosi chiqmaydi)."""
    if not conn_id:
        return None
    owner = biz_conn_to_user.get(conn_id)
    if owner:
        return owner
    try:
        conn = await bot.get_business_connection(business_connection_id=conn_id)
    except Exception as e:
        print("Ulanishni aniqlab bo'lmadi:", e)
        return None
    if not conn or not conn.is_enabled:
        return None
    owner = conn.user.id
    biz_conn_to_user[conn_id] = owner
    u = get_user_data(owner)
    rights = conn.rights
    u["biz_connection_id"] = conn_id
    u["biz_can_name"] = bool(getattr(rights, "can_edit_name", False)) if rights else False
    u["biz_can_bio"] = bool(getattr(rights, "can_edit_bio", False)) if rights else False
    u["biz_can_msg"] = bool(getattr(rights, "can_reply", False)) if rights else False
    if not u.get("biz_first_name"):
        u["biz_first_name"] = strip_clock(conn.user.first_name)
    save_db(db)
    return owner


# ------------------- AVTO JAVOB (xotira) -------------------
AUTOREPLY_MAX_PER_HOUR = 3           # bir odamga 1 soatda ko'pi bilan 3 ta xabar
OWNER_ACTIVE_WINDOW = 10 * 60        # egasi shu chatda 10 daqiqa ichida yozgan bo'lsa — javob yubormaymiz
AUTO_AWAY_AFTER = 15 * 60            # "Avtomatik" rejim: egasi 15 daqiqa hech qayerda yozmasa — "yo'q" deb hisoblanadi
autoreply_sent = {}                  # (conn_id, chat_id) -> [yuborilgan vaqtlar]
owner_last_write = {}                # (conn_id, chat_id) -> egasi oxirgi marta yozgan vaqt
owner_last_any = {}                  # owner_id -> egasi istalgan chatda oxirgi marta yozgan vaqt


def autoreply_mode(u_data):
    """'open' (Ochiq — yubormaydi) | 'closed' (Yopiq — doim yuboradi) | 'auto' (Avtomatik)."""
    m = u_data.get("autoreply_mode")
    if m in ("open", "closed", "auto"):
        return m
    return "closed" if u_data.get("autoreply_active") else "open"   # eski sozlamadan o'tkazish


async def maybe_autoreply(message, owner_id, u_data):
    if not (u_data.get("autoreply_text") or "").strip():
        return
    mode = autoreply_mode(u_data)
    if mode == "open":
        return                                   # Ochiq: egasi Telegramda — yubormaymiz
    if not u_data.get("biz_can_msg", False):
        return
    chat = message.chat
    if chat.type != "private" or (message.from_user and message.from_user.is_bot):
        return
    key = (message.business_connection_id, chat.id)
    now = time.time()
    if mode == "auto" and now - owner_last_any.get(owner_id, 0) < AUTO_AWAY_AFTER:
        return                                   # Avtomatik: egasi yaqinda faol bo'lgan — yubormaymiz
    if now - owner_last_write.get(key, 0) < OWNER_ACTIVE_WINDOW:
        return
    recent = [t for t in autoreply_sent.get(key, []) if now - t < 3600]
    if len(recent) >= AUTOREPLY_MAX_PER_HOUR:
        autoreply_sent[key] = recent
        return
    first_in_window = not recent
    recent.append(now)
    autoreply_sent[key] = recent
    try:
        await bot.send_message(
            chat_id=chat.id,
            text=u_data["autoreply_text"],
            business_connection_id=message.business_connection_id,
        )
    except Exception as e:
        recent.pop()
        print(f"Avto javob yuborilmadi ({owner_id}):", e)
        return

    # Egasiga: kim yozgani (faqat username, xabar matni ko'rsatilmaydi). Spam bo'lmasligi uchun soatiga 1 marta.
    if first_in_window:
        fu = message.from_user
        if fu and fu.username:
            who = f"@{esc(fu.username)}"
        elif fu:
            who = f'<a href="tg://user?id={fu.id}">{esc(fu.full_name)}</a>'
        else:
            who = esc(chat.full_name or chat.title or "Noma'lum")
        try:
            await bot.send_message(owner_id, f"📨 Sizga yozdi: {who}", parse_mode="HTML")
        except Exception as e:
            print(f"Avto javob bildirishnomasi yuborilmadi ({owner_id}):", e)


@dp.business_message()
async def cache_business_message(message: types.Message):
    """Business chatlardagi xabarlarni keshlaymiz (matn + rasm/ovoz/video file_id) — chat nazorati yoqilgan bo'lsa."""
    conn_id = message.business_connection_id
    owner_id = await resolve_owner(conn_id)
    if not owner_id:
        return
    biz_msg_seen[owner_id] = time.time()
    u_data = get_user_data(owner_id)
    if u_data.get("banned"):
        return

    # Egasining o'z xabari: avto javob uchun "band emas" belgisi; keshlanmaydi
    if message.from_user and message.from_user.id == owner_id:
        owner_last_write[(conn_id, message.chat.id)] = time.time()
        owner_last_any[owner_id] = time.time()
        return

    try:
        await maybe_autoreply(message, owner_id, u_data)
    except Exception as e:
        print("Avto javob xatosi:", e)

    if not u_data.get("antidelete_active", False):
        return

    content, kind, file_id = extract_msg_content(message)
    sender = message.from_user.full_name if message.from_user else "Noma'lum"
    sender_id = message.from_user.id if message.from_user else None
    sender_username = message.from_user.username if message.from_user else None
    chat = message.chat
    chat_title = chat.title or chat.full_name or chat.first_name or "Shaxsiy chat"

    business_msg_cache[(conn_id, chat.id, message.message_id)] = {
        "text": content, "kind": kind, "file_id": file_id,
        "sender": sender, "chat_title": chat_title,
        "sender_id": sender_id, "sender_username": sender_username,
    }
    while len(business_msg_cache) > BUSINESS_CACHE_LIMIT:
        business_msg_cache.popitem(last=False)


@dp.edited_business_message()
async def handle_edited_business_message(message: types.Message):
    """Xabar tahrirlansa: avval yozilgan matn va tahrirdan keyingi matnni ko'rsatadi."""
    conn_id = message.business_connection_id
    owner_id = await resolve_owner(conn_id)
    if not owner_id:
        return
    u_data = get_user_data(owner_id)
    if not u_data.get("antidelete_active", False):
        return
    if message.from_user and message.from_user.id == owner_id:
        return

    chat = message.chat
    chat_title = chat.title or chat.full_name or chat.first_name or "Shaxsiy chat"
    sender = message.from_user.full_name if message.from_user else "Noma'lum"
    sender_id = message.from_user.id if message.from_user else None
    sender_username = message.from_user.username if message.from_user else None
    new_text, kind, file_id = extract_msg_content(message)

    key = (conn_id, chat.id, message.message_id)
    cached = business_msg_cache.get(key)
    old_text = cached["text"] if cached else None

    business_msg_cache[key] = {"text": new_text, "kind": kind, "file_id": file_id,
                               "sender": sender, "chat_title": chat_title,
                               "sender_id": sender_id, "sender_username": sender_username}
    try:
        if old_text is not None and old_text != new_text:
            await bot.send_message(
                owner_id,
                f"✏️ <b>Xabar tahrirlandi!</b> ✏️\n"
                "━━━━━━━━━━━━━━━\n"
                f"💬 Chat: <b>{esc(chat_title)}</b>\n"
                f"👤 Kim: <b>{esc(sender)}</b>\n"
                f"{person_line(sender_id, sender_username)}\n"
                f"⏮ <b>Avval yozgani:</b>\n<blockquote>{esc(old_text)}</blockquote>\n"
                f"⏭ <b>Tahrirdan keyin:</b>\n<blockquote>{esc(new_text)}</blockquote>",
                parse_mode="HTML",
            )
    except Exception as e:
        print(f"Anti-edit xabar yuborishda xato ({owner_id}):", e)


@dp.deleted_business_messages()
async def handle_deleted_business_messages(event: types.BusinessMessagesDeleted):
    """Xabar o'chirilganda: kim yozgan, nima yozgan — matn bo'lsa matnni, rasm/ovoz/video bo'lsa o'zini qaytarib beradi."""
    owner_id = await resolve_owner(event.business_connection_id)
    if not owner_id:
        return
    u_data = get_user_data(owner_id)
    if not u_data.get("antidelete_active", False):
        return

    chat = event.chat
    chat_title = chat.title or chat.full_name or chat.first_name or "Noma'lum chat"

    for message_id in event.message_ids:
        key = (event.business_connection_id, chat.id, message_id)
        cached = business_msg_cache.pop(key, None)
        if not cached:
            continue  # bizda saqlanmagan (egasining o'z xabari yoki bot ulanishidan oldingi) — shovqin qilmaymiz
        label = KIND_LABEL.get(cached.get("kind"), "📦 Xabar")
        s_id = cached.get("sender_id") or (chat.id if chat.id > 0 else None)
        head = (
            "🗑 <b>Xabar o'chirildi!</b> 🗑\n"
            "━━━━━━━━━━━━━━━\n"
            f"💬 Chat: <b>{esc(chat_title)}</b>\n"
            f"👤 Yozgan odam: <b>{esc(cached['sender'])}</b>\n"
            f"{person_line(s_id, cached.get('sender_username'))}"
            f"📌 Turi: {label}\n"
        )
        try:
            if cached.get("kind") == "text" or not cached.get("file_id"):
                await bot.send_message(
                    owner_id, head + f"\n📝 <b>Yozgani:</b>\n<blockquote>{esc(cached['text'])}</blockquote>",
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(owner_id, head + "\n⬇️ <b>O'chirilgan fayl pastda:</b>", parse_mode="HTML")
                await resend_cached_media(owner_id, cached, f"🗑 {esc(cached['sender'])} o'chirgan {label.lower()}" +
                                          (f"\n\n{esc(cached['text'])}" if cached['text'] and not cached['text'].startswith('[') else ""))
        except Exception as e:
            print(f"Anti-delete xabar yuborishda xato ({owner_id}):", e)


# ======================= CHAT NAZORATI (asosiy menyu) =======================
def reset_business_state(user_id, u_data):
    """Ulanish yo'q bo'lib qolgan (eskirgan) holatni tozalaydi."""
    biz_conn_to_user.pop(u_data.get("biz_connection_id"), None)
    active_biz_clocks.pop(user_id, None)
    u_data["biz_active"] = False
    u_data["biz_connection_id"] = None
    u_data["antidelete_active"] = False
    save_db(db)


async def verify_business_connection(user_id, u_data):
    """Ulanish HAQIQATAN mavjudligini Telegram'dan tekshiradi.
    (conn, status) qaytaradi: status = 'ok' | 'gone' | 'error'."""
    conn_id = u_data.get("biz_connection_id")
    if not conn_id:
        return None, "gone"
    try:
        conn = await bot.get_business_connection(business_connection_id=conn_id)
    except TelegramBadRequest as e:
        m = str(e).lower()
        if "not found" in m or "invalid" in m:
            conn = None
        else:
            print(f"Business ulanishni tekshirishda xato ({user_id}):", e)
            return None, "error"
    except Exception as e:
        print(f"Business ulanishni tekshirishda xato ({user_id}):", e)
        return None, "error"
    if conn is None or not conn.is_enabled:
        reset_business_state(user_id, u_data)
        return None, "gone"
    return conn, "ok"


biz_msg_seen = {}   # owner_id -> oxirgi marta business xabari kelgan vaqt (kelayotgan bo'lsa — o'qish ruxsati bor)


def rights_summary(conn):
    """Telegram haqiqatda bergan ruxsatlar ro'yxati (tashxis uchun)."""
    r = getattr(conn, "rights", None)
    if r is None:
        return "rights yo'q"
    try:
        flags = r.model_dump(exclude_none=True)
    except Exception:
        flags = {k: getattr(r, k) for k in dir(r) if k.startswith("can_")}
    on = [k.replace("can_", "") for k, v in flags.items() if v is True]
    return ", ".join(on) or "hech narsa"


def chatctl_can_read(conn, user_id=None):
    """Xabarlarni o'qish ruxsati bormi? Telegram `can_read_messages` ni faqat YOQILGAN bo'lsagina yuboradi
    (o'chiq bo'lsa maydon None bo'ladi) — shuning uchun None/yo'qni darhol 'yo'q' deb hisoblamaymiz:
    eski ulanishlarda `can_reply` bor bo'lsa, yoki ulanish orqali xabarlar HAQIQATAN kelayotgan bo'lsa — ruxsat bor."""
    rights = getattr(conn, "rights", None)
    if rights is not None and getattr(rights, "can_read_messages", None) is True:
        return True
    if rights is None and getattr(conn, "can_reply", None):
        return True
    if user_id and time.time() - biz_msg_seen.get(user_id, 0) < 3 * 86400:
        return True
    return False


def chatctl_missing(conn, user_id=None):
    """Ruxsat YETISHMASLIGI endi chat nazoratini bloklamaydi: ulanish mavjud bo'lsa, Telegram xabarlarni
    baribir yuboradi. (Avval 'xabarlarni o'qish' bayrog'i kelmasa ham 'o'rnatmadingiz' deb chiqardi — shu xato edi.)"""
    return []


def chat_control_text(u_data, missing=None):
    if missing:
        status = "⚠️ Ruxsat yetarli emas"
    elif u_data.get("antidelete_active", False):
        status = "✅ Yoqilgan"
    else:
        status = "⭕️ O'chiq"
    warn = ""
    if missing:
        warn = (
            f"\n\n⚠️ Yetishmayotgan ruxsat: <b>{', '.join(missing)}</b>\n"
            "Sozlamalar → Telegram Business → Chatbots bo'limida botga shu ruxsatni bering, "
            "so'ng 🔄 tugmasini bosing."
        )
    return (
        "💬✨ <b>Chat nazorati</b> ✨💬\n"
        "━━━━━━━━━━━━━━━\n"
        f"📡 Holati: <b>{status}</b>\n\n"
        "Kimdir sizga yozib, keyin xabarni <b>o'chirsa</b> 🗑 yoki <b>tahrirlasa</b> ✏️ — men darhol sizga yuboraman:\n\n"
        "🗑 O'chirilgan matn — kim yozgani bilan\n"
        "🖼 O'chirilgan rasm / 🎤 ovozli xabar / 🎬 video — o'zini qaytarib beraman\n"
        "✏️ Tahrirlangan xabar — <b>avval yozgani</b> va <b>tahrirdan keyingisi</b>\n\n"
        "ℹ️ Bot faqat ulanganidan keyingi xabarlarni ko'ra oladi.\n"
        "Agar xabarlar kelmasa: Sozlamalar → Telegram Business → Chatbots bo'limida botga <b>«Xabarlarni o'qish»</b> ruxsatini bering."
        f"{warn}"
    )


def chat_control_kb(u_data, missing=None):
    rows = []
    if not missing:
        on = u_data.get("antidelete_active", False)
        rows.append([ibtn("⭕️ O'chirish" if on else "✅ Yoqish", callback_data="toggle_chatctl",
                          style="danger" if on else "success")])
    rows.append([ibtn("🔄 Ruxsatlarni qayta tekshirish", callback_data="recheck_chatctl", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def chatctl_guide_view():
    username = (await bot.get_me()).username
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("🛡 Ruxsat berish", url=PERMISSION_URL, style="primary")],
        [ibtn("🎬 Video Qo'llanma", url=VIDEO_GUIDE_URL, style="primary")],
        [ibtn("🔄 Qayta tekshirish (ulagandan keyin bosing)", callback_data="recheck_chatctl", style="success")],
    ])
    text = (
        "💬✨ <b>Chat nazorati</b> ✨💬\n━━━━━━━━━━━━━━━\n\n"
        "Bu funksiya uchun botni Telegram Business orqali ulang 👇\n\n"
        "1️⃣ \"🛡 <b>Ruxsat berish</b>\" tugmasini bosing.\n\n"
        "2️⃣ Ochilgan oynada \"<b>Chat automation</b>\" (Chatlarni avtomatlashtirish) qatorini bosing.\n\n"
        "3️⃣ Qidiruv maydoniga bot username'ini kiriting:\n"
        f"<code>@{username}</code>\n\n"
        "4️⃣ Ruxsatlarda faqat shuni yoqish yetarli:\n"
        "     ✅ <b>Xabarlarni o'qish</b> (chat nazorati uchun)\n"
        "     ➕ «Xabarlarga javob berish» — faqat Avto javob uchun (ixtiyoriy)\n\n"
        "5️⃣ Saqlang va botga qayting 👇 «Qayta tekshirish» ni bosing.\n\n"
        "ℹ️ Soat telefon orqali ishlayotgan bo'lsa, ism va bio ruxsatlari kerak emas — soatingizga tegilmaydi."
    )
    return text, kb


async def show_chatctl_guide(call):
    try:
        text, kb = await chatctl_guide_view()
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@dp.message(F.text == "Chat nazorati 💬")
async def chat_control_menu(message: types.Message):
    user_id = message.from_user.id
    u_data = get_user_data(user_id)
    conn, st = await verify_business_connection(user_id, u_data)

    if st == "gone":
        text, kb = await chatctl_guide_view()
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return
    if st == "error":
        await message.answer("❌ Telegram bilan bog'lanib bo'lmadi, birozdan so'ng qayta urinib ko'ring.")
        return

    missing = chatctl_missing(conn, user_id) if conn else []
    if missing:
        if u_data.get("antidelete_active", False):
            u_data["antidelete_active"] = False
            save_db(db)
    elif conn and not u_data.get("antidelete_active", False):
        u_data["antidelete_active"] = True
        save_db(db)
    await message.answer(chat_control_text(u_data, missing), reply_markup=chat_control_kb(u_data, missing),
                         parse_mode="HTML")


@dp.callback_query(F.data == "toggle_chatctl")
async def toggle_chatctl_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    conn, st = await verify_business_connection(user_id, u_data)
    if st == "gone":
        await call.answer("⚠️ Bot Telegram Business orqali ulanmagan. Avval ruxsat bering.", show_alert=True)
        await show_chatctl_guide(call)
        return
    missing = chatctl_missing(conn, user_id) if conn else []
    if missing:
        u_data["antidelete_active"] = False
        save_db(db)
        await call.answer("⚠️ Yetishmayotgan ruxsat: " + ", ".join(missing), show_alert=True)
    else:
        u_data["antidelete_active"] = not u_data.get("antidelete_active", False)
        save_db(db)
        await call.answer("✅ Chat nazorati yoqildi!" if u_data["antidelete_active"] else "⭕️ Chat nazorati o'chirildi.")
    try:
        await call.message.edit_text(chat_control_text(u_data, missing), reply_markup=chat_control_kb(u_data, missing),
                                     parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data == "recheck_chatctl")
async def recheck_chatctl_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    conn, st = await verify_business_connection(user_id, u_data)
    if st == "gone":
        await call.answer(
            "⚠️ Ulanish topilmadi. Sozlamalar → Telegram Business → Chatbots orqali botni qo'shing va hamma ruxsatlarni bering.",
            show_alert=True,
        )
        await show_chatctl_guide(call)
        return
    if st == "error":
        await call.answer("❌ Tekshirib bo'lmadi, birozdan so'ng qayta urinib ko'ring.", show_alert=True)
        return

    rights = conn.rights
    u_data["biz_can_msg"] = bool(getattr(rights, "can_reply", False)) if rights else False
    missing = chatctl_missing(conn, user_id)
    u_data["antidelete_active"] = not missing
    print(f"Ruxsat tekshiruvi {user_id}: Telegram bergan = {rights_summary(conn)}; yetishmayotgan = {missing}")
    save_db(db)

    others = []
    if rights:
        if not getattr(rights, "can_reply", False):
            others.append("javob berish")
    if missing:
        msg = ("⚠️ Chat nazorati yoqilmadi. Yetishmayotgan ruxsat: " + ", ".join(missing) +
               f"\nTelegram bergan: {rights_summary(conn)}")[:195]
    elif others:
        msg = "✅ Chat nazorati yoqildi! (Avto javob uchun «javob berish» ruxsati ham kerak)"
    else:
        msg = "✅ Hammasi joyida, chat nazorati yoqilgan!"
    await call.answer(msg, show_alert=True)
    try:
        await call.message.edit_text(chat_control_text(u_data, missing), reply_markup=chat_control_kb(u_data, missing),
                                     parse_mode="HTML")
    except Exception:
        pass


# ======================= AVTO JAVOB =======================
class AutoReplyState(StatesGroup):
    waiting_text = State()


def autoreply_view(u_data, can_reply=True):
    text_saved = (u_data.get("autoreply_text") or "").strip()
    mode = autoreply_mode(u_data)
    mode_label = {"open": "🟢 Ochiq", "closed": "🔴 Yopiq", "auto": "🤖 Avtomatik"}[mode]
    shown = f"<blockquote>{esc(text_saved)}</blockquote>" if text_saved else "<i>Hali matn kiritilmagan</i>"
    warn = "" if can_reply else (
        "\n\n⚠️ Botga <b>«Javob berish»</b> ruxsati berilmagan. Sozlamalar → Telegram Business → Chatbots "
        "bo'limida shu ruxsatni yoqing."
    )
    text = (
        "🤖✨ <b>Avto javob</b> ✨🤖\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Siz offline (Telegramdan chiqib ketgan) yoki band bo'lsangiz, sizga yozgan odamlarga "
        "o'zingiz yozgan xabarni men yuboraman 📨\n\n"
        "<b>Rejimlar:</b>\n"
        "🟢 <b>Ochiq</b> — yubormayman. Siz Telegramda o'zingiz javob berasiz.\n"
        "🔴 <b>Yopiq</b> — odamlarga har doim xabaringizni yuboraman (siz band yoki chetdasiz).\n"
        "🤖 <b>Avtomatik</b> — aqlli rejim: siz Telegramda faol bo'lsangiz yubormayman, "
        "chiqib ketsangiz (15 daqiqa hech narsa yozmasangiz) o'zim javob beraman.\n\n"
        f"📡 Hozirgi rejim: <b>{mode_label}</b>\n"
        f"📝 Matn:\n{shown}\n\n"
        "ℹ️ Bir odamga 1 soatda ko'pi bilan <b>3 ta</b> xabar yuboriladi. Siz shu chatda o'zingiz yozayotgan bo'lsangiz "
        "(oxirgi 10 daqiqa) — yuborilmaydi.\n"
        "ℹ️ Telegram botlarga online holatingizni ko'rsatmaydi, shuning uchun «Avtomatik» rejim sizning "
        "yozishingizga qarab aniqlaydi."
        f"{warn}"
    )
    rows = []
    if text_saved:
        def mb(label, m, style):
            return ibtn(("✅ " if mode == m else "") + label, callback_data=f"ar_mode_{m}",
                        style=style if mode == m else None)
        rows.append([mb("Ochiq", "open", "success"), mb("Yopiq", "closed", "danger"), mb("Avtomatik", "auto", "primary")])
        rows.append([
            ibtn("✏️ Matnni tahrirlash", callback_data="ar_edit", style="primary"),
            ibtn("🗑 Matnni o'chirish", callback_data="ar_delete", style="danger"),
        ])
    else:
        rows.append([ibtn("✏️ Matn kiritish", callback_data="ar_edit", style="primary")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def autoreply_open(target, user_id, edit=False):
    """target: Message (yangi xabar) yoki CallbackQuery.message (tahrirlash)."""
    u_data = get_user_data(user_id)
    conn, st = await verify_business_connection(user_id, u_data)
    if st == "gone":
        text, kb = await chatctl_guide_view()
        text = text.replace("Chat nazorati", "Avto javob", 1).replace(
            "Bu funksiya uchun botni Telegram Business orqali ulang", "Avto javob uchun botni Telegram Business orqali ulang", 1)
        if edit:
            try:
                await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
        return
    if st == "error":
        await target.answer("❌ Telegram bilan bog'lanib bo'lmadi, birozdan so'ng qayta urinib ko'ring.")
        return
    rights = conn.rights if conn else None
    can_reply = bool(getattr(rights, "can_reply", False)) if rights else bool(getattr(conn, "can_reply", False))
    u_data["biz_can_msg"] = can_reply
    save_db(db)
    text, kb = autoreply_view(u_data, can_reply)
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(F.text == "Avto javob 🤖")
async def autoreply_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await autoreply_open(message, message.from_user.id)


@dp.callback_query(F.data == "ar_edit")
async def autoreply_edit_cb(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AutoReplyState.waiting_text)
    await call.message.answer(
        "✍️ <b>Avto javob matnini yozing</b>\n\n"
        "Odamlar sizga yozganda shu matn yuboriladi. Masalan:\n"
        "<i>Salom! Hozir band/offlineman, tez orada javob beraman 🙌</i>\n\n"
        "Matnni hozir yuboring 👇",
        reply_markup=cancel_keyboard, parse_mode="HTML",
    )
    await call.answer()


@dp.message(AutoReplyState.waiting_text, F.text)
async def autoreply_save_text(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("❌ Matn bo'sh bo'lmasligi kerak. Qaytadan yuboring:", reply_markup=cancel_keyboard)
        return
    if len(txt) > 1000:
        await message.answer("❌ Matn juda uzun (1000 belgidan oshmasin). Qisqaroq yuboring:", reply_markup=cancel_keyboard)
        return
    user_id = message.from_user.id
    u_data = get_user_data(user_id)
    first_time = not (u_data.get("autoreply_text") or "").strip()
    u_data["autoreply_text"] = txt
    if first_time:
        u_data["autoreply_mode"] = "auto"      # birinchi marta saqlansa — aqlli (Avtomatik) rejim yoqiladi
    save_db(db)
    await state.clear()
    await message.answer("✅ Matn saqlandi!" + (" Rejim: 🤖 Avtomatik" if first_time else ""), reply_markup=main_menu)
    await autoreply_open(message, user_id)


@dp.message(AutoReplyState.waiting_text)
async def autoreply_wrong_input(message: types.Message):
    await message.answer("❌ Faqat matn yuboring (rasm/stiker emas).", reply_markup=cancel_keyboard)


@dp.callback_query(F.data.startswith("ar_mode_"))
async def autoreply_mode_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    if not (u_data.get("autoreply_text") or "").strip():
        await call.answer("Avval matn kiriting.", show_alert=True)
        return
    mode = call.data.replace("ar_mode_", "")
    if mode not in ("open", "closed", "auto"):
        await call.answer()
        return
    if autoreply_mode(u_data) == mode:
        await call.answer("Bu rejim allaqachon tanlangan.")
        return
    u_data["autoreply_mode"] = mode
    u_data["autoreply_active"] = mode != "open"
    save_db(db)
    msgs = {
        "open": "🟢 Ochiq: Telegramdagi vaqtingizda odamlarga xabar yubormayman.",
        "closed": "🔴 Yopiq: odamlarga xabaringizni yuboraman.",
        "auto": "🤖 Avtomatik: Telegramdan chiqib ketsangiz, o'zim javob beraman.",
    }
    await call.answer(msgs[mode], show_alert=True)
    await autoreply_open(call.message, user_id, edit=True)


@dp.callback_query(F.data == "ar_delete")
async def autoreply_delete_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    u_data["autoreply_text"] = ""
    u_data["autoreply_mode"] = "open"
    u_data["autoreply_active"] = False
    save_db(db)
    await call.answer("🗑 Matn o'chirildi")
    await autoreply_open(call.message, user_id, edit=True)


BROADCAST_EMOJIS = [
    "🔥", "✨", "🎉", "🕒", "💎", "🎁",
    "📢", "⚡️", "👑", "💰", "✅", "❤️",
    "🚀", "🌟", "🎮", "💬", "📌", "😊",
]


def broadcast_preview_kb():
    rows = []
    row = []
    for i, e in enumerate(BROADCAST_EMOJIS):
        row.append(InlineKeyboardButton(text=e, callback_data=f"bemoji_{i}"))
        if len(row) == 6:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(text="✅ Hammaga yuborish", callback_data="broadcast_send"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_preview_text(text):
    return (
        "📢✨ <b>Xabar oldindan ko'rinishi</b> ✨📢\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"{text}\n\n"
        "━━━━━━━━━━━━━━━\n"
        "👇 Pastdagi emojilardan bosib matningizga qo'shing, yoki yangi matn yozing (oxiriga qo'shiladi)."
    )


@dp.message(F.text == "/xabar", F.from_user.id == ADMIN_ID)
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminBroadcast.composing)
    await state.update_data(text="")
    await message.answer(
        "📢✨ <b>Hammaga xabar yuborish</b> ✨📢\n\nYubormoqchi bo'lgan matningizni yozing 👇",
        parse_mode="HTML",
    )


@dp.message(AdminBroadcast.composing, F.text)
async def admin_broadcast_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current = data.get("text", "")
    new_text = (current + "\n" + message.text).strip() if current else message.text
    await state.update_data(text=new_text)
    await message.answer(
        broadcast_preview_text(new_text), reply_markup=broadcast_preview_kb(), parse_mode="HTML"
    )


@dp.callback_query(AdminBroadcast.composing, F.data.startswith("bemoji_"))
async def admin_broadcast_add_emoji(call: types.CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_", 1)[1])
    emoji = BROADCAST_EMOJIS[idx]
    data = await state.get_data()
    new_text = (data.get("text", "") + " " + emoji).strip()
    await state.update_data(text=new_text)
    try:
        await call.message.edit_text(
            broadcast_preview_text(new_text), reply_markup=broadcast_preview_kb(), parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"{emoji} qo'shildi")


@dp.callback_query(AdminBroadcast.composing, F.data == "broadcast_cancel")
async def admin_broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Xabar yuborish bekor qilindi.")
    await call.answer()


@dp.callback_query(AdminBroadcast.composing, F.data == "broadcast_send")
async def admin_broadcast_send(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "").strip()
    if not text:
        await call.answer("⚠️ Matn bo'sh!", show_alert=True)
        return
    await state.clear()
    try:
        await call.message.edit_text("⏳ Yuborilmoqda...")
    except Exception:
        pass

    sent, failed = 0, 0
    for str_id in list(db.keys()):
        try:
            await bot.send_message(int(str_id), text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    try:
        await call.message.edit_text(
            f"✅✨ <b>Xabar yuborildi!</b>\n\n📬 Yetib bordi: <b>{sent}</b> ta\n🚫 Yetib bormadi: <b>{failed}</b> ta",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("Yuborildi ✅")


@dp.message(F.document, F.from_user.id == ADMIN_ID)
async def admin_restore_from_file(message: types.Message):
    """Admin backup.json faylini botga yuborsa, ma'lumotlar shundan tiklanadi."""
    doc = message.document
    if not (doc.file_name or "").lower().endswith(".json"):
        return
    try:
        f = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(f.file_path, buf)
        data = json.loads(buf.getvalue().decode("utf-8"))
        if not isinstance(data, dict) or "db" not in data:
            await message.answer("❌ Bu zaxira (backup.json) fayliga o'xshamaydi.")
            return
        sess = _apply_backup(data)
        await message.answer(
            f"♻️ Fayldan tiklandi:\n👥 Foydalanuvchilar: {len(db)}\n"
            f"🎟 Promokodlar: {len(promos_db)}\n🕒 Soat sessiyalari: {sess}\n\n"
            f"🕒 Soatlar qayta yoqilmoqda, Restart shart emas.\n"
            f"Agar biror soat ishlamasa, o'sha foydalanuvchi soatni qayta ulashi kerak."
        )
        # Soatlarni darhol ishga tushiramiz
        asyncio.create_task(resume_active_clocks())
    except Exception as e:
        await message.answer(f"❌ Tiklab bo'lmadi: {e}")


@dp.message(F.text.startswith("/addpromo"))
async def add_promo_admin_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) == 4:
        _, code, amount_str, uses_str = parts
        code_upper = code.upper()
        promos_db[code_upper] = {
            "amount": int(amount_str),
            "uses": int(uses_str)
        }
        save_promos(promos_db)
        
        copy_text = f"copromo {code_upper} {amount_str} {uses_str}"
        resp_msg = (
            f"✅ Promokod yaratildi: <b>{code_upper}</b> ({int(amount_str):,} so'm, {uses_str} ta limit)\n\n"
            f"📋 <b>Copy promo uchun:</b>\n"
            f"<code>{copy_text}</code>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Copy promo", callback_data=f"copy_promo_info_{code_upper}")]
            ]
        )
        await message.answer(resp_msg, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer("ℹ️ Foydalanish: <code>/addpromo <KOD> <summa> <limit></code>", parse_mode="HTML")


@dp.message(F.text.startswith("/3"))
async def admin_add_balance_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) == 3:
        _, target_user_id_str, amount_str = parts
        if target_user_id_str.isdigit() and amount_str.isdigit():
            target_user_id = int(target_user_id_str)
            amount = int(amount_str)
            
            u_data = get_user_data(target_user_id)
            u_data["balance"] += amount
            save_db(db)
            
            await message.answer(
                f"✅ Foydalanuvchi (<code>{target_user_id}</code>) balansiga <b>{amount:,} so'm</b> qo'shildi!\n"
                f"Jami balans: <b>{u_data['balance']:,} so'm</b>",
                parse_mode="HTML"
            )
            try:
                await bot.send_message(
                    target_user_id,
                    f"🎁 Admin tomonidan hisobingizga <b>{amount:,} so'm</b> qo'shildi! 💰",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            await message.answer("❌ ID va summa faqat raqamlardan iborat bo'lishi kerak!")
    else:
        await message.answer("ℹ️ Foydalanish: <code>/3 &lt;user_id&gt; &lt;summa&gt;</code>", parse_mode="HTML")


@dp.message(F.text.startswith("/setzero"))
async def admin_set_zero_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) == 2:
        _, target_user_id_str = parts
        if target_user_id_str.isdigit():
            target_user_id = int(target_user_id_str)
            u_data = get_user_data(target_user_id)
            u_data["balance"] = 0
            save_db(db)
            await message.answer(f"✅ Foydalanuvchi (<code>{target_user_id}</code>) balansi <b>0 so'm</b> qilindi!", parse_mode="HTML")
            try:
                await bot.send_message(
                    target_user_id,
                    "⚠️ Admin tomonidan hisobingiz <b>0 so'm</b> qilib qo'yildi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            await message.answer("❌ ID raqam noto'g'ri!")
    else:
        await message.answer("ℹ️ Foydalanish: <code>/setzero &lt;user_id&gt;</code>", parse_mode="HTML")


@dp.callback_query(F.data.startswith("copy_promo_info_"))
async def copy_promo_callback(call: types.CallbackQuery):
    c_code = call.data.replace("copy_promo_info_", "")
    pdata = promos_db.get(c_code, {})
    amt = pdata.get("amount", 0)
    uses = pdata.get("uses", 0)
    copy_payload = f"copromo {c_code} {amt} {uses}"
    await call.message.answer(
        f"📋 <b>Nusxalash uchun matn:</b>\n<code>{copy_payload}</code>",
        parse_mode="HTML"
    )
    await call.answer("Tayyor!")


@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        ref_id = int(args[1])
        if ref_id != user_id:
            u_data = get_user_data(user_id)
            if u_data.get("referred_by") is None:
                u_data["referred_by"] = ref_id
                ref_data = get_user_data(ref_id)
                ref_data["referrals_count"] = ref_data.get("referrals_count", 0) + 1
                save_db(db)

    get_user_data(user_id)
    first_name = esc(message.from_user.first_name or "Foydalanuvchi")
    await message.answer(
        f"👋✨ <b>Xush kelibsiz, {first_name}!</b> ✨\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕒 Profilingizga soat o'rnating, 🎮 PUBG UC xarid qiling va ko'proq imkoniyatlardan foydalaning.\n\n"
        f"👇 Pastdagi menyudan birini tanlang:",
        reply_markup=main_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "⬅️ Bekor qilish")
async def cancel_all_states(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌✨ Amal bekor qilindi.", reply_markup=main_menu)


@dp.message(F.text == "PUBG UC 🎮")
async def pubg_uc_menu(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "🎮✨ <b>PUBG Mobile UC do'koni</b> ✨🎮\n"
        "━━━━━━━━━━━━━━━\n\n"
        "💎 Kerakli UC miqdorini tanlang 👇"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="60 UC - 12,500 so'm", callback_data="buy_uc_60"),
                InlineKeyboardButton(text="325 UC - 58,200 so'm", callback_data="buy_uc_325"),
            ],
            [
                InlineKeyboardButton(text="660 UC - 117,300 so'm", callback_data="buy_uc_660"),
                InlineKeyboardButton(text="1800 UC - 290,000 so'm", callback_data="buy_uc_1800"),
            ],
            [
                InlineKeyboardButton(text="3850 UC - 570,200 so'm", callback_data="buy_uc_3850"),
                InlineKeyboardButton(text="8100 UC - 1,220,000 so'm", callback_data="buy_uc_8100"),
            ],
            [
                InlineKeyboardButton(text="16200 UC - 2,400,000 so'm", callback_data="buy_uc_16200"),
                InlineKeyboardButton(text="24300 UC - 3,520,000 so'm", callback_data="buy_uc_24300"),
            ],
            [
                InlineKeyboardButton(text="32400 UC - 4,620,000 so'm", callback_data="buy_uc_32400"),
                InlineKeyboardButton(text="40500 UC - 6,000,000 so'm", callback_data="buy_uc_40500"),
            ]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("buy_uc_"))
async def process_uc_selection(call: types.CallbackQuery, state: FSMContext):
    uc_amount = call.data.replace("buy_uc_", "")
    
    prices = {
        "60": 12500,
        "325": 58200,
        "660": 117300,
        "1800": 290000,
        "3850": 570200,
        "8100": 1220000,
        "16200": 2400000,
        "24300": 3520000,
        "32400": 4620000,
        "40500": 6000000,
    }
    
    price = prices.get(uc_amount, 0)
    user_id = call.from_user.id
    u_data = get_user_data(user_id)

    if u_data["balance"] < price:
        await call.answer(f"❌ Hisobingizda mablag' yetarli emas! Kerakli summa: {price:,} so'm", show_alert=True)
        return

    await state.update_data(uc_amount=uc_amount, uc_price=price)
    
    saved_id = u_data.get("saved_pubg_id")
    if saved_id:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"Saqlangan ID: {saved_id} ✅", callback_data=f"use_saved_id_{saved_id}")],
                [InlineKeyboardButton(text="Boshqa ID kiritish ✍️", callback_data="enter_new_pubg_id")]
            ]
        )
        await call.message.edit_text(
            f"🛒 Siz tanladingiz: <b>{uc_amount} UC</b> — <b>{price:,} so'm</b>\n\n"
            f"Sizda oldindan saqlangan PUBG ID mavjud. Qaysi biridan foydalanasiz?",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await state.set_state(PubgState.waiting_for_pubg_id)
        await call.message.edit_text(
            f"🛒 Siz tanladingiz: <b>{uc_amount} UC</b> — <b>{price:,} so'm</b>\n\n"
            f"🆔 Iltimos, PUBG ID raqamingizni yuboring (Nik emas!):",
            parse_mode="HTML"
        )


@dp.callback_query(F.data.startswith("use_saved_id_"))
async def use_saved_pubg_id_cb(call: types.CallbackQuery, state: FSMContext):
    pubg_id = call.data.replace("use_saved_id_", "")
    await finalize_pubg_order(call.message, state, pubg_id, call.from_user)
    await call.answer()


@dp.callback_query(F.data == "enter_new_pubg_id")
async def enter_new_pubg_id_cb(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(PubgState.waiting_for_pubg_id)
    await call.message.edit_text(
        "🆔 Iltimos, yangi PUBG ID raqamingizni yuboring (Nik emas!):",
        parse_mode="HTML"
    )


@dp.message(PubgState.waiting_for_pubg_id)
async def process_pubg_id(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return

    pubg_id = message.text.strip()

    if not pubg_id.isdigit():
        await message.answer(
            "❌ <b>Xato!</b> Faqat ID raqamingizni tashlang (faqat raqamlardan iborat bo'lsin):",
            parse_mode="HTML"
        )
        return

    await state.update_data(pubg_id=pubg_id)
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Ha ✅", callback_data="save_pubg_yes"),
                InlineKeyboardButton(text="Yo'q ❌", callback_data="save_pubg_no")
            ]
        ]
    )
    await message.answer(
        "Shu ID ni eslab qolaylikmi?",
        reply_markup=kb
    )


@dp.callback_query(F.data.in_(["save_pubg_yes", "save_pubg_no"]))
async def process_save_pubg_choice(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pubg_id = data.get("pubg_id")
    user_id = call.from_user.id
    u_data = get_user_data(user_id)

    if call.data == "save_pubg_yes":
        u_data["saved_pubg_id"] = pubg_id
        save_db(db)
        await finalize_pubg_order(call.message, state, pubg_id, call.from_user, ask_update=True)
    else:
        u_data["saved_pubg_id"] = None
        save_db(db)
        await finalize_pubg_order(call.message, state, pubg_id, call.from_user, ask_update=False)
    await call.answer()


async def finalize_pubg_order(message_obj, state: FSMContext, pubg_id: str, user_obj, ask_update=False):
    data = await state.get_data()
    uc_amount = data.get("uc_amount")
    uc_price = data.get("uc_price")
    
    user_id = user_obj.id
    u_data = get_user_data(user_id)

    if u_data["balance"] >= uc_price:
        u_data["balance"] -= uc_price
        save_db(db)
        await state.clear()
        
        await message_obj.answer(
            f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
            f"🎮 Miqdor: <b>{uc_amount} UC</b>\n"
            f"🆔 PUBG ID: <code>{pubg_id}</code>\n"
            f"💵 Narxi: <b>{uc_price:,} so'm</b>\n\n"
            f"⏳ Admin UC ni profilingizga tushirgach, xabar beramiz.",
            reply_markup=main_menu,
            parse_mode="HTML"
        )
        
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Tushdi (Bajarildi)",
                        callback_data=f"uc_done_{user_id}_{uc_amount}"
                    )
                ]
            ]
        )
        
        extra_note = "\n📌 (Saqlangan ID orqali buyurtma berildi)" if ask_update else ""
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 <b>Yangi PUBG UC buyurtmasi!</b>{extra_note}\n\n"
                f"👤 Foydalanuvchi: <a href='tg://user?id={user_id}'>{user_obj.first_name}</a> (ID: <code>{user_id}</code>)\n"
                f"🎮 UC miqdori: <b>{uc_amount} UC</b>\n"
                f"🆔 PUBG ID: <code>{pubg_id}</code>\n"
                f"💵 Narxi: <b>{uc_price:,} so'm</b>",
                reply_markup=admin_kb,
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await state.clear()
        await message_obj.answer(
            "❌ Hisobingizda yetarli mablag' qolmadi.",
            reply_markup=main_menu
        )


@dp.callback_query(F.data.startswith("uc_done_"))
async def admin_uc_done(call: types.CallbackQuery):
    parts = call.data.split("_")
    if len(parts) >= 4:
        target_user_id = int(parts[2])
        uc_amount = parts[3]
    else:
        await call.answer("Xatolik: ma'lumot formati noto'g'ri!", show_alert=True)
        return

    try:
        await bot.send_message(
            target_user_id,
            f"✅ Xarid qilgan <b>{uc_amount} UC</b> pubg mobile akkauntingizga tushirib berildi! 🎮",
            parse_mode="HTML"
        )
        old_text = call.message.text or ""
        await call.message.edit_text(old_text + "\n\n<b>✅ STATUS: Bajarildi (Tushirildi)</b>", parse_mode="HTML")
        await call.answer("Foydalanuvchiga xabar yuborildi!")
    except Exception as e:
        await call.answer(f"Xatolik yuz berdi: {e}", show_alert=True)


# ======================= SAVOLLAR (FAQ) / YORDAM =======================
class SupportState(StatesGroup):
    waiting_for_message = State()


support_reply_map = {}  # admin xabar id -> foydalanuvchi id

FAQ_ITEMS = {
    "money": (
        "💰 Hisobni qanday to'ldirish mumkin?",
        "💰 <b>Hisobni qanday to'ldirish mumkin?</b>\n\n"
        "Balansingizni to'ldirish uchun \"💰 <b>Hisobni To'ldirish</b>\" bo'limiga o'ting.\n\n"
        "💳 Mavjud to'lov usulini tanlang va ko'rsatilgan ma'lumotlar bo'yicha to'lovni amalga oshiring.\n\n"
        "📸 To'lov chekini yuboring. Administrator tekshirganidan so'ng mablag' balansingizga qo'shiladi.",
    ),
    "free": (
        "🆓 Botdan bepul foydalanish mumkinmi?",
        "🆓 <b>Botdan bepul foydalanish mumkinmi?</b>\n\n"
        "Ha! Botda bepul tarif mavjud.\n\n"
        "🔰 <b>Bepul tarif:</b>\n"
        "• Profil soatidan foydalanish.\n"
        "• Default shrift.\n"
        "• Asosiy imkoniyatlar.\n\n"
        "💎 Qo'shimcha shriftlar va kengaytirilgan imkoniyatlar uchun pullik tariflardan foydalanishingiz mumkin.",
    ),
    "nopay": (
        "❓ Hisobimga pul nega tushmadi?",
        "❓ <b>Hisobimga pul nega tushmadi?</b>\n\n"
        "To'lovlar administrator tomonidan qo'lda tekshiriladi va tasdiqlanadi.\n\n"
        "⏳ Odatda tekshirish jarayoni 5–30 daqiqa davom etadi.\n\n"
        "🆘 Agar to'lovingiz uzoq vaqt tasdiqlanmasa, \"📞 <b>Admin</b>\" tugmasi orqali administratorga murojaat qiling.",
    ),
    "safe": (
        "🔒 Botni akkauntga ulash xavfsizmi?",
        "🔐 <b>Botni akkauntga ulash xavfsizmi?</b>\n\n"
        "Bot Telegram Business imkoniyatlari orqali ishlaydi.\n\n"
        "🔒 Ulanish vaqtida Telegram akkauntingiz paroli so'ralmaydi.\n\n"
        "⚠️ Bot faqat siz ruxsat bergan imkoniyatlardan foydalanishi mumkin. Ruxsatlarni ulashdan oldin diqqat bilan tekshiring.",
    ),
    "ref": (
        "🎁 Referal orqali nega pul to'lanmaydi?",
        "🎁 <b>Referal bonusi nega to'lanmadi?</b>\n\n"
        "Referal bonusi quyidagi shartlar bajarilganda beriladi:\n\n"
        "1️⃣ Do'stingiz botga aynan sizning havolangiz orqali kirishi kerak.\n\n"
        "2️⃣ Botni muvaffaqiyatli ulashi kerak.\n\n"
        "3️⃣ Birinchi marta soat funksiyasini yoqishi kerak.\n\n"
        "✅ Barcha shartlar bajarilgandan so'ng bonus hisobingizga o'tkaziladi.",
    ),
}


def help_menu_text():
    return (
        f"{pe('help', '🛟')} <b>Yordam markazi</b> {pe('spark', '✨')}\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Sizga yordam berishga doimo tayyormiz!\n\n"
        "💬 Savollaringiz, takliflaringiz yoki muammolaringiz bo'lsa, bizga murojaat qiling.\n\n"
        "⚡ Murojaatlaringiz imkon qadar tez ko'rib chiqiladi."
    )


def help_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("❓ Ko'p beriladigan savollar", callback_data="faq_list", style="danger")],
        [
            ibtn("📞 Admin", url=f"https://t.me/{ADMIN_USERNAME}", style="primary"),
            ibtn("💬 Online murojaat", callback_data="support_start", style="primary"),
        ],
        [ibtn("🧑‍💻 Dasturchi", url=f"https://t.me/{DEV_USERNAME}", style="primary")],
    ])


def faq_list_kb():
    rows = [[ibtn(title, callback_data=f"faq_{key}", style="primary")] for key, (title, _) in FAQ_ITEMS.items()]
    rows.append([ibtn("🔙 Orqaga", callback_data="faq_back_help", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text == "Savollar (FAQ) ❓")
async def faq_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(help_menu_text(), reply_markup=help_menu_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "faq_back_help")
async def faq_back_help_cb(call: types.CallbackQuery):
    await call.message.edit_text(help_menu_text(), reply_markup=help_menu_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "faq_list")
async def faq_list_cb(call: types.CallbackQuery):
    await call.message.edit_text(
        "❓ <b>KO'P BERILADIGAN SAVOLLAR</b>\n\nJavob olmoqchi bo'lgan savolingizni tanlang:",
        reply_markup=faq_list_kb(), parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("faq_") & ~F.data.in_({"faq_list", "faq_back_help"}))
async def faq_answer_cb(call: types.CallbackQuery):
    key = call.data[4:]
    item = FAQ_ITEMS.get(key)
    if not item:
        await call.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[ibtn("🔙 Orqaga", callback_data="faq_list", style="danger")]])
    await call.message.edit_text(item[1], reply_markup=kb, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "support_start")
async def support_start_cb(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_for_message)
    await call.message.answer(
        "💬✨ <b>Online murojaat</b>\n\n"
        "Savol yoki muammoingizni yozing (matn, rasm yoki chek yuborishingiz mumkin) — xabaringiz to'g'ridan-to'g'ri adminga boradi 📨",
        reply_markup=cancel_keyboard, parse_mode="HTML",
    )
    await call.answer()


@dp.message(SupportState.waiting_for_message)
async def support_receive(message: types.Message, state: FSMContext):
    user = message.from_user
    uname = f"@{user.username}" if user.username else "username yo'q"
    try:
        copied = await bot.copy_message(ADMIN_ID, message.chat.id, message.message_id)
        info = await bot.send_message(
            ADMIN_ID,
            "📨 <b>Yangi murojaat</b>\n"
            f"👤 {esc(user.full_name)} ({uname})\n"
            f"🆔 <code>{user.id}</code>\n\n"
            "↩️ Javob berish uchun shu xabarga <b>reply</b> qiling.",
            reply_to_message_id=copied.message_id, parse_mode="HTML",
        )
        support_reply_map[copied.message_id] = user.id
        support_reply_map[info.message_id] = user.id
        await state.clear()
        await message.answer("✅ Murojaatingiz adminga yuborildi! Tez orada javob beramiz 🙌", reply_markup=main_menu)
    except Exception as e:
        print("Murojaat yuborishda xato:", e)
        await state.clear()
        await message.answer("❌ Murojaatni yuborib bo'lmadi, birozdan so'ng qayta urinib ko'ring.", reply_markup=main_menu)


@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message, F.reply_to_message.message_id.func(lambda i: i in support_reply_map))
async def admin_support_reply(message: types.Message):
    target = support_reply_map.get(message.reply_to_message.message_id)
    try:
        await bot.send_message(target, "👨‍💼 <b>Admin javobi:</b>", parse_mode="HTML")
        await bot.copy_message(target, message.chat.id, message.message_id)
        await message.answer("✅ Javob foydalanuvchiga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Yuborib bo'lmadi: {e}")


@dp.message(F.text == "Referral 💸")
async def referral_menu(message: types.Message):
    user_id = message.from_user.id
    u_data = get_user_data(user_id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    installed_count = u_data.get("clock_installed_referrals", 0)
    
    share_text = f"🤖 Eng zo'r profil soat boti!\n\n🔗 Mening havolam orqali kiring va soat o'rnating: {ref_link}"
    share_url = f"https://t.me/share/url?url={ref_link}&text={share_text}"

    text = (
        f"🔗✨ <b>Referral bo'limi</b> ✨🔗\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"✅ Do'stingiz havolangiz orqali botga kirib, <b>soat o'rnatganida</b> referral hisobga olinadi.\n"
        f"❌ Faqat /start bosib chiqib ketsa — hisoblanmaydi.\n\n"
        f"🎁 <b>Har bir referral uchun 900 so'm beriladi!</b>\n"
        f"📊 Jami natijangiz: <b>{installed_count} ta do'st soat o'rnatgan.</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>{ref_link}</code>\n\n"
        f"🔻 👤 <b>Do'stlarga yuborish</b> tugmasini bosing — chat tanlaysiz va tayyor post o'zi yuboriladi."
    )
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Do'stlarga yuborish",
                    url=share_url
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(F.text == "Promokod 🎟")
async def promo_menu(message: types.Message, state: FSMContext):
    await state.set_state(PromoState.waiting_for_promo)
    await message.answer(
        "🎟✨ Promokodni kiriting 👇",
        reply_markup=cancel_keyboard,
    )


@dp.message(PromoState.waiting_for_promo)
async def process_promo_code(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return
    
    code = message.text.strip().upper()
    user_id = message.from_user.id
    u_data = get_user_data(user_id)
    
    if "used_promos" not in u_data:
        u_data["used_promos"] = []
        
    if code in u_data["used_promos"]:
        await message.answer("❌ Siz bu promokoddan allaqachon foylangansiz!", reply_markup=main_menu)
        await state.clear()
        return
        
    if code in promos_db:
        promo_info = promos_db[code]
        if promo_info["uses"] > 0:
            promo_info["uses"] -= 1
            amount = promo_info["amount"]
            u_data["balance"] += amount
            u_data["used_promos"].append(code)
            save_promos(promos_db)
            save_db(db)
            await message.answer(f"🎉 Tabriklaymiz! Promokod muvaffaqiyatli faollashtirildi va balansingizga <b>{amount:,} so'm</b> qo'shildi! 💰", reply_markup=main_menu, parse_mode="HTML")
        else:
            await message.answer("❌ Bu promokodning ishlatish limiti tugagan!", reply_markup=main_menu)
    else:
        await message.answer("❌ Bunday promokod mavjud emas yoki xato kiritildi!", reply_markup=main_menu)
    
    await state.clear()


def _map_range(txt, upper, lower, digits=None, exc=None):
    out = []
    for ch in txt:
        if exc and ch in exc:
            out.append(exc[ch])
        elif "A" <= ch <= "Z" and upper:
            out.append(chr(upper + ord(ch) - 65))
        elif "a" <= ch <= "z" and lower:
            out.append(chr(lower + ord(ch) - 97))
        elif "0" <= ch <= "9" and digits:
            out.append(chr(digits + ord(ch) - 48))
        else:
            out.append(ch)
    return "".join(out)


_SMALLCAPS = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"))
_DS_EXC = {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"}
_IT_EXC = {"h": "ℎ"}


def nick_fonts(t):
    """Matn uchun turli Unicode shriftlar."""
    return [
        ("Qalin", _map_range(t, 0x1D400, 0x1D41A, 0x1D7CE)),
        ("Kursiv", _map_range(t, 0x1D434, 0x1D44E, None, _IT_EXC)),
        ("Qalin kursiv", _map_range(t, 0x1D468, 0x1D482, 0x1D7CE)),
        ("Yozma (script)", _map_range(t, 0x1D4D0, 0x1D4EA, 0x1D7CE)),
        ("Gotik", _map_range(t, 0x1D56C, 0x1D586, 0x1D7CE)),
        ("Ikki chiziqli", _map_range(t, 0x1D538, 0x1D552, 0x1D7D8, _DS_EXC)),
        ("Sans", _map_range(t, 0x1D5A0, 0x1D5BA, 0x1D7E2)),
        ("Sans qalin", _map_range(t, 0x1D5D4, 0x1D5EE, 0x1D7EC)),
        ("Sans kursiv", _map_range(t, 0x1D608, 0x1D622, None)),
        ("Monospace", _map_range(t, 0x1D670, 0x1D68A, 0x1D7F6)),
        ("Keng (fullwidth)", _map_range(t, 0xFF21, 0xFF41, 0xFF10)),
        ("Aylana", _map_range(t, 0x24B6, 0x24D0, None)),
        ("To'ldirilgan aylana", _map_range(t.upper(), 0x1F150, None)),
        ("Kvadrat", _map_range(t.upper(), 0x1F130, None)),
        ("To'ldirilgan kvadrat", _map_range(t.upper(), 0x1F170, None)),
        ("Kichik bosh harf", "".join(_SMALLCAPS.get(c, c) for c in t.lower())),
        ("Chizilgan", "".join(c + "\u0336" if c.strip() else c for c in t)),
        ("Tagiga chizilgan", "".join(c + "\u0332" if c.strip() else c for c in t)),
        ("Nuqtali", "".join(c + "\u0307" if c.strip() else c for c in t)),
    ]


def nick_decorated(t, bold, script):
    """Bezak (ramka, belgilar) bilan niklar."""
    return [
        ("Qirollik", f"꧁ {bold} ꧂"),
        ("Toj", f"♛ {script} ♛"),
        ("Chaqmoq", f"⚡️ {bold} ⚡️"),
        ("Yulduz", f"★彡 {bold} 彡★"),
        ("Kitob ramka", f"『 {bold} 』"),
        ("Qalin ramka", f"【 {bold} 】"),
        ("Gul", f"༺ {script} ༻"),
        ("Olov", f"🔥 {bold} 🔥"),
        ("Yulduzcha", f"✦ {script} ✦"),
        ("Yurak", f"♡ {script} ♡"),
        ("Brilliant", f"💎 {bold} 💎"),
        ("Strelka", f"»»— {bold} —««"),
        ("Qalqon", f"🛡 {bold} 🛡"),
        ("Premium", f"✧･ﾟ: *✧･ﾟ:* {script} *:･ﾟ✧*:･ﾟ✧"),
        ("Zamonaviy", f"•°•{bold}•°•"),
        ("Oddiy chiziqlar", f"▁▂▃ {bold} ▃▂▁"),
    ]


def build_nicks(name):
    name = name.strip()[:25]
    fonts = nick_fonts(name)
    bold = fonts[0][1]
    script = fonts[3][1]
    allnicks = fonts + nick_decorated(name, bold, script)
    return {str(i + 1): (title, nick) for i, (title, nick) in enumerate(allnicks)}


@dp.message(F.text == "Nik yaratish 🤩")
async def nick_gen_menu(message: types.Message, state: FSMContext):
    await state.set_state(NickGenState.waiting_for_name)
    await message.answer(
        "🤩 <b>Nik yaratish</b>\n\n"
        "Ismingizni yoki xohlagan so'zni yozing (lotin harflarida yaxshiroq chiqadi) — "
        "men sizga <b>30 dan ortiq</b> chiroyli nik tayyorlab beraman: har xil shriftlar, ramkalar va belgilar bilan ✨",
        reply_markup=cancel_keyboard,
        parse_mode="HTML",
    )


@dp.message(NickGenState.waiting_for_name)
async def process_nick_generation(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return
    if not message.text or not message.text.strip():
        await message.answer("✍️ Iltimos, matn yuboring.", reply_markup=cancel_keyboard)
        return

    nicks = build_nicks(message.text)
    await state.update_data(nicks=nicks)
    await state.set_state(NickGenState.waiting_for_choice)

    lines = [f"{k}. {nick}" for k, (title, nick) in nicks.items()]
    res = (
        "✨ <b>Siz uchun chiroyli niklar:</b>\n\n"
        + "\n".join(esc(l) for l in lines)
        + f"\n\n<i>💡 Kerakli nik raqamini (1 dan {len(nicks)} gacha) yuboring — men uni nusxalash uchun qulay ko'rinishda beraman. "
        "Yangi so'z bilan qayta yaratish uchun «⬅️ Bekor qilish» ni bosib, Nik yaratishni qaytadan tanlang.</i>"
    )
    await message.answer(res, reply_markup=cancel_keyboard, parse_mode="HTML")


@dp.message(NickGenState.waiting_for_choice)
async def process_nick_choice(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return

    choice = (message.text or "").strip()
    data = await state.get_data()
    nicks = data.get("nicks", {})

    if choice in nicks:
        title, selected_nick = nicks[choice]
        await message.answer(
            f"✅ Siz tanlagan nik (<b>{esc(title)}</b>):\n\n<code>{esc(selected_nick)}</code>\n\n"
            "👆 Ustiga bossangiz nusxalanadi. Boshqasini tanlash uchun yana raqam yuboring.",
            reply_markup=cancel_keyboard,
            parse_mode="HTML",
        )
    else:
        await message.answer(f"❌ Iltimos, 1 dan {len(nicks)} gacha bo'lgan raqamlardan birini yuboring yoki Bekor qilishni bosing:", reply_markup=cancel_keyboard)


PLAN_PRICES = {"Free": 0, "Standard": 4000, "Plus": 7000, "Premium": 13000}
PLAN_TITLES = {"Free": "🔰 Free", "Standard": "⏰ Standard", "Plus": "✨ Plus", "Premium": "⭐️ Premium"}


def tariffs_view(prefix="buy_plan_", changing=False):
    text = (
        "📋✨ <b>Tariflar haqida ma'lumot</b> ✨📋\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📌 Tarif: 🔰 Free\n"
        "💰 Narxi: 0 so'm / oy\n"
        "✨ Imkoniyatlar:\n"
        "> Profil soat: ✅\n\n"
        "📌 Tarif: ⏰ Standard\n"
        "💰 Narxi: 4,000 so'm / oy\n"
        "✨ Imkoniyatlar:\n"
        "> Profil soat: ✅\n"
        "> Reklamasiz: ✅\n"
        "> Bioga soat: ✅\n\n"
        "📌 Tarif: ✨ Plus\n"
        "💰 Narxi: 7,000 so'm / oy\n"
        "✨ Imkoniyatlar:\n"
        "> Profil soat: ✅\n"
        "> Reklamasiz: ✅\n"
        "> Bioga soat: ✅\n\n"
        "📌 Tarif: ⭐️ Premium ✔️\n"
        "💰 Narxi: 13,000 so'm / oy\n"
        "✨ Imkoniyatlar:\n"
        "> Profil soat: ✅\n"
        "> Reklamasiz: ✅\n"
        "> Bioga soat: ✅\n"
        "> Online Mode: ✅\n"
        "> Soat fontlari: ✅\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💵 Ko'rsatilgan narxlar 1 oy uchun!\n"
        "👇 Tariflardan birini tanlang:"
    )
    if changing:
        text = "🔄 <b>Tarifni almashtirish</b>\n⚠️ Yangi tarif to'liq narxda olinadi va 30 kunga amal qiladi.\n\n" + text
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔰 Free", callback_data=f"{prefix}Free"),
                InlineKeyboardButton(text="⏰ Standard", callback_data=f"{prefix}Standard"),
            ],
            [
                InlineKeyboardButton(text="✨ Plus", callback_data=f"{prefix}Plus"),
                InlineKeyboardButton(text="⭐️ Premium", callback_data=f"{prefix}Premium"),
            ],
            [
                InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_tariffs")
                if changing else
                InlineKeyboardButton(text="💰 Hisobni to'ldirish", callback_data="go_topup")
            ],
        ]
    )
    return text, kb


def get_active_paid_plan(u_data):
    """Faol pullik tarif bo'lsa (plan, boshlanish_dt, tugash_dt) qaytaradi, aks holda None."""
    plan = u_data.get("plan", "Free")
    exp_str = u_data.get("plan_expire", "Mavjud emas")
    if plan == "Free" or exp_str == "Mavjud emas":
        return None
    try:
        exp_dt = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    if exp_dt <= datetime.now(TASHKENT_TZ).replace(tzinfo=None):
        return None
    start_str = u_data.get("plan_start")
    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        start_dt = exp_dt - timedelta(days=30)  # eski foydalanuvchilar uchun
    return plan, start_dt, exp_dt


async def apply_plan_purchase(call: types.CallbackQuery, plan_name: str):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    cost = PLAN_PRICES.get(plan_name, 0)
    if u_data["balance"] < cost:
        await call.answer("❌ Hisobingizda mablag' yetarli emas! Avval hisobni to'ldiring.", show_alert=True)
        return
    u_data["balance"] -= cost
    u_data["plan"] = plan_name
    if plan_name == "Free":
        u_data["plan_expire"] = "Mavjud emas"
        u_data["plan_start"] = None
    else:
        now_dt = datetime.now(TASHKENT_TZ)
        u_data["plan_start"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        u_data["plan_expire"] = (now_dt + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    save_db(db)
    await call.message.edit_text(
        f"🎉 Tabriklaymiz! Siz muvaffaqiyatli <b>{plan_name}</b> tarifini tanladingiz!", parse_mode="HTML"
    )


@dp.message(F.text == "Tariflar 🛍")
async def tariffs_menu(message: types.Message):
    text, kb = tariffs_view()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs_cb(call: types.CallbackQuery):
    text, kb = tariffs_view()
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("buy_plan_"))
async def choose_plan_callback(call: types.CallbackQuery):
    plan_name = call.data.replace("buy_plan_", "")
    u_data = get_user_data(call.from_user.id)

    active = get_active_paid_plan(u_data)
    if active:
        cur_plan, start_dt, exp_dt = active
        info = (
            f"ℹ️ <b>Sizda tarif allaqachon faol!</b>\n\n"
            f"📌 Tarif: <b>{PLAN_TITLES.get(cur_plan, cur_plan)}</b>\n"
            f"🛒 Siz bu tarifni <b>{start_dt.strftime('%d.%m.%Y %H:%M')}</b> da sotib olgansiz.\n"
            f"⏳ Tarifingiz <b>{exp_dt.strftime('%d.%m.%Y %H:%M')}</b> da tugaydi."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Tarifni almashtirish", callback_data="change_plan")],
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_tariffs")],
            ]
        )
        await call.message.edit_text(info, reply_markup=kb, parse_mode="HTML")
        await call.answer()
        return

    if u_data.get("plan") == plan_name:
        await call.answer(f"Siz allaqachon {plan_name} tarifidasiz!", show_alert=True)
        return

    await apply_plan_purchase(call, plan_name)


@dp.callback_query(F.data == "change_plan")
async def change_plan_cb(call: types.CallbackQuery):
    text, kb = tariffs_view(prefix="switch_plan_", changing=True)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("switch_plan_"))
async def switch_plan_cb(call: types.CallbackQuery):
    plan_name = call.data.replace("switch_plan_", "")
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") == plan_name:
        await call.answer(f"Siz allaqachon {plan_name} tarifidasiz!", show_alert=True)
        return
    await apply_plan_purchase(call, plan_name)


@dp.callback_query(F.data == "go_topup")
async def go_topup_cb(call: types.CallbackQuery, state: FSMContext):
    await call.message.delete()
    await state.set_state(PaymentState.waiting_for_amount)
    await call.message.answer(
        "🌀 To'lov miqdorini so'mda kiriting (masalan: 10000):",
        reply_markup=cancel_keyboard,
    )


def settings_panel(u_data):
    """Soat sozlamalari matni va tugmalari (hamma joyda bir xil, tugmalar yo'qolib qolmaydi)."""
    online_status = online_status_text(u_data)
    method = u_data.get("setup_method")
    method_label = "📞 Telefon raqam" if method != "business" else "💼 Telegram Business"
    rows = [
        [InlineKeyboardButton(text="👤 Nickdagi soat sozlamalari", callback_data="set_nick_menu")],
        [InlineKeyboardButton(text="📝 Biodagi soat sozlamalari", callback_data="set_bio_menu")],
        [InlineKeyboardButton(text=f"🌐 Online rejim ({online_status})", callback_data="toggle_online_mode")],
    ]
    if u_data.get("biz_connection_id"):
        st = "✅ Yoqilgan" if u_data.get("antidelete_active", False) else "⭕️ O'chiq"
        rows.append([InlineKeyboardButton(
            text=f"💬 Chat nazorati — o'chirilgan/tahrirlangan ({st})", callback_data="toggle_antidelete")])
    text = (
        f"⚙️ <b>✨ Soat sozlamalari ✨</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 Ulanish usuli: <b>{method_label}</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Quyidagi bo'limlardan birini tanlang 👇"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text == "Soat Sozlamalari ⚙️")
async def clock_settings(message: types.Message):
    user_id = message.from_user.id
    u_data = get_user_data(user_id)

    # Bazada telefon soati 'faol', lekin xotirada yo'q bo'lsa — sessiyani tiklashga urinamiz
    if u_data.get("clock_active") and user_id not in active_clocks:
        if not await restore_phone_clock(user_id):
            u_data["clock_active"] = False
            save_db(db)
            await message.answer(
                "⚠️ Telefon sessiyangiz topilmadi (bot qayta ishga tushgan bo'lishi mumkin). Soatni qaytadan ulang 👇"
            )
    # Biznes soati 'faol', lekin sikl to'xtab qolgan bo'lsa — qayta ishga tushiramiz
    if u_data.get("biz_active") and u_data.get("biz_connection_id") and user_id not in active_biz_clocks:
        active_biz_clocks[user_id] = True
        asyncio.create_task(start_business_clock(user_id))

    if user_id in active_clocks or user_id in active_biz_clocks:
        text, kb = settings_panel(u_data)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        text = (
            "🕒✨ <b>Profil soatini o'rnatish</b> ✨🕒\n"
            "━━━━━━━━━━━━━━━\n\n"
            "Profilingizga chiroyli, avtomatik yangilanadigan soat qo'yish uchun 2 ta usuldan birini tanlang 👇\n\n"
            "1️⃣ <b>Telefon raqam orqali</b>\n"
            "   📞 Raqam, 🔢 Telegram kodi va (agar bo'lsa) 2 bosqichli parol orqali ulanadi.\n"
            "   ✅ Hamma uchun ishlaydi.\n\n"
            "2️⃣ <b>Telegram Business orqali</b> 💼 (tavsiya etiladi!)\n"
            "   🚫 Kod ham, parol ham kerak emas!\n"
            "   Faqat botni Sozlamalar → Telegram Business → Chatbots bo'limidan ulaysiz — tamom ✅\n"
            f"   ⚠️ Faqat Telegram Premium/Business foydalanuvchilari uchun.\n"
            "━━━━━━━━━━━━━━━\n"
            "🔒 Ma'lumotlaringiz 100% maxfiy saqlanadi va faqat soat funksiyasi uchun ishlatiladi."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="1️⃣ 📞 Telefon raqam orqali", callback_data="setup_method_phone")],
                [InlineKeyboardButton(text="2️⃣ 💼 Telegram Business orqali", callback_data="setup_method_business")],
            ]
        )
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "setup_method_phone")
async def setup_method_phone_cb(call: types.CallbackQuery):
    text = (
        "📞✨ <b>1-usul: Telefon raqam orqali</b> ✨\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Shartlar</b>\n"
        "1. Tekin tarifda bot profil bioingizga avtomatik kichik reklama qo'shadi.\n"
        "2. Reklamasiz soat uchun pullik tariflardan birini tanlang (🛍 Tariflar bo'limida).\n\n"
        "📖 <b>O'rnatish qo'llanmasi</b>\n"
        "1. 📞 Telefon raqamingizni yuboring.\n"
        "2. Telegramdan kelgan kodni pastdagi raqam tugmalari bilan kiriting.\n"
        "3. 2 bosqichli parolingiz bo'lsa, uni ham yuboring.\n"
        "4. 1 daqiqa ichida profilingizda avtomatik soat chiqadi ⏱\n\n"
        "🔒 <b>Xavfsizlik</b>\n"
        "Telefon, kod va parol faqat soat o'rnatish uchun ishlatiladi, uchinchi shaxslarga berilmaydi."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="O'qib chiqdim, boshlayman ✅", callback_data="read_rules")]]
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# Profil tahrirlash oynasi (Info): shu yerda "Chat automation" qatori turadi.
# Telegram rasmiy ro'yxatida "Chat automation"ning o'ziga to'g'ridan-to'g'ri havola yo'q,
# shuning uchun eng yaqin sahifa — edit_profile ochiladi.
PERMISSION_URL = "tg://settings/edit_profile"
VIDEO_GUIDE_URL = "https://t.me/profilsoat/2"


def business_guide_text(username):
    return (
        "💼✨ <b>2-usul: Telegram Business orqali</b> ✨\n"
        "━━━━━━━━━━━━━━━\n\n"
        "1️⃣ \"🛡 <b>Ruxsat berish</b>\" tugmasini bosing.\n\n"
        "2️⃣ Ochilgan oynada \"<b>Chat automation</b>\" (Chatlarni avtomatlashtirish) qatorini bosing.\n\n"
        "3️⃣ Qidiruv maydoniga bot username'ini kiriting:\n"
        f"<code>@{username}</code>\n\n"
        "4️⃣ Ruxsatlar bo'limida <b>hamma ruxsatlarni</b> yoqing:\n"
        "     ✅ Ism va bionni tahrirlash\n"
        "     ✅ Xabarlarni o'qish va boshqarish (chat nazorati uchun)\n\n"
        "5️⃣ Sozlamalarni saqlang va botga qayting — soat o'zi qo'shiladi 🕒\n\n"
        "ℹ️ Ismingiz (first name) o'zgarmaydi — soat faqat familiya o'rnida chiqadi.\n"
        "⚠️ Bu usul faqat Telegram Premium/Business foydalanuvchilari uchun mavjud."
    )


def business_guide_kb(extra_back=True):
    rows = [
        [ibtn("🛡 Ruxsat berish", url=PERMISSION_URL, style="primary")],
        [ibtn("🎬 Video Qo'llanma", url=VIDEO_GUIDE_URL, style="primary")],
        [ibtn("🔄 Qayta tekshirish (ulagandan keyin bosing)", callback_data="recheck_business", style="success")],
    ]
    if extra_back:
        rows.append([ibtn("🔙 Orqaga", callback_data="back_to_setup_methods", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "setup_method_business")
async def setup_method_business_cb(call: types.CallbackQuery):
    username = (await bot.get_me()).username
    await call.message.edit_text(business_guide_text(username), reply_markup=business_guide_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "back_to_setup_methods")
async def back_to_setup_methods_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    text = (
        "🕒✨ <b>Profil soatini o'rnatish</b> ✨🕒\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Profilingizga chiroyli, avtomatik yangilanadigan soat qo'yish uchun 2 ta usuldan birini tanlang 👇\n\n"
        "1️⃣ <b>Telefon raqam orqali</b>\n"
        "   📞 Raqam, 🔢 Telegram kodi va (agar bo'lsa) 2 bosqichli parol orqali ulanadi.\n"
        "   ✅ Hamma uchun ishlaydi.\n\n"
        "2️⃣ <b>Telegram Business orqali</b> 💼 (tavsiya etiladi!)\n"
        "   🚫 Kod ham, parol ham kerak emas!\n"
        "   Faqat botni Sozlamalar → Telegram Business → Chatbots bo'limidan ulaysiz — tamom ✅\n"
        "   ⚠️ Faqat Telegram Premium/Business foydalanuvchilari uchun.\n"
        "━━━━━━━━━━━━━━━\n"
        "🔒 Ma'lumotlaringiz 100% maxfiy saqlanadi va faqat soat funksiyasi uchun ishlatiladi."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1️⃣ 📞 Telefon raqam orqali", callback_data="setup_method_phone")],
            [InlineKeyboardButton(text="2️⃣ 💼 Telegram Business orqali", callback_data="setup_method_business")],
        ]
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "toggle_antidelete")
async def toggle_antidelete_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)
    conn, st = await verify_business_connection(user_id, u_data)
    if st != "ok":
        await call.answer(
            "⚠️ Bot Telegram Business orqali ulanmagan. Avval \"Chat nazorati 💬\" bo'limidan ulang.",
            show_alert=True,
        )
        return

    u_data["antidelete_active"] = not u_data.get("antidelete_active", False)
    save_db(db)

    if u_data["antidelete_active"]:
        await call.answer(
            "✅ Chat nazorati yoqildi!\nEndi shaxsiy chatlaringizda kimdir xabarni O'CHIRSA yoki TAHRIRLASA, sizga darhol xabar beraman.",
            show_alert=True,
        )
    else:
        await call.answer("⭕️ Chat nazorati o'chirildi.", show_alert=True)

    text, kb = settings_panel(u_data)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data == "toggle_online_mode")
async def toggle_online_mode_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    u_data = get_user_data(user_id)

    if u_data.get("plan") != "Premium":
        if u_data.get("online_mode", False):
            u_data["online_mode"] = False
            save_db(db)
        await call.answer("❌ Online rejim faqat Premium ⭐️ tarifidagi foydalanuvchilar uchun!", show_alert=True)
        return

    # Online holatni faqat telefon (sessiya) orqali o'zgartirish mumkin. Telegram Business botlariga bu ruxsat berilmagan.
    if user_id not in active_clocks:
        await call.answer("ℹ️ Online rejim faqat telefon raqam orqali ulanganda ishlaydi.", show_alert=True)
        await call.message.answer(
            "🌐 <b>Online rejim haqida</b>\n\n"
            "Telegram <b>Business</b> orqali ulangan botlar akkauntingizni «online» qila olmaydi — bu Telegram cheklovi.\n\n"
            "Online rejim ishlashi uchun soatni <b>📞 Telefon raqam orqali</b> ulang. "
            "Chat nazorati va Avto javob Business ulanishida avvalgidek qolaveradi ✅",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [ibtn("📞 Telefon orqali ulash", callback_data="setup_method_phone", style="primary")]
            ]),
            parse_mode="HTML",
        )
        return

    u_data["online_mode"] = not u_data.get("online_mode", False)
    save_db(db)
    if u_data["online_mode"]:
        ensure_online_task(user_id)
        try:   # kutmasdan darhol online qilamiz
            client = active_clocks[user_id]
            if not client.is_connected():
                await client.connect()
            await client(functions.account.UpdateStatusRequest(offline=False))
        except Exception as e:
            print(f"Online rejim yoqishda xato ({user_id}):", e)
    await call.answer("Online rejim yoqildi 🟢" if u_data["online_mode"] else "Online rejim o'chirildi 🔴")

    text, kb = settings_panel(u_data)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data == "read_rules")
async def rules_accepted(call: types.CallbackQuery, state: FSMContext):
    u_data = get_user_data(call.from_user.id)
    u_data["setup_method"] = "phone"
    save_db(db)
    await call.message.delete()
    await state.set_state(ClockSetup.waiting_for_phone)
    await call.message.answer(
        "🕒✨ <b>Soat O'rnatish</b> ✨\n\n📞 Telefon raqamingizni jo'nating:",
        reply_markup=phone_keyboard,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "set_nick_menu")
async def nick_menu_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    current_font = effective_font(u_data)
    sample_time = apply_font("22:55", current_font)
    font_btn_text = "✏️ Fontni o'zgartirish" + ("" if u_data.get("plan") == "Premium" else " 🔒")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Soatni o'chirish", callback_data="toggle_clock_off"
                )
            ],
            [
                InlineKeyboardButton(
                    text=font_btn_text, callback_data="choose_font_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga", callback_data="back_to_main_settings"
                )
            ],
        ]
    )
    await call.message.edit_text(
        f"🌐ℹ️ <b>Nickdagi soat sozlamalari</b>\n\n📊 Holat: <i>Yoniq</i> 🟢\n✏️ Font: <i>{current_font}</i>\n✨ Misol: {sample_time}",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "set_bio_menu")
async def set_bio_menu_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    bio_active = u_data.get("bio_clock", False)
    status_text = "Yoniq 🟢" if bio_active else "O'chiq 🔴"
    
    b_type = u_data.get("bio_type", "oddiy")
    type_names = {
        "oddiy": "Oddiy bio soat",
        "salomlashish": "Salomlashish",
        "tugilgan_kun": "Tug'ilgan kun hisoblagichi",
        "yangi_yil": "Yangi yil hisoblagichi",
        "vatan_himoyachilari": "14-yanvar (Vatan himoyachilari)",
        "sakkiz_mart": "8-mart (Xalqaro xotin-qizlar)",
        "namoz": "Namoz vaqtlari (Toshkent)",
        "qurbon_hayiti": "Qurbon hayiti & Namoz vaqti"
    }
    bio_type_text = type_names.get(b_type, "Oddiy bio soat")
    if b_type == "namoz":
        bio_type_text = f"Namoz vaqtlari ({city_name(city_of(u_data))})"
    
    toggle_text = "Bioni o'chirish" if bio_active else "Bioni yoqish"
    toggle_cb = "toggle_bio_off" if bio_active else "toggle_bio_on"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🟢 {toggle_text}" if not bio_active else f"🔴 {toggle_text}", callback_data=toggle_cb
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎨 Bio tipini o'zgartirish", callback_data="choose_bio_type_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga", callback_data="back_to_main_settings"
                )
            ],
        ]
    )
    
    if b_type == "namoz":
        kb.inline_keyboard.insert(2, [InlineKeyboardButton(text="🏙 Shaharni o'zgartirish", callback_data="namoz_city_menu")])

    info_note = ""
    if u_data.get("plan") not in BIO_PLANS:
        info_note = f"\n\nℹ️ Biodagi soat funksiyasi faqat {BIO_PLANS_TEXT} tariflarida ishlaydi."

    await call.message.edit_text(
        f"🎨 <b>Biodagi soat sozlamalari</b>\n\n📊 Holat: <i>{status_text}</i>\n🎨 Bio tipi: <i>{bio_type_text}</i>{info_note}",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "toggle_bio_on")
async def toggle_bio_on_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") not in BIO_PLANS:
        await call.answer(f"❌ Biodagi soat funksiyasi {BIO_PLANS_TEXT} tariflarida mavjud!", show_alert=True)
        return
    u_data["bio_clock"] = True
    save_db(db)
    asyncio.create_task(apply_business_clock_now(call.from_user.id))
    await set_bio_menu_cb(call)


@dp.callback_query(F.data == "toggle_bio_off")
async def toggle_bio_off_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    u_data["bio_clock"] = False
    u_data["biz_tag_set"] = True   # bioni bir marta tozalash uchun belgi
    save_db(db)
    asyncio.create_task(apply_business_clock_now(call.from_user.id))
    await set_bio_menu_cb(call)


@dp.callback_query(F.data == "choose_bio_type_menu")
async def choose_bio_type_menu_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") not in BIO_PLANS:
        await call.answer(f"❌ Bio tiplarini o'zgartirish {BIO_PLANS_TEXT} tariflarida mavjud!", show_alert=True)
        return

    cur = u_data.get("bio_type", "oddiy")

    def mark(name, key):
        return f"{name}" + (" ✅" if cur == key else " ❌")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=mark("Oddiy bio soat", "oddiy"), callback_data="set_btype_oddiy")],
            [InlineKeyboardButton(text=mark("Salomlashish", "salomlashish"), callback_data="set_btype_salomlashish")],
            [InlineKeyboardButton(text=mark("Tug'ilgan kun", "tugilgan_kun"), callback_data="set_btype_tugilgan_kun")],
            [InlineKeyboardButton(text=mark("Yangi yil", "yangi_yil"), callback_data="set_btype_yangi_yil")],
            [InlineKeyboardButton(text=mark("14-yanvar", "vatan_himoyachilari"), callback_data="set_btype_vatan_himoyachilari")],
            [InlineKeyboardButton(text=mark("8-mart", "sakkiz_mart"), callback_data="set_btype_sakkiz_mart")],
            [InlineKeyboardButton(text=mark("Namoz vaqtlari 🕌", "namoz"), callback_data="set_btype_namoz")],
            [InlineKeyboardButton(text=mark("Qurbon hayiti & Namoz", "qurbon_hayiti"), callback_data="set_btype_qurbon_hayiti")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="set_bio_menu")],
        ]
    )
    
    desc_text = (
        "🎨 <b>Bio tipini tanlang:</b>\n\n"
        "🕒 Oddiy - Standart vaqt\n"
        "☀️ Salomlashish - Kun vaqti salomi\n"
        "🎂 Tug'ilgan kun - Shaxsiy sana\n"
        "🎄 Yangi yil - 1-yanvar 00:00 gacha kun, soat va daqiqa\n"
        "🕌 Namoz vaqtlari - Toshkent bo'yicha: hozirgi namoz qachon kirdi/chiqadi va qancha vaqt qolgani\n"
        "🎖 14-yanvar - Vatan himoyachilari kuni va qolgan vaqt/hafta kuni\n"
        "🌷 8-mart - Xalqaro xotin-qizlar kuni va qolgan vaqt/hafta kuni\n"
        "🕌 Qurbon hayiti - Hayit kuni, hafta kuni, qolgan soat/kun va hayit namoz vaqti"
    )
    await call.message.edit_text(desc_text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("set_btype_"))
async def set_btype_callback(call: types.CallbackQuery, state: FSMContext):
    btype = call.data.replace("set_btype_", "")
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") not in BIO_PLANS:
        await call.answer(f"❌ Bio tiplarini tanlash {BIO_PLANS_TEXT} tariflarida mavjud!", show_alert=True)
        return

    u_data["bio_type"] = btype
    save_db(db)
    asyncio.create_task(apply_business_clock_now(call.from_user.id))
    
    if btype == "tugilgan_kun":
        await state.set_state(ClockSetup.waiting_for_birthday)
        await call.message.answer(
            "🎂 Tug'ilgan kuningizni OY-KUN formatida kiriting (masalan: 25-dekabr uchun 12-25):",
            reply_markup=cancel_keyboard
        )
        return

    if btype == "namoz":
        await call.answer("Bio tipi o'zgartirildi!")
        await show_namoz_city_menu(call)
        return

    await call.answer("Bio tipi o'zgartirildi!")
    await choose_bio_type_menu_cb(call)


def namoz_city_kb(cur):
    rows, row = [], []
    for key, val in NAMOZ_CITIES.items():
        row.append(InlineKeyboardButton(
            text=("✅ " if key == cur else "") + val[0], callback_data=f"namoz_city_{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="set_bio_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_namoz_city_menu(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    cur = city_of(u_data)
    await call.message.edit_text(
        "🕌 <b>Namoz vaqtlari</b>\n\n"
        "Shaharingizni tanlang — bio'ngizda shu shahar bo'yicha namoz vaqtlari chiqadi: "
        "hozirgi namoz qachon kirgan/qachon chiqishi va qancha vaqt qolgani. "
        "Vaqtlar O'zbekiston Musulmonlari idorasi taqvimidan olinadi va avtomatik yangilanib turadi.\n\n"
        f"📍 Hozirgi shahar: <b>{city_name(cur)}</b>",
        reply_markup=namoz_city_kb(cur),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "namoz_city_menu")
async def namoz_city_menu_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") not in BIO_PLANS:
        await call.answer(f"❌ Bio tiplarini o'zgartirish {BIO_PLANS_TEXT} tariflarida mavjud!", show_alert=True)
        return
    await show_namoz_city_menu(call)


async def _after_city_change(user_id, city):
    try:
        await refresh_prayer_cache([city])      # tanlangan shahar vaqtlarini darhol olamiz
    except Exception as e:
        print("Shahar vaqtlarini olishda xato:", e)
    await apply_business_clock_now(user_id)     # bioga darhol yozamiz


@dp.callback_query(F.data.startswith("namoz_city_"))
async def namoz_city_pick_cb(call: types.CallbackQuery):
    key = call.data.replace("namoz_city_", "", 1)
    if key == "menu":
        return
    if key not in NAMOZ_CITIES:
        await call.answer("❌ Shahar topilmadi", show_alert=True)
        return
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") not in BIO_PLANS:
        await call.answer(f"❌ Bio tiplarini o'zgartirish {BIO_PLANS_TEXT} tariflarida mavjud!", show_alert=True)
        return
    u_data["prayer_city"] = key
    u_data["bio_type"] = "namoz"
    save_db(db)
    asyncio.create_task(_after_city_change(call.from_user.id, key))
    await call.answer(f"✅ {city_name(key)} tanlandi")
    await show_namoz_city_menu(call)


@dp.message(ClockSetup.waiting_for_birthday)
async def process_birthday_input(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return
    
    text = message.text.strip()
    if not re.match(r"^\d{2}-\d{2}$", text):
        await message.answer("❌ Noto'g'ri format! OY-KUN ko'rinishida kiriting (masalan: 12-25):", reply_markup=cancel_keyboard)
        return

    u_data = get_user_data(message.from_user.id)
    u_data["birthday_date"] = text
    save_db(db)
    await state.clear()
    await message.answer("✅ Tug'ilgan kun muvaffaqiyatli saqlandi va bot uni avtomatik hisoblaydi! 🎂", reply_markup=main_menu)


@dp.callback_query(F.data == "back_to_main_settings")
async def back_settings_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    online_status = online_status_text(u_data)
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Nickdagi soat sozlamalari",
                    callback_data="set_nick_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Biodagi soat sozlamalari",
                    callback_data="set_bio_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🌐 Online rejim ({online_status})",
                    callback_data="toggle_online_mode",
                )
            ]
        ]
    )
    await call.message.edit_text(
        "⚙️ <b>Soat sozlamalari</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "choose_font_menu")
async def choose_font_menu_cb(call: types.CallbackQuery):
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") != "Premium":
        await call.answer("❌ Font o'zgartirish faqat Premium ⭐️ tarifidagi foydalanuvchilar uchun!", show_alert=True)
        return
    cur = u_data.get("font_style", "Default")

    def mark(name):
        styled_sample = apply_font("22:55", name)
        is_selected = (cur == name)
        icon = " ✅" if is_selected else " ❌"
        return f"{name} {styled_sample}{icon}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=mark("Default"), callback_data="set_font_Default"),
                InlineKeyboardButton(text=mark("Monospace"), callback_data="set_font_Monospace"),
            ],
            [
                InlineKeyboardButton(text=mark("Strike-Through"), callback_data="set_font_Strike-Through"),
                InlineKeyboardButton(text=mark("SuperScript"), callback_data="set_font_SuperScript"),
            ],
            [
                InlineKeyboardButton(text=mark("SubScript"), callback_data="set_font_SubScript"),
                InlineKeyboardButton(text=mark("Bold"), callback_data="set_font_Bold"),
            ],
            [
                InlineKeyboardButton(text=mark("Bold Serif"), callback_data="set_font_Bold Serif"),
                InlineKeyboardButton(text=mark("Double Struck"), callback_data="set_font_Double Struck"),
            ],
            [
                InlineKeyboardButton(text=mark("Circle"), callback_data="set_font_Circle"),
                InlineKeyboardButton(text=mark("Double Circle"), callback_data="set_font_Double Circle"),
            ],
            [
                InlineKeyboardButton(text=mark("Dark Circle"), callback_data="set_font_Dark Circle"),
                InlineKeyboardButton(text=mark("Crazify"), callback_data="set_font_Crazify"),
            ],
            [
                InlineKeyboardButton(text="🔙 Orqaga", callback_data="set_nick_menu"),
            ],
        ]
    )
    
    text = (
        "✏️ <b>Font tanlash</b>\n\n"
        "Crazify Fonti barcha fontlarining aralashmasi bo'lib, har safar turli fontda soat ko'rsatadi ✨\n\n"
        "Qaysi fontni tanlaysiz?"
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("set_font_"))
async def set_font_callback(call: types.CallbackQuery):
    font_name = call.data.replace("set_font_", "")
    u_data = get_user_data(call.from_user.id)
    if u_data.get("plan") != "Premium":
        await call.answer("❌ Font o'zgartirish faqat Premium ⭐️ tarifidagi foydalanuvchilar uchun!", show_alert=True)
        return
    u_data["font_style"] = font_name
    save_db(db)
    await call.answer(f"Font o'zgartirildi: {font_name}")
    await choose_font_menu_cb(call)


@dp.callback_query(F.data == "toggle_clock_off")
async def stop_clock_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    active_clocks.pop(user_id, None)
    active_biz_clocks.pop(user_id, None)
    u_data = get_user_data(user_id)
    u_data["clock_active"] = False
    u_data["biz_active"] = False
    save_db(db)
    await call.message.edit_text("🔴✨ Soat to'xtatildi!")
    await call.message.answer(
        "🏠 Asosiy menyuga qaytdingiz:", reply_markup=main_menu
    )


@dp.message(F.text == "Mening Hisobim 👤")
async def my_account(message: types.Message):
    user_id = message.from_user.id
    u_data = get_user_data(user_id)

    plan_name = u_data.get("plan", "Free")
    plan_expire = u_data.get("plan_expire", "Mavjud emas")

    text = (
        f"Sizning hisobingiz 🏷:\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Username: @{esc(message.from_user.username or 'Mavjud emas')}\n"
        f"Ism: {esc(message.from_user.full_name)}\n"
        f"Hisobdagi mablag': {u_data['balance']:,} so'm\n"
        f"Botga qo'shilgan sana: {u_data['joined_date']}\n\n"
        f"Tug'ilgan kun: {u_data.get('birthday_date', '12-25')}\n\n"
        f"Tarif: 🌟 {plan_name}\n"
        f"Tarif tugash sanasi: {plan_expire}"
    )
    await message.answer(text, reply_markup=main_menu, parse_mode="HTML")


@dp.message(F.text == "Hisobni To'ldirish 💰")
async def topup_start(message: types.Message, state: FSMContext):
    await state.set_state(PaymentState.waiting_for_amount)
    await message.answer(
        "🌀 To'lov miqdorini so'mda kiriting (masalan: 10000):",
        reply_markup=cancel_keyboard,
    )


@dp.message(PaymentState.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return
    if not (message.text or "").isdigit() or int(message.text) <= 0:
        await message.answer("❌ Faqat musbat raqam yuboring!", reply_markup=cancel_keyboard)
        return

    amount = int(message.text)
    await state.update_data(amount=amount)
    await state.set_state(PaymentState.waiting_for_receipt)

    text = (
        f"💳 <b>To'lov qilish uchun karta:</b>\n"
        f"<code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: {CARD_OWNER}\n"
        f"💰 Miqdor: {amount:,} so'm\n\n"
        f"📸 Yuqoridagi kartaga pul o'tkazing va to'lov cheki rasmini shu yerga yuboring:"
    )
    await message.answer(text, reply_markup=cancel_keyboard, parse_mode="HTML")


@dp.message(PaymentState.waiting_for_receipt, F.photo)
async def process_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    user_id = message.from_user.id
    username = esc(message.from_user.username or "Mavjud emas")
    full_name = esc(message.from_user.full_name)

    photo_file_id = message.photo[-1].file_id

    admin_text = (
        f"💰 <b>Yangi to'lov cheki!</b>\n\n"
        f"👤 Foydalanuvchi: {full_name} (@{username})\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💵 Summa: <b>{amount:,} so'm</b>"
    )

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Tasdiqlash ✅",
                    callback_data=f"pay_yes_{user_id}_{amount}",
                ),
                InlineKeyboardButton(
                    text="Rad etish ❌", callback_data=f"pay_no_{user_id}"
                ),
            ]
        ]
    )

    try:
        await bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=admin_text,
            reply_markup=admin_kb,
            parse_mode="HTML",
        )
        await message.answer(
            "✅ Chekingiz adminga yuborildi!", reply_markup=main_menu
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}", reply_markup=main_menu)

    await state.clear()


@dp.message(PaymentState.waiting_for_receipt)
async def receipt_not_photo(message: types.Message):
    await message.answer("📸 Iltimos, to'lov <b>chekining rasmini</b> yuboring.", reply_markup=cancel_keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("pay_yes_"))
async def admin_approve_payment(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Faqat admin uchun.", show_alert=True)
        return
    if "STATUS" in (call.message.caption or ""):
        await call.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    parts = call.data.split("_")
    try:
        target_user_id = int(parts[2])
        amount = int(parts[3])
    except (IndexError, ValueError):
        await call.answer("Xatolik!", show_alert=True)
        return

    u_data = get_user_data(target_user_id)
    u_data["balance"] += amount
    save_db(db)

    try:
        await call.message.edit_caption(
            caption=(call.message.html_text or "") + f"\n\n<b>✅ STATUS: Tasdiqlandi ({amount:,} so'm qo'shildi)</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        print("Caption tahrirlashda xato:", e)
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"✅ Pulingiz muvaffaqiyatli hisobingizga qo'shildi! Summa: <b>{amount:,} so'm</b> 💰",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("Tasdiqlash bajarildi!")


class RejectState(StatesGroup):
    waiting_reason = State()
    confirm = State()


def reject_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            ibtn("🚫 Block", callback_data="rej_block", style="danger"),
            ibtn("💾 Save", callback_data="rej_save", style="success"),
        ],
        [ibtn("✏️ Sababni o'zgartirish", callback_data="rej_edit", style="primary")],
    ])


@dp.callback_query(F.data.startswith("pay_no_"))
async def admin_reject_payment(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Faqat admin uchun.", show_alert=True)
        return
    if "STATUS" in (call.message.caption or ""):
        await call.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    try:
        target_user_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("Xatolik!", show_alert=True)
        return
    await state.set_state(RejectState.waiting_reason)
    await state.update_data(
        target=target_user_id, chat_id=call.message.chat.id,
        msg_id=call.message.message_id, caption_html=call.message.html_text or "",
    )
    await call.message.answer(
        "✍️ <b>To'lov nima uchun bekor qilindi?</b>\nSababni yozing (foydalanuvchiga ko'rsatiladi) 👇",
        reply_markup=cancel_keyboard, parse_mode="HTML",
    )
    await call.answer()


@dp.message(RejectState.waiting_reason, F.from_user.id == ADMIN_ID, F.text)
async def admin_reject_reason(message: types.Message, state: FSMContext):
    reason = (message.text or "").strip()[:500]
    if not reason:
        await message.answer("❌ Sabab bo'sh bo'lmasin. Qaytadan yozing:")
        return
    await state.update_data(reason=reason)
    await state.set_state(RejectState.confirm)
    await message.answer(
        "📋 <b>Foydalanuvchiga boradigan sabab:</b>\n"
        f"<blockquote>{esc(reason)}</blockquote>\n"
        "🚫 <b>Block</b> — foydalanuvchi botda bloklanadi\n"
        "💾 <b>Save</b> — faqat to'lov bekor qilinadi, bloklanmaydi",
        reply_markup=reject_confirm_kb(), parse_mode="HTML",
    )


@dp.callback_query(RejectState.confirm, F.data == "rej_edit")
async def admin_reject_edit(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(RejectState.waiting_reason)
    await call.message.answer("✍️ Yangi sababni yozing 👇", reply_markup=cancel_keyboard)
    await call.answer()


async def _finish_reject(call: types.CallbackQuery, state: FSMContext, block: bool):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Faqat admin uchun.", show_alert=True)
        return
    d = await state.get_data()
    target, reason = d.get("target"), d.get("reason", "")
    await state.clear()
    if not target:
        await call.answer("Ma'lumot topilmadi, qaytadan urinib ko'ring.", show_alert=True)
        return

    if block:
        u = get_user_data(target)
        u["banned"] = True
        u["banned_reason"] = reason
        save_db(db)
        await kick_banned([str(target)])

    status = "🚫 STATUS: Rad etildi va BLOKLANDI" if block else "❌ STATUS: Rad etildi"
    try:
        await bot.edit_message_caption(
            chat_id=d["chat_id"], message_id=d["msg_id"],
            caption=d.get("caption_html", "") + f"\n\n<b>{status}</b>\n📝 Sabab: {esc(reason)}",
            parse_mode="HTML",
        )
    except Exception as e:
        print("Chek captionini yangilashda xato:", e)

    # Foydalanuvchiga xabar
    try:
        await bot.send_message(
            target,
            "❌ <b>To'lov so'rovingiz bekor qilindi.</b>\n\n"
            "<b>Sabab:</b>\n"
            f"<blockquote>{esc(reason)}</blockquote>"
            + ("" if block else "\n\nQayta urinib ko'ring."),
            parse_mode="HTML",
        )
        if block:
            await bot.send_message(target, ban_notice_text(), reply_markup=ban_notice_kb(), parse_mode="HTML")
    except Exception:
        pass

    try:
        await call.message.edit_text(
            ("🚫 Foydalanuvchi <b>bloklandi</b> va to'lov bekor qilindi." if block
             else "💾 To'lov bekor qilindi, sabab foydalanuvchiga yuborildi.")
            + f"\n🆔 <code>{target}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await bot.send_message(ADMIN_ID, "🏠 Asosiy menyu", reply_markup=main_menu)
    await call.answer("Bajarildi ✅")


@dp.callback_query(RejectState.confirm, F.data == "rej_block")
async def admin_reject_block(call: types.CallbackQuery, state: FSMContext):
    await _finish_reject(call, state, block=True)


@dp.callback_query(RejectState.confirm, F.data == "rej_save")
async def admin_reject_save(call: types.CallbackQuery, state: FSMContext):
    await _finish_reject(call, state, block=False)


@dp.message(F.text.regexp(r"^/ban(\s|$)"), F.from_user.id == ADMIN_ID)
async def admin_ban_cmd(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("ℹ️ Foydalanish: <code>/ban &lt;user_id&gt; [sabab]</code>", parse_mode="HTML")
        return
    uid = int(parts[1])
    u = get_user_data(uid)
    u["banned"] = True
    u["banned_reason"] = parts[2] if len(parts) > 2 else ""
    save_db(db)
    await kick_banned([str(uid)])
    try:
        await bot.send_message(uid, ban_notice_text(u["banned_reason"] or None), reply_markup=ban_notice_kb(), parse_mode="HTML")
    except Exception:
        pass
    await message.answer(f"🚫 <code>{uid}</code> bloklandi.", parse_mode="HTML")


@dp.message(F.text.regexp(r"^/unban(\s|$)"), F.from_user.id == ADMIN_ID)
async def admin_unban_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("ℹ️ Foydalanish: <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    uid = int(parts[1])
    u = get_user_data(uid)
    u["banned"] = False
    u["banned_reason"] = ""
    save_db(db)
    try:
        await bot.send_message(uid, "✅ Blokdan chiqarildingiz! Botdan qayta foydalanishingiz mumkin. /start", parse_mode="HTML")
    except Exception:
        pass
    await message.answer(f"✅ <code>{uid}</code> blokdan chiqarildi.", parse_mode="HTML")


@dp.message(ClockSetup.waiting_for_phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return

    phone = message.contact.phone_number if message.contact else message.text
    phone = re.sub(r"[^\d+]", "", phone)

    await state.set_state(ClockSetup.waiting_for_code)
    sent_msg = await message.answer("🔄 Kod yuborilmoqda...", reply_markup=ReplyKeyboardRemove())

    os.makedirs("sessions", exist_ok=True)
    # Oldingi tugallanmagan urinish bo'lsa, uni yopamiz (sessiya fayli band bo'lib qolmasin)
    old = user_sessions.pop(message.from_user.id, None)
    if old:
        try:
            await old["client"].disconnect()
        except Exception:
            pass
    client = TelegramClient(f"sessions/user_{message.from_user.id}", API_ID, API_HASH)
    await client.connect()

    try:
        send_code = await client.send_code_request(phone)
        user_sessions[message.from_user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": send_code.phone_code_hash,
            "code_len": getattr(getattr(send_code, "type", None), "length", None) or 5,
            "digits": "",
            "kp_msg_id": None,
        }
        await sent_msg.delete()
        # Ortiqcha matn yubormasdan, to'g'ridan-to'g'ri klaviaturani (keypad) chiqaramiz
        await send_keypad(message, message.from_user.id)
    except Exception as e:
        await sent_msg.delete()
        await message.answer(f"❌ Xatolik: {e}", reply_markup=main_menu)
        await state.clear()


def code_keypad_text(sd):
    n = sd.get("code_len", 5)
    digits = sd.get("digits", "")
    shown = " ".join(list(digits) + ["_"] * max(0, n - len(digits)))
    return f"🔢 <b>Kod:</b>  {shown}\n\nTelegramdan kelgan kodni tugmalar bilan kiriting 👇"


def code_keypad_markup():
    def b(text, data):
        return InlineKeyboardButton(text=text, callback_data=f"kp_{data}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("1", "1"), b("2", "2"), b("3", "3")],
        [b("4", "4"), b("5", "5"), b("6", "6")],
        [b("7", "7"), b("8", "8"), b("9", "9")],
        [b("⌫", "del"), b("0", "0"), b("✅", "ok")],
        [b("🔄 Yangi kod", "new"), b("❌ Bekor", "cancel")],
    ])


async def send_keypad(message, user_id):
    sd = user_sessions.get(user_id)
    if not sd:
        return
    sd["digits"] = ""
    sent = await message.answer(code_keypad_text(sd), reply_markup=code_keypad_markup(), parse_mode="HTML")
    sd["kp_msg_id"] = sent.message_id


async def do_sign_in(message, state, user_id, code):
    session_data = user_sessions.get(user_id)

    if not session_data:
        await message.answer("❌ Sessiya topilmadi. Qaytadan /start bosing.", reply_markup=main_menu)
        await state.clear()
        return

    client = session_data["client"]
    session_data["digits"] = ""
    phone = session_data["phone"]
    phone_code_hash = session_data["phone_code_hash"]

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        active_clocks[user_id] = client
        persist_session(user_id, client)
        u_data = get_user_data(user_id)
        u_data["clock_active"] = True
        active_biz_clocks.pop(user_id, None)
        u_data["biz_active"] = False
        
        if not u_data.get("clock_bonus_given", False):
            u_data["clock_bonus_given"] = True
            ref_id = u_data.get("referred_by")
            if ref_id:
                ref_data = get_user_data(ref_id)
                ref_data["clock_installed_referrals"] = ref_data.get("clock_installed_referrals", 0) + 1
                ref_data["balance"] += 900
                try:
                    await bot.send_message(
                        chat_id=ref_id,
                        text="🎉 Siz taklif qilgan do'st soat o'rnatdi va balansingizga <b>900 so'm</b> qo'shildi! 💸",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        save_db(db)

        asyncio.create_task(start_user_clock(user_id, client))
        await message.answer("✅ Muvaffaqiyatli ulandi va soat ishga tushdi! 🕒", reply_markup=main_menu)
        await state.clear()
        
    except SessionPasswordNeededError:
        await state.set_state(ClockSetup.waiting_for_password)
        await message.answer(
            "🔐 Akkauntingizda <b>ikki bosqichli parol (2-step verification)</b> yoqilgan ekan.\n"
            "Iltimos, Telegram parolingizni kiriting:",
            reply_markup=cancel_keyboard,
            parse_mode="HTML"
        )
    except PhoneCodeInvalidError:
        await message.answer("❌ Kod noto'g'ri. To'g'ri kodni qaytadan yuboring:", reply_markup=cancel_keyboard)
        await send_keypad(message, user_id)
    except PhoneCodeExpiredError:
        # Kod eskirgan yoki Telegram uni bloklagan: avtomatik yangi kod yuboramiz
        try:
            if not client.is_connected():
                await client.connect()
            new_code = await client.send_code_request(phone)
            session_data["phone_code_hash"] = new_code.phone_code_hash
            await message.answer(
                "⌛ Kod eskirgan yoki Telegram uni bloklagan edi.\n"
                "📞 Yangi kod yuborildi, uni tugmalar bilan kiriting 👇",
                reply_markup=cancel_keyboard
            )
            await send_keypad(message, user_id)
        except Exception as e2:
            await message.answer(f"❌ Yangi kod yuborib bo'lmadi: {e2}\nBekor qilib, qaytadan boshlang.", reply_markup=cancel_keyboard)
    except Exception as e:
        # Ulanish uzilgan bo'lsa, qayta ulanamiz va yana urinib ko'rishga ruxsat beramiz
        try:
            if not client.is_connected():
                await client.connect()
        except Exception:
            pass
        await message.answer(f"❌ Kod qabul qilinmadi: {e}\nKodni qaytadan yuboring:", reply_markup=cancel_keyboard)
        await send_keypad(message, user_id)


@dp.message(ClockSetup.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return
    code = re.sub(r"[^\d]", "", message.text or "")
    await do_sign_in(message, state, message.from_user.id, code)


@dp.callback_query(F.data.startswith("kp_"), ClockSetup.waiting_for_code)
async def code_keypad_press(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    sd = user_sessions.get(user_id)
    if not sd:
        await call.answer("Sessiya topilmadi. /start bosing.", show_alert=True)
        await state.clear()
        return
    action = call.data[3:]

    if action == "cancel":
        await call.answer()
        old = user_sessions.pop(user_id, None)
        if old:
            try:
                await old["client"].disconnect()
            except Exception:
                pass
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return

    if action == "new":
        try:
            client = sd["client"]
            if not client.is_connected():
                await client.connect()
            res = await client.send_code_request(sd["phone"])
            sd["phone_code_hash"] = res.phone_code_hash
            sd["digits"] = ""
            await call.answer("Yangi kod yuborildi ✅")
            try:
                await call.message.edit_text(code_keypad_text(sd), reply_markup=code_keypad_markup(), parse_mode="HTML")
            except Exception:
                pass
        except Exception as e:
            await call.answer(f"Xatolik: {e}"[:190], show_alert=True)
        return

    submit = False
    if action == "del":
        sd["digits"] = sd.get("digits", "")[:-1]
    elif action == "ok":
        if len(sd.get("digits", "")) < 4:
            await call.answer("Kod hali to'liq emas", show_alert=True)
            return
        submit = True
    elif action.isdigit():
        if len(sd.get("digits", "")) < 8:
            sd["digits"] = sd.get("digits", "") + action
        if len(sd["digits"]) >= sd.get("code_len", 5):
            submit = True
    await call.answer()

    if submit:
        code = sd["digits"]
        try:
            await call.message.delete()
        except Exception:
            pass
        await do_sign_in(call.message, state, user_id, code)
        return

    try:
        await call.message.edit_text(code_keypad_text(sd), reply_markup=code_keypad_markup(), parse_mode="HTML")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("kp_"))
async def code_keypad_stale(call: types.CallbackQuery):
    await call.answer("Bu tugmalar eskirgan. Soatni qaytadan ulang.", show_alert=True)


@dp.message(ClockSetup.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Bekor qilish":
        await state.clear()
        await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu)
        return

    password = message.text
    user_id = message.from_user.id
    session_data = user_sessions.get(user_id)

    if not session_data:
        await message.answer("❌ Sessiya topilmadi. Qaytadan /start bosing.", reply_markup=main_menu)
        await state.clear()
        return

    client = session_data["client"]

    try:
        await client.sign_in(password=password)
        active_clocks[user_id] = client
        persist_session(user_id, client)
        u_data = get_user_data(user_id)
        u_data["clock_active"] = True
        active_biz_clocks.pop(user_id, None)
        u_data["biz_active"] = False
        
        if not u_data.get("clock_bonus_given", False):
            u_data["clock_bonus_given"] = True
            ref_id = u_data.get("referred_by")
            if ref_id:
                ref_data = get_user_data(ref_id)
                ref_data["clock_installed_referrals"] = ref_data.get("clock_installed_referrals", 0) + 1
                ref_data["balance"] += 900
                try:
                    await bot.send_message(
                        chat_id=ref_id,
                        text="🎉 Siz taklif qilgan do'st so'rnatdi va balansingizga <b>900 so'm</b> qo'shildi! 💸",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        save_db(db)

        asyncio.create_task(start_user_clock(user_id, client))
        await message.answer("✅ Parol qabul qilindi! Muvaffaqiyatli ulandi va soat ishga tushdi! 🕒", reply_markup=main_menu)
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Parol xato: {e}\nQaytadan parolni kiriting:", reply_markup=cancel_keyboard)


_restore_locks = {}


def persist_session(user_id, client):
    """Telethon sessiyasini matn (StringSession) ko'rinishida bazaga saqlaydi.
    Baza GitHub'ga zaxiralanadi — shuning uchun bot qayta ishga tushsa/deploy bo'lsa ham sessiya YO'QOLMAYDI."""
    try:
        s = StringSession.save(client.session)
        if not s:
            return
        u = get_user_data(user_id)
        if u.get("tg_session") != s:
            u["tg_session"] = s
            save_db(db)
    except Exception as e:
        print(f"Sessiyani saqlash xatosi {user_id}: {e}")


async def _try_client(session_obj, user_id):
    """Sessiya bilan ulanib ko'radi. -> (client|None, holat) holat: 'ok' | 'invalid' | 'error'"""
    client = None
    try:
        client = TelegramClient(session_obj, API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            return client, "ok"
        await client.disconnect()
        return None, "invalid"
    except (AuthKeyDuplicatedError, UserDeactivatedError):
        status = "invalid"
    except Exception as e:
        print(f"Sessiyani tiklash xatosi {user_id}: {e}")
        status = "error"
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass
    return None, status


async def restore_phone_clock(user_id, retries=3):
    """Bazada soat 'faol' deb turgan, lekin xotirada ulanishi yo'q (bot qayta ishga tushgan, tarmoq xatosi...)
    foydalanuvchi uchun sessiyani tiklaydi: avval disk fayli, keyin bazadagi matnli sessiya (tg_session).
    Muvaffaqiyatli bo'lsa True. Bir foydalanuvchi uchun bir vaqtda faqat bitta tiklash ishlaydi."""
    if user_id in active_clocks:
        return True
    lock = _restore_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        if user_id in active_clocks:
            return True
        for attempt in range(retries):
            candidates = []
            if os.path.exists(f"sessions/user_{user_id}.session"):
                candidates.append(f"sessions/user_{user_id}")
            s = get_user_data(user_id).get("tg_session")
            if s:
                candidates.append(StringSession(s))
            if not candidates:
                return False
            had_error = False
            for cand in candidates:
                client, status = await _try_client(cand, user_id)
                if status == "ok":
                    active_clocks[user_id] = client
                    persist_session(user_id, client)
                    asyncio.create_task(start_user_clock(user_id, client))
                    return True
                if status == "error":
                    had_error = True
            if not had_error:
                return False          # sessiya aniq yaroqsiz (chiqarib yuborilgan) — qayta urinish befoyda
            await asyncio.sleep(5 * (attempt + 1))   # vaqtincha tarmoq xatosi — biroz kutib qayta urinamiz
        return False


async def fallback_to_business_clock(user_id, u_data):
    """Telefon sessiyasi yo'qolgan bo'lsa-yu, Business ulanishida ism huquqi bo'lsa — soatni avtomatik Business'ga o'tkazadi."""
    if u_data.get("biz_connection_id") and u_data.get("biz_can_name"):
        u_data["biz_active"] = True
        u_data["setup_method"] = "business"
        save_db(db)
        if user_id not in active_biz_clocks:
            active_biz_clocks[user_id] = True
            asyncio.create_task(start_business_clock(user_id))
        return True
    return False


async def bootstrap_from_github():
    """Bot ishga tushganda GitHub'dagi bazadan yetishmayotgan foydalanuvchilar va sessiyalarni (tg_session) qo'shib oladi."""
    if not GITHUB_TOKEN:
        return
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            remote = await fetch_remote_db(session)
        if not remote:
            return
        changed = False
        for uid, r in remote.items():
            if not isinstance(r, dict):
                continue
            cur = db.get(uid)
            if cur is None:
                db[uid] = copy.deepcopy(r)
                changed = True
                continue
            cur_fresh = (cur.get("plan", "Free") == "Free" and not cur.get("balance")
                         and not cur.get("tg_session") and not cur.get("biz_connection_id"))
            if cur_fresh and (r.get("plan", "Free") != "Free" or r.get("balance")):
                db[uid] = copy.deepcopy(r)       # baza yo'qolgandan keyin qayta yaratilgan bo'sh yozuvni tiklaymiz
                changed = True
                continue
            for k in ("tg_session", "clock_active", "biz_connection_id", "biz_can_name", "biz_can_bio", "biz_can_msg", "biz_can_read"):
                if r.get(k) and not cur.get(k):
                    cur[k] = copy.deepcopy(r[k])
                    changed = True
        if changed:
            with db_lock:
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("GitHub'dan tiklashda xato:", e)


async def resume_active_clocks():
    for str_id, u_data in list(db.items()):
        if u_data.get("banned"):
            continue
        if u_data.get("biz_connection_id"):
            await verify_business_connection(int(str_id), u_data)  # eskirgan ulanishni tozalaydi
            await asyncio.sleep(0.05)
        if u_data.get("biz_connection_id"):
            biz_conn_to_user[u_data["biz_connection_id"]] = int(str_id)

        if u_data.get("biz_active", False) and u_data.get("biz_connection_id"):
            user_id = int(str_id)
            if user_id not in active_biz_clocks:
                active_biz_clocks[user_id] = True
                asyncio.create_task(start_business_clock(user_id))

        if u_data.get("clock_active", False):
            user_id = int(str_id)
            if user_id in active_clocks:
                continue
            if not await restore_phone_clock(user_id):
                # Sessiya haqiqatan yaroqsiz: avval Business orqali soatni davom ettirishga urinamiz
                u_data["clock_active"] = False
                switched = await fallback_to_business_clock(user_id, u_data)
                save_db(db)
                if switched:
                    note = (
                        "ℹ️ Telefon sessiyangiz yaroqsiz bo'lib qoldi, shuning uchun soat avtomatik "
                        "💼 Telegram Business orqali davom etmoqda.\n"
                        "💬 Chat nazorati va avto javob ishlashda davom etadi.\n"
                        "Telefon orqali qayta ulash uchun «Soat Sozlamalari ⚙️» ga kiring."
                    )
                else:
                    biz_note = (
                        "\n💬 Chat nazorati va avto javob (Business orqali) ishlashda davom etadi."
                        if u_data.get("biz_connection_id") else ""
                    )
                    note = (
                        "⚠️ Telefon orqali ulangan soat sessiyangiz yaroqsiz bo'lib qoldi, shuning uchun soat to'xtadi."
                        f"{biz_note}\n«Soat Sozlamalari ⚙️» orqali qaytadan ulang 🙏"
                    )
                try:
                    await bot.send_message(user_id, note)
                except Exception:
                    pass


async def main():
    os.makedirs("sessions", exist_ok=True)
    print("ABDULLOHNING BOTI ISHGA TUSHDI")
    # Eski webhook yoki osilib qolgan getUpdates so'rovlari konflikt bermasligi uchun tozalaymiz
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print("Webhook tozalashda xato (e'tiborsiz qoldirsa bo'ladi):", e)

    # Oddiy foydalanuvchilarga faqat /start, adminga esa barcha buyruqlar ko'rinadi
    try:
        await bot.set_my_commands(
            [BotCommand(command="start", description="🏠 Botni ishga tushirish")],
            scope=BotCommandScopeDefault(),
        )
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="🏠 Botni ishga tushirish"),
                BotCommand(command="xabar", description="📢 Hammaga xabar yuborish"),
            ],
            scope=BotCommandScopeChat(chat_id=ADMIN_ID),
        )
    except Exception as e:
        print("Buyruqlar menyusini sozlashda xato:", e)
    await bootstrap_from_github()
    global _last_synced
    _last_synced = copy.deepcopy(db)
    asyncio.create_task(prayer_refresh_loop())
    asyncio.create_task(resume_active_clocks())
    dp.message.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())
    if GITHUB_TOKEN:
        asyncio.create_task(sync_remote_loop())
        asyncio.create_task(github_autosave_loop())

    # Render deploy/o'chirish (SIGTERM) paytida ham oxirgi o'zgarishlar GitHub'ga yoziladi
    try:
        import signal

        async def _graceful_stop():
            try:
                await asyncio.wait_for(push_to_github(), timeout=20)
            except Exception as e:
                print("O'chirishdan oldin saqlashda xato:", e)
            try:
                await dp.stop_polling()
            except Exception:
                pass

        asyncio.get_running_loop().add_signal_handler(
            signal.SIGTERM, lambda: asyncio.create_task(_graceful_stop()))
    except Exception as e:
        print("SIGTERM handler o'rnatilmadi:", e)

    await dp.start_polling(bot)


if __name__ == "__main__":
    os.makedirs("sessions", exist_ok=True)
    threading.Thread(target=run_web_server, daemon=True).start()
    asyncio.run(main())
