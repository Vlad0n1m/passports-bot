from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.session import BTN_FINISH, BTN_NEW_TABLE, BTN_NEXT_SEAMAN, idle_keyboard

router = Router()

WELCOME_TEXT = (
    "Привет! Я помогаю заполнять таблицы экипажа по фото документов.\n\n"
    "Как это работает:\n"
    f"1. Нажмите «{BTN_NEW_TABLE}»\n"
    "2. Отправьте фото документов моряка — паспорт, УЛМ (можно несколько фото)\n"
    "3. Я покажу, какие поля заполнил, а какие не нашёл\n"
    f"4. Нажмите «{BTN_NEXT_SEAMAN}» и загрузите документы следующего\n"
    f"5. Нажмите «{BTN_FINISH}» — пришлю ссылку на готовую таблицу в Google Sheets"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=idle_keyboard)
