from __future__ import annotations

import argparse
import base64
import json
import os
import pickle
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image
from twocaptcha import TwoCaptcha


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
OUT_DIR = TESTS_DIR / "proeis_captcha_solver_comparison"
LOCAL_MODEL_PATH = TESTS_DIR / "saved_captcha_ocr_model.pkl"

sys.path.insert(0, str(TESTS_DIR))
from captcha_ocr_train import char_crop, featurize_char  # noqa: E402


BASE_URL = "https://www.proeis.rj.gov.br/"
DEFAULT_URL = urljoin(BASE_URL, "Default.aspx")


@dataclass(frozen=True)
class SolverResult:
    solver: str
    index: int
    file: str
    answer: str
    solve_ms: int
    total_ms: int
    valid_shape: bool
    status: str
    message: str


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
    value = normalize_answer(value)
    return bool(re.fullmatch(r"[A-Z0-9]{6}", value))


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
        raise RuntimeError("Captcha base64 nao encontrado no HTML.")
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


def password_for_form(soup: BeautifulSoup, password: str) -> str:
    password_input = soup.select_one("#txtSenha, input[name=txtSenha]")
    max_length = password_input.get("maxlength") if password_input else None
    if max_length and max_length.isdigit():
        return password[: int(max_length)]
    return password


def submit_login(session: requests.Session, soup: BeautifulSoup, answer: str) -> tuple[str, str]:
    payload = form_payload(soup)
    payload.update(
        {
            "txtLogin": required_env("PROEIS_LOGIN"),
            "txtSenha": password_for_form(soup, required_env("PROEIS_PASSWORD")),
            "TextCaptcha": answer,
            "btnEntrar": "Entrar",
        }
    )
    response = session.post(DEFAULT_URL, data=payload, timeout=(8, 25))
    response.raise_for_status()
    result_soup = BeautifulSoup(response.text, "html.parser")
    text = norm_text(result_soup.get_text(" ", strip=True))
    if not result_soup.select_one("#txtSenha") and not result_soup.select_one("#TextCaptcha"):
        return "success", "login aceito"
    if "erro ao confirmar imagem" in text:
        return "captcha_error", "captcha recusado"
    if "senha invalida" in text:
        return "password_error", "senha recusada"
    return "unknown_error", re.sub(r"\s+", " ", result_soup.get_text(" ", strip=True))[:180]


def predict_local(model_payload: dict, image_bytes: bytes) -> str:
    image_path = OUT_DIR / "_tmp_predict.png"
    image_path.write_bytes(image_bytes)
    image = Image.open(image_path).convert("RGB")
    model = model_payload["model"]
    return "".join(model.predict([featurize_char(char_crop(image, pos))])[0] for pos in range(6))


def solve_2captcha(solver: TwoCaptcha, image_path: Path) -> str:
    result = solver.normal(str(image_path), numeric=0, minLen=6, maxLen=6, caseSensitive=0)
    return normalize_answer(str(result.get("code", "")))


def run_one(solver_name: str, index: int, solver, out_dir: Path) -> SolverResult:
    started = time.perf_counter()
    session = new_session()
    soup, image = load_login_captcha(session)

    image_path = out_dir / f"{solver_name}_{index:02d}.png"
    image_path.write_bytes(image)

    solve_started = time.perf_counter()
    if solver_name == "local":
        answer = normalize_answer(predict_local(solver, image))
    else:
        answer = solve_2captcha(solver, image_path)
    solve_ms = int((time.perf_counter() - solve_started) * 1000)

    if not valid_shape(answer):
        status, message = "invalid_shape", "resposta fora do formato de 6 caracteres"
    else:
        status, message = submit_login(session, soup, answer)

    total_ms = int((time.perf_counter() - started) * 1000)
    return SolverResult(
        solver=solver_name,
        index=index,
        file=image_path.name,
        answer=answer,
        solve_ms=solve_ms,
        total_ms=total_ms,
        valid_shape=valid_shape(answer),
        status=status,
        message=message,
    )


def summarize(results: list[SolverResult]) -> dict[str, object]:
    by_solver: dict[str, dict[str, object]] = {}
    for solver_name in sorted({item.solver for item in results}):
        subset = [item for item in results if item.solver == solver_name]
        solve_times = [item.solve_ms for item in subset]
        by_solver[solver_name] = {
            "count": len(subset),
            "success": sum(1 for item in subset if item.status == "success"),
            "captcha_error": sum(1 for item in subset if item.status == "captcha_error"),
            "invalid_shape": sum(1 for item in subset if item.status == "invalid_shape"),
            "other_error": sum(1 for item in subset if item.status not in {"success", "captcha_error", "invalid_shape"}),
            "avg_solve_ms": round(sum(solve_times) / len(solve_times), 1) if solve_times else 0,
            "min_solve_ms": min(solve_times, default=0),
            "max_solve_ms": max(solve_times, default=0),
        }
    return by_solver


def write_report(out_dir: Path, results: list[SolverResult], completed: bool) -> None:
    report = {
        "completed": completed,
        "summary": summarize(results),
        "results": [asdict(item) for item in results],
    }
    (out_dir / "comparison_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara OCR local e 2captcha em captchas reais do PROEIS.")
    parser.add_argument("--count", type=int, default=20, help="Quantidade por solver.")
    parser.add_argument("--solver", choices=["both", "local", "2captcha"], default="both")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    load_env_file()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    local_payload = None
    two_solver = None
    if args.solver in {"both", "local"}:
        if not LOCAL_MODEL_PATH.exists():
            raise SystemExit(f"Modelo local nao encontrado: {LOCAL_MODEL_PATH}")
        with LOCAL_MODEL_PATH.open("rb") as fh:
            local_payload = pickle.load(fh)
    if args.solver in {"both", "2captcha"}:
        two_solver = TwoCaptcha(required_env("TWOCAPTCHA_API_KEY"), pollingInterval=1.5, defaultTimeout=120)

    plan = []
    if args.solver in {"both", "local"}:
        plan.extend(("local", i, local_payload) for i in range(1, args.count + 1))
    if args.solver in {"both", "2captcha"}:
        plan.extend(("2captcha", i, two_solver) for i in range(1, args.count + 1))

    results: list[SolverResult] = []
    try:
        for solver_name, index, solver in plan:
            result = run_one(solver_name, index, solver, out_dir)
            results.append(result)
            write_report(out_dir, results, completed=False)
            print(
                f"{solver_name} {index:02d}/{args.count}: answer={result.answer or '-'} "
                f"status={result.status} solve={result.solve_ms}ms total={result.total_ms}ms"
            )
            if args.delay > 0:
                time.sleep(args.delay)
    finally:
        write_report(out_dir, results, completed=len(results) == len(plan))

    print(json.dumps(summarize(results), indent=2, ensure_ascii=False))
    print(f"Relatorio: {out_dir / 'comparison_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
