# -*- coding: utf-8 -*-
import asyncio, hashlib, hmac, html, json, logging, os, re, secrets, sqlite3
from urllib.parse import parse_qsl
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
DB_PATH = os.getenv("DB_PATH", "shopping.db")
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))
MAX_LEN = 120
NOTIFY_PARTNER = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("CREATE TABLE IF NOT EXISTS families(id INTEGER PRIMARY KEY, code TEXT UNIQUE, title TEXT); CREATE TABLE IF NOT EXISTS members(family_id INTEGER, user_id INTEGER, name TEXT, PRIMARY KEY(family_id, user_id)); CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, family_id INTEGER, text TEXT, done INTEGER DEFAULT 0, added_name TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS panels(family_id INTEGER, user_id INTEGER, message_id INTEGER, PRIMARY KEY(family_id, user_id));")
for col, defn in {"category": "TEXT DEFAULT 'Р”СЂСѓРіРѕРµ'", "qty": "TEXT DEFAULT ''"}.items():
    try: db.execute(f"ALTER TABLE items ADD COLUMN {col} {defn}")
    except sqlite3.OperationalError: pass
db.commit()

BOT_USERNAME, DELETE_MODE, dp = "", set(), Dispatcher()
def q(sql, args=()): return db.execute(sql, args).fetchall()
def one(sql, args=()): return db.execute(sql, args).fetchone()
def ex(sql, args=()): db.execute(sql, args); db.commit()
def family_of(uid):
    r = one("SELECT family_id FROM members WHERE user_id=?", (uid,))
    return r["family_id"] if r else None
def members(fid): return q("SELECT * FROM members WHERE family_id=?", (fid,))
def create_family(uid, name):
    code = secrets.token_hex(4).upper()
    cur = db.execute("INSERT INTO families(code, title) VALUES(?, ?)", (code, "РќР°С€Рё РїРѕРєСѓРїРєРё"))
    fid = cur.lastrowid
    db.execute("INSERT INTO members VALUES(?,?,?)", (fid, uid, name))
    db.commit()
    return fid
def join_family(uid, name, code):
    fam = one("SELECT * FROM families WHERE code=?", (code.strip().upper(),))
    if not fam: return None
    ex("INSERT OR REPLACE INTO members VALUES(?,?,?)", (fam["id"], uid, name))
    return fam["id"]
def guess_category(text):
    t = text.lower()
    if any(x in t for x in ["С‚Р°Р±Р»РµС‚","Р»РµРєР°СЂ","РІРёС‚Р°РјРёРЅ","Р±РёРЅС‚","РїР»Р°СЃС‚С‹СЂСЊ","РіСЂР°РґСѓСЃ","РєР°РїР»Рё","РјР°Р·СЊ","Р°РїС‚РµРє"]): return "РђРїС‚РµРєР°"
    if any(x in t for x in ["РјС‹Р»Рѕ","С€Р°РјРїСѓРЅСЊ","РіРµР»СЊ","РїРѕСЂРѕС€РѕРє","РіСѓР±Рє","СЃР°Р»С„РµС‚","Р±СѓРјР°Рі","РїР°РєРµС‚","РјРµС€Рє","С‡РёСЃС‚","РјРѕСЋС‰","Р·СѓР±РЅ","РїР°СЃС‚Р°","Р±Р°С‚Р°СЂРµР№"]): return "РҐРѕР·С‚РѕРІР°СЂС‹"
    if any(x in t for x in ["РјРѕР»РѕРєРѕ","С…Р»РµР±","СЃС‹СЂ","Р№РѕРіСѓСЂС‚","РєРµС„РёСЂ","РјР°СЃР»Рѕ","СЏР№С†","РјСЏСЃ","РєСѓСЂ","СЂС‹Р±","РѕРІРѕС‰","С„СЂСѓРєС‚","СЏР±Р»РѕРє","Р±Р°РЅР°РЅ","РєР°СЂС‚Рѕ","Р»СѓРє","РїРѕРјРёРґРѕСЂ","РѕРіСѓСЂ","РєРѕС„Рµ","С‡Р°Р№","СЃР°С…Р°СЂ","СЃРѕР»СЊ","РєСЂСѓРїР°","СЂРёСЃ","РіСЂРµС‡","РјР°РєР°СЂРѕРЅ","РїРµС‡РµРЅСЊ","СЃРѕРє","РІРѕРґР°","РєРѕР»Р±Р°СЃ","С‚РІРѕСЂРѕРі"]): return "РџСЂРѕРґСѓРєС‚С‹"
    return "Р”СЂСѓРіРѕРµ"
