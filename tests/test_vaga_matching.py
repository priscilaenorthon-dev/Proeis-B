import unittest

from proeis_http import ProeisHTTP


class VagaMatchingTests(unittest.TestCase):
    def setUp(self):
        self.client = ProeisHTTP("login", "password", "captcha-key")

    def test_qualquer_matches_reserva(self):
        self.assertTrue(self.client.matches_preference("ras teste reserva - curso: n eu vou", "qualquer"))

    def test_qualquer_matches_normal_available_rows(self):
        self.assertTrue(self.client.matches_preference("ras teste 2 - curso: n eu vou", "qualquer"))


if __name__ == "__main__":
    unittest.main()
