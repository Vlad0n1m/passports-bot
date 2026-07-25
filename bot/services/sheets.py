import asyncio
import logging
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from bot.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER = [
    "Фамилия, имя, отчество",
    "Должность",
    "Дата рождения, гражданство",
    "№ паспорта, УЛМ Выдан, годен до",
]

COLUMN_WIDTHS = [230, 180, 170, 220]


class SheetsError(Exception):
    pass


def _create_table_sync(rows: list[list[str]]) -> str:
    key_path = Path(settings.google_service_account_file)
    if not key_path.exists():
        raise SheetsError(
            f"Файл ключа сервисного аккаунта не найден: {key_path}. "
            "Укажите GOOGLE_SERVICE_ACCOUNT_FILE в .env."
        )

    creds = Credentials.from_service_account_file(str(key_path), scopes=SCOPES)
    gc = gspread.authorize(creds)

    title = f"Экипаж {datetime.now():%d.%m.%Y %H-%M-%S}"
    values = [HEADER] + rows

    if settings.google_spreadsheet_id:
        spreadsheet = gc.open_by_key(settings.google_spreadsheet_id)
        worksheet = spreadsheet.add_worksheet(
            title=title, rows=len(values) + 10, cols=len(HEADER) + 2
        )
    else:
        spreadsheet = gc.create(title)
        spreadsheet.share(None, perm_type="anyone", role="writer", with_link=True)
        worksheet = spreadsheet.sheet1
        worksheet.update_title("Экипаж")

    # RAW — чтобы Sheets не переформатировал даты и номера, текст копируется как есть
    worksheet.update(values=values, value_input_option="RAW")
    _apply_formatting(spreadsheet, worksheet.id, n_rows=len(values))

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit#gid={worksheet.id}"


def _apply_formatting(spreadsheet: gspread.Spreadsheet, sheet_id: int, n_rows: int) -> None:
    n_cols = len(HEADER)
    full_range = {
        "sheetId": sheet_id,
        "startRowIndex": 0,
        "endRowIndex": n_rows,
        "startColumnIndex": 0,
        "endColumnIndex": n_cols,
    }
    solid = {"style": "SOLID"}
    requests = [
        {
            "repeatCell": {
                "range": {**full_range, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
            }
        },
        {
            "repeatCell": {
                "range": {**full_range, "startRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                    }
                },
                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)",
            }
        },
        {
            "updateBorders": {
                "range": full_range,
                "top": solid,
                "bottom": solid,
                "left": solid,
                "right": solid,
                "innerHorizontal": solid,
                "innerVertical": solid,
            }
        },
    ]
    for col_index, width in enumerate(COLUMN_WIDTHS):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": col_index,
                        "endIndex": col_index + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )
    spreadsheet.batch_update({"requests": requests})


async def create_table(rows: list[list[str]]) -> str:
    """Создаёт лист с таблицей экипажа и возвращает прямую ссылку на него."""
    try:
        return await asyncio.to_thread(_create_table_sync, rows)
    except SheetsError:
        raise
    except gspread.exceptions.APIError as exc:
        logger.exception("Google Sheets API error")
        if "storage quota" in str(exc):
            raise SheetsError(
                "у сервисных аккаунтов Google нет места на Drive, поэтому создать "
                "новую таблицу нельзя. Создайте свою Google-таблицу, дайте сервисному "
                "аккаунту доступ «Редактор» и укажите её ID в GOOGLE_SPREADSHEET_ID "
                "в .env — бот будет добавлять в неё листы."
            ) from exc
        raise SheetsError(f"Ошибка Google Sheets API: {exc}") from exc