def add_items(fid, name, texts, category="auto"):
    added = 0
    for raw in texts:
        text = str(raw).strip(" -вЂў\t\r\n")
        if not text: continue
        text, cat = text[:MAX_LEN], guess_category(text) if category == "auto" else category
        if one("SELECT id FROM items WHERE family_id=? AND lower(text)=? AND done=0", (fid, text.lower())): continue
        ex("INSERT INTO items(family_id, text, added_name, category) VALUES(?,?,?,?)", (fid, text, name, cat))
        added += 1
    return added
def items_of(fid): return q("SELECT * FROM items WHERE family_id=? ORDER BY done, id DESC", (fid,))
def items_json(fid): return [{"id":r["id"],"text":r["text"],"done":bool(r["done"]),"category":r["category"] or "Р”СЂСѓРіРѕРµ","added_name":r["added_name"] or "","ts":r["ts"]} for r in items_of(fid)]
def panel_of(fid, uid): return one("SELECT message_id FROM panels WHERE family_id=? AND user_id=?", (fid, uid))
def save_panel(fid, uid, mid): ex("INSERT OR REPLACE INTO panels VALUES(?,?,?)", (fid, uid, mid))
def drop_panel(fid, uid): ex("DELETE FROM panels WHERE family_id=? AND user_id=?", (fid, uid))
def build_text(fid):
    rows = items_of(fid)
    left, done = sum(1 for r in rows if not r["done"]), len(rows) - sum(1 for r in rows if not r["done"])
    if not rows: return "рџ›’ <b>РќР°С€Рё РїРѕРєСѓРїРєРё</b>\n\nРЎРїРёСЃРѕРє РїСѓСЃС‚ рџ™‚\nРћС‚РєСЂРѕР№С‚Рµ РїСЂРёР»РѕР¶РµРЅРёРµ РёР»Рё РЅР°РїРёС€РёС‚Рµ: РјРѕР»РѕРєРѕ, С…Р»РµР±"
    return f"рџ›’ <b>РќР°С€Рё РїРѕРєСѓРїРєРё</b>\n\nРћСЃС‚Р°Р»РѕСЃСЊ: <b>{left}</b> вЂў РљСѓРїР»РµРЅРѕ: <b>{done}</b>\nРњРѕР¶РЅРѕ РѕС‚РјРµС‡Р°С‚СЊ РїСЂСЏРјРѕ Р·РґРµСЃСЊ РёР»Рё РѕС‚РєСЂС‹С‚СЊ РїСЂРёР»РѕР¶РµРЅРёРµ рџ‘‡"
def build_kb(fid, uid):
    rows, kb = items_of(fid), []
    if WEBAPP_URL: kb.append([InlineKeyboardButton(text="рџ“± РћС‚РєСЂС‹С‚СЊ РїСЂРёР»РѕР¶РµРЅРёРµ", web_app=WebAppInfo(url=WEBAPP_URL))])
    deleting = uid in DELETE_MODE
    for r in rows[:40]:
        title = r["text"][:33] + "вЂ¦" if len(r["text"]) > 34 else r["text"]
        if deleting: kb.append([InlineKeyboardButton(text=f"вќЊ {title}", callback_data=f"d:{r['id']}")])
        else: kb.append([InlineKeyboardButton(text=f"{'вњ…' if r['done'] else 'в–«пёЏ'} {title}", callback_data=f"t:{r['id']}")])
    controls = [InlineKeyboardButton(text="рџ”„ РћР±РЅРѕРІРёС‚СЊ", callback_data="r")]
    done_count = sum(1 for r in rows if r["done"])
    if done_count: controls.append(InlineKeyboardButton(text=f"рџ§№ РЈР±СЂР°С‚СЊ РєСѓРїР»РµРЅРЅРѕРµ ({done_count})", callback_data="c"))
    kb.append(controls)
    if rows: kb.append([InlineKeyboardButton(text="в†©пёЏ Р“РѕС‚РѕРІРѕ" if deleting else "рџ—‘ РЈРґР°Р»РёС‚СЊ С‚РѕРІР°СЂ", callback_data="m")])
    return InlineKeyboardMarkup(inline_keyboard=kb)
