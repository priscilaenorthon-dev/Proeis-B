import unittest

from proeis_http import coerce_scan_rounds, display_date_for_log, is_valid_captcha_answer, normalize_captcha_answer


class CaptchaUtilsTests(unittest.TestCase):
    def test_normalizes_to_uppercase_alphanumeric(self):
        self.assertEqual(normalize_captcha_answer(" a-1 b_2 c! "), "A1B2C")

    def test_validates_exactly_six_alphanumeric_characters(self):
        self.assertTrue(is_valid_captcha_answer("A1B2C3"))
        self.assertFalse(is_valid_captcha_answer("A1B2C"))
        self.assertFalse(is_valid_captcha_answer("A1B2C34"))
        self.assertFalse(is_valid_captcha_answer("A1B2-C"))

    def test_scan_rounds_is_at_least_one(self):
        self.assertEqual(coerce_scan_rounds(0), 1)
        self.assertEqual(coerce_scan_rounds(-2), 1)
        self.assertEqual(coerce_scan_rounds(2), 2)

    def test_display_date_for_log_normalizes_supported_formats(self):
        self.assertEqual(display_date_for_log("27/04/2026"), "2026-04-27")
        self.assertEqual(display_date_for_log("2026-04-27"), "2026-04-27")


if __name__ == "__main__":
    unittest.main()
