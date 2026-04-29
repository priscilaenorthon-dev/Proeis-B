from __future__ import annotations

import argparse
import base64
import json
import os
import pickle
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageOps
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC


BASE_URL = "https://automacao5.deploy.app.br"
AUTH_LOGIN_URL = f"{BASE_URL}/server/server.php/auth/login"
CPROEIS_LOGIN0_URL = f"{BASE_URL}/server/server.php/cproeis2/login/0"
CPROEIS_SOLVE_URL = f"{BASE_URL}/server/server.php/cproeis2/login/0/solve-captcha"
DATA_DIR = Path(__file__).resolve().parent / "ocr_captcha_dataset"
MODEL_PATH = Path(__file__).resolve().parent / "ocr_captcha_model.pkl"


@dataclass(frozen=True)
class Sample:
    index: int
    file: str
    label: str
    load_ms: int
    solve_ms: int
    bytes: int


def env_or_fail(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Defina a variavel de ambiente {name}.")
    return value


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, int((time.perf_counter() - start) * 1000)


def valid_label(value: str) -> bool:
    return isinstance(value, str) and len(value) == 6 and value.isalnum()


def login(session: requests.Session) -> None:
    response = session.post(
        AUTH_LOGIN_URL,
        data={"email": env_or_fail("AUTOMACAO5_EMAIL"), "password": env_or_fail("AUTOMACAO5_PASSWORD")},
        timeout=(8, 30),
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"Login falhou: {data.get('message') or data}")


def collect(count: int, delay: float, out_dir: Path, access_type: str = "ID") -> dict:
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
    login(session)

    manifest_path = out_dir / "manifest.json"
    samples: list[Sample] = []
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        samples = [Sample(**item) for item in previous.get("samples", [])]

    start_index = len(samples) + 1
    for index in range(start_index, count + 1):
        captcha_data, load_ms = timed(
            lambda: session.post(CPROEIS_LOGIN0_URL, data={"tipoAcesso": access_type}, timeout=(8, 30)).json()
        )
        if not captcha_data.get("success"):
            raise RuntimeError(f"Falha ao carregar captcha: {captcha_data}")

        image = base64.b64decode(captcha_data["captcha"])

        solve_response, solve_ms = timed(lambda: session.get(CPROEIS_SOLVE_URL, timeout=(8, 30)))
        if solve_response.status_code == 429:
            print(f"{index:03d}: rate limit; aguardando 60s...")
            time.sleep(60)
            solve_response, solve_ms = timed(lambda: session.get(CPROEIS_SOLVE_URL, timeout=(8, 30)))
        solve_response.raise_for_status()
        solve_data = solve_response.json()
        label = str(solve_data.get("captchaSolution") or "").upper()

        if not valid_label(label):
            print(f"{index:03d}: label invalido recebido: {label!r}; pulando")
            continue

        filename = f"captcha_{index:03d}_{label}.png"
        path = out_dir / filename
        path.write_bytes(image)
        sample = Sample(index=index, file=filename, label=label, load_ms=load_ms, solve_ms=solve_ms, bytes=len(image))
        samples.append(sample)

        report = {"source": BASE_URL, "samples": [asdict(item) for item in samples]}
        manifest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{index:03d}/{count}: {label} load={load_ms}ms solve={solve_ms}ms")
        if delay > 0 and index < count:
            time.sleep(delay)

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def char_crop(image: Image.Image, position: int, total: int = 6) -> Image.Image:
    gray = ImageOps.grayscale(image)
    width, height = gray.size
    margin_x = int(width * 0.035)
    usable_w = width - 2 * margin_x
    cell_w = usable_w / total
    left = int(margin_x + position * cell_w)
    right = int(margin_x + (position + 1) * cell_w)
    top = int(height * 0.04)
    bottom = int(height * 0.96)
    return gray.crop((left, top, right, bottom))


def featurize_char(crop: Image.Image, size: int = 28) -> np.ndarray:
    crop = ImageOps.autocontrast(crop)
    crop = crop.resize((size, size), Image.Resampling.LANCZOS)
    arr = np.asarray(crop, dtype=np.float32) / 255.0
    return (1.0 - arr).reshape(-1)


def build_dataset(manifest_path: Path, data_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    x_rows: list[np.ndarray] = []
    y_rows: list[str] = []
    groups: list[int] = []

    for sample in manifest.get("samples", []):
        label = sample["label"].upper()
        if not valid_label(label):
            continue
        image = Image.open(data_dir / sample["file"]).convert("RGB")
        for pos, char in enumerate(label):
            x_rows.append(featurize_char(char_crop(image, pos)))
            y_rows.append(char)
            groups.append(int(sample["index"]))

    return np.vstack(x_rows), np.array(y_rows), np.array(groups)


def captcha_accuracy(model, manifest_path: Path, data_dir: Path, groups_to_eval: set[int]) -> float:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    total = 0
    correct = 0
    for sample in manifest.get("samples", []):
        if int(sample["index"]) not in groups_to_eval:
            continue
        image = Image.open(data_dir / sample["file"]).convert("RGB")
        pred = "".join(model.predict([featurize_char(char_crop(image, pos))])[0] for pos in range(6))
        total += 1
        correct += int(pred == sample["label"].upper())
    return correct / total if total else 0.0


def train(manifest_path: Path, data_dir: Path, model_path: Path, seed: int = 7) -> dict:
    x, y, groups = build_dataset(manifest_path, data_dir)
    unique_groups = sorted(set(groups.tolist()))
    if len(unique_groups) < 5:
        raise SystemExit("Colete pelo menos 5 captchas rotulados antes de treinar.")

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    train_idx, test_idx = next(splitter.split(x, y, groups))
    test_groups = set(groups[test_idx].tolist())

    models = {
        "linear_svc": make_pipeline(StandardScaler(), LinearSVC(C=1.0, max_iter=20000, random_state=seed)),
        "logistic": make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, n_jobs=None, random_state=seed),
        ),
        "knn_3": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=3, weights="distance")),
        "random_forest": RandomForestClassifier(n_estimators=250, random_state=seed, n_jobs=-1),
    }

    results = []
    best_name = ""
    best_score = -1.0
    best_model = None
    for name, model in models.items():
        start = time.perf_counter()
        model.fit(x[train_idx], y[train_idx])
        train_ms = int((time.perf_counter() - start) * 1000)
        pred = model.predict(x[test_idx])
        char_acc = accuracy_score(y[test_idx], pred)
        cap_acc = captcha_accuracy(model, manifest_path, data_dir, test_groups)
        row = {
            "model": name,
            "train_ms": train_ms,
            "char_accuracy": round(char_acc, 4),
            "captcha_accuracy": round(cap_acc, 4),
        }
        results.append(row)
        print(f"{name}: char={char_acc:.3f} captcha={cap_acc:.3f} train={train_ms}ms")
        score = cap_acc * 10 + char_acc
        if score > best_score:
            best_score = score
            best_name = name
            best_model = model

    assert best_model is not None
    best_model.fit(x, y)
    with model_path.open("wb") as fh:
        pickle.dump({"model": best_model, "model_name": best_name}, fh)

    report = {
        "samples": len(unique_groups),
        "characters": len(y),
        "test_captchas": len(test_groups),
        "best_model": best_name,
        "results": results,
        "model_path": str(model_path),
    }
    (data_dir / "training_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def predict(image_path: Path, model_path: Path) -> str:
    with model_path.open("rb") as fh:
        payload = pickle.load(fh)
    model = payload["model"]
    image = Image.open(image_path).convert("RGB")
    return "".join(model.predict([featurize_char(char_crop(image, pos))])[0] for pos in range(6))


def main() -> int:
    parser = argparse.ArgumentParser(description="Laboratorio de OCR local para captcha CPROEIS.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_collect = sub.add_parser("collect", help="Coleta captchas rotulados usando o backend do automacao5 como oraculo.")
    p_collect.add_argument("--count", type=int, default=25)
    p_collect.add_argument("--delay", type=float, default=8.0)
    p_collect.add_argument("--out-dir", default=str(DATA_DIR))

    p_train = sub.add_parser("train", help="Treina e compara modelos locais.")
    p_train.add_argument("--data-dir", default=str(DATA_DIR))
    p_train.add_argument("--model-path", default=str(MODEL_PATH))
    p_train.add_argument("--seed", type=int, default=7)

    p_predict = sub.add_parser("predict", help="Prediz um captcha com o modelo treinado.")
    p_predict.add_argument("image")
    p_predict.add_argument("--model-path", default=str(MODEL_PATH))

    args = parser.parse_args()
    random.seed(7)
    np.random.seed(7)

    if args.cmd == "collect":
        collect(args.count, args.delay, Path(args.out_dir))
    elif args.cmd == "train":
        report = train(Path(args.data_dir) / "manifest.json", Path(args.data_dir), Path(args.model_path), seed=args.seed)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.cmd == "predict":
        print(predict(Path(args.image), Path(args.model_path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
