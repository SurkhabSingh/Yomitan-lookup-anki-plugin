import unittest
from pathlib import Path

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.dictionary.service import DictionaryService
from anki_lookup.furigana import (
    FURIGANA_HOVER_STYLE,
    furigana_segments,
    render_furigana_html,
    render_furigana_plain,
    render_furigana_ruby,
)


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

    def test_renders_ruby_without_the_hover_wrapper_for_notes(self) -> None:
        # The hover style hides the reading until moused over, which is right for
        # reading along in the app and wrong for a card that exists to show it.
        service = self._service([["日本語", "にほんご", "", "", 10, ["Japanese"], 1, ""]])

        html = render_furigana_ruby("日本語", service)

        self.assertEqual(html, "<ruby>日本語<rt>にほんご</rt></ruby>")
        self.assertNotIn("wonder-of-u-furigana", html)
        self.assertNotIn("<style>", html)

    def test_renders_ankis_own_bracket_syntax(self) -> None:
        # What {{furigana:Field}} reads, so the card template decides the presentation
        # rather than having our markup baked into the note.
        service = self._service([["食べる", "たべる", "", "v1", 9, ["to eat"], 1, ""]])

        self.assertEqual(render_furigana_plain("食べる", service), "食[た]べる")

    def test_bracket_syntax_separates_annotated_runs(self) -> None:
        # A reading applies back to the previous space, so without one the annotation
        # would swallow the text before it.
        service = self._service(
            [
                ["日本語", "にほんご", "", "", 10, ["Japanese"], 1, ""],
                ["食べる", "たべる", "", "v1", 9, ["to eat"], 2, ""],
            ]
        )

        self.assertEqual(
            render_furigana_plain("日本語を食べる", service),
            "日本語[にほんご]を 食[た]べる",
        )

    def test_unmatched_text_carries_no_brackets(self) -> None:
        service = self._service([["かな", "", "", "", 1, ["kana"], 1, ""]])

        self.assertEqual(render_furigana_plain("未知語", service), "未知語")

    def test_segments_expose_the_alignment_once(self) -> None:
        # Three renderings share one alignment pass rather than three copies of the
        # matching logic.
        service = self._service([["食べる", "たべる", "", "v1", 9, ["to eat"], 1, ""]])

        segments = furigana_segments("食べる", service)

        self.assertEqual(
            [(segment.text, segment.reading) for segment in segments],
            [("食", "た"), ("べる", "")],
        )
        self.assertEqual("".join(segment.text for segment in segments), "食べる")

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
