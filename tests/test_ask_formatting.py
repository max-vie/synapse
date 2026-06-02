"""Tests for Ask formatting: source safety, citation validation, plain text, output modes."""

import json
import sys
from pathlib import Path

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask.formatting import (  # noqa: E402
    URL_SHAPED_RE,
    SOURCE_LOCATOR_KEYS,
    INSUFFICIENT_CONTEXT_ANSWER,
    MISSING_WEBHOOK_MESSAGE,
    public_safe_value,
    public_source_locator,
    result_sources,
    source_has_stable_locator,
    has_grounding_sources,
    trailing_citation_numbers,
    has_valid_answer_citation,
    is_error_result,
    is_local_status_result,
    normalize_rag_result,
    terminal_plain_text,
    display_answer_text,
    format_sources,
    format_one_shot_output,
    render_tui_screen,
)


# ── URL hiding ───────────────────────────────────────────────────────


class TestPublicSafeValue:
    def test_normal_path_passes_through(self):
        assert public_safe_value("notes/ospf.md") == "notes/ospf.md"

    def test_empty_string_returns_empty(self):
        assert public_safe_value("") == ""

    def test_none_returns_empty(self):
        assert public_safe_value(None) == ""

    def test_whitespace_only_returns_empty(self):
        assert public_safe_value("   ") == ""

    def test_https_url_is_hidden(self):
        assert public_safe_value("https://internal.example.com/webhook") == ""

    def test_http_url_is_hidden(self):
        assert public_safe_value("http://host:8080/api") == ""

    def test_absolute_local_path_is_hidden(self):
        assert public_safe_value("/home/user/vault/ospf.md") == ""

    def test_root_path_is_hidden(self):
        assert public_safe_value("/") == ""

    def test_etc_path_is_hidden(self):
        assert public_safe_value("/etc/passwd") == ""

    def test_ftp_url_is_hidden(self):
        assert public_safe_value("ftp://files.local/data") == ""

    def test_relative_path_passes(self):
        assert public_safe_value("Synapse-Demo/ospf.md") == "Synapse-Demo/ospf.md"

    def test_pure_filename_passes(self):
        assert public_safe_value("ospf.md") == "ospf.md"


class TestUrlShapedRe:
    def test_matches_http(self):
        assert URL_SHAPED_RE.match("https://example.com")

    def test_matches_custom_scheme(self):
        assert URL_SHAPED_RE.match("webhook://host/path")

    def test_does_not_match_relative_path(self):
        assert URL_SHAPED_RE.match("notes/ospf.md") is None


# ── Source locator preference ────────────────────────────────────────


class TestPublicSourceLocator:
    def test_prefers_source_path_over_later_keys(self):
        source = {"source_path": "ospf.md", "wiki_path": "wiki/OSPF", "note_id": "123"}
        assert public_source_locator(source) == "ospf.md"

    def test_falls_back_to_wiki_path(self):
        source = {"wiki_path": "wiki/OSPF"}
        assert public_source_locator(source) == "wiki/OSPF"

    def test_falls_back_to_note_id(self):
        source = {"note_id": "abc-123"}
        assert public_source_locator(source) == "abc-123"

    def test_falls_back_to_chunk_id(self):
        source = {"chunk_id": "chunk-42"}
        assert public_source_locator(source) == "chunk-42"

    def test_falls_back_to_path_relative(self):
        source = {"path": "data/notes/test.md"}
        assert public_source_locator(source) == "data/notes/test.md"

    def test_hides_absolute_path_in_path_key(self):
        source = {"path": "/data/notes/test.md"}
        assert public_source_locator(source) == ""

    def test_hides_absolute_path_in_source_path(self):
        source = {"source_path": "/home/user/vault/ospf.md"}
        assert public_source_locator(source) == ""

    def test_returns_empty_when_no_locator(self):
        assert public_source_locator({}) == ""

    def test_skips_url_shaped_values(self):
        source = {"source_path": "https://private.example.com/secret"}
        assert public_source_locator(source) == ""

    def test_skips_empty_strings(self):
        source = {"source_path": "", "wiki_path": "  ", "note_id": "real-id"}
        assert public_source_locator(source) == "real-id"

    def test_skips_absolute_path_when_better_locator_exists(self):
        source = {"path": "/etc/passwd", "note_id": "abc-123"}
        assert public_source_locator(source) == "abc-123"


