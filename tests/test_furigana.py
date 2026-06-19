import unittest
from pathlib import Path

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.dictionary.service import DictionaryService
from anki_lookup.furigana import FURIGANA_HOVER_STYLE, render_furigana_html


class FuriganaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("furigana.sqlite3")
        self.archive_path = artifact_path("furigana.zip")
        _remove_database(self.database_path)
        self.archive_path.unlink(missing_ok=True)

    def tearDown(self) -> None:
        _remove_database(self.database_path)
        self.archive_path.unlink(missing_ok=True)

    def test_renders_exact_dictionary_readings_as_ruby(self) -> None:
        service = self._service(
            [
                ["日本語", "にほんご", "", "", 10, ["Japanese language"], 1, ""],
                ["食べる", "たべる", "", "v1", 9, ["to eat"], 2, ""],
            ]
        )

        html = render_furigana_html("日本語を食べる", service)

        self.assertEqual(
            html,
            _hover_furigana("<ruby>日本語<rt>にほんご</rt></ruby>を<ruby>食<rt>た</rt></ruby>べる"),
        )

    def test_does_not_guess_when_no_dictionary_reading_exists(self) -> None:
        service = self._service([["かな", "", "", "", 1, ["kana"], 1, ""]])

        html = render_furigana_html("未知語", service)

        self.assertEqual(html, "未知語")

    def test_escapes_plain_text_and_preserves_line_breaks(self) -> None:
        service = self._service([["日本語", "にほんご", "", "", 1, ["Japanese"], 1, ""]])

        html = render_furigana_html("<日本語>\n", service)

        self.assertEqual(
            html,
            _hover_furigana("&lt;<ruby>日本語<rt>にほんご</rt></ruby>&gt;<br>"),
        )

    def _service(self, terms: list[list[object]]) -> DictionaryService:
        write_dictionary(self.archive_path, title="Japanese", terms=terms)
        service = DictionaryService(self.database_path)
        service.import_archive(self.archive_path)
        return service


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-shm").unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-wal").unlink(missing_ok=True)


def _hover_furigana(body: str) -> str:
    return f'{FURIGANA_HOVER_STYLE}<span class="wonder-of-u-furigana">{body}</span>'


if __name__ == "__main__":
    unittest.main()
