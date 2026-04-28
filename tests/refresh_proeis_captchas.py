from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.proeis.rj.gov.br/"
DEFAULT_URL = urljoin(BASE_URL, "Default.aspx")
OUT_DIR = Path(__file__).resolve().parent / "captcha_refresh_samples"


def form_payload(soup: BeautifulSoup) -> dict[str, str]:
    payload: dict[str, str] = {}
    for tag in soup.select("input[name], select[name], textarea[name]"):
        name = tag.get("name")
        if not name:
            continue
        if tag.name == "select":
            selected = tag.select_one("option[selected]")
            option = selected or tag.select_one("option")
            payload[name] = option.get("value", option.get_text(strip=True)) if option else ""
        elif tag.name == "textarea":
            payload[name] = tag.get_text()
        elif tag.get("type") in {"checkbox", "radio"}:
            if tag.has_attr("checked"):
                payload[name] = tag.get("value", "on")
        elif tag.get("type") not in {"submit", "button", "image", "file"}:
            payload[name] = tag.get("value", "")
    return payload


def extract_captcha(html: str) -> bytes:
    match = re.search(r"data:image/png;base64,([^'\";)]+)", html)
    if not match:
        raise RuntimeError("Captcha base64 nao encontrado no HTML")
    return base64.b64decode(match.group(1))


def select_id_access(session: requests.Session) -> BeautifulSoup:
    response = session.get(DEFAULT_URL, timeout=(8, 25))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    payload = form_payload(soup)
    if "ddlTipoAcesso" in payload:
        payload["ddlTipoAcesso"] = "ID"
        payload["__EVENTTARGET"] = "ddlTipoAcesso"
        payload["__EVENTARGUMENT"] = ""
        response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    return soup


def refresh_captcha(session: requests.Session, soup: BeautifulSoup) -> BeautifulSoup:
    payload = form_payload(soup)
    payload["__EVENTTARGET"] = "lnkNewCaptcha"
    payload["__EVENTARGUMENT"] = ""
    response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def save_sample(index: int, soup: BeautifulSoup) -> dict[str, object]:
    html = str(soup)
    image = extract_captcha(html)
    digest = hashlib.sha256(image).hexdigest()
    path = OUT_DIR / f"refresh_{index:02d}.png"
    path.write_bytes(image)
    return {"index": index, "file": path.name, "bytes": len(image), "sha256": digest}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )

    soup = select_id_access(session)
    manifest = []
    for index in range(1, 11):
        if index > 1:
            soup = refresh_captcha(session, soup)
        sample = save_sample(index, soup)
        manifest.append(sample)
        print(f"{index:02d}: {OUT_DIR / sample['file']} ({sample['bytes']} bytes) {sample['sha256']}")
        time.sleep(0.5)

    unique = len({sample["sha256"] for sample in manifest})
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"unique_images": unique, "samples": manifest}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Imagens unicas: {unique}/{len(manifest)}")
    print(f"Manifesto: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