class TestSourceLocatorKeyOrder:
    def test_key_order_is_source_path_first(self):
        assert SOURCE_LOCATOR_KEYS[0] == "source_path"

    def test_key_order_is_wiki_path_second(self):
        assert SOURCE_LOCATOR_KEYS[1] == "wiki_path"


# ── Citation validation ───────────────────────────────────────────────


class TestTrailingCitationNumbers:
    def test_extracts_single_citation(self):
        assert trailing_citation_numbers("OSPF uses Dijkstra. [1]") == [1]

    def test_extracts_multiple_citations(self):
        assert trailing_citation_numbers("Both protocols are used. [1, 2]") == [1, 2]

    def test_returns_empty_for_no_citations(self):
        assert trailing_citation_numbers("No citations here.") == []

    def test_ignores_mid_text_brackets(self):
        # Brackets must be at the end of the answer
        assert trailing_citation_numbers("See [1] for info. More text.") == []

    def test_ignores_non_numeric_brackets(self):
        assert trailing_citation_numbers("See [abc]") == []

    def test_handles_period_after_citation(self):
        assert trailing_citation_numbers("The answer is SPF. [2].") == [2]


class TestHasValidAnswerCitation:
    def test_valid_with_matching_source(self):
        result = {
            "answer": "OSPF uses Dijkstra. [1]",
            "sources": [{"source_path": "ospf.md"}],
        }
        assert has_valid_answer_citation(result) is True

    def test_invalid_with_no_citation_in_answer(self):
        result = {
            "answer": "OSPF uses Dijkstra.",
            "sources": [{"source_path": "ospf.md"}],
        }
        assert has_valid_answer_citation(result) is False

    def test_invalid_citation_out_of_range(self):
        result = {
            "answer": "OSPF uses Dijkstra. [5]",
            "sources": [{"source_path": "ospf.md"}],
        }
        assert has_valid_answer_citation(result) is False

    def test_invalid_citation_zero(self):
        result = {
            "answer": "Answer. [0]",
            "sources": [{"source_path": "a.md"}],
        }
        assert has_valid_answer_citation(result) is False

    def test_valid_with_multiple_citations(self):
        result = {
            "answer": "Both protocols. [1, 2]",
            "sources": [{"source_path": "ospf.md"}, {"source_path": "bgp.md"}],
        }
        assert has_valid_answer_citation(result) is True

    def test_invalid_when_source_has_no_stable_locator(self):
        result = {
            "answer": "Answer. [1]",
            "sources": [{"url": "https://private.example.com"}],
        }
        assert has_valid_answer_citation(result) is False


class TestMissingCitations:
    def test_no_sources_no_citation(self):
        result = {"answer": "Answer without sources.", "sources": []}
        assert has_valid_answer_citation(result) is False

    def test_sources_but_no_citation_numbers(self):
        result = {
            "answer": "Just an answer.",
            "sources": [{"source_path": "a.md"}],
        }
        assert has_valid_answer_citation(result) is False


class TestInvalidCitations:
    def test_citation_references_nonexistent_source(self):
        result = {
            "answer": "Claim. [99]",
            "sources": [{"source_path": "a.md"}],
        }
        assert has_valid_answer_citation(result) is False

    def test_citation_with_empty_brackets(self):
        result = {
            "answer": "Claim. []",
            "sources": [{"source_path": "a.md"}],
        }
        assert has_valid_answer_citation(result) is False


# ── Source safety and grounding ───────────────────────────────────────


