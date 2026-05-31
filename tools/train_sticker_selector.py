from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline


NO_STICKER_LABEL = "__none__"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def can_stratify(labels: list[str]) -> bool:
    counts = Counter(labels)
    return len(counts) > 1 and min(counts.values()) >= 2


def build_pipeline(max_iter: int, c_value: float) -> Pipeline:
    features = FeatureUnion(
        [
            ("char", TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1, max_features=80000, sublinear_tf=True)),
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, max_features=40000, sublinear_tf=True)),
        ]
    )
    clf = LogisticRegression(
        C=c_value,
        class_weight="balanced",
        max_iter=max_iter,
        n_jobs=1,
        solver="lbfgs",
        multi_class="auto",
    )
    return Pipeline([("features", features), ("classifier", clf)])


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a lightweight sticker selector classifier.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-iter", type=int, default=1000)
    parser.add_argument("--c", type=float, default=2.0)
    parser.add_argument("--threshold", type=float, default=0.45)
    args = parser.parse_args()

    data_path = Path(args.data)
    rows = read_jsonl(data_path)
    rows = [row for row in rows if str(row.get("text", "")).strip() and str(row.get("label", "")).strip()]
    if len(rows) < 5:
        raise SystemExit(f"not enough selector rows: {len(rows)}")

    texts = [str(row["text"]) for row in rows]
    labels = [str(row["label"]) for row in rows]
    label_counts = Counter(labels)
    if len(label_counts) < 2:
        raise SystemExit(f"need at least 2 labels, got: {dict(label_counts)}")

    stratify = labels if can_stratify(labels) else None
    if 0 < args.test_size < 1 and len(rows) >= 10:
        x_train, x_test, y_train, y_test = train_test_split(
            texts,
            labels,
            test_size=args.test_size,
            random_state=args.seed,
            stratify=stratify,
        )
    else:
        x_train, y_train = texts, labels
        x_test, y_test = [], []

    model = build_pipeline(args.max_iter, args.c)
    model.fit(x_train, y_train)

    metrics: dict[str, object] = {
        "data": str(data_path),
        "total_rows": len(rows),
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "label_count": len(label_counts),
        "label_counts": dict(label_counts.most_common()),
        "none_label": NO_STICKER_LABEL,
        "decision_threshold": args.threshold,
        "model_type": "tfidf_char_word_logistic_regression",
        "class_weight": "balanced",
    }
    if x_test:
        pred = model.predict(x_test)
        metrics["accuracy"] = accuracy_score(y_test, pred)
        metrics["macro_f1"] = f1_score(y_test, pred, average="macro")
        metrics["weighted_f1"] = f1_score(y_test, pred, average="weighted")
        metrics["classification_report"] = classification_report(y_test, pred, zero_division=0, output_dict=True)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "sticker_selector.joblib"
    metrics_path = out_dir / "metrics.json"
    labels_path = out_dir / "labels.json"
    config_path = out_dir / "selector_config.json"

    joblib.dump(model, model_path)
    labels_from_file = json.loads(Path(args.labels).read_text(encoding="utf-8")) if args.labels and Path(args.labels).exists() else None
    labels_out = labels_from_file or [NO_STICKER_LABEL] + sorted(label for label in label_counts if label != NO_STICKER_LABEL)
    labels_path.write_text(json.dumps(labels_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "model": "sticker_selector.joblib",
                "labels": "labels.json",
                "threshold": args.threshold,
                "none_label": NO_STICKER_LABEL,
                "input_format": "text = 上下文 + 我的回复",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"model={model_path}")
    print(f"labels={labels_path}")
    print(f"metrics={metrics_path}")
    print(f"label_count={len(label_counts)}")
    print(f"total_rows={len(rows)}")
    if "macro_f1" in metrics:
        print(f"macro_f1={metrics['macro_f1']:.4f}")


if __name__ == "__main__":
    main()
