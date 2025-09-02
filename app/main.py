import os, re, json
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Update, Message
import httpx

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
WEBHOOK_SECRET= os.environ.get("WEBHOOK_SECRET", "secret")
WEBAPP_URL    = os.environ.get("WEBAPP_URL", "")
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")

bot = Bot(BOT_TOKEN)
dp  = Dispatcher()
app = FastAPI()

async def sb_insert(table: str, row: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"ok": False, "error": "Supabase not configured"}
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=row)
        try:
            data = r.json()
        except Exception:
            data = {"status": r.status_code, "text": r.text}
        return {"status": r.status_code, "data": data}

def parse_expense(text: str):
    m = re.search(r"(?P<cat>[^\d]+?)\s+(?P<amt>\d{2,})\s*(?P<rest>.*)$", text.strip(), re.IGNORECASE)
    if not m: return None
    return {
        "category_name": m.group("cat").strip().lower(),
        "amount_krw": int(m.group("amt")),
        "merchant": (m.group("rest") or "").strip() or None
    }

def parse_food(text: str):
    m = re.search(r"^(?P<name>[^\d]+?)\s+(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>шт|г|мл|л)$", text.strip(), re.IGNORECASE)
    if not m: return None
    return {
        "product_name": m.group("name").strip(),
        "amount": float(m.group("amount").replace(",", ".")),
        "amount_unit": m.group("unit").lower()
    }

@dp.message(Command("start"))
async def cmd_start(m: Message):
    await m.answer(
        "👋 Привет! Я помогу вести калории и бюджет.\n"
        "Открой WebApp или пиши: `яйца 2шт`, `кофе 4800`.",
        parse_mode="Markdown"
    )
    await cmd_app(m)

@dp.message(Command("app"))
async def cmd_app(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL or "https://example.com"))
    ]])
    await m.answer("Открыть приложение:", reply_markup=kb)

@dp.message(Command("product"))
async def cmd_product(m: Message):
    template = (
        "Скопируй и заполни, потом пришли обратно:\n"
        "```\n"
        "название: \nалиасы: \nединица_базовая: шт|г|мл|л\nвес_1_ед_в_г: \n"
        "ккал_на_100г: \nбелки_на_100г: \nжиры_на_100г: \nуглеводы_на_100г: \n"
        "размер_упаковки_ед: \nцена_за_упаковку_krw: \nисточник: \n"
        "```\nИли используй форму в WebApp."
    )
    await m.answer(template, parse_mode="Markdown")

@dp.message(Command("day"))
async def cmd_day(m: Message):
    await m.answer("📅 Сегодня: калории 0 / 0 · Еда 0₩ · Расходы 0₩ · Остаток месяца: 0₩ (демо)")

@dp.message(F.web_app_data)
async def on_webapp_data(m: Message):
    try:
        payload = json.loads(m.web_app_data.data)
    except Exception:
        return await m.answer("Не удалось прочитать данные из формы.")
    if "name" in payload and "base_unit" in payload:
        row = {
            "user_id": str(m.from_user.id),
            "name": payload.get("name"),
            "aliases": payload.get("aliases") or [],
            "base_unit": payload.get("base_unit"),
            "unit_weight_g": payload.get("unit_weight_g"),
            "pack_size_units": payload.get("pack_size_units"),
            "pack_price_krw": payload.get("pack_price_krw"),
            "kcal_per_100g": payload.get("kcal_per_100g"),
            "p_per_100g": payload.get("p_per_100g"),
            "f_per_100g": payload.get("f_per_100g"),
            "c_per_100g": payload.get("c_per_100g"),
            "image_url": None,
            "source": payload.get("source"),
        }
        res = await sb_insert("products", row)
        if res.get("status") in (200, 201):
            await m.answer(f"✅ Продукт «{row['name']}» сохранён.")
        else:
            await m.answer(f"⚠️ Не удалось сохранить продукт: {res}")
    else:
        await m.answer("Получены данные формы (демо).")

@dp.message(F.text)
async def fallback_text(m: Message):
    text = m.text.strip()

    e = parse_expense(text)
    if e and e["amount_krw"] > 0:
        row = {"user_id": str(m.from_user.id), **e}
        _ = await sb_insert("expenses", row)
        return await m.answer(f"💸 {e['category_name']}: −{e['amount_krw']}₩ записано.")

    f = parse_food(text)
    if f:
        row = {"user_id": str(m.from_user.id), **f}
        _ = await sb_insert("intake", row)
        return await m.answer(f"🍽️ {f['product_name']} {f['amount']}{f['amount_unit']} — записано.")

    await m.answer("Не понял. Пример: «кофе 4800» или «яйца 2шт». Команда: /app")

@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_webhook_update(bot, update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok"}