async def refresh_family(bot, fid):
    text = build_text(fid)
    for m in members(fid):
        uid, kb, panel = m["user_id"], build_kb(fid, m["user_id"]), panel_of(fid, m["user_id"])
        if panel:
            try: await bot.edit_message_text(text, chat_id=uid, message_id=panel["message_id"], reply_markup=kb); continue
            except TelegramBadRequest as e:
                if "message is not modified" in str(e): continue
                drop_panel(fid, uid)
            except Exception: continue
        try:
            msg = await bot.send_message(uid, text, reply_markup=kb); save_panel(fid, uid, msg.message_id)
        except Exception: pass
async def notify_partner(bot, fid, actor_id, actor_name, texts):
    if not NOTIFY_PARTNER or not texts: return
    body = "\n".join("вЂў " + html.escape(str(x)[:MAX_LEN]) for x in texts[:15])
    for m in members(fid):
        if m["user_id"] == actor_id: continue
        try: await bot.send_message(m["user_id"], f"вћ• <b>{html.escape(actor_name)}</b> РґРѕР±Р°РІРёР»(Р°):\n{body}")
        except Exception: pass
def display_name(m): return m.from_user.first_name or "РљС‚Рѕ-С‚Рѕ"

@dp.message(CommandStart(deep_link=True))
async def start_deeplink(m, command):
    code = (command.args or "").strip(); fid = family_of(m.from_user.id)
    if fid: await cmd_list(m); return
    fid = join_family(m.from_user.id, display_name(m), code)
    if not fid: await m.answer("РЎСЃС‹Р»РєР° РЅРµРґРµР№СЃС‚РІРёС‚РµР»СЊРЅР° рџ¤”\nРќР°РїРёС€РёС‚Рµ /start"); return
    await m.answer("Р“РѕС‚РѕРІРѕ! РўРµРїРµСЂСЊ Сѓ РІР°СЃ РѕР±С‰РёР№ СЃРїРёСЃРѕРє РїРѕРєСѓРїРѕРє рџЋ‰"); await cmd_list(m); await refresh_family(m.bot, fid)

@dp.message(CommandStart())
async def cmd_start(m):
    fid = family_of(m.from_user.id)
    if not fid: fid = create_family(m.from_user.id, display_name(m))
    code = one("SELECT code FROM families WHERE id=?", (fid,))["code"]
    await m.answer(f"рџ‘‹ РЇ вЂ” РЅР°С€ РѕР±С‰РёР№ СЃРїРёСЃРѕРє РїРѕРєСѓРїРѕРє.\n\nРћС‚РїСЂР°РІСЊС‚Рµ СЃСЃС‹Р»РєСѓ:\nhttps://t.me/{BOT_USERNAME}?start={code}\n\nРџРѕСЃР»Рµ РїРѕРґРєР»СЋС‡РµРЅРёСЏ Сѓ РІР°СЃ Р±СѓРґРµС‚ РѕРґРёРЅ РѕР±С‰РёР№ СЃРїРёСЃРѕРє.", disable_web_page_preview=True)
    await cmd_list(m)

