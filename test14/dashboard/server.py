from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

try:
    import duckdb
except ImportError:  # pragma: no cover - dependency check endpoint reports this.
    duckdb = None


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
RAW_PATH = DATA_DIR / "online_shopping_10_cats.csv"
FEATURES_PATH = DATA_DIR / "batch_1000_features.csv"
FALLBACK_PATH = DATA_DIR / "fallback_reviews_sample.csv"
DUCKDB_PATH = DATA_DIR / "analytics.db"

SENTIMENT_ORDER = ["正面", "负面", "中性"]
SENTIMENT_SCORE = {"负面": -1.0, "中性": 0.0, "正面": 1.0}
LLM_ENV_KEYS = ["SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("week14")


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def feature_file_is_dashboard_ready(df: pd.DataFrame) -> bool:
    required = {"cat", "label", "review", "sentiment"}
    return required.issubset(df.columns) and df["cat"].nunique() >= 2 and df["label"].nunique() >= 2


def detect_llm_status() -> dict[str, Any]:
    configured_key = next((key for key in LLM_ENV_KEYS if os.getenv(key)), None)
    if configured_key:
        return {
            "llm_active": True,
            "degraded": False,
            "reason": "",
            "configured_key": configured_key,
            "message": "大模型 API Key 已配置，可启用完整 LLM 特征链路。",
        }

    warning = (
        "API_KEY_MISSING: 未检测到 SILICONFLOW_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY，"
        "系统降级为内置规则与历史数据看板，不影响基础可视化。"
    )
    logger.warning(warning)
    return {
        "llm_active": False,
        "degraded": True,
        "reason": "API_KEY_MISSING",
        "configured_key": "",
        "message": warning,
    }


def open_duckdb_read_only() -> Any | None:
    """Use read_only=True to avoid writer/reader lock conflicts in integrated runs."""
    if duckdb is None or not DUCKDB_PATH.exists():
        return None
    return duckdb.connect(database=str(DUCKDB_PATH), read_only=True)


def load_data() -> tuple[pd.DataFrame, dict[str, Any]]:
    metadata: dict[str, Any] = {
        "raw_path": str(RAW_PATH),
        "features_path": str(FEATURES_PATH),
        "fallback_path": str(FALLBACK_PATH),
        "selected_source": "",
        "selected_path": "",
        "fallback_reason": "",
        "warnings": [],
        "data_degraded": False,
    }

    candidate_df: pd.DataFrame | None = None
    if FEATURES_PATH.exists():
        feature_df = read_csv(FEATURES_PATH)
        metadata["feature_rows"] = int(len(feature_df))
        metadata["feature_categories"] = int(feature_df["cat"].nunique()) if "cat" in feature_df else 0
        metadata["feature_label_classes"] = int(feature_df["label"].nunique()) if "label" in feature_df else 0
        if feature_file_is_dashboard_ready(feature_df):
            candidate_df = feature_df.copy()
            metadata["selected_source"] = FEATURES_PATH.name
            metadata["selected_path"] = str(FEATURES_PATH)
        else:
            metadata["warnings"].append(
                "batch_1000_features.csv 只有单一品类或单一标签，不适合多维看板，继续寻找原始真实数据。"
            )

    if candidate_df is None and RAW_PATH.exists():
        candidate_df = read_csv(RAW_PATH)
        metadata["selected_source"] = RAW_PATH.name
        metadata["selected_path"] = str(RAW_PATH)
        if metadata["warnings"]:
            metadata["fallback_reason"] = "特征宽表不适合看板，已回退到 online_shopping_10_cats.csv。"

    if candidate_df is None and FALLBACK_PATH.exists():
        candidate_df = read_csv(FALLBACK_PATH)
        metadata["selected_source"] = FALLBACK_PATH.name
        metadata["selected_path"] = str(FALLBACK_PATH)
        metadata["data_degraded"] = True
        metadata["fallback_reason"] = (
            "核心数据文件缺失，已加载由真实数据抽样生成的 fallback_reviews_sample.csv。"
        )
        metadata["warnings"].append(metadata["fallback_reason"])

    if candidate_df is None:
        candidate_df = pd.DataFrame(
            [
                {"cat": "系统", "label": 0, "review": "未找到任何数据文件，请检查 test14/data 目录。"},
                {"cat": "系统", "label": 1, "review": "服务保持启动，等待补充真实数据后自动恢复。"},
            ]
        )
        metadata["selected_source"] = "in_memory_emergency_rows"
        metadata["selected_path"] = ""
        metadata["data_degraded"] = True
        metadata["fallback_reason"] = "数据文件全部缺失，已启用内存级应急样本，避免服务崩溃。"
        metadata["warnings"].append(metadata["fallback_reason"])

    df = candidate_df.copy()
    if "source_index" not in df.columns:
        df.insert(0, "source_index", df.index.astype(int))
    if "sentiment" not in df.columns:
        df["sentiment"] = df["label"].map({1: "正面", 0: "负面"}).fillna("中性")
    if "summary" not in df.columns:
        df["summary"] = ""
    if "category" not in df.columns:
        df["category"] = df["cat"]

    df["review"] = df["review"].fillna("").astype(str).str.replace("\ufeff", "", regex=False)
    df["cat"] = df["cat"].fillna("未知").astype(str)
    df["sentiment"] = df["sentiment"].fillna("中性").astype(str)
    df["label"] = pd.to_numeric(df["label"], errors="coerce").fillna(-1).astype(int)
    df["review_length"] = df["review"].str.len().astype(int)
    df["sentiment_score"] = df["sentiment"].map(SENTIMENT_SCORE).fillna(0.0)

    metadata["rows"] = int(len(df))
    metadata["categories"] = int(df["cat"].nunique())
    metadata["label_counts"] = {str(k): int(v) for k, v in df["label"].value_counts().sort_index().items()}
    for warning in metadata["warnings"]:
        logger.warning(warning)
    logger.info("Loaded %s rows from %s", metadata["rows"], metadata["selected_source"])
    return df, metadata


llm_status = detect_llm_status()
df, data_metadata = load_data()

app = FastAPI(title="M4 系统联调评论看板 API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_ids(ids: str | None) -> set[int] | None:
    if not ids:
        return None
    parsed: set[int] = set()
    for item in ids.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            parsed.add(int(item))
        except ValueError:
            continue
    return parsed or None


def filter_data(
    cat: str | None = None,
    sentiment: str | None = None,
    query: str | None = None,
    ids: str | None = None,
) -> tuple[pd.DataFrame, str]:
    filtered = df
    id_set = parse_ids(ids)
    if id_set is not None:
        filtered = filtered[filtered["source_index"].isin(id_set)]
    if cat:
        filtered = filtered[filtered["cat"] == cat]
    if sentiment:
        filtered = filtered[filtered["sentiment"] == sentiment]

    query_mode = "none"
    if query:
        review = filtered["review"].fillna("")
        try:
            re.compile(query)
            mask = review.str.contains(query, case=False, na=False, regex=True)
            query_mode = "regex"
        except re.error:
            mask = review.str.contains(query, case=False, na=False, regex=False)
            query_mode = "literal_fallback"
        filtered = filtered[mask]
    return filtered, query_mode


def category_distribution(filtered: pd.DataFrame) -> dict[str, Any]:
    stats = filtered["cat"].value_counts()
    return {
        "categories": stats.index.tolist(),
        "counts": [int(v) for v in stats.values],
        "total": int(stats.sum()),
    }


def sentiment_distribution(filtered: pd.DataFrame) -> dict[str, Any]:
    if filtered.empty:
        return {"sentiments": SENTIMENT_ORDER, "data": []}
    pivot = filtered.groupby(["cat", "sentiment"]).size().unstack(fill_value=0)
    for sentiment in SENTIMENT_ORDER:
        if sentiment not in pivot.columns:
            pivot[sentiment] = 0
    pivot = pivot[SENTIMENT_ORDER]
    result = []
    for cat in pivot.index:
        row = {sentiment: int(pivot.loc[cat, sentiment]) for sentiment in SENTIMENT_ORDER}
        result.append({"category": str(cat), "total": int(sum(row.values())), **row})
    result.sort(key=lambda item: item["total"], reverse=True)
    return {"sentiments": SENTIMENT_ORDER, "data": result}


@app.get("/api/system-status")
def system_status() -> dict[str, Any]:
    duckdb_read_only_available = False
    try:
        conn = open_duckdb_read_only()
        if conn is not None:
            duckdb_read_only_available = True
            conn.close()
    except Exception as exc:  # pragma: no cover - depends on local db state.
        logger.warning("DuckDB read-only check failed: %s", exc)

    return {
        "status": "degraded" if llm_status["degraded"] or data_metadata["data_degraded"] else "ok",
        "llm": llm_status,
        "data": {
            "data_degraded": data_metadata["data_degraded"],
            "source": data_metadata["selected_source"],
            "rows": data_metadata["rows"],
            "categories": data_metadata["categories"],
            "fallback_reason": data_metadata["fallback_reason"],
            "warnings": data_metadata["warnings"],
        },
        "storage": {
            "duckdb_dependency_installed": duckdb is not None,
            "duckdb_path_exists": DUCKDB_PATH.exists(),
            "duckdb_read_only_available": duckdb_read_only_available,
            "read_only_strategy": "duckdb.connect(database='data/analytics.db', read_only=True)",
        },
    }


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "message": "服务运行正常",
        "data_source": data_metadata["selected_source"],
        "rows": data_metadata["rows"],
        "categories": data_metadata["categories"],
        "fallback_reason": data_metadata["fallback_reason"],
        "system_status": "degraded" if llm_status["degraded"] or data_metadata["data_degraded"] else "ok",
    }


@app.get("/api/stats")
def get_stats(
    cat: str | None = None,
    sentiment: str | None = None,
    query: str | None = None,
    ids: str | None = None,
) -> dict[str, Any]:
    filtered, query_mode = filter_data(cat=cat, sentiment=sentiment, query=query, ids=ids)
    return {
        "filters": {
            "cat": cat,
            "sentiment": sentiment,
            "query": query,
            "ids_count": len(parse_ids(ids) or []),
            "query_mode": query_mode,
        },
        "rows": int(len(filtered)),
        "category_distribution": category_distribution(filtered),
        "sentiment_overview": sentiment_distribution(filtered),
    }


@app.get("/api/category-distribution")
def get_category_distribution(
    cat: str | None = None,
    sentiment: str | None = None,
    query: str | None = None,
    ids: str | None = None,
) -> dict[str, Any]:
    filtered, query_mode = filter_data(cat=cat, sentiment=sentiment, query=query, ids=ids)
    result = category_distribution(filtered)
    result["source"] = data_metadata["selected_source"]
    result["query_mode"] = query_mode
    return result


@app.get("/api/sentiment-overview")
def get_sentiment_overview(
    cat: str | None = None,
    sentiment: str | None = None,
    query: str | None = None,
    ids: str | None = None,
) -> dict[str, Any]:
    filtered, query_mode = filter_data(cat=cat, sentiment=sentiment, query=query, ids=ids)
    result = sentiment_distribution(filtered)
    result["source"] = data_metadata["selected_source"]
    result["query_mode"] = query_mode
    return result


@app.get("/api/reviews")
def get_reviews(
    cat: str | None = Query(default=None, description="商品品类，如 手机、书籍"),
    sentiment: str | None = Query(default=None, description="情感筛选，如 正面、负面"),
    query: str | None = Query(default=None, description="正则或普通关键词"),
    ids: str | None = Query(default=None, description="Brush 框选得到的 source_index 逗号列表"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    filtered, query_mode = filter_data(cat=cat, sentiment=sentiment, query=query, ids=ids)
    cols = ["source_index", "cat", "label", "sentiment", "review", "review_length", "summary", "category"]
    records = filtered.head(limit)[cols].to_dict(orient="records")
    return {
        "total": int(len(filtered)),
        "limit": int(limit),
        "query_mode": query_mode,
        "data": records,
    }


@app.get("/api/scatter-points")
def get_scatter_points(
    cat: str | None = None,
    sentiment: str | None = None,
    query: str | None = None,
    limit: int = Query(default=700, ge=50, le=1500),
) -> dict[str, Any]:
    filtered, query_mode = filter_data(cat=cat, sentiment=sentiment, query=query)
    if len(filtered) > limit:
        step = max(1, math.ceil(len(filtered) / limit))
        sampled = filtered.iloc[::step].head(limit)
    else:
        sampled = filtered

    points = []
    for _, row in sampled.iterrows():
        jitter = ((int(row["source_index"]) % 17) - 8) * 0.015
        y = float(row["sentiment_score"]) + jitter
        points.append(
            {
                "source_index": int(row["source_index"]),
                "cat": row["cat"],
                "sentiment": row["sentiment"],
                "review_length": int(row["review_length"]),
                "value": [int(row["review_length"]), round(y, 3), int(row["source_index"])],
                "review": row["review"][:120],
            }
        )
    return {
        "total": int(len(filtered)),
        "sampled": int(len(points)),
        "query_mode": query_mode,
        "data": points,
    }


app.mount("/", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="frontend")
