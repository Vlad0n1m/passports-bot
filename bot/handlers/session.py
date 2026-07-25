import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.models.seaman import SeamanData
from bot.services import sheets
from bot.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)
router = Router()
openrouter = OpenRouterClient()

BTN_NEW_TABLE = "🆕 Новая таблица"
BTN_NEXT_SEAMAN = "➡️ Следующий паспорт"
BTN_RESET_SEAMAN = "🔄 Сбросить текущего моряка"
BTN_FINISH = "✅ Завершить"
BTN_CANCEL = "❌ Отменить всё"

ALBUM_COLLECT_DELAY = 2.0

idle_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_NEW_TABLE)]],
    resize_keyboard=True,
)

session_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_NEXT_SEAMAN)],
        [KeyboardButton(text=BTN_RESET_SEAMAN)],
        [KeyboardButton(text=BTN_FINISH), KeyboardButton(text=BTN_CANCEL)],
    ],
    resize_keyboard=True,
)


class TableSession(StatesGroup):
    collecting = State()


# Буфер фото из альбомов: (chat_id, media_group_id) -> список изображений
_album_buffers: dict[tuple[int, str], list[tuple[bytes, str]]] = {}


async def _get_current(state: FSMContext) -> tuple[list[dict], SeamanData]:
    data = await state.get_data()
    persons: list[dict] = data.get("persons", [])
    current = SeamanData(**data.get("current", {}))
    return persons, current


@router.message(F.text == BTN_NEW_TABLE)
async def new_table(message: Message, state: FSMContext) -> None:
    await state.set_state(TableSession.collecting)
    await state.set_data({"persons": [], "current": {}, "person_token": 0})
    await message.answer(
        "📋 Сессия начата!\n\n"
        "Отправьте фото документов <b>первого моряка</b> — паспорт, УЛМ, "
        "можно несколько фото сразу (альбомом или по одному).\n\n"
        f"Когда данные моряка заполнены — нажмите «{BTN_NEXT_SEAMAN}».\n"
        f"Замешалось не то фото — «{BTN_RESET_SEAMAN}», сохранённые моряки не пострадают.\n"
        f"Когда все моряки добавлены — «{BTN_FINISH}», и я пришлю ссылку на таблицу.",
        reply_markup=session_keyboard,
    )


@router.message(TableSession.collecting, F.text == BTN_NEXT_SEAMAN)
async def next_seaman(message: Message, state: FSMContext) -> None:
    persons, current = await _get_current(state)
    if current.is_empty():
        await message.answer(
            "Сначала отправьте фото документов текущего моряка.",
            reply_markup=session_keyboard,
        )
        return

    persons.append(current.model_dump())
    data = await state.get_data()
    await state.set_data(
        {
            "persons": persons,
            "current": {},
            "person_token": data.get("person_token", 0) + 1,
        }
    )

    missing = current.missing_fields()
    warning = (
        f"\n⚠️ У него остались пустые поля: {', '.join(missing)}." if missing else ""
    )
    await message.answer(
        f"💾 Моряк №{len(persons)} сохранён.{warning}\n\n"
        f"Отправьте фото документов <b>следующего моряка</b> "
        f"(№{len(persons) + 1}).",
        reply_markup=session_keyboard,
    )


@router.message(TableSession.collecting, F.text == BTN_FINISH)
async def finish(message: Message, state: FSMContext) -> None:
    persons, current = await _get_current(state)
    if not current.is_empty():
        persons.append(current.model_dump())

    if not persons:
        await message.answer(
            "Таблица пуста — сначала отправьте фото документов хотя бы одного моряка.",
            reply_markup=session_keyboard,
        )
        return

    status_msg = await message.answer("⏳ Генерирую таблицу...")

    rows = [SeamanData(**person).to_row() for person in persons]

    try:
        url = await sheets.create_table(rows)
    except sheets.SheetsError as exc:
        logger.error("Sheets error: %s", exc)
        await status_msg.edit_text(
            f"Не удалось создать таблицу: {exc}\n\n"
            "Данные не потеряны — исправьте настройки и нажмите "
            f"«{BTN_FINISH}» ещё раз."
        )
        return
    except Exception:
        logger.exception("Failed to create Google Sheet")
        await status_msg.edit_text(
            "Не удалось создать таблицу из-за внутренней ошибки. "
            f"Данные не потеряны — нажмите «{BTN_FINISH}» ещё раз."
        )
        return

    await state.clear()
    await status_msg.edit_text(
        f"✅ Готово! Моряков в таблице: {len(persons)}.\n\n"
        f'<a href="{url}">Открыть таблицу в Google Sheets</a>\n\n'
        "Скопируйте таблицу целиком и вставьте в ваш документ.",
        disable_web_page_preview=True,
    )
    await message.answer(
        "Чтобы начать новую таблицу — нажмите кнопку ниже.",
        reply_markup=idle_keyboard,
    )