@dp.message(Command("invite"))
async def cmd_invite(m):
    fid = family_of(m.from_user.id)
    if not fid: await m.answer("РЎРЅР°С‡Р°Р»Р° РЅР°РїРёС€РёС‚Рµ /start"); return
    code = one("SELECT code FROM families WHERE id=?", (fid,))["code"]
    await m.answer(f"рџ”— РЎСЃС‹Р»РєР°:\nhttps://t.me/{BOT_USERNAME}?start={code}", disable_web_page_preview=True)

@dp.message(Command("app"))
async def cmd_app(m):
    if not WEBAPP_URL: await m.answer("РџСЂРёР»РѕР¶РµРЅРёРµ РЅРµ РїРѕРґРєР»СЋС‡РµРЅРѕ."); return
    await m.answer("РћС‚РєСЂС‹С‚СЊ СЃРїРёСЃРѕРє:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="рџ“± РћС‚РєСЂС‹С‚СЊ РїСЂРёР»РѕР¶РµРЅРёРµ", web_app=WebAppInfo(url=WEBAPP_URL))]]))

@dp.message(Command("list"))
async def cmd_list(m):
    fid = family_of(m.from_user.id)
    if not fid: await m.answer("РќР°РїРёС€РёС‚Рµ /start"); return
    uid = m.from_user.id; DELETE_MODE.discard(uid)
    panel = panel_of(fid, uid)
    if panel:
        try: await m.bot.delete_message(uid, panel["message_id"])
        except Exception: pass
    msg = await m.answer(build_text(fid), reply_markup=build_kb(fid, uid))
    save_panel(fid, uid, msg.message_id)
    try: await m.bot.pin_chat_message(uid, msg.message_id, disable_notification=True)
    except Exception: pass

@dp.message(Command("help"))
async def cmd_help(m):
    await m.answer("РљР°Рє РїРѕР»СЊР·РѕРІР°С‚СЊСЃСЏ:\nвЂў РќР°РїРёС€РёС‚Рµ С‚РѕРІР°СЂ (РјРѕР»РѕРєРѕ, С…Р»РµР±)\nвЂў /app вЂ” РѕС‚РєСЂС‹С‚СЊ РїСЂРёР»РѕР¶РµРЅРёРµ\nвЂў /list вЂ” СЃРїРёСЃРѕРє РІ С‡Р°С‚Рµ\nвЂў /invite вЂ” СЃСЃС‹Р»РєР° РґР»СЏ РІС‚РѕСЂРѕРіРѕ")

@dp.message(F.text & ~F.text.startswith("/"))
async def add_text(m):
    fid = family_of(m.from_user.id)
    if not fid: await m.answer("РќР°РїРёС€РёС‚Рµ /start"); return
    parts = [p.strip() for p in re.split(r"[\n,;]+", m.text) if p.strip()]
    name, added = display_name(m), add_items(fid, display_name(m), parts)
    if added == 0: await m.answer("Р­С‚Рѕ СѓР¶Рµ РµСЃС‚СЊ РІ СЃРїРёСЃРєРµ рџ‰")
    await refresh_family(m.bot, fid); await notify_partner(m.bot, fid, m.from_user.id, name, parts)

@dp.callback_query(F.data == "r")
async def cb_refresh(c):
    fid = family_of(c.from_user.id)
    if fid: await refresh_family(c.bot, fid)
    await c.answer("РћР±РЅРѕРІР»РµРЅРѕ")

@dp.callback_query(F.data == "m")
async def cb_mode(c):
    uid, fid = c.from_user.id, family_of(c.from_user.id)
    if not fid: await c.answer(); return
    if uid in DELETE_MODE: DELETE_MODE.discard(uid); await c.answer("РћР±С‹С‡РЅС‹Р№ СЂРµР¶РёРј")
    else: DELETE_MODE.add(uid); await c.answer("РќР°Р¶РјРёС‚Рµ вќЊ РЅР° С‚РѕРІР°СЂРµ")
    try: await c.message.edit_reply_markup(reply_markup=build_kb(fid, uid))
    except Exception: pass

@dp.callback_query(F.data.startswith("t:"))
async def cb_toggle(c):
    fid = family_of(c.from_user.id)
    if not fid: await c.answer(); return
    iid = int(c.data.split(":")[1])
    row = one("SELECT * FROM items WHERE id=? AND family_id=?", (iid, fid))
    if not row: await c.answer("РўРѕРІР°СЂ СѓРґР°Р»С‘РЅ"); await refresh_family(c.bot, fid); return
    new = 0 if row["done"] else 1
    ex("UPDATE items SET done=? WHERE id=?", (new, iid))
    await c.answer(("вњ… РљСѓРїР»РµРЅРѕ: " if new else "в†©пёЏ Р’РµСЂРЅСѓР»: ") + row["text"][:60])
    await refresh_family(c.bot, fid)

@dp.callback_query(F.data.startswith("d:"))
async def cb_delete(c):
    fid = family_of(c.from_user.id)
    if not fid: await c.answer(); return
    iid = int(c.data.split(":")[1])
    if one("SELECT id FROM items WHERE id=? AND family_id=?", (iid, fid)):
        ex("DELETE FROM items WHERE id=?", (iid,)); await c.answer("РЈРґР°Р»РµРЅРѕ")
    await refresh_family(c.bot, fid)

@dp.callback_query(F.data == "c")
async def cb_clear(c):
    fid = family_of(c.from_user.id)
    if not fid: await c.answer(); return
    count = one("SELECT COUNT(*) n FROM items WHERE family_id=? AND done=1", (fid,))["n"]
    ex("DELETE FROM items WHERE family_id=? AND done=1", (fid,))
    await c.answer(f"РЈР±СЂР°РЅРѕ: {count}"); await refresh_family(c.bot, fid)

@dp.callback_query()
async def cb_other(c): await c.answer()

def verify_telegram_init(init_data):
    if not init_data: return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True); received_hash = None; data = []
        for key, value in pairs:
            if key == "hash": received_hash = value
            else: data.append(f"{key}={value}")
        if not received_hash: return None
        data_check_string = "\n".join(sorted(data))
        secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash): return None
        user = json.loads(dict(pairs).get("user", "{}"))
        return {"id": int(user["id"]), "first_name": user.get("first_name") or "РљС‚Рѕ-С‚Рѕ"}
    except Exception: return None

