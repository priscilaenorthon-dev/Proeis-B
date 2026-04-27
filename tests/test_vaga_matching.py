import unittest

from proeis_http import ProeisHTTP, next_scan_date_index


class VagaMatchingTests(unittest.TestCase):
    def setUp(self):
        self.client = ProeisHTTP("login", "password", "captcha-key")

    def test_qualquer_matches_reserva(self):
        self.assertTrue(self.client.matches_preference("ras teste reserva - curso: n eu vou", "qualquer"))

    def test_qualquer_matches_normal_available_rows(self):
        self.assertTrue(self.client.matches_preference("ras teste 2 - curso: n eu vou", "qualquer"))

    def test_scan_stays_on_same_date_after_success(self):
        self.assertEqual(next_scan_date_index(3, found_candidate=True), 3)

    def test_scan_advances_after_empty_date(self):
        self.assertEqual(next_scan_date_index(3, found_candidate=False), 4)


if __name__ == "__main__":
    unittest.main()
