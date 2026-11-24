from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from time_finder import (
    extract_visible_text,
    fetch_webpage,
    find_times,
    is_valid_time,
    main,
    read_file,
)


# Проверяем допустимые и недопустимые значения времени.
class TimeValidationTests(unittest.TestCase):
    def test_correct_times(self) -> None:
        valid = ["00:00:00", "23:59:59", "07:08:09", "12:30:45", "20:00:01"]
        for value in valid:
            with self.subTest(value=value):
                self.assertTrue(is_valid_time(value))

    def test_incorrect_times(self) -> None:
        invalid = [
            "24:00:00", "12:60:00", "12:34:60", "99:99:99", "1:02:03",
            "01:2:03", "01:02:3", "01-02-03", " 12:30:45",
            "12:30:45 ", "12:30:45 extra", "", "１２:30:45", "١٢:٣٠:٤٥",
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(is_valid_time(value))


# Проверяем поиск времени в тексте и исключение ложных совпадений.
class TimeSearchTests(unittest.TestCase):
    def test_search_finds_all_valid_times(self) -> None:
        text = "Начало в 08:05:09, конец в 19:20:30; повтор 08:05:09."
        self.assertEqual(
            find_times(text), ["08:05:09", "19:20:30", "08:05:09"]
        )

    def test_search_skips_invalid_times(self) -> None:
        text = "24:00:00, 12:60:00, 08:20:61, 7:08:09, 00:00:00"
        self.assertEqual(find_times(text), ["00:00:00"])

    def test_search_respects_word_boundaries(self) -> None:
        text = "abc12:30:45 12:30:45xyz _12:30:45 12:30:45_ (12:30:45)"
        self.assertEqual(find_times(text), ["12:30:45"])

    def test_search_does_not_extract_colon_chain_or_fractional_time(
        self,
    ) -> None:
        text = "12:30:45:12, 12:30:45.123; 12:30:45!"
        self.assertEqual(find_times(text), ["12:30:45"])

    def test_search_returns_empty_list_for_no_matches(self) -> None:
        self.assertEqual(find_times("Время неизвестно"), [])


# Проверяем чтение файлов, обработку HTML и загрузку веб-страниц.
class SourceTests(unittest.TestCase):
    def test_html_parser_ignores_scripts_styles_and_head(self) -> None:
        html = (
            '<html><head><title>22:22:22</title><style>00:00:00</style></head>'
            '<body><p>Встреча 09:10:11.</p><script>12:12:12</script>'
            '<div>Конец 18:19:20</div></body></html>'
        )
        self.assertEqual(
            find_times(extract_visible_text(html)), ["09:10:11", "18:19:20"]
        )

    def test_html_parser_preserves_inline_time(self) -> None:
        html = "<p><span>12</span>:<span>34</span>:<span>56</span></p>"
        self.assertEqual(find_times(extract_visible_text(html)), ["12:34:56"])

    # Временные файлы создаются только на время теста.
    def test_read_utf8_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "пример.txt"
            path.write_text("Событие в 14:15:16.", encoding="utf-8")
            self.assertEqual(find_times(read_file(path)), ["14:15:16"])

    def test_read_html_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.html"
            path.write_text(
                "<p>10:11:12</p><script>13:14:15</script>",
                encoding="utf-8",
            )
            self.assertEqual(find_times(read_file(path)), ["10:11:12"])

    def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                read_file(Path(tmp) / "missing.txt")

    def test_url_validation(self) -> None:
        for url in [
            "example.com", "file:///etc/passwd", "ftp://example.com/time"
        ]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    fetch_webpage(url)

    # Подменяем сетевой ответ, чтобы тест не зависел от интернета.
    def test_fetch_html_page_with_mock_server(self) -> None:
        response = io.BytesIO(
            b"<html><body><p>16:17:18</p>"
            b"<script>21:22:23</script></body></html>"
        )
        headers = Message()
        headers.add_header("Content-Type", "text/html", charset="utf-8")
        response.headers = headers
        with patch("time_finder.urlopen", return_value=response) as opener:
            text = fetch_webpage("https://example.org/schedule")
        self.assertEqual(find_times(text), ["16:17:18"])
        opener.assert_called_once()


# Проверяем запуск программы, вывод результата и обработку ошибок.
class CommandLineTests(unittest.TestCase):
    def test_text_argument_reports_validation_and_search(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--text", "23:59:59"])
        self.assertEqual(code, 0)
        self.assertIn("корректно", output.getvalue())
        self.assertIn("1. 23:59:59", output.getvalue())

    # Имитируем ответы пользователя без ручного ввода.
    def test_interactive_input(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", side_effect=["1", "23:50:10"]):
            with redirect_stdout(output):
                code = main([])
        self.assertEqual(code, 0)
        self.assertIn("23:50:10", output.getvalue())

    def test_missing_file_returns_nonzero_status(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "missing.txt")
            with redirect_stdout(output):
                code = main(["--file", missing])
        self.assertEqual(code, 1)
        self.assertIn("Ошибка обработки", output.getvalue())


if __name__ == "__main__":
    unittest.main()
