import unittest

from proeis_gui import backend_disponivel, display_disponivel


class GuiLabelsTests(unittest.TestCase):
    def test_displays_titular_label_for_nao_reserva(self):
        self.assertEqual(display_disponivel("nao-reserva"), "nao-reserva (Titular)")

    def test_converts_titular_label_to_backend_value(self):
        self.assertEqual(backend_disponivel("nao-reserva (Titular)"), "nao-reserva")


if __name__ == "__main__":
    unittest.main()
