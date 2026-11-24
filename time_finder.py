from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

TIME_CORE = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
TIME_FULL = re.compile(TIME_CORE)
TIME_SEARCH = re.compile(rf"(?<![\w:]){TIME_CORE}(?![\w:]|\.[0-9])")
MAX_PAGE_BYTES = 5 * 1024 * 1024


class VisibleTextParser(HTMLParser):

    HIDDEN = frozenset({"head", "script", "style", "noscript", "template", "svg"})
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.HIDDEN:
            self._hidden.append(tag)
        elif not self._hidden and tag in self.BLOCK:
            self._parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
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
        raise ValueError("Нужен полный адрес, начинающийся с http:// или https://")

    request = Request(url, headers={"User-Agent": "TimeRegexLab/1.0"})
    with urlopen(request, timeout=10) as response:
        content_type = response.headers.get_content_type()
        encoding = response.headers.get_content_charset() or "utf-8"
        raw = response.read(MAX_PAGE_BYTES + 1)

    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError("Размер веб-страницы превышает 5 МиБ")
    content = raw.decode(encoding, errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        return extract_visible_text(content)
    return content


def interactive_input() -> tuple[str, str]:
    print("Источник данных: 1 — ввод, 2 — файл, 3 — веб-страница")
    choice = input("Выберите 1, 2 или 3: ").strip()
    if choice == "1":
        print("Формат времени: ЧЧ:ММ:СС (например, 14:30:05).")
        print("Часы: 00–23, минуты и секунды: 00–59.")
        print("Можно ввести одно время или текст с несколькими значениями времени.")
        return "text", input("Введите время или текст: ")
    if choice == "2":
        return "file", input("Укажите путь к файлу: ").strip()
    if choice == "3":
        return "url", input("Укажите URL (http/https): ").strip()
    raise ValueError("Неизвестный пункт меню; выберите 1, 2 или 3")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка и поиск времени в формате ЧЧ:ММ:СС"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="Текст для проверки и поиска")
    source.add_argument("--file", help="Путь к текстовому или HTML-файлу в UTF-8")
    source.add_argument("--url", help="Полный URL веб-страницы (HTTP/HTTPS)")
    args = parser.parse_args(argv)

    if args.text is not None:
        kind, value = "text", args.text
    elif args.file is not None:
        kind, value = "file", args.file
    elif args.url is not None:
        kind, value = "url", args.url
    else:
        try:
            kind, value = interactive_input()
        except (EOFError, ValueError) as error:
            print(f"Ошибка ввода: {error}")
            return 1

    try:
        if kind == "text":
            content = value
            print("Проверка всей строки:", "корректно" if is_valid_time(content) else "некорректно")
        elif kind == "file":
            content = read_file(value)
        else:
            content = fetch_webpage(value)
        matches = find_times(content)
    except (OSError, UnicodeError, ValueError, LookupError) as error:
        print(f"Ошибка обработки: {error}")
        return 1

    if matches:
        print(f"Найдено значений времени: {len(matches)}")
        for index, time_value in enumerate(matches, start=1):
            print(f"{index}. {time_value}")
    else:
        print("Корректное время в формате ЧЧ:ММ:СС не найдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
