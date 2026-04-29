from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from twocaptcha import TwoCaptcha


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = [
    ROOT / "tests" / "captcha_samples",
    ROOT / "tests" / "captcha_refresh_samples",
]
OUT_DIR = ROOT / "tests" / "saved_captcha_2captcha_labels"


@dataclass(frozen=True)
class LabeledCaptcha:
    index: int
    source_dir: str
    source_file: str
    file: str
    label: str
    solve_ms: int
    captcha_id: str
    valid_shape: bool


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def valid_shape(value: str) -> bool:
    return len(value) == 6 and value.isalnum()


def iter_images() -> list[Path]:
    images: list[Path] = []
    for source_dir in SOURCE_DIRS:
        images.extend(sorted(source_dir.glob("*.png")))
    return images


def solve_image(solver: TwoCaptcha, image_path: Path) -> tuple[str, int, str]:
    start = time.perf_counter()
    result = solver.normal(
        str(image_path),
        numeric=0,
        minLen=5,
        maxLen=6,
        caseSensitive=0,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    label = normalize(str(result.get("code", "")))
    captcha_id = str(result.get("captchaId") or result.get("id") or "")
    return label, elapsed_ms, captcha_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotula os captchas salvos usando 2captcha.")
    parser.add_argument("--limit", type=int, default=0, help="0 = todos")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    load_env_file()
    api_key = os.getenv("TWOCAPTCHA_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TWOCAPTCHA_API_KEY nao definido no .env ou ambiente.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    images = iter_images()
    if args.limit:
        images = images[: args.limit]
    if not images:
        raise SystemExit("Nenhuma imagem PNG encontrada.")

    solver = TwoCaptcha(api_key, pollingInterval=1.5, defaultTimeout=120)
    samples: list[LabeledCaptcha] = []

    for index, image_path in enumerate(images, 1):
        label, solve_ms, captcha_id = solve_image(solver, image_path)
        dest_name = f"captcha_{index:03d}_{label or 'INVALID'}.png"
        shutil.copy2(image_path, out_dir / dest_name)
        sample = LabeledCaptcha(
            index=index,
            source_dir=image_path.parent.name,
            source_file=image_path.name,
            file=dest_name,
            label=label,
            solve_ms=solve_ms,
            captcha_id=captcha_id,
            valid_shape=valid_shape(label),
        )
        samples.append(sample)
        manifest_path.write_text(
            json.dumps(
                {
                    "source": "2captcha",
                    "count": len(samples),
                    "samples": [asdict(item) for item in samples],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"{index:02d}/{len(images)} {image_path.parent.name}/{image_path.name}: {label} {solve_ms}ms valid={sample.valid_shape}")
        if args.delay > 0 and index < len(images):
            time.sleep(args.delay)

    valid = sum(1 for item in samples if item.valid_shape)
    avg_ms = round(sum(item.solve_ms for item in samples) / len(samples), 1)
    print(f"Validos: {valid}/{len(samples)} | media 2captcha: {avg_ms}ms")
    print(f"Manifesto: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
