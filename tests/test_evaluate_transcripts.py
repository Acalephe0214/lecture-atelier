"""Synthetic references only: these tests validate arithmetic, not speech quality."""
import copy
import unittest

from evaluate_transcripts import edit_distance, normalized, score


def case(identifier="demo", reference="the cat", **extra):
    return {"id": identifier, "language": "en", "reference": reference,
            "reference_status": "human_verified", "reference_method": "independent_listening",
            "hypotheses": {"baseline": "the cat", "guarded": "the dog"}, **extra}


class EvaluationTests(unittest.TestCase):
    def test_edit_distance(self):
        for reference, hypothesis, expected in (("", "abc", 3), ("abc", "", 3),
                                                 ("kitten", "sitting", 3), ("中国", "中国", 0)):
            self.assertEqual(edit_distance(reference, hypothesis), expected)
            self.assertEqual(edit_distance(hypothesis, reference), expected)

    def test_no_reference_is_pending_not_zero_error(self):
        report = score({"cases": [case(reference_status="missing", reference="")]})
        self.assertEqual(report["status"], "pending_reference")
        self.assertEqual(report["systems"], {})
        self.assertEqual(report["scored_cases"], 0)

    def test_normalization_and_chinese_cer(self):
        self.assertEqual(normalized("ÉCOLE， café!"), "école café")
        report = score({"cases": [case(reference="你好，世界！", language="zh",
                                       hypotheses={"baseline": "你好世间"})]})
        self.assertEqual(report["systems"]["baseline"]["cer"], .25)
        self.assertEqual(report["systems"]["baseline"]["reference_characters"], 4)

    def test_micro_average_and_input_not_mutated(self):
        dataset = {"cases": [case("a", "a", hypotheses={"x": "b"}),
                             case("b", "abcdefghi", hypotheses={"x": "abcdefghi"})]}
        before = copy.deepcopy(dataset)
        report = score(dataset)
        self.assertEqual(dataset, before)
        self.assertEqual(report["systems"]["x"]["cer"], .1)
        self.assertTrue(report["paired_system_coverage"])

    def test_errors_can_exceed_one_and_empty_hypothesis_is_scored(self):
        report = score({"cases": [case(reference="a", hypotheses={"x": "aaaa", "empty": ""})]})
        self.assertEqual(report["systems"]["x"]["cer"], 3)
        self.assertEqual(report["systems"]["empty"]["cer"], 1)

    def test_unequal_system_coverage_is_flagged(self):
        report = score({"cases": [case("a"), case("b", hypotheses={"baseline": "the cat"})]})
        self.assertFalse(report["paired_system_coverage"])
        self.assertEqual(report["systems"]["baseline"]["cases"], 2)
        self.assertEqual(report["systems"]["guarded"]["cases"], 1)

    def test_verified_but_invalid_reference_or_hypothesis_rejected(self):
        for item in (case(reference=""), case(reference="!!!"), case(reference_method="not_reviewed"),
                     case(hypotheses={}), case(hypotheses={"x": None})):
            with self.assertRaises(ValueError):
                score({"cases": [item]})
        for cases in ([], [case("same"), case("same")], [None]):
            with self.assertRaises(ValueError):
                score({"cases": cases})
        for value in (None, [], "invalid"):
            with self.assertRaises(ValueError):
                score(value)

    def test_report_omits_source_text_and_private_paths(self):
        report = str(score({"cases": [case(reference="PRIVATE words", hypotheses={"x": "SECRET words"},
                                          private_source={"filename": "personal.wav"})]}))
        for value in ("PRIVATE", "SECRET", "personal.wav"):
            self.assertNotIn(value, report)


if __name__ == "__main__":
    unittest.main()
