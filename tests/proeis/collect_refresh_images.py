from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.proeis.rj.gov.br/"
DEFAULT_URL = urljoin(BASE_URL, "Default.aspx")
OUT_DIR = Path(__file__).resolve().parent / "raw_refresh_images"


@dataclass(frozen=True)
class RawCaptcha:
    index: int
    file: str
    bytes: int
    sha256: str


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
        raise RuntimeError("Captcha base64 nao encontrado.")
    return base64.b64decode(match.group(1))


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )
    return session


def select_id_access(session: requests.Session) -> BeautifulSoup:
    response = session.get(DEFAULT_URL, timeout=(8, 25))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    payload = form_payload(soup)
    payload["ddlTipoAcesso"] = "ID"
    payload["__EVENTTARGET"] = "ddlTipoAcesso"
    payload["__EVENTARGUMENT"] = ""
    response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def refresh_captcha(session: requests.Session, soup: BeautifulSoup) -> BeautifulSoup:
    payload = form_payload(soup)
    payload["__EVENTTARGET"] = "lnkNewCaptcha"
    payload["__EVENTARGUMENT"] = ""
    response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta imagens de captcha do PROEIS via Gerar Nova Imagem.")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = new_session()
    soup = select_id_access(session)
    samples: list[RawCaptcha] = []

    for index in range(1, args.count + 1):
        if index > 1:
            soup = refresh_captcha(session, soup)
        image = extract_captcha(str(soup))
        digest = hashlib.sha256(image).hexdigest()
        filename = f"raw_{index:03d}.png"
        (out_dir / filename).write_bytes(image)
        sample = RawCaptcha(index=index, file=filename, bytes=len(image), sha256=digest)
        samples.append(sample)
        (out_dir / "manifest.json").write_text(
            json.dumps({"count": len(samples), "samples": [asdict(item) for item in samples]}, indent=2),
            encoding="utf-8",
        )
        print(f"{index:03d}/{args.count}: {filename} {len(image)} bytes {digest[:12]}")
        if args.delay > 0 and index < args.count:
            time.sleep(args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