def api_user(request): return verify_telegram_init(request.headers.get("X-Telegram-Init-Data", ""))
def unauthorized(): return web.json_response({"error": "unauthorized"}, status=401)
def no_family(): return web.json_response({"error": "no_family", "message": "РЎРЅР°С‡Р°Р»Р° РЅР°РїРёС€РёС‚Рµ Р±РѕС‚Сѓ /start"}, status=400)

@web.middleware
async def cors_middleware(request, handler):
    response = web.Response() if request.method == "OPTIONS" else await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

async def page_index(request): return web.Response(text=INDEX_HTML, content_type="text/html")
async def api_list(request):
    user = api_user(request)
    if not user: return unauthorized()
    fid = family_of(user["id"])
    if not fid: return no_family()
    return web.json_response({"items": items_json(fid)})

async def api_add(request):
    user = api_user(request)
    if not user: return unauthorized()
    fid = family_of(user["id"])
    if not fid: return no_family()
    data = await request.json(); items = data.get("items", []); category = data.get("category", "auto")
    if not isinstance(items, list): return web.json_response({"error": "bad_request"}, status=400)
    added = add_items(fid, user["first_name"], items, category)
    asyncio.create_task(refresh_family(dp.bot, fid)); asyncio.create_task(notify_partner(dp.bot, fid, user["id"], user["first_name"], items))
    return web.json_response({"added": added, "items": items_json(fid)})

async def api_toggle(request):
    user = api_user(request)
    if not user: return unauthorized()
    fid = family_of(user["id"])
    if not fid: return no_family()
    data = await request.json(); iid = data.get("id")
    row = one("SELECT * FROM items WHERE id=? AND family_id=?", (iid, fid))
    if not row: return web.json_response({"error": "not_found"}, status=404)
    new = 0 if row["done"] else 1
    ex("UPDATE items SET done=? WHERE id=?", (new, iid))
    asyncio.create_task(refresh_family(dp.bot, fid))
    return web.json_response({"done": bool(new), "items": items_json(fid)})

