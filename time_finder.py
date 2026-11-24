from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

# Проверяем время в 24-часовом формате: от 00:00:00 до 23:59:59.
TIME_CORE = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
TIME_FULL = re.compile(TIME_CORE)
# При поиске исключаем совпадения внутри слов и более длинных значений.
TIME_SEARCH = re.compile(rf"(?<![\w:]){TIME_CORE}(?![\w:]|\.[0-9])")
MAX_PAGE_BYTES = 5 * 1024 * 1024


# Из HTML извлекаем текст, пропуская некоторые служебные теги.
class VisibleTextParser(HTMLParser):
    HIDDEN = frozenset({
        "head", "script", "style", "noscript", "template", "svg"
    })
    BLOCK = frozenset({
        "address", "article", "aside", "blockquote", "br", "div", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
        "main", "nav", "ol", "p", "section", "table", "td", "th",
        "tr", "ul",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._hidden: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in self.HIDDEN:
            self._hidden.append(tag)
        elif not self._hidden and tag in self.BLOCK:
            self._parts.append(" ")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if not self._hidden and tag in self.BLOCK:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._hidden:
            if tag == self._hidden[-1]:
                self._hidden.pop()
        elif tag in self.BLOCK:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def extract_visible_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def is_valid_time(value: str) -> bool:
    return TIME_FULL.fullmatch(value) is not None


def find_times(text: str) -> list[str]:
    return [match.group(0) for match in TIME_SEARCH.finditer(text)]


def read_file(path: str | Path) -> str:
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8-sig")
    if file_path.suffix.lower() in {".html", ".htm"}:
        return extract_visible_text(content)
    return content


def fetch_webpage(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "Нужен полный адрес, начинающийся с http:// или https://"
        )

    # Ограничиваем время ожидания и размер загружаемой страницы.
    request = Request(url, headers={"User-Agent": "TimeRegexLab/1.0"})
    with urlopen(request, timeout=10) as response:
        content_type = response.headers.get_content_type()
        encoding = response.headers.get_content_charset() or "utf-8"
        raw = response.read(MAX_PAGE_BYTES + 1)

    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError("Размер веб-страницы превышает 5 МБ")
    content = raw.decode(encoding, errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        return extract_visible_text(content)
    return content


def interactive_input() -> tuple[str, str]:
    # Меню повторяется до корректного выбора или команды выхода.
    while True:
        print("\n" + "=" * 52)
        print("ПОИСК И ПРОВЕРКА ВРЕМЕНИ — ЧЧ:ММ:СС")
        print("=" * 52)
        print("1. Проверить введённое время или найти время в тексте")
        print("2. Найти время в файле (TXT, HTML)")
        print("3. Найти время на веб-странице (URL)")
        print("0. Выход")
        print("-" * 52)
        choice = input("Выберите пункт [0–3]: ").strip()

        if choice == "0":
            return "exit", ""
        if choice == "1":
            print("\nФормат: ЧЧ:ММ:СС (например, 14:30:05).")
            print("Часы — 00–23; минуты и секунды — 00–59.")
            print("Можно ввести одно время или предложение с несколькими.")
            value = input("Введите время или текст: ")
            if value.strip():
                return "text", value
            print("Ошибка: пустой ввод. Повторите попытку.")
        elif choice == "2":
            print("\nПоддерживаются TXT, HTML и HTM в кодировке UTF-8.")
            print("Пример: schedule.txt или C:\\data\\schedule.txt")
            value = input("Путь к файлу: ").strip().strip('"')
            if value:
                return "file", value
            print("Ошибка: путь к файлу не указан.")
        elif choice == "3":
            print("\nПример адреса: https://example.org/schedule")
            value = input("URL страницы: ").strip()
            if value:
                return "url", value
            print("Ошибка: URL не указан.")
        else:
            print("Ошибка: выберите 0, 1, 2 или 3.")


def process_source(kind: str, value: str) -> int:
    # Обработка текста едина для ввода, файлов и веб-страниц.
    try:
        if kind == "text":
            content = value
        elif kind == "file":
            content = read_file(value)
        else:
            content = fetch_webpage(value)
        matches = find_times(content)
    except (OSError, UnicodeError, ValueError, LookupError) as error:
        print(f"\nОшибка обработки: {error}")
        return 1

    print("\n" + "-" * 20 + " РЕЗУЛЬТАТ " + "-" * 20)
    if kind == "text":
        status = "корректно" if is_valid_time(content) else "некорректно"
        print("Проверка всей строки:", status)
    if matches:
        print(f"Найдено значений времени: {len(matches)}")
        for index, time_value in enumerate(matches, start=1):
            print(f"{index}. {time_value}")
    else:
        print("Корректное время в формате ЧЧ:ММ:СС не найдено.")
    print("-" * 51)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка и поиск времени в формате ЧЧ:ММ:СС"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="Текст для проверки и поиска")
    source.add_argument(
        "--file", help="Путь к текстовому или HTML-файлу в UTF-8"
    )
    source.add_argument("--url", help="Полный URL веб-страницы (HTTP/HTTPS)")
    args = parser.parse_args(argv)

    # Аргументы командной строки запускают один поиск без меню.
    if args.text is not None:
        return process_source("text", args.text)
    if args.file is not None:
        return process_source("file", args.file)
    if args.url is not None:
        return process_source("url", args.url)

    # В интерактивном режиме можно выполнять несколько поисков подряд.
    print("Добро пожаловать! Программа ищет время от 00:00:00 до 23:59:59.")
    while True:
        try:
            kind, value = interactive_input()
        except (EOFError, KeyboardInterrupt):
            print("\nВвод завершён. До свидания!")
            return 0
        if kind == "exit":
            print("Работа завершена.")
            return 0
        process_source(kind, value)


if __name__ == "__main__":
    raise SystemExit(main())
