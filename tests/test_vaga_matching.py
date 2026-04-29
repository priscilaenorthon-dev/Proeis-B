import unittest

from proeis_http import ProeisHTTP, first_scan_date_index, next_scan_date_index


class VagaMatchingTests(unittest.TestCase):
    def setUp(self):
        self.client = ProeisHTTP("login", "password", "captcha-key")

    def test_qualquer_matches_reserva(self):
        self.assertTrue(self.client.matches_preference("ras teste reserva - curso: n eu vou", "qualquer"))

    def test_qualquer_matches_normal_available_rows(self):
        self.assertTrue(self.client.matches_preference("ras teste 2 - curso: n eu vou", "qualquer"))

    def test_scan_advances_after_success(self):
        self.assertEqual(next_scan_date_index(3, found_candidate=True), 4)

    def test_scan_advances_after_empty_date(self):
        self.assertEqual(next_scan_date_index(3, found_candidate=False), 4)

    def test_first_scan_date_index_starts_at_requested_date(self):
        dates = [("90", "2026-04-29"), ("91", "2026-04-30"), ("92", "2026-05-01")]
        self.assertEqual(first_scan_date_index(dates, "01/05/2026"), 2)

    def test_first_scan_date_index_uses_next_later_date(self):
        dates = [("90", "2026-04-29"), ("92", "2026-05-01")]
        self.assertEqual(first_scan_date_index(dates, "30/04/2026"), 1)


if __name__ == "__main__":
    unittest.main()