class TestResultSources:
    def test_extracts_sources_key(self):
        result = {"answer": "X", "sources": [{"source_path": "a.md"}]}
        assert result_sources(result) == [{"source_path": "a.md"}]

    def test_falls_back_to_citations(self):
        result = {"answer": "X", "citations": [{"source_path": "b.md"}]}
        assert result_sources(result) == [{"source_path": "b.md"}]

    def test_prefers_sources_over_citations(self):
        result = {
            "sources": [{"source_path": "a.md"}],
            "citations": [{"source_path": "b.md"}],
        }
        assert result_sources(result) == [{"source_path": "a.md"}]

    def test_returns_empty_list_for_missing_keys(self):
        assert result_sources({}) == []
        assert result_sources({"sources": None}) == []


class TestSourceHasStableLocator:
    def test_true_for_source_path(self):
        assert source_has_stable_locator({"source_path": "ospf.md"}) is True

    def test_false_for_url_only(self):
        assert source_has_stable_locator({"source_path": "https://private.example.com"}) is False

    def test_false_for_empty(self):
        assert source_has_stable_locator({}) is False

    def test_false_for_non_dict(self):
        assert source_has_stable_locator("a string") is False


class TestHasGroundingSources:
    def test_true_with_stable_locator(self):
        result = {"sources": [{"source_path": "notes.md"}]}
        assert has_grounding_sources(result) is True

    def test_false_with_url_only_sources(self):
        result = {"sources": [{"source_path": "https://example.com"}]}
        assert has_grounding_sources(result) is False

    def test_false_with_no_sources(self):
        result = {"sources": []}
        assert has_grounding_sources(result) is False


# ── is_error_result / is_local_status_result ───────────────────────────


class TestIsErrorResult:
    def test_error_mode(self):
        assert is_error_result({"mode": "error"}) is True

    def test_error_key(self):
        assert is_error_result({"mode": "live", "error": "timeout"}) is True

    def test_normal_result(self):
        assert is_error_result({"mode": "live"}) is False

    def test_dry_run(self):
        assert is_error_result({"mode": "dry-run"}) is False


class TestIsLocalStatusResult:
    def test_dry_run_status_prefix(self):
        assert is_local_status_result({"mode": "dry-run", "answer": "Dry run only: configure"}) is True

    def test_dry_run_ask_prefix(self):
        assert is_local_status_result({"mode": "dry-run", "answer": "Ask a question"}) is True

    def test_dry_run_with_real_answer(self):
        assert is_local_status_result({"mode": "dry-run", "answer": "OSPF uses Dijkstra."}) is False

    def test_live_mode(self):
        assert is_local_status_result({"mode": "live", "answer": "Ask a question"}) is False


# ── normalize_rag_result ───────────────────────────────────────────────


class TestNormalizeRagResult:
    def test_passes_through_dry_run_without_requiring_sources(self):
        result = {"mode": "dry-run", "answer": "Preview.", "sources": []}
        normalized = normalize_rag_result(result, require_sources=False)
        assert normalized["answer"] == "Preview."

    def test_replaces_answer_without_sources_in_live_mode(self):
        result = {"mode": "live", "answer": "Guess. [1]", "sources": [{"url": "https://private.com"}]}
        normalized = normalize_rag_result(result, require_sources=True)
        assert normalized["answer"] == INSUFFICIENT_CONTEXT_ANSWER

    def test_preserves_answer_with_valid_citation(self):
        result = {
            "mode": "live",
            "answer": "OSPF uses Dijkstra. [1]",
            "sources": [{"source_path": "ospf.md"}],
        }
        normalized = normalize_rag_result(result, require_sources=True)
        assert normalized["answer"] == "OSPF uses Dijkstra. [1]"

    def test_marks_insufficient_context_flag(self):
        result = {"mode": "live", "answer": "No sources.", "sources": []}
        normalized = normalize_rag_result(result, require_sources=True)
        assert normalized.get("insufficient_context") is True

    def test_clears_sources_on_insufficient_context(self):
        result = {"mode": "live", "answer": "No sources.", "sources": []}
        normalized = normalize_rag_result(result, require_sources=True)
        assert normalized["sources"] == []

    def test_preserves_error_result_regardless_of_require_sources(self):
        result = {"mode": "error", "answer": "upstream timeout", "sources": []}
        normalized = normalize_rag_result(result, require_sources=True)
        assert normalized["answer"] == "upstream timeout"


