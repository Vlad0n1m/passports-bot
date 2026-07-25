import html
import re

from pydantic import BaseModel

# Порядок полей соответствует колонкам таблицы заказчика
FIELD_LABELS = {
    "fio_en": "ФИО (латиницей)",
    "fio_ru": "ФИО (кириллицей)",
    "birth_date": "Дата рождения",
    "citizenship": "Гражданство",
    "passport_number": "№ паспорта",
    "passport_issue_date": "Паспорт выдан",
    "passport_expiry_date": "Паспорт годен до",
    "ulm_number": "№ УЛМ",
    "ulm_issue_date": "УЛМ выдан",
    "ulm_expiry_date": "УЛМ годен до",
}

_EMPTY_MARKERS = {"", "null", "none", "—", "-"}

_NAME_FIELDS = {"fio_en", "fio_ru"}


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _EMPTY_MARKERS:
        return None
    return text


def _clean_name(value: str | None) -> str | None:
    """Убирает артефакты MRZ-строки: цифры, '<', лишние пробелы."""
    if value is None:
        return None
    cleaned = re.sub(r"[0-9<]+", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


class SeamanData(BaseModel):
    fio_en: str | None = None
    fio_ru: str | None = None
    birth_date: str | None = None
    citizenship: str | None = None
    passport_number: str | None = None
    passport_issue_date: str | None = None
    passport_expiry_date: str | None = None
    ulm_number: str | None = None
    ulm_issue_date: str | None = None
    ulm_expiry_date: str | None = None

    @classmethod
    def from_raw(cls, data: dict) -> "SeamanData":
        values = {key: _clean(data.get(key)) for key in FIELD_LABELS}
        for key in _NAME_FIELDS:
            values[key] = _clean_name(values[key])
        return cls(**values)

    def merge(self, other: "SeamanData") -> None:
        """Новые непустые значения перекрывают старые (свежее фото — точнее)."""
        for key in FIELD_LABELS:
            value = getattr(other, key)
            if value is not None:
                setattr(self, key, value)

    def is_empty(self) -> bool:
        return all(getattr(self, key) is None for key in FIELD_LABELS)

    def missing_fields(self) -> list[str]:
        return [FIELD_LABELS[key] for key in FIELD_LABELS if getattr(self, key) is None]

    def status_message(self, index: int) -> str:
        def line(label: str, key: str) -> str:
            value = getattr(self, key)
            if value is None:
                return f"❌ <b>{label}</b>: не найдено"
            return f"✅ <b>{label}</b>: {html.escape(value)}"

        lines = [f"👤 <b>Моряк №{index}</b>", ""]
        lines.append(line("ФИО (латиницей)", "fio_en"))
        lines.append(line("ФИО (кириллицей)", "fio_ru"))
        lines.append("✍️ <b>Должность</b>: заполняется вручную")
        lines.append(line("Дата рождения", "birth_date"))
        lines.append(line("Гражданство", "citizenship"))
        lines.append(line("№ паспорта", "passport_number"))
        lines.append(line("Паспорт выдан", "passport_issue_date"))
        lines.append(line("Паспорт годен до", "passport_expiry_date"))
        lines.append(line("№ УЛМ", "ulm_number"))
        lines.append(line("УЛМ выдан", "ulm_issue_date"))
        lines.append(line("УЛМ годен до", "ulm_expiry_date"))

        missing = self.missing_fields()
        lines.append("")
        if missing:
            lines.append(
                "⚠️ Не удалось найти: " + ", ".join(missing) + ".\n"
                "Отправьте ещё фото (другую страницу паспорта, УЛМ) — данные дополнятся."
            )
        else:
            lines.append("Все поля заполнены! 🎉")
        return "\n".join(lines)

    def to_row(self) -> list[str]:
        """Одна строка таблицы на моряка, внутри ячеек — переносы строк."""

        def period(issue: str | None, expiry: str | None) -> str:
            if issue and expiry:
                return f"{issue} – {expiry}"
            return issue or expiry or ""

        def doc_lines(number: str | None, issue: str | None, expiry: str | None) -> list[str]:
            return [part for part in (number or "", period(issue, expiry)) if part]

        fio = "\n".join(part for part in (self.fio_en, self.fio_ru) if part)
        birth = "\n".join(part for part in (self.birth_date, self.citizenship) if part)
        docs = "\n".join(
            doc_lines(self.passport_number, self.passport_issue_date, self.passport_expiry_date)
            + doc_lines(self.ulm_number, self.ulm_issue_date, self.ulm_expiry_date)
        )
        return [fio, "", birth, docs]  # должность заполняется вручную
