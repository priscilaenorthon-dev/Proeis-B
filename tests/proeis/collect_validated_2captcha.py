from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from twocaptcha import TwoCaptcha


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://www.proeis.rj.gov.br/"
DEFAULT_URL = urljoin(BASE_URL, "Default.aspx")
OUT_DIR = Path(__file__).resolve().parent / "validated_2captcha"


@dataclass(frozen=True)
class ValidatedCaptcha:
    index: int
    attempt: int
    file: str
    label: str
    solve_ms: int
    total_ms: int
    captcha_id: str


@dataclass(frozen=True)
class RejectedCaptcha:
    attempt: int
    file: str
    answer: str
    status: str
    solve_ms: int
    total_ms: int
    captcha_id: str


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Variavel {name} nao definida.")
    return value


def normalize_answer(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def valid_shape(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{6}", normalize_answer(value)))


def norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
            "Origin": BASE_URL.rstrip("/"),
            "Referer": DEFAULT_URL,
        }
    )
    return session


def load_login_captcha(session: requests.Session) -> tuple[BeautifulSoup, bytes]:
    response = session.get(DEFAULT_URL, timeout=(8, 25))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    payload = form_payload(soup)
    payload["ddlTipoAcesso"] = "ID"
    payload["__EVENTTARGET"] = "ddlTipoAcesso"
    payload["__EVENTARGUMENT"] = ""
    response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return soup, extract_captcha(response.text)


def password_for_form(soup: BeautifulSoup) -> str:
    password = required_env("PROEIS_PASSWORD")
    password_input = soup.select_one("#txtSenha, input[name=txtSenha]")
    max_length = password_input.get("maxlength") if password_input else None
    if max_length and max_length.isdigit():
        return password[: int(max_length)]
    return password


def solve_2captcha(solver: TwoCaptcha, image_path: Path) -> tuple[str, int, str]:
    start = time.perf_counter()
    result = solver.normal(str(image_path), numeric=0, minLen=6, maxLen=6, caseSensitive=0)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return normalize_answer(str(result.get("code", ""))), elapsed_ms, str(result.get("captchaId") or result.get("id") or "")


def submit_login(session: requests.Session, soup: BeautifulSoup, answer: str) -> str:
    payload = form_payload(soup)
    payload.update(
        {
            "txtLogin": required_env("PROEIS_LOGIN"),
            "txtSenha": password_for_form(soup),
            "TextCaptcha": answer,
            "btnEntrar": "Entrar",
        }
    )
    response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
    response.raise_for_status()
    result_soup = BeautifulSoup(response.text, "html.parser")
    text = norm_text(result_soup.get_text(" ", strip=True))
    if not result_soup.select_one("#txtSenha") and not result_soup.select_one("#TextCaptcha"):
        return "accepted"
    if "erro ao confirmar imagem" in text:
        return "captcha_error"
    if "senha invalida" in text:
        return "password_error"
    return "unknown_error"


def write_manifest(out_dir: Path, accepted: list[ValidatedCaptcha], rejected: list[RejectedCaptcha], completed: bool) -> None:
    solve_times = [item.solve_ms for item in accepted]
    manifest = {
        "completed": completed,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "avg_accepted_solve_ms": round(sum(solve_times) / len(solve_times), 1) if solve_times else 0,
        "accepted": [asdict(item) for item in accepted],
        "rejected": [asdict(item) for item in rejected],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta captchas com rotulo validado pelo PROEIS.")
    parser.add_argument("--target", type=int, default=100, help="Quantidade de captchas aceitos pelo PROEIS.")
    parser.add_argument("--max-attempts", type=int, default=250)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    load_env_file()
    out_dir = Path(args.out_dir)
    accepted_dir = out_dir / "accepted"
    rejected_dir = out_dir / "rejected"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    solver = TwoCaptcha(required_env("TWOCAPTCHA_API_KEY"), pollingInterval=1.5, defaultTimeout=120)
    accepted: list[ValidatedCaptcha] = []
    rejected: list[RejectedCaptcha] = []

    try:
        for attempt in range(1, args.max_attempts + 1):
            if len(accepted) >= args.target:
                break
            started = time.perf_counter()
            session = new_session()
            soup, image = load_login_captcha(session)
            temp_path = out_dir / f"attempt_{attempt:04d}.png"
            temp_path.write_bytes(image)

            try:
                answer, solve_ms, captcha_id = solve_2captcha(solver, temp_path)
            except Exception as exc:
                answer, solve_ms, captcha_id = f"ERROR:{str(exc)[:60]}", 0, ""

            if valid_shape(answer):
                status = submit_login(session, soup, answer)
            else:
                status = "invalid_shape"

            total_ms = int((time.perf_counter() - started) * 1000)
            if status == "accepted":
                index = len(accepted) + 1
                filename = f"validated_{index:04d}_{answer}.png"
                temp_path.replace(accepted_dir / filename)
                accepted.append(ValidatedCaptcha(index, attempt, f"accepted/{filename}", answer, solve_ms, total_ms, captcha_id))
                print(f"OK {index:04d}/{args.target} attempt={attempt} label={answer} solve={solve_ms}ms total={total_ms}ms")
            else:
                filename = f"rejected_{attempt:04d}_{answer[:20] or 'EMPTY'}_{status}.png"
                temp_path.replace(rejected_dir / filename)
                rejected.append(RejectedCaptcha(attempt, f"rejected/{filename}", answer, status, solve_ms, total_ms, captcha_id))
                print(f"NO attempt={attempt} status={status} answer={answer} solve={solve_ms}ms")

            write_manifest(out_dir, accepted, rejected, completed=False)
            if args.delay > 0:
                time.sleep(args.delay)
    finally:
        write_manifest(out_dir, accepted, rejected, completed=len(accepted) >= args.target)

    print(f"Aceitos: {len(accepted)} | Rejeitados: {len(rejected)}")
    print(f"Manifesto: {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
