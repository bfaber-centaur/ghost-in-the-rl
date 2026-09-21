import unittest

from metric_map import pearson, structural_pattern, summarize, tag_features


class MetricMapTests(unittest.TestCase):
    def test_structural_pattern_normalizes_ids_and_partial_bucket(self):
        self.assertEqual(
            structural_pattern("partial/code/dataset-yfch/8/n_tokens"),
            "partial/code/{dataset}/{bucket}/n_tokens",
        )
        self.assertEqual(
            structural_pattern("penalty/harness/harness-foo/bar"),
            "penalty/harness/{harness}/bar",
        )

    def test_scope_hints_are_lexical_and_precedence_is_stable(self):
        self.assertEqual(tag_features("actor/code/dataset-x/reward")["scope_hint"], "dataset")
        self.assertEqual(tag_features("penalty/harness/harness-x/foo")["scope_hint"], "harness")
        self.assertEqual(tag_features("partial/code/8/n_tokens")["scope_hint"], "partial-bucket")
        self.assertEqual(tag_features("ctx_total_length/code/mean")["scope_hint"], "workload-aggregate")
        self.assertEqual(tag_features("penalty/foo/bar")["scope_hint"], "penalty-subsystem")
        self.assertEqual(tag_features("train/trace/records")["scope_hint"], "train-subsystem")
        self.assertEqual(tag_features("timing_s/step")["scope_hint"], "run-global-looking")

    def test_summary_preserves_nulls_and_finds_largest_jump(self):
        s = summarize([1, None, 4, 10])
        self.assertEqual(s["nonnull"], 3)
        self.assertEqual(s["null"], 1)
        self.assertEqual(s["min"], 1)
        self.assertEqual(s["max"], 10)
        self.assertEqual(s["largest_abs_jump"], 6)
        self.assertEqual(s["largest_abs_jump_step"], 4)

    def test_pearson_ignores_null_pairs_and_constant_series(self):
        self.assertAlmostEqual(pearson([1, None, 3], [2, 4, 6]), 1.0)
        self.assertEqual(pearson([1, 1, 1], [2, 3, 4]), "")


if __name__ == "__main__":
    unittest.main()
