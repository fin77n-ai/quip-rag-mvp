import unittest

from backend.services import retake_detector


class RetakeDetectorTest(unittest.TestCase):
    def test_detects_explicit_retake_terms(self):
        result = retake_detector.detect_explicit_retake(
            "Description/ Comment: VO needs retake and should be re-recorded due to mouth noise."
        )

        self.assertEqual(result["retake_explicit"], "yes")
        self.assertIn("retake", result["retake_terms"])
        self.assertIn("re-record", result["retake_terms"])

    def test_returns_no_when_no_retake_terms_present(self):
        result = retake_detector.detect_explicit_retake(
            "Description/ Comment: VO pacing is slightly slow but can be fixed in animation timing."
        )

        self.assertEqual(result["retake_explicit"], "no")
        self.assertEqual(result["retake_terms"], "")


if __name__ == "__main__":
    unittest.main()
