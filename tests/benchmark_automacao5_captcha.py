from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests


BASE_URL = "https://automacao5.deploy.app.br"
AUTH_LOGIN_URL = f"{BASE_URL}/server/server.php/auth/login"
CPROEIS_LOGIN0_URL = f"{BASE_URL}/server/server.php/cproeis2/login/0"
CPROEIS_SOLVE_URL = f"{BASE_URL}/server/server.php/cproeis2/login/0/solve-captcha"
OUT_DIR = Path(__file__).resolve().parent / "automacao5_captcha_samples"


@dataclass(frozen=True)
class CaptchaBenchResult:
    index: int
    file: str
    captcha_bytes: int
    load_ms: int
    solve_ms: int
    total_ms: int
    solution: str
    valid_shape: bool
    success: bool
    message: str


class RateLimited(RuntimeError):
    pass


def env_or_fail(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Defina a variavel de ambiente {name}.")
    return value


def timed_request(fn):
    start = time.perf_counter()
    result = fn()
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return result, elapsed_ms


def login(session: requests.Session, email: str, password: str) -> dict:
    response = session.post(
        AUTH_LOGIN_URL,
        data={"email": email, "password": password},
        timeout=(8, 30),
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"Login falhou: {data.get('message') or data}")
    return data


def load_captcha(session: requests.Session, access_type: str) -> dict:
    response = session.post(
        CPROEIS_LOGIN0_URL,
        data={"tipoAcesso": access_type},
        timeout=(8, 30),
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"Carregamento do captcha falhou: {data.get('message') or data}")
    return data


def solve_captcha(session: requests.Session) -> dict:
    response = session.get(CPROEIS_SOLVE_URL, timeout=(8, 30))
    if response.status_code == 429:
        raise RateLimited("HTTP 429 Too Many Requests")
    response.raise_for_status()
    return response.json()


def valid_solution_shape(value: str) -> bool:
    return isinstance(value, str) and len(value) == 6 and value.isalnum()


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * pct)
    return ordered[index]


def summarize(results: list[CaptchaBenchResult]) -> dict:
    solve_times = [item.solve_ms for item in results]
    total_times = [item.total_ms for item in results]
    valid_count = sum(1 for item in results if item.valid_shape)
    success_count = sum(1 for item in results if item.success)
    return {
        "count": len(results),
        "success_count": success_count,
        "valid_shape_count": valid_count,
        "solve_ms_min": min(solve_times, default=0),
        "solve_ms_avg": round(statistics.mean(solve_times), 1) if solve_times else 0,
        "solve_ms_median": round(statistics.median(solve_times), 1) if solve_times else 0,
        "solve_ms_p90": percentile(solve_times, 0.90),
        "solve_ms_max": max(solve_times, default=0),
        "total_ms_avg": round(statistics.mean(total_times), 1) if total_times else 0,
    }


def write_report(out_dir: Path, access_type: str, results: list[CaptchaBenchResult], completed: bool) -> dict:
    report = {
        "source": BASE_URL,
        "endpoint": CPROEIS_SOLVE_URL,
        "access_type": access_type,
        "completed": completed,
        "summary": summarize(results),
        "results": [asdict(item) for item in results],
    }
    (out_dir / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def run(count: int, access_type: str, out_dir: Path, delay_seconds: float, retry_after_429: float, max_429_retries: int) -> dict:
    email = env_or_fail("AUTOMACAO5_EMAIL")
    password = env_or_fail("AUTOMACAO5_PASSWORD")

    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/cproeis2.html",
        }
    )

    login_data = login(session, email, password)
    print(f"Login OK: {login_data.get('data', {}).get('name', 'usuario')}")

    results: list[CaptchaBenchResult] = []
    for index in range(1, count + 1):
        captcha_data, load_ms = timed_request(lambda: load_captcha(session, access_type))
        raw_b64 = captcha_data.get("captcha", "")
        image = base64.b64decode(raw_b64)
        image_path = out_dir / f"captcha_{index:02d}.png"
        image_path.write_bytes(image)

        solve_data = {"success": False, "message": "", "captchaSolution": ""}
        solve_ms = 0
        for retry in range(max_429_retries + 1):
            try:
                solve_data, solve_ms = timed_request(lambda: solve_captcha(session))
                break
            except RateLimited as exc:
                if retry >= max_429_retries:
                    solve_data = {"success": False, "message": str(exc), "captchaSolution": ""}
                    break
                wait = retry_after_429 * (retry + 1)
                print(f"{index:02d}/{count}: rate limit; aguardando {wait:.1f}s antes de tentar de novo...")
                time.sleep(wait)

        solution = str(solve_data.get("captchaSolution") or "")
        result = CaptchaBenchResult(
            index=index,
            file=image_path.name,
            captcha_bytes=len(image),
            load_ms=load_ms,
            solve_ms=solve_ms,
            total_ms=load_ms + solve_ms,
            solution=solution,
            valid_shape=valid_solution_shape(solution),
            success=bool(solve_data.get("success")),
            message=str(solve_data.get("message") or ""),
        )
        results.append(result)
        print(
            f"{index:02d}/{count}: load={load_ms}ms solve={solve_ms}ms "
            f"solution={solution or '-'} valid={result.valid_shape}"
        )
        write_report(out_dir, access_type, results, completed=False)
        if not result.success and "429" in result.message:
            print("Parando por rate limit persistente. O manifesto parcial foi salvo.")
            return write_report(out_dir, access_type, results, completed=False)
        if delay_seconds > 0 and index < count:
            time.sleep(delay_seconds)

    return write_report(out_dir, access_type, results, completed=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark isolado do solver de captcha do automacao5.")
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--access-type", choices=["ID", "CPF"], default="ID")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--delay", type=float, default=3.0, help="Pausa entre captchas para evitar rate limit.")
    parser.add_argument("--retry-after-429", type=float, default=20.0)
    parser.add_argument("--max-429-retries", type=int, default=3)
    args = parser.parse_args()

    report = run(args.count, args.access_type, Path(args.out_dir), args.delay, args.retry_after_429, args.max_429_retries)
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    print(f"Manifesto: {Path(args.out_dir) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