async def api_delete(request):
    user = api_user(request)
    if not user: return unauthorized()
    fid = family_of(user["id"])
    if not fid: return no_family()
    data = await request.json(); iid = data.get("id")
    ex("DELETE FROM items WHERE id=? AND family_id=?", (iid, fid))
    asyncio.create_task(refresh_family(dp.bot, fid))
    return web.json_response({"ok": True, "items": items_json(fid)})

async def api_clear(request):
    user = api_user(request)
    if not user: return unauthorized()
    fid = family_of(user["id"])
    if not fid: return no_family()
    ex("DELETE FROM items WHERE family_id=? AND done=1", (fid,))
    asyncio.create_task(refresh_family(dp.bot, fid))
    return web.json_response({"ok": True, "items": items_json(fid)})

def create_web_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", page_index)
    app.router.add_get("/api/list", api_list)
    app.router.add_post("/api/add", api_add)
    app.router.add_post("/api/toggle", api_toggle)
    app.router.add_post("/api/delete", api_delete)
    app.router.add_post("/api/clear", api_clear)
    return app

async def on_startup(app):
    global BOT_USERNAME
    if not TOKEN: raise SystemExit("РќРµ Р·Р°РґР°РЅ BOT_TOKEN")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)); dp.bot = bot
    me = await bot.get_me(); BOT_USERNAME = me.username
    await bot.set_my_commands([BotCommand(command="app", description="рџ“± РћС‚РєСЂС‹С‚СЊ РїСЂРёР»РѕР¶РµРЅРёРµ"), BotCommand(command="list", description="рџ›’ РЎРїРёСЃРѕРє РІ С‡Р°С‚Рµ"), BotCommand(command="invite", description="рџ”— РџСЂРёРіР»Р°СЃРёС‚СЊ РІС‚РѕСЂРѕРіРѕ"), BotCommand(command="help", description="в„№пёЏ РџРѕРјРѕС‰СЊ")])
    await bot.delete_webhook(drop_pending_updates=False)
    logging.info("Р‘РѕС‚ @%s Р·Р°РїСѓС‰РµРЅ", BOT_USERNAME); logging.info("API Рё Mini App Р·Р°РїСѓС‰РµРЅС‹ РЅР° РїРѕСЂС‚Сѓ %s", API_PORT)
    asyncio.create_task(dp.start_polling(bot))

async def on_cleanup(app):
    try: await dp.bot.session.close()
    except Exception: pass