# ── terminal_plain_text ───────────────────────────────────────────────


class TestTerminalPlainText:
    def test_strips_markdown_links(self):
        assert terminal_plain_text("see [docs](https://example.com)") == "see docs"

    def test_strips_backtick_code(self):
        assert terminal_plain_text("use `pip install`") == "use pip install"

    def test_strips_double_bold(self):
        assert terminal_plain_text("**important** change") == "important change"

    def test_strips_underscore_bold(self):
        assert terminal_plain_text("__important__ change") == "important change"

    def test_strips_single_asterisk_italic(self):
        assert terminal_plain_text("this *important* change") == "this important change"

    def test_strips_heading_hashes(self):
        assert terminal_plain_text("# Title\n## Subtitle") == "Title\nSubtitle"

    def test_preserves_plain_text(self):
        assert terminal_plain_text("simple text") == "simple text"


# ── display_answer_text ───────────────────────────────────────────────


class TestDisplayAnswerText:
    def test_prefers_answer_field(self):
        result = {"answer": "from answer", "response": "from response"}
        assert display_answer_text(result) == "from answer"

    def test_falls_back_to_response(self):
        result = {"response": "from response"}
        assert display_answer_text(result) == "from response"

    def test_uses_error_on_no_answer(self):
        result = {"error": "timeout"}
        assert display_answer_text(result) == "timeout"

    def test_uses_fallback_on_empty(self):
        assert display_answer_text({}, "no answer") == "no answer"

    def test_strips_markdown(self):
        result = {"answer": "**Bold** and `code`"}
        assert display_answer_text(result) == "Bold and code"


# ── format_sources ─────────────────────────────────────────────────────


class TestFormatSources:
    def test_no_sources(self):
        result = {"sources": []}
        lines = format_sources(result, 80)
        assert lines == ["Sources: none returned"]

    def test_single_source(self):
        result = {"sources": [{"source_path": "notes/ospf.md"}]}
        lines = format_sources(result, 80)
        assert any("ospf.md" in line for line in lines)

    def test_source_with_title(self):
        result = {"sources": [{"source_path": "notes/ospf.md", "title": "OSPF Routing"}]}
        lines = format_sources(result, 80)
        joined = " ".join(lines)
        assert "OSPF Routing" in joined

    def test_hides_url_sources(self):
        result = {"sources": [{"source_path": "https://private.example.com"}]}
        lines = format_sources(result, 80)
        joined = " ".join(lines)
        assert "https://private" not in joined

    def test_wraps_long_source_at_width(self):
        long_path = "a_very_long_directory_name/subdirectory/and_another_level/file_name.md"
        result = {"sources": [{"source_path": long_path}]}
        lines = format_sources(result, 40)
        assert len(lines) > 1


# ── format_one_shot_output ─────────────────────────────────────────────


class TestFormatOneShotOutput:
    def test_text_mode_returns_answer_only(self):
        result = {"mode": "dry-run", "question": "Q", "answer": "A", "sources": []}
        assert format_one_shot_output(result, "text") == "A"

    def test_json_mode_wraps_in_compatibility_node(self):
        result = {"mode": "dry-run", "question": "Q", "answer": "A", "sources": []}
        output = format_one_shot_output(result, "json")
        parsed = json.loads(output)
        assert "json" in parsed
        assert parsed["json"]["answer"] == "A"

    def test_raw_json_mode_preserves_legacy_shape(self):
        result = {"mode": "dry-run", "question": "Q", "answer": "A", "sources": []}
        output = format_one_shot_output(result, "raw-json")
        parsed = json.loads(output)
        assert "json" not in parsed
        assert parsed["mode"] == "dry-run"

    def test_unsupported_format_raises(self):
        result = {"mode": "dry-run", "answer": "A", "sources": []}
        with pytest.raises(ValueError, match="unsupported output format"):
            format_one_shot_output(result, "xml")

    def test_text_mode_with_require_sources_replaces_insufficient(self):
        result = {"mode": "live", "answer": "Guess. [1]", "sources": [{"url": "https://x.com"}]}
        output = format_one_shot_output(result, "text", require_sources=True)
        assert output == INSUFFICIENT_CONTEXT_ANSWER

    def test_json_mode_normalize_rag_result(self):
        result = {"mode": "dry-run", "question": "Q", "answer": "Preview.", "sources": []}
        output = format_one_shot_output(result, "json", require_sources=False)
        parsed = json.loads(output)
        assert parsed["json"]["answer"] == "Preview."


