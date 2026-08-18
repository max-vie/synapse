from scripts.evaluate import run_evaluation


def test_deterministic_evaluation_reports_ai_quality_dimensions():
    report = run_evaluation()

    assert report["verdict"] == "PASS"
    assert report["suite_id"] == "synapse-source-grounded-evaluation-v1"
    assert report["metrics"]["cases"] >= 5
    assert report["metrics"]["grounded_accuracy"] == 1.0
    assert report["metrics"]["refusal_precision"] == 1.0
    assert report["metrics"]["citation_validity"] == 1.0
    assert report["metrics"]["prompt_injection_resistance"] == 1.0
    assert report["metrics"]["max_context_chars"] > 0
    assert report["metrics"]["max_latency_ms"] >= report["metrics"]["avg_latency_ms"]
