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


#Проверяем допустимые и недопустимые значения времени.
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


#Проверяем поиск времени в тексте и исключение ложных совпадений.
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


#Проверяем чтение файлов, обработку HTML и загрузку веб-страниц.
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

    #Временные файлы создаются только на время теста.
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

    #Подменяем сетевой ответ, чтобы тест не зависел от интернета.
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


#Проверяем запуск программы, вывод результата и обработку ошибок.
class CommandLineTests(unittest.TestCase):
    def test_text_argument_reports_validation_and_search(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--text", "23:59:59"])
        self.assertEqual(code, 0)
        self.assertIn("корректно", output.getvalue())
        self.assertIn("1. 23:59:59", output.getvalue())

    #Имитируем ответы пользователя без ручного ввода.
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


#Дополнительно проверяем границы HTML, ошибки загрузки и разные меню.
class ExtendedSourceTests(unittest.TestCase):
    def test_html_self_closing_and_regular_inline_tags(self) -> None:
        html = (
            "<p>до<br/>после</p>"
            "<div>без<img/>разрыва</div>"
            "<template><br/>скрыто 12:12:12</template>"
        )
        visible = extract_visible_text(html)
        self.assertIn("до после", visible)
        self.assertIn("безразрыва", visible)
        self.assertNotIn("скрыто", visible)
        self.assertNotIn("12:12:12", visible)

    def test_html_self_closing_tag_in_hidden_section(self) -> None:
        html = (
            "<template>до<br/>после</template>"
            "<p>Начало 08:00:00</p>"
        )
        visible = extract_visible_text(html)
        self.assertNotIn("до", visible)
        self.assertNotIn("после", visible)
        self.assertEqual(find_times(visible), ["08:00:00"])

    def test_read_htm_file_with_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.htm"
            path.write_text(
                "<p>Начало 11:22:33</p><script>12:12:12</script>",
                encoding="utf-8-sig",
            )
            self.assertEqual(find_times(read_file(path)), ["11:22:33"])

    #Подменяем ответы сервера, чтобы тесты не зависели от сети.
    def test_fetch_plain_text_page(self) -> None:
        response = io.BytesIO("Расписание в 06:07:08".encode("utf-8"))
        headers = Message()
        headers.add_header("Content-Type", "text/plain")
        response.headers = headers
        with patch("time_finder.urlopen", return_value=response):
            content = fetch_webpage("https://example.org/times.txt")
        self.assertEqual(content, "Расписание в 06:07:08")

    def test_fetch_xhtml_page(self) -> None:
        response = io.BytesIO(
            b"<html><body><p>08:09:10</p>"
            b"<script>20:20:20</script></body></html>"
        )
        headers = Message()
        headers.add_header(
            "Content-Type", "application/xhtml+xml", charset="utf-8"
        )
        response.headers = headers
        with patch("time_finder.urlopen", return_value=response):
            content = fetch_webpage("https://example.org/schedule.xhtml")
        self.assertEqual(find_times(content), ["08:09:10"])

    def test_fetch_rejects_page_larger_than_limit(self) -> None:
        response = io.BytesIO(b"0123456789")
        headers = Message()
        headers.add_header("Content-Type", "text/plain")
        response.headers = headers
        with patch("time_finder.MAX_PAGE_BYTES", 8):
            with patch("time_finder.urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "превышает 5 МБ"):
                    fetch_webpage("https://example.org/large")

    def test_fetch_uses_declared_charset(self) -> None:
        response = io.BytesIO("Время 15:16:17".encode("cp1251"))
        headers = Message()
        headers.add_header("Content-Type", "text/plain", charset="cp1251")
        response.headers = headers
        with patch("time_finder.urlopen", return_value=response):
            content = fetch_webpage("https://example.org/times.txt")
        self.assertEqual(content, "Время 15:16:17")


#Проверяем все пути запуска и сообщения для пользователя.
class ExtendedCommandLineTests(unittest.TestCase):
    def test_cli_file_with_existing_file(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "times.txt"
            path.write_text("Начало 10:20:30", encoding="utf-8")
            with redirect_stdout(output):
                code = main(["--file", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("1. 10:20:30", output.getvalue())

    def test_cli_url_with_mock_page(self) -> None:
        output = io.StringIO()
        with patch(
            "time_finder.fetch_webpage", return_value="Время 17:18:19"
        ) as fetch:
            with redirect_stdout(output):
                code = main(["--url", "https://example.org/schedule"])
        self.assertEqual(code, 0)
        self.assertIn("1. 17:18:19", output.getvalue())
        fetch.assert_called_once_with("https://example.org/schedule")

    def test_cli_invalid_time_reports_no_matches(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--text", "25:61:90"])
        self.assertEqual(code, 0)
        self.assertIn("Проверка всей строки: некорректно", output.getvalue())
        self.assertIn("не найдено", output.getvalue())

    def test_interactive_file_choice(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "times.txt"
            path.write_text("Событие 04:05:06", encoding="utf-8")
            with patch("builtins.input", side_effect=[" 2 ", str(path)]):
                with redirect_stdout(output):
                    code = main([])
        self.assertEqual(code, 0)
        self.assertIn("1. 04:05:06", output.getvalue())

    def test_interactive_url_choice(self) -> None:
        output = io.StringIO()
        with patch(
            "builtins.input",
            side_effect=["3", " https://example.org/times "],
        ):
            with patch(
                "time_finder.fetch_webpage", return_value="18:19:20"
            ) as fetch:
                with redirect_stdout(output):
                    code = main([])
        self.assertEqual(code, 0)
        self.assertIn("1. 18:19:20", output.getvalue())
        fetch.assert_called_once_with("https://example.org/times")

    def test_interactive_unknown_menu_item(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", return_value="7"):
            with redirect_stdout(output):
                code = main([])
        self.assertEqual(code, 1)
        self.assertIn("Ошибка ввода", output.getvalue())
        self.assertIn("Неизвестный пункт меню", output.getvalue())

    def test_interactive_input_eof(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", side_effect=EOFError):
            with redirect_stdout(output):
                code = main([])
        self.assertEqual(code, 1)
        self.assertIn("Ошибка ввода", output.getvalue())

    def test_cli_url_network_error(self) -> None:
        output = io.StringIO()
        with patch(
            "time_finder.fetch_webpage", side_effect=OSError("сеть недоступна")
        ):
            with redirect_stdout(output):
                code = main(["--url", "https://example.org/schedule"])
        self.assertEqual(code, 1)
        self.assertIn("Ошибка обработки: сеть недоступна", output.getvalue())

    def test_cli_url_invalid_charset(self) -> None:
        response = io.BytesIO(b"07:08:09")
        headers = Message()
        headers.add_header(
            "Content-Type", "text/plain", charset="not-a-python-encoding"
        )
        response.headers = headers
        output = io.StringIO()
        with patch("time_finder.urlopen", return_value=response):
            with redirect_stdout(output):
                code = main(["--url", "https://example.org/times"])
        self.assertEqual(code, 1)
        self.assertIn("Ошибка обработки", output.getvalue())

    def test_running_script_as_main(self) -> None:
        import runpy
        import sys

        output = io.StringIO()
        script = str(Path(__file__).with_name("time_finder.py"))
        with patch.object(sys, "argv", [script, "--text", "23:59:59"]):
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(script, run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("1. 23:59:59", output.getvalue())


if __name__ == "__main__":
    unittest.main()