async def main():
    app = create_web_app(); app.on_startup.append(on_startup); app.on_cleanup.append(on_cleanup)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT); await site.start()
    await asyncio.Event().wait()

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>РќР°С€Рё РїРѕРєСѓРїРєРё</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root { --bg: var(--tg-theme-bg-color, #ffffff); --text: var(--tg-theme-text-color, #111111); --hint: var(--tg-theme-hint-color, #8a8a8e); --btn: var(--tg-theme-button-color, #3390ec); --btnText: var(--tg-theme-button-text-color, #ffffff); --card: var(--tg-theme-secondary-bg-color, #f3f4f6); }
* { box-sizing: border-box; }
body { margin: 0; padding: 14px; padding-bottom: 90px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: var(--bg); color: var(--text); }
.header { position: sticky; top: 0; z-index: 5; background: var(--bg); padding-bottom: 12px; }
.title { display: flex; justify-content: space-between; align-items: center; }
h1 { margin: 0; font-size: 24px; }
.counter { color: var(--hint); font-size: 14px; margin-top: 4px; }
.clear { border: none; background: var(--card); color: var(--text); border-radius: 12px; padding: 9px 12px; font-size: 14px; }
.addbox { display: grid; grid-template-columns: 1fr 52px; gap: 8px; margin-top: 12px; }
input, select { width: 100%; border: none; outline: none; background: var(--card); color: var(--text); border-radius: 14px; padding: 14px; font-size: 16px; }
.addbtn { border: none; background: var(--btn); color: var(--btnText); border-radius: 14px; font-size: 26px; font-weight: 700; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.tabs { display: flex; gap: 8px; margin: 14px 0; }
.tab { flex: 1; border: none; background: var(--card); color: var(--text); border-radius: 999px; padding: 10px; font-size: 14px; }
.tab.active { background: var(--btn); color: var(--btnText); }
.list { display: flex; flex-direction: column; gap: 9px; }
.item { display: grid; grid-template-columns: 32px 1fr 34px; gap: 10px; align-items: center; background: var(--card); border-radius: 16px; padding: 13px; }
.item.done { opacity: .55; }
.check { width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--hint); display: flex; align-items: center; justify-content: center; font-weight: 800; }
.done .check { background: var(--btn); border-color: var(--btn); color: var(--btnText); }
.name { font-size: 16px; word-break: break-word; }
.done .name { text-decoration: line-through; }
.meta { margin-top: 4px; color: var(--hint); font-size: 12px; }
.del { border: none; background: transparent; color: #ff3b30; font-size: 20px; }
.empty { text-align: center; color: var(--hint); margin-top: 40px; line-height: 1.5; }
.toast { position: fixed; left: 14px; right: 14px; bottom: 18px; background: rgba(0,0,0,.82); color: white; padding: 12px 14px; border-radius: 14px; display: none; text-align: center; z-index: 20; }
.error { background: #ff3b30; color: white; padding: 12px; border-radius: 14px; margin: 12px 0; display: none; }
</style>
</head>
<body>
<div class="header">
    <div class="title">
        <div><h1>рџ›’ РќР°С€Рё РїРѕРєСѓРїРєРё</h1><div class="counter" id="counter">Р—Р°РіСЂСѓР·РєР°...</div></div>
        <button class="clear" onclick="clearBought()">рџ§№</button>
    </div>
    <div class="addbox">
        <input id="newItem" placeholder="РњРѕР»РѕРєРѕ, С…Р»РµР±, СЏР№С†Р°..." onkeydown="if(event.key==='Enter') addItem()">
        <button class="addbtn" onclick="addItem()">+</button>
    </div>
    <div class="row">
        <select id="category">
            <option value="auto">вњЁ РђРІС‚РѕРєР°С‚РµРіРѕСЂРёСЏ</option>
            <option value="РџСЂРѕРґСѓРєС‚С‹">рџҐ¦ РџСЂРѕРґСѓРєС‚С‹</option>
            <option value="РҐРѕР·С‚РѕРІР°СЂС‹">рџ§Ѕ РҐРѕР·С‚РѕРІР°СЂС‹</option>
            <option value="РђРїС‚РµРєР°">рџ’Љ РђРїС‚РµРєР°</option>
            <option value="Р”СЂСѓРіРѕРµ">рџ“¦ Р”СЂСѓРіРѕРµ</option>
        </select>
        <input id="search" placeholder="РџРѕРёСЃРє..." oninput="render()">
    </div>
    <div class="tabs">
        <button class="tab active" id="tab-active" onclick="setFilter('active')">РљСѓРїРёС‚СЊ</button>
        <button class="tab" id="tab-all" onclick="setFilter('all')">Р’СЃРµ</button>
        <button class="tab" id="tab-done" onclick="setFilter('done')">РљСѓРїР»РµРЅРѕ</button>
    </div>
</div>
<div class="error" id="error"></div>
<div class="list" id="list"></div>
<div class="empty" id="empty" style="display:none;">РЎРїРёСЃРѕРє РїСѓСЃС‚.<br>Р”РѕР±Р°РІСЊС‚Рµ РїРµСЂРІСѓСЋ РїРѕРєСѓРїРєСѓ СЃРІРµСЂС…Сѓ рџ™‚</div>
<div class="toast" id="toast"></div>
<script>
const tg = window.Telegram.WebApp; tg.ready(); tg.expand();
let items = []; let filter = "active";
function haptic(type) { try { if (type === "success") tg.HapticFeedback.notificationOccurred("success"); else tg.HapticFeedback.impactOccurred("light"); } catch(e) {} }
function showToast(text) { const el = document.getElementById("toast"); el.textContent = text; el.style.display = "block"; setTimeout(() => el.style.display = "none", 1600); }
function showError(text) { const el = document.getElementById("error"); el.textContent = text; el.style.display = "block"; }
function hideError() { document.getElementById("error").style.display = "none"; }
function esc(s) { const div = document.createElement("div"); div.textContent = s; return div.innerHTML; }
async function api(path, method = "GET", body = null) {
    const options = { method, headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": tg.initData } };
    if (body) options.body = JSON.stringify(body);
    const res = await fetch(path, options);
    if (!res.ok) { let data = {}; try { data = await res.json(); } catch(e) {} throw new Error(data.message || data.error || "РћС€РёР±РєР° СЃРµСЂРІРµСЂР°"); }
    return await res.json();
}
async function loadList() { try { hideError(); const data = await api("/api/list"); items = data.items || []; render(); } catch(e) { showError("РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ СЃРїРёСЃРѕРє. РќР°РїРёС€РёС‚Рµ Р±РѕС‚Сѓ /start."); } }
function setFilter(value) { filter = value; document.querySelectorAll(".tab").forEach(x => x.classList.remove("active")); document.getElementById("tab-" + value).classList.add("active"); render(); }
function render() {
    const search = document.getElementById("search").value.trim().toLowerCase();
    let visible = items.filter(item => { if (filter === "active" && item.done) return false; if (filter === "done" && !item.done) return false; if (search && !item.text.toLowerCase().includes(search)) return false; return true; });
    const left = items.filter(x => !x.done).length; const done = items.filter(x => x.done).length;
    document.getElementById("counter").textContent = "РћСЃС‚Р°Р»РѕСЃСЊ: " + left + " вЂў РљСѓРїР»РµРЅРѕ: " + done;
    const list = document.getElementById("list"); const empty = document.getElementById("empty"); list.innerHTML = "";
    if (visible.length === 0) { empty.style.display = "block"; return; }
    empty.style.display = "none";
    visible.forEach(item => {
        const div = document.createElement("div"); div.className = "item" + (item.done ? " done" : "");
        div.innerHTML = '<div class="check" onclick="toggleItem(' + item.id + ')">' + (item.done ? "вњ“" : "") + '</div><div onclick="toggleItem(' + item.id + ')"><div class="name">' + esc(item.text) + '</div><div class="meta">' + esc(item.category || "Р”СЂСѓРіРѕРµ") + '</div></div><button class="del" onclick="deleteItem(' + item.id + ')">Г—</button>';
        list.appendChild(div);
    });
}
async function addItem() { const input = document.getElementById("newItem"); const category = document.getElementById("category").value; const text = input.value.trim(); if (!text) return; const newItems = text.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean); try { input.value = ""; const data = await api("/api/add", "POST", { items: newItems, category }); items = data.items || items; render(); haptic("success"); showToast("Р”РѕР±Р°РІР»РµРЅРѕ"); } catch(e) { showError(e.message); } }
async function toggleItem(id) { try { const item = items.find(x => x.id === id); if (item) item.done = !item.done; render(); haptic("light"); const data = await api("/api/toggle", "POST", { id }); items = data.items || items; render(); } catch(e) { showError(e.message); loadList(); } }
async function deleteItem(id) { try { items = items.filter(x => x.id !== id); render(); const data = await api("/api/delete", "POST", { id }); items = data.items || items; render(); haptic("light"); } catch(e) { showError(e.message); loadList(); } }
async function clearBought() { try { const data = await api("/api/clear", "POST"); items = data.items || []; render(); haptic("success"); showToast("РљСѓРїР»РµРЅРЅРѕРµ СѓР±СЂР°РЅРѕ"); } catch(e) { showError(e.message); } }
loadList(); setInterval(loadList, 5000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass

