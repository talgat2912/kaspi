import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import db
import kaspi
import report

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Asia/Almaty")


# ── FSM ────────────────────────────────────────────────────────────────────
class AddCodes(StatesGroup):
    waiting = State()

class CheckSingle(StatesGroup):
    waiting = State()

class SetSchedule(StatesGroup):
    waiting = State()


# ── Клавиатура ─────────────────────────────────────────────────────────────
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить коды"), KeyboardButton(text="📋 Мои коды")],
            [KeyboardButton(text="🔍 Проверить код"), KeyboardButton(text="▶️ Запуск")],
            [KeyboardButton(text="📊 Отчёт"),         KeyboardButton(text="📅 Расписание")],
            [KeyboardButton(text="📥 Массовый ввод"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )


# ── Форматирование результата ───────────────────────────────────────────────
def format_result(res: dict, delta: int | None = None) -> str:
    code = res["code"]

    if not res.get("name"):
        return f"Код {code}: не найден на Kaspi ❌"

    if not res["found"]:
        return f"Код {code}: не найден в топ-1008 ⚠️\nТовар: {res['name']}"

    delta_str = ""
    if delta is not None:
        if delta > 0:
            delta_str = f" ↑ {delta} поз."
        elif delta < 0:
            delta_str = f" ↓ {abs(delta)} поз."
        else:
            delta_str = " → без изменений"

    return (
        f"Товар: {res['name']} | Код: {code} | "
        f"Позиция: стр. {res['page']}, место {res['place_on_page']} "
        f"(#{res['position']}){delta_str}"
    )


async def run_check_for_user(user_id: int) -> str:
    codes = db.get_codes(user_id)
    if not codes:
        return "У тебя нет добавленных кодов. Нажми ➕ Добавить коды"

    lines = []
    for code in codes:
        res = await kaspi.check_code(code)

        delta = None
        last = db.get_last_position(user_id, code)
        if last and res.get("position") is not None:
            if last["position"] is not None:
                delta = last["position"] - res["position"]

        db.save_position(
            user_id, code, res.get("name"),
            res.get("position"), res.get("page"), res.get("place_on_page")
        )
        lines.append(format_result(res, delta))

    return "\n\n".join(lines)


# ── /start ──────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Привет! Я бот для отслеживания позиций товаров на Kaspi.kz\n\n"
        "Добавь коды своих товаров и я буду следить за их позициями в поиске.",
        reply_markup=main_kb()
    )


# ── Добавить коды ───────────────────────────────────────────────────────────
@dp.message(F.text.in_({"➕ Добавить коды", "📥 Массовый ввод"}))
async def add_codes_start(message: Message, state: FSMContext):
    await state.set_state(AddCodes.waiting)
    await message.answer(
        "Отправь коды товаров — каждый с новой строки или через пробел.\n\n"
        "Пример:\n<code>158994351\n159364582\n158994341</code>\n\n"
        "Где найти код: открой товар на Kaspi → в конце URL будет число.\n"
        "kaspi.kz/shop/p/название-<b>158994351</b>/",
        parse_mode="HTML"
    )


@dp.message(AddCodes.waiting)
async def add_codes_process(message: Message, state: FSMContext):
    await state.clear()
    import re
    raw = re.findall(r'\d{6,12}', message.text)

    if not raw:
        await message.answer("❌ Не нашёл корректных кодов. Код — это число от 6 до 12 цифр.")
        return

    added, dupes = [], []
    for code in raw:
        if db.add_code(message.from_user.id, code):
            added.append(code)
        else:
            dupes.append(code)

    text = ""
    if added:
        text += f"✅ Добавлено: {', '.join(added)}\n"
    if dupes:
        text += f"⚠️ Уже были: {', '.join(dupes)}"

    await message.answer(text.strip(), reply_markup=main_kb())


# ── Мои коды ────────────────────────────────────────────────────────────────
@dp.message(F.text == "📋 Мои коды")
async def my_codes(message: Message):
    codes = db.get_codes(message.from_user.id)
    if not codes:
        await message.answer("У тебя нет добавленных кодов.\nНажми ➕ Добавить коды")
        return

    text = "Ваши коды:\n"
    for code in codes:
        text += f"• <code>{code}</code>\n"
    text += "\nЧтобы удалить: /untrack 158994351"
    await message.answer(text, parse_mode="HTML")


# ── /untrack ─────────────────────────────────────────────────────────────────
@dp.message(Command("untrack"))
async def untrack_cmd(message: Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Использование: /untrack 158994351")
        return
    code = parts[1].strip()
    if db.remove_code(message.from_user.id, code):
        await message.answer(f"✅ Код {code} удалён.")
    else:
        await message.answer(f"❌ Код {code} не найден в твоём списке.")


# ── Проверить один код ──────────────────────────────────────────────────────
@dp.message(F.text == "🔍 Проверить код")
async def check_single_start(message: Message, state: FSMContext):
    await state.set_state(CheckSingle.waiting)
    await message.answer("Отправь код товара для проверки:")


@dp.message(CheckSingle.waiting)
async def check_single_process(message: Message, state: FSMContext):
    await state.clear()
    code = message.text.strip()
    if not code.isdigit():
        await message.answer("❌ Код должен быть числом.")
        return

    msg = await message.answer(f"🔍 Проверяю код {code}...")
    res = await kaspi.check_code(code)

    last = db.get_last_position(message.from_user.id, code)
    delta = None
    if last and res.get("position") is not None and last["position"] is not None:
        delta = last["position"] - res["position"]

    db.save_position(
        message.from_user.id, code, res.get("name"),
        res.get("position"), res.get("page"), res.get("place_on_page")
    )
    await msg.edit_text(format_result(res, delta))


# ── Запуск всех кодов ────────────────────────────────────────────────────────
@dp.message(F.text == "▶️ Запуск")
async def run_all(message: Message):
    codes = db.get_codes(message.from_user.id)
    if not codes:
        await message.answer("У тебя нет добавленных кодов.")
        return
    msg = await message.answer(f"Проверяю {len(codes)} шт...")
    result_text = await run_check_for_user(message.from_user.id)
    await msg.edit_text(result_text)


# ── Отчёт Excel ──────────────────────────────────────────────────────────────
@dp.message(F.text == "📊 Отчёт")
async def send_report(message: Message):
    rows = db.get_all_history(message.from_user.id)
    if not rows:
        await message.answer("Нет данных. Сначала запусти ▶️ Запуск")
        return
    xlsx = report.generate_report(rows)
    filename = f"kaspi_report_{datetime.now().strftime('%d%m%Y_%H%M')}.xlsx"
    await message.answer_document(
        BufferedInputFile(xlsx.read(), filename=filename),
        caption="📊 Отчёт по позициям товаров"
    )


# ── Расписание ───────────────────────────────────────────────────────────────
@dp.message(F.text == "📅 Расписание")
async def schedule_menu(message: Message, state: FSMContext):
    sched = db.get_schedule(message.from_user.id)
    current = f"Текущее расписание: {sched['hour']:02d}:{sched['minute']:02d}\n\n" if sched else ""
    await state.set_state(SetSchedule.waiting)
    await message.answer(
        f"{current}"
        "Введи время автопроверки в формате ЧЧ:ММ (по Алматы)\n"
        "Пример: <code>09:00</code> или <code>18:30</code>\n\n"
        "Отключить: /schedule_off",
        parse_mode="HTML"
    )


@dp.message(SetSchedule.waiting)
async def schedule_set(message: Message, state: FSMContext):
    await state.clear()
    try:
        parts = message.text.strip().split(":")
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except Exception:
        await message.answer("❌ Неверный формат. Пример: 09:00")
        return
    db.set_schedule(message.from_user.id, hour, minute)
    _reload_schedules()
    await message.answer(f"✅ Автопроверка каждый день в {hour:02d}:{minute:02d} по Алматы.")


@dp.message(Command("schedule_off"))
async def schedule_off(message: Message, state: FSMContext):
    await state.clear()
    db.remove_schedule(message.from_user.id)
    _reload_schedules()
    await message.answer("✅ Автопроверка отключена.")


# ── Помощь ────────────────────────────────────────────────────────────────────
@dp.message(F.text == "ℹ️ Помощь")
async def help_cmd(message: Message):
    await message.answer(
        "📖 <b>Как пользоваться:</b>\n\n"
        "1️⃣ <b>Добавить коды</b> — вводи артикулы товаров\n"
        "2️⃣ <b>Запуск</b> — проверить все товары сразу\n"
        "3️⃣ <b>Проверить код</b> — проверить один товар\n"
        "4️⃣ <b>Отчёт</b> — скачать Excel с позициями\n"
        "5️⃣ <b>Расписание</b> — автопроверка каждый день\n"
        "6️⃣ /untrack <код> — удалить код из списка\n\n"
        "📌 <b>Где найти код товара:</b>\n"
        "Открой товар на Kaspi → смотри URL в браузере:\n"
        "kaspi.kz/shop/p/название-<b>158994351</b>/\n"
        "Число в конце — это и есть код.",
        parse_mode="HTML"
    )


# ── Scheduler ─────────────────────────────────────────────────────────────────
def _reload_schedules():
    for job in scheduler.get_jobs():
        if job.id.startswith("autocheck_"):
            job.remove()
    for row in db.get_all_schedules():
        scheduler.add_job(
            _auto_check,
            CronTrigger(hour=row["hour"], minute=row["minute"], timezone="Asia/Almaty"),
            id=f"autocheck_{row['user_id']}",
            args=[row["user_id"]],
            replace_existing=True,
        )


async def _auto_check(user_id: int):
    try:
        result_text = await run_check_for_user(user_id)
        await bot.send_message(
            user_id,
            f"⏰ <b>Автопроверка позиций:</b>\n\n{result_text}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка автопроверки user {user_id}: {e}")


# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    db.init_db()
    _reload_schedules()
    scheduler.start()
    logger.info("Бот запущен ✅")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
