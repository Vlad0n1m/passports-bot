import base64
import json
import logging
import re
from typing import Optional

import httpx

from bot.config import settings
from bot.models.seaman import SeamanData

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

EXTRACTION_PROMPT = """Ты — система распознавания документов моряков. На фото могут быть:
загранпаспорт РФ, внутренний паспорт РФ, удостоверение личности моряка (УЛМ),
мореходная книжка или другие документы. Все фото относятся к ОДНОМУ человеку.

Извлеки данные и верни JSON-объект строго с такими ключами:
- "fio_en" — фамилия и имя латиницей, в первую очередь из визуальной зоны загранпаспорта
  (поля Surname / Given names). Если визуальная зона не читается — возьми из машиносчитываемой
  MRZ-строки внизу, но убери оттуда символы "<" и цифры (в MRZ имя может быть обрезано — это нормально).
  Пример результата: "Kormakov Aleksandr". Цифр и "<" в ответе быть не должно.
- "fio_ru" — фамилия, имя, отчество кириллицей (пример: "Кормаков Александр Романович")
- "birth_date" — дата рождения
- "citizenship" — гражданство кириллицей заглавными буквами (пример: "РОССИЯ")
- "passport_number" — номер паспорта: ЛЮБОГО, который есть на фото — заграничного
  (пример: "75 5715427") или внутреннего паспорта РФ (пример: "40 25 243511").
  Если на фото оба — приоритет у заграничного.
- "passport_issue_date" — дата выдачи этого паспорта
- "passport_expiry_date" — дата окончания этого паспорта (у внутреннего паспорта РФ её нет — null)
- "ulm_number" — номер УЛМ (пример: "RUS 0621224")
- "ulm_issue_date" — дата выдачи УЛМ
- "ulm_expiry_date" — дата окончания УЛМ

Правила:
- Если поле не видно или его нет на документах — верни null. Не выдумывай значения.
- Все даты в формате ДД.ММ.ГГГГ.
- Не путай загранпаспорт и УЛМ: номер УЛМ обычно начинается с кода страны (RUS и т.п.).
- Верни только JSON без markdown и пояснений."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


class OpenRouterError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenRouterClient:
    def __init__(self) -> None:
        self._api_key = settings.openrouter_api_key
        self._model = settings.openrouter_model

    async def extract_seaman_data(
        self, images: list[tuple[bytes, str]]
    ) -> SeamanData:
        """Извлекает данные моряка из одного или нескольких фото документов."""
        content: list[dict] = [{"type": "text", "text": EXTRACTION_PROMPT}]
        for image_bytes, mime_type in images:
            b64 = base64.b64encode(image_bytes).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                }
            )

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/passports-bot",
            "X-Title": "Passports Bot",
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)

        if response.is_error:
            try:
                error_body = response.json()
                message = error_body.get("error", {}).get("message", response.text)
            except json.JSONDecodeError:
                message = response.text
            raise OpenRouterError(message, response.status_code)

        body = response.json()
        content_text = body["choices"][0]["message"]["content"]
        raw_data = _extract_json(content_text)
        return SeamanData.from_raw(raw_data)
