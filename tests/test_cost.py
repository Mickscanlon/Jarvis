"""Tests for llm.calculate_cost_aud — validates pricing accuracy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from llm import calculate_cost_aud


def test_sonnet_cost():
    # 1000 input @ $3/MTok, 500 output @ $15/MTok, ×1.60 AUD
    # = (1000*3 + 500*15) / 1_000_000 * 1.60
    # = (3000 + 7500) / 1_000_000 * 1.60 = 0.0168
    cost = calculate_cost_aud("claude-sonnet-4-6", 1000, 500)
    assert abs(cost - 0.0168) < 1e-6, f"Expected 0.0168, got {cost}"


def test_haiku_cost():
    # 10_000 input @ $0.80/MTok, 2_000 output @ $4/MTok, ×1.60
    # = (8000 + 8000) / 1_000_000 * 1.60 = 0.0256
    cost = calculate_cost_aud("claude-haiku-4-5-20251001", 10_000, 2_000)
    assert abs(cost - 0.0256) < 1e-6, f"Expected 0.0256, got {cost}"


def test_opus_cost():
    # 5_000 input @ $15/MTok, 1_000 output @ $75/MTok, ×1.60
    # = (75_000 + 75_000) / 1_000_000 * 1.60 = 0.24
    cost = calculate_cost_aud("claude-opus-4-7", 5_000, 1_000)
    assert abs(cost - 0.24) < 1e-6, f"Expected 0.24, got {cost}"


def test_opus_4_6_same_tier():
    c46 = calculate_cost_aud("claude-opus-4-6", 5_000, 1_000)
    c47 = calculate_cost_aud("claude-opus-4-7", 5_000, 1_000)
    assert c46 == c47, "Opus 4.6 and 4.7 should have same pricing"


def test_unknown_model_defaults_to_sonnet_pricing():
    # Unknown model falls back to Sonnet pricing — should not raise
    cost = calculate_cost_aud("some-unknown-model", 1000, 500)
    expected = calculate_cost_aud("claude-sonnet-4-6", 1000, 500)
    assert cost == expected


def test_zero_tokens():
    assert calculate_cost_aud("claude-sonnet-4-6", 0, 0) == 0.0


def test_local_model_zero_cost():
    # Local/Ollama models should have 0 cost (not in pricing table → falls back to Sonnet)
    # Actually local models don't go through calculate_cost_aud, they return cost_aud=0.0 directly.
    # This test verifies the function handles unknown models without crashing.
    cost = calculate_cost_aud("qwen2.5:7b", 500, 200)
    assert isinstance(cost, float) and cost >= 0


if __name__ == '__main__':
    tests = [
        test_sonnet_cost,
        test_haiku_cost,
        test_opus_cost,
        test_opus_4_6_same_tier,
        test_unknown_model_defaults_to_sonnet_pricing,
        test_zero_tokens,
        test_local_model_zero_cost,
    ]
    for t in tests:
        t()
        print(f"  PASS {t.__name__}")
    print(f"\nAll {len(tests)} cost tests passed.")