@router.message(TableSession.collecting, F.text == BTN_RESET_SEAMAN)
async def reset_current_seaman(message: Message, state: FSMContext) -> None:
    persons, current = await _get_current(state)
    if current.is_empty():
        await message.answer(
            f"У текущего моряка (№{len(persons) + 1}) ещё нет данных — сбрасывать нечего.",
            reply_markup=session_keyboard,
        )
        return

    data = await state.get_data()
    await state.update_data(
        current={}, person_token=data.get("person_token", 0) + 1
    )
    saved_note = (
        f"Сохранённые моряки (1–{len(persons)}) не тронуты.\n\n" if persons else ""
    )
    await message.answer(
        f"🔄 Данные моряка №{len(persons) + 1} сброшены. {saved_note}"
        "Отправьте его документы заново.",
        reply_markup=session_keyboard,
    )


@router.message(TableSession.collecting, F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Сессия отменена, данные удалены.", reply_markup=idle_keyboard)


async def _download_image(message: Message, bot: Bot) -> tuple[bytes, str]:
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        mime_type = "image/jpeg"
    else:
        file = await bot.get_file(message.document.file_id)
        mime_type = message.document.mime_type
    data = await bot.download_file(file.file_path)
    return data.read(), mime_type


async def _process_images(
    message: Message, state: FSMContext, images: list[tuple[bytes, str]]
) -> None:
    count_note = f" ({len(images)} фото)" if len(images) > 1 else ""
    status_msg = await message.answer(f"🔍 Распознаю документы{count_note}...")

    # Запоминаем, к какому моряку относились фото на момент отправки
    token_before = (await state.get_data()).get("person_token", 0)

    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        extracted = await openrouter.extract_seaman_data(images)
    except OpenRouterError as exc:
        logger.error("OpenRouter API error: %s", exc)
        await status_msg.edit_text(
            f"Ошибка распознавания: {exc}\nПопробуйте отправить фото ещё раз."
        )
        return
    except Exception:
        logger.exception("Failed to process document photos")
        await status_msg.edit_text(
            "Не удалось распознать документ. Попробуйте более чёткое фото."
        )
        return

    # Состояние могло измениться, пока шло распознавание — перечитываем
    if await state.get_state() != TableSession.collecting.state:
        await status_msg.edit_text(
            "Сессия уже завершена, эти фото не были добавлены."
        )
        return

    data = await state.get_data()
    if data.get("person_token", 0) != token_before:
        await status_msg.edit_text(
            "Пока шло распознавание, вы сбросили или сохранили моряка — "
            "эти фото не были добавлены. Если нужно, отправьте их заново."
        )
        return

    persons, current = await _get_current(state)
    current.merge(extracted)
    await state.update_data(current=current.model_dump())

    await status_msg.edit_text(current.status_message(len(persons) + 1))


async def _flush_album(key: tuple[int, str], message: Message, state: FSMContext) -> None:
    await asyncio.sleep(ALBUM_COLLECT_DELAY)
    images = _album_buffers.pop(key, [])
    if images:
        await _process_images(message, state, images)


@router.message(
    TableSession.collecting,
    F.photo | (F.document & F.document.mime_type.startswith("image/")),
)
async def handle_document_photo(message: Message, bot: Bot, state: FSMContext) -> None:
    try:
        image = await _download_image(message, bot)
    except Exception:
        logger.exception("Failed to download photo")
        await message.answer("Не удалось скачать фото, отправьте его ещё раз.")
        return

    if message.media_group_id:
        key = (message.chat.id, message.media_group_id)
        buffer = _album_buffers.setdefault(key, [])
        buffer.append(image)
        if len(buffer) == 1:
            asyncio.create_task(_flush_album(key, message, state))
        return

    await _process_images(message, state, [image])


@router.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def photo_without_session(message: Message) -> None:
    await message.answer(
        f"Сначала нажмите «{BTN_NEW_TABLE}», чтобы начать заполнение таблицы.",
        reply_markup=idle_keyboard,
    )


@router.message(F.text.in_({BTN_NEXT_SEAMAN, BTN_RESET_SEAMAN, BTN_FINISH, BTN_CANCEL}))
async def session_button_without_session(message: Message) -> None:
    await message.answer(
        f"Активной сессии нет. Нажмите «{BTN_NEW_TABLE}», чтобы начать.",
        reply_markup=idle_keyboard,
    )
