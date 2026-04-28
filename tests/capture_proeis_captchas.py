from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.proeis.rj.gov.br/"
DEFAULT_URL = urljoin(BASE_URL, "Default.aspx")
OUT_DIR = Path(__file__).resolve().parent / "captcha_samples"


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


def captcha_related_controls(soup: BeautifulSoup) -> list[str]:
    controls: list[str] = []
    for tag in soup.select("a, input, button, img"):
        text = " ".join(
            [
                tag.name or "",
                tag.get_text(" ", strip=True),
                tag.get("id", ""),
                tag.get("name", ""),
                tag.get("value", ""),
                tag.get("alt", ""),
                tag.get("title", ""),
                tag.get("src", ""),
                tag.get("href", ""),
            ]
        )
        if any(word in text.lower() for word in ("captcha", "imagem", "atual", "refresh", "reload", "nova")):
            controls.append(re.sub(r"\s+", " ", text).strip()[:300])
    return controls


def fetch_login_captcha(session: requests.Session) -> tuple[bytes, list[str], str]:
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

    return extract_captcha(response.text), captcha_related_controls(soup), response.url


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

    manifest = []
    for index in range(1, 11):
        image, controls, url = fetch_login_captcha(session)
        path = OUT_DIR / f"captcha_{index:02d}.png"
        path.write_bytes(image)
        manifest.append(
            {
                "index": index,
                "file": path.name,
                "bytes": len(image),
                "url": url,
                "controls": controls,
            }
        )
        print(f"{index:02d}: {path} ({len(image)} bytes)")
        time.sleep(0.5)

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifesto: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
