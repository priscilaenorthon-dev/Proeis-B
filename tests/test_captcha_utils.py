import unittest

from bs4 import BeautifulSoup

from proeis_http import (
    AutomationError,
    ProeisHTTP,
    coerce_scan_rounds,
    display_date_for_log,
    is_valid_captcha_answer,
    normalize_captcha_answer,
)


CAPTCHA_HTML = """
<form>
  <input type="hidden" name="__VIEWSTATE" value="state1" />
  <div style="background: url(data:image/png;base64,QUJD);"></div>
  <a id="lnkNewCaptcha" href="javascript:__doPostBack('lnkNewCaptcha','')">Gerar Nova Imagem</a>
  <input name="TextCaptcha" />
</form>
"""

REFRESHED_CAPTCHA_HTML = """
<form>
  <input type="hidden" name="__VIEWSTATE" value="state2" />
  <div style="background: url(data:image/png;base64,REVG);"></div>
  <a id="lnkNewCaptcha" href="javascript:__doPostBack('lnkNewCaptcha','')">Gerar Nova Imagem</a>
  <input name="TextCaptcha" />
</form>
"""


class RefreshingCaptchaClient(ProeisHTTP):
    def __init__(self):
        super().__init__("login", "password", "captcha-key", debug=False)
        self.answers = ["B", "8", "A1B2C3"]
        self.refresh_count = 0

    def solve_captcha_once(self, image: bytes) -> str:
        answer = self.answers.pop(0)
        if not is_valid_captcha_answer(answer):
            raise AutomationError(f"2captcha retornou resposta invalida para captcha de 6 caracteres: {answer}")
        return normalize_captcha_answer(answer)

    def refresh_page_captcha(self, soup: BeautifulSoup) -> BeautifulSoup | None:
        self.refresh_count += 1
        refreshed = BeautifulSoup(REFRESHED_CAPTCHA_HTML, "html.parser")
        self.soup = refreshed
        return refreshed


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

    def test_solving_page_captcha_refreshes_image_after_two_invalid_answers(self):
        client = RefreshingCaptchaClient()
        soup = BeautifulSoup(CAPTCHA_HTML, "html.parser")
        client.soup = soup

        final_soup, text = client.solve_page_captcha(soup, refresh_after_invalids=2)

        self.assertEqual(text, "A1B2C3")
        self.assertEqual(client.refresh_count, 1)
        self.assertIn("state2", str(final_soup))

    def test_fill_page_captcha_preserves_selected_fields_after_refresh(self):
        client = RefreshingCaptchaClient()
        soup = BeautifulSoup(CAPTCHA_HTML, "html.parser")
        client.soup = soup
        payload = {
            "__VIEWSTATE": "state1",
            "ddlDataEvento": "2026-04-30",
            "ddlCPAS": "8o BPM - 6o CPA",
        }

        client.fill_page_captcha(soup, payload)

        self.assertEqual(payload["__VIEWSTATE"], "state2")
        self.assertEqual(payload["ddlDataEvento"], "2026-04-30")
        self.assertEqual(payload["ddlCPAS"], "8o BPM - 6o CPA")
        self.assertEqual(payload["TextCaptcha"], "A1B2C3")


if __name__ == "__main__":
    unittest.main()
