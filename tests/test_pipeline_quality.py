import unittest
import urllib.error
from unittest.mock import patch

import telos_domain_radar
import telos_dream
import telos_radar


class OllamaFinalizationTests(unittest.TestCase):
    def test_thinking_only_response_is_finalized(self):
        responses = [
            {"message": {"content": "", "thinking": "private notes"}, "done_reason": "length"},
            {"message": {"content": "Final grounded answer", "thinking": ""}, "done_reason": "stop"},
        ]
        with patch("telos_radar.ollama_chat", side_effect=responses) as mocked:
            result = telos_radar.call_ollama(
                model="qwen3.5:9b",
                prompt="Analyze this source",
                timeout=30,
                temperature=0.1,
                num_ctx=8192,
                num_predict=300,
                thinking=True,
            )
        self.assertEqual(result, "Final grounded answer")
        self.assertEqual(mocked.call_count, 2)
        self.assertFalse(mocked.call_args_list[1].kwargs["thinking"])

    def test_empty_final_response_is_rejected(self):
        responses = [
            {"message": {"content": "", "thinking": "private notes"}, "done_reason": "length"},
            {"message": {"content": "", "thinking": ""}, "done_reason": "stop"},
        ]
        with patch("telos_radar.ollama_chat", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "no final content"):
                telos_radar.call_ollama(
                    model="qwen3.5:9b",
                    prompt="Analyze this source",
                    timeout=30,
                    temperature=0.1,
                    num_ctx=8192,
                    num_predict=300,
                    thinking=True,
                )


class OutputValidationTests(unittest.TestCase):
    def test_reader_api_url_wraps_target(self):
        self.assertEqual(
            telos_radar.reader_api_url("https://example.com/story"),
            "https://r.jina.ai/http://https://example.com/story",
        )

    def test_google_news_rate_limit_does_not_poison_domain_cooldown_when_disabled(self):
        item = {
            "id": "one",
            "title": "Important finance item",
            "url": "https://news.google.com/rss/articles/test-one?oc=5",
            "published_at": None,
        }
        second = {
            "id": "two",
            "title": "Second finance item",
            "url": "https://news.google.com/rss/articles/test-two?oc=5",
            "published_at": None,
        }
        domain_state = {}
        with patch("telos_domain_radar.core.resolve_article_url", side_effect=urllib.error.URLError("HTTP Error 429")):
            telos_domain_radar.fetch_article(
                item,
                timeout=1,
                max_chars=1000,
                retries=0,
                domain_state=domain_state,
                cooldown_seconds=180,
                google_news_cooldown_seconds=0,
            )
            telos_domain_radar.fetch_article(
                second,
                timeout=1,
                max_chars=1000,
                retries=0,
                domain_state=domain_state,
                cooldown_seconds=180,
                google_news_cooldown_seconds=0,
            )
        self.assertIn("429", item["article_error"])
        self.assertIn("429", second["article_error"])
        self.assertNotIn("Domain cooldown active", second["article_error"])

    def test_transient_rate_limit_fetch_errors_are_not_reused_from_cache(self):
        item = {}
        cached = {
            "article_status": "fetch_error",
            "article_error": "Domain cooldown active after rate limit: news.google.com",
            "article_text": "",
        }
        self.assertFalse(telos_domain_radar.apply_cached_article(item, cached))

    def test_domain_analysis_requires_all_sections(self):
        complete = "\n".join(
            (
                "## Verified Core\n" + "x" * 250,
                "## Strategic Relevance",
                "## Cross-Domain Links",
                "## What This Does Not Prove",
                "## Thesis Impact",
                "## Next Verification",
            )
        )
        self.assertTrue(telos_domain_radar.valid_deep_analysis(complete))
        self.assertFalse(telos_domain_radar.valid_deep_analysis("## Verified Core\nToo short"))

    def test_claim_routing_never_infers_polarity(self):
        item = {
            "llm_analysis": {"status": "ok", "analysis": "Strengthens: everything"},
            "triage": {"reason": "breakthrough release"},
            "prefilter": {"reason": "supports the thesis"},
        }
        self.assertEqual(telos_radar.suggested_item_polarity(item), "uncertain")

    def test_ai_analysis_compacts_repeated_label_blocks(self):
        repeated = "\n".join(
            (
                "- Core claim: first claim",
                "- Why it matters: first reason that is long enough to count",
                "- Strengthens: first direction",
                "- Weakens/Limit: first limitation",
                "- Next watchpoint: first watchpoint",
                "- Core claim: second claim",
                "- Why it matters: second reason",
            )
        )
        compacted = telos_radar.compact_ai_analysis(repeated)
        self.assertEqual(compacted.count("Core claim:"), 1)
        self.assertIn("first watchpoint", compacted)
        self.assertNotIn("second claim", compacted)

    def test_relevance_normalizes_old_and_new_scales(self):
        self.assertEqual(telos_radar.normalize_relevance(9), 90)
        self.assertEqual(telos_radar.normalize_relevance("87"), 87)
        self.assertEqual(telos_radar.normalize_relevance(101), 100)

    def test_final_priority_prefers_model_scores_over_rule_score(self):
        item = {
            "row": {"score": 2},
            "triage": {"status": "ok", "relevance": 92},
            "prefilter": {"status": "ok", "score": 95},
            "topics": [],
            "claims": [],
            "keywords": [],
        }
        self.assertGreaterEqual(telos_radar.final_priority_score(item), 75)

    def test_domain_priority_prefers_model_scores_over_rule_score(self):
        item = {
            "score": 2,
            "triage": {"relevance": 92},
            "prefilter": {"score": 95},
            "topics": [],
            "keywords": [],
        }
        self.assertGreaterEqual(telos_domain_radar.final_priority_score(item), 75)

    def test_synthesis_sanitizer_quarantines_claim_impact_and_scope_errors(self):
        source = """# Daily Synthesis Core
## Bottom Line
Mirage proves a physical AI thesis with massive gains. """ + "x" * 180 + """
## Relevance Ranking
1. Mirage validates the thesis. """ + "x" * 180 + """
## What Happened Today
SWE-Explore found lines required for fixes. """ + "x" * 180 + """
## Thesis Impact
- Stronger: Regulation weakens the capability curve and confirms the thesis. """ + "x" * 180 + """
## What I Would Watch Tomorrow
1. Review the primary sources and exact benchmark scope. """ + "x" * 180
        cleaned = telos_radar.sanitize_synthesis_overclaims(source)
        self.assertEqual(telos_radar.synthesis_overclaim_flags(cleaned), [])
        self.assertTrue(telos_radar.valid_daily_synthesis(cleaned))

    def test_dream_rejects_unclean_macro_data_forecasts(self):
        self.assertFalse(
            telos_dream.forecast_is_clean_next_day_item(
                "By tomorrow, the US CPI inflation rate will be reported at or above 4.25%, driven by AI data center demand.",
                "BLS releases CPI data at or above 4.25%.",
                "CPI data is reported below 4.0%.",
            )
        )
        self.assertTrue(
            telos_dream.forecast_is_clean_next_day_item(
                "By tomorrow, at least one major AI company will publish a model-access policy clarification.",
                "An official company post states a new or clarified model-access policy.",
                "No official clarification appears in the daily scan.",
            )
        )


if __name__ == "__main__":
    unittest.main()