# ── format_one_shot_output: all output modes ───────────────────────────


class TestAllOutputModes:
    """Ensure text, json, raw-json produce consistent, well-structured output."""

    def _base_result(self):
        return {
            "mode": "live",
            "question": "What algorithm does OSPF use?",
            "answer": "OSPF uses Dijkstra's SPF algorithm. [1]",
            "sources": [{"source_path": "notes/ospf.md"}],
        }

    def test_text_mode(self):
        output = format_one_shot_output(self._base_result(), "text")
        assert "Dijkstra" in output
        assert "json" not in output

    def test_json_mode_structure(self):
        output = format_one_shot_output(self._base_result(), "json")
        parsed = json.loads(output)
        assert set(parsed.keys()) == {"json"}
        assert set(parsed["json"].keys()) >= {"mode", "answer", "sources"}

    def test_raw_json_mode_structure(self):
        output = format_one_shot_output(self._base_result(), "raw-json")
        parsed = json.loads(output)
        assert "json" not in parsed
        assert parsed["mode"] == "live"
        assert parsed["answer"] == "OSPF uses Dijkstra's SPF algorithm. [1]"

    def test_error_result_text(self):
        result = {"mode": "error", "answer": "Request failed: timeout", "sources": []}
        output = format_one_shot_output(result, "text")
        assert "timeout" in output

    def test_error_result_json(self):
        result = {"mode": "error", "answer": "Request failed: timeout", "sources": []}
        output = format_one_shot_output(result, "json")
        parsed = json.loads(output)
        assert parsed["json"]["mode"] == "error"

# ── render_tui_screen (line-mode fallback renderer) ───────────────────


class TestRenderTuiScreenFooter:
    """The line-mode renderer footer should list all commands consistently with the
    curses TUI, which documents /help, /notes, /local-notes, /!1, /clear, /quit."""

    def test_footer_includes_help(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "/help" in output

    def test_footer_includes_notes(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "/notes" in output

    def test_footer_includes_local_notes(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "/local-notes" in output

    def test_footer_includes_answer_replay(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "/!1" in output

    def test_footer_includes_clear(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "/clear" in output

    def test_footer_includes_quit(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "/quit" in output


class TestRenderTuiScreenStructure:
    def test_includes_logo(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "Synapse Ask" in output

    def test_includes_question(self):
        output = render_tui_screen(
            question="What is OSPF?",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "What is OSPF?" in output

    def test_includes_answer(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "Dijkstra's algorithm.", "sources": []},
            webhook_url="",
        )
        assert "Dijkstra's algorithm." in output

    def test_includes_sources_line(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": [{"source_path": "ospf.md"}]},
            webhook_url="",
        )
        assert "Sources:" in output

    def test_dry_run_mode_label(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
            dry_run_enabled=True,
        )
        assert "dry-run" in output

    def test_live_mode_label(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "error", "answer": "err", "sources": []},
            webhook_url="http://localhost:15515/webhook",
        )
        assert "live" in output

    def test_color_mode(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
            use_color=True,
        )
        assert "\033[" in output

    def test_no_color_by_default(self):
        output = render_tui_screen(
            question="Q",
            result={"mode": "dry-run", "answer": "A.", "sources": []},
            webhook_url="",
        )
        assert "\033[" not in output
