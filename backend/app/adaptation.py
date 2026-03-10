from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import numpy as np

from .hashing import normalize_title

ADAPTIVE_SCORE_WEIGHTS = {
    "base": 0.55,
    "fingerprint": 0.20,
    "template": 0.10,
    "category": 0.07,
    "confidence": 0.05,
    "evidence": 0.03,
}
RIDGE_ALPHA = 0.75
CONFIDENCE_SIGNAL_WEIGHTS = {
    "fingerprint": 0.20,
    "template": 0.10,
    "category": 0.05,
    "confidence": 0.15,
}
FEATURE_STAT_TYPES = (
    "fingerprint",
    "title_template",
    "category",
    "delivery_mode",
    "confidence_bucket",
    "evidence_signature",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def severity_weight(value: str) -> int:
    if value == "critical":
        return 5
    if value == "high":
        return 4
    if value == "medium":
        return 3
    if value == "low":
        return 2
    return 1


def smoothed_utility(up_count: int, down_count: int) -> float:
    total = up_count + down_count
    if total < 0:
        total = 0
    return float(2.0 * ((up_count + 1.0) / (total + 2.0)) - 1.0)


def confidence_bucket(value: float) -> str:
    clipped = max(0.0, min(0.999, float(value)))
    lower = int(clipped * 10) / 10
    upper = lower + 0.1
    return f"{lower:.1f}-{min(1.0, upper):.1f}"


def evidence_signature(evidence: list[dict[str, Any]] | None) -> str:
    if not evidence:
        return "none"
    types = sorted({str(item.get("type") or "").strip() for item in evidence if str(item.get("type") or "").strip()})
    if not types:
        return "none"
    return "+".join(types)


def title_template(category: str, title: str) -> str:
    return f"{category}:{normalize_title(title)}"


def category_key(category: str, severity: str, language: str) -> str:
    return f"{category}|{severity}|{language}"


def build_feature_stat(key_type: str, key_value: str) -> dict[str, Any]:
    return {
        "keyType": key_type,
        "keyValue": key_value,
        "upCount": 0,
        "downCount": 0,
        "voteCount": 0,
        "score": 0,
        "smoothedUtility": 0.0,
        "updatedAt": now_iso(),
    }


def add_vote_counts(target: dict[str, Any], up_count: int, down_count: int) -> None:
    target["upCount"] += up_count
    target["downCount"] += down_count
    target["voteCount"] += up_count + down_count
    target["score"] += up_count - down_count
    target["smoothedUtility"] = smoothed_utility(target["upCount"], target["downCount"])
    target["updatedAt"] = now_iso()


def vote_totals(votes: list[dict[str, Any]]) -> dict[str, int]:
    up_count = len([item for item in votes if item.get("vote") == "up"])
    down_count = len([item for item in votes if item.get("vote") == "down"])
    return {
        "up": up_count,
        "down": down_count,
        "score": up_count - down_count,
        "voteCount": up_count + down_count,
    }


def feature_snapshot_from_suggestion(suggestion: dict[str, Any], model_version: str) -> dict[str, Any]:
    suggestion_meta = suggestion.get("meta") or {}
    rank_features = suggestion_meta.get("rankFeatures") or {}
    confidence = float(rank_features.get("confidence", suggestion.get("confidence", 0.0)))
    language = str(rank_features.get("language") or suggestion_meta.get("language") or "unknown")
    file_role = str(rank_features.get("fileRole") or suggestion_meta.get("fileRole") or suggestion_meta.get("fileClass") or "unknown")
    delivery_mode = str(suggestion.get("deliveryMode") or rank_features.get("deliveryMode") or "inline")
    evidence_sig = str(rank_features.get("evidenceSignature") or evidence_signature(suggestion.get("evidence")))
    template = str(rank_features.get("titleTemplate") or title_template(str(suggestion.get("category") or "unknown"), str(suggestion.get("title") or "")))
    return {
        "suggestionId": suggestion["id"],
        "fingerprint": suggestion["fingerprint"],
        "jobId": suggestion["jobId"],
        "prId": suggestion["prId"],
        "snapshotId": suggestion["snapshotId"],
        "modelVersion": model_version,
        "confidence": confidence,
        "rankScore": float(rank_features.get("rankScore", 0.0)),
        "retrievalScore": float(rank_features.get("retrievalScore", 0.0)),
        "plannerPriority": float(rank_features.get("plannerPriority", 0.0)),
        "staticSupport": float(rank_features.get("staticSupport", 0.0)),
        "repoFeedbackScore": float(rank_features.get("repoFeedbackScore", 0.0)),
        "deliveryMode": delivery_mode,
        "category": str(suggestion.get("category") or rank_features.get("category") or "unknown"),
        "severity": str(suggestion.get("severity") or rank_features.get("severity") or "info"),
        "language": language,
        "fileRole": file_role,
        "evidenceSignature": evidence_sig,
        "titleTemplate": template,
        "confidenceBucket": confidence_bucket(confidence),
        "promptContextVersion": str(suggestion_meta.get("promptContextVersion") or "rag-v2"),
        "createdAt": suggestion.get("createdAt") or now_iso(),
    }


def default_model_record() -> dict[str, Any]:
    return {
        "version": "bootstrap",
        "trainedAt": now_iso(),
        "trainingExamples": 0,
        "status": "ACTIVE",
        "weights": {
            "intercept": 0.0,
            "featureNames": [],
            "coefficients": [],
        },
        "metrics": {
            "weightedMae": 0.0,
            "weightedRmse": 0.0,
        },
    }


def build_training_priors(snapshot: dict[str, Any], feature_stats: dict[str, dict[str, dict[str, Any]]]) -> dict[str, float]:
    fingerprint_stat = feature_stats["fingerprint"].get(snapshot["fingerprint"])
    template_stat = feature_stats["title_template"].get(snapshot["titleTemplate"])
    category_stat = feature_stats["category"].get(category_key(snapshot["category"], snapshot["severity"], snapshot["language"]))
    return {
        "fingerprint_prior": float(fingerprint_stat["smoothedUtility"]) if fingerprint_stat else 0.0,
        "template_prior": float(template_stat["smoothedUtility"]) if template_stat else 0.0,
        "category_prior": float(category_stat["smoothedUtility"]) if category_stat else 0.0,
    }


def encode_training_features(snapshot: dict[str, Any], priors: dict[str, float]) -> dict[str, float]:
    encoded: dict[str, float] = {
        "confidence": float(snapshot["confidence"]),
        "rank_score": float(snapshot["rankScore"]),
        "retrieval_score": float(snapshot["retrievalScore"]),
        "planner_priority": float(snapshot["plannerPriority"]),
        "static_support": float(snapshot["staticSupport"]),
        "repo_feedback_score": float(snapshot["repoFeedbackScore"]),
        "fingerprint_prior": float(priors["fingerprint_prior"]),
        "template_prior": float(priors["template_prior"]),
        "category_prior": float(priors["category_prior"]),
    }
    encoded[f"category={snapshot['category']}"] = 1.0
    encoded[f"severity={snapshot['severity']}"] = 1.0
    encoded[f"delivery_mode={snapshot['deliveryMode']}"] = 1.0
    encoded[f"language={snapshot['language']}"] = 1.0
    encoded[f"file_role={snapshot['fileRole']}"] = 1.0
    encoded[f"evidence_signature={snapshot['evidenceSignature']}"] = 1.0
    encoded[f"confidence_bucket={snapshot['confidenceBucket']}"] = 1.0
    return encoded


def train_reward_model(training_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not training_rows:
        return default_model_record()

    feature_names = sorted({name for row in training_rows for name in row["features"].keys()})
    x = np.zeros((len(training_rows), len(feature_names)), dtype=np.float64)
    y = np.zeros(len(training_rows), dtype=np.float64)
    sample_weight = np.ones(len(training_rows), dtype=np.float64)

    feature_index = {name: index for index, name in enumerate(feature_names)}
    for row_index, row in enumerate(training_rows):
        for feature_name, feature_value in row["features"].items():
            x[row_index, feature_index[feature_name]] = float(feature_value)
        y[row_index] = float(row["target"])
        sample_weight[row_index] = max(1.0, float(row["sampleWeight"]))

    design = np.concatenate([np.ones((x.shape[0], 1), dtype=np.float64), x], axis=1)
    regularizer = np.eye(design.shape[1], dtype=np.float64) * RIDGE_ALPHA
    regularizer[0, 0] = 0.0
    weights = np.sqrt(sample_weight)[:, np.newaxis]
    weighted_design = design * weights
    weighted_target = y * weights[:, 0]
    gram = weighted_design.T @ weighted_design + regularizer
    rhs = weighted_design.T @ weighted_target
    coefficients = np.linalg.solve(gram, rhs)
    predictions = design @ coefficients
    residuals = predictions - y
    total_weight = float(np.sum(sample_weight))
    weighted_mae = float(np.sum(np.abs(residuals) * sample_weight) / total_weight)
    weighted_rmse = float(np.sqrt(np.sum((residuals**2) * sample_weight) / total_weight))
    return {
        "version": f"adapt_{uuid4().hex[:12]}",
        "trainedAt": now_iso(),
        "trainingExamples": len(training_rows),
        "status": "ACTIVE",
        "weights": {
            "intercept": float(coefficients[0]),
            "featureNames": feature_names,
            "coefficients": [float(item) for item in coefficients[1:]],
        },
        "metrics": {
            "weightedMae": weighted_mae,
            "weightedRmse": weighted_rmse,
        },
    }


def predict_reward(features: dict[str, float], model_record: dict[str, Any] | None) -> float:
    if not model_record:
        return 0.0
    weights = model_record.get("weights") or {}
    feature_names = list(weights.get("featureNames") or [])
    coefficients = list(weights.get("coefficients") or [])
    if not feature_names or not coefficients:
        return 0.0
    score = float(weights.get("intercept", 0.0))
    for feature_name, coefficient in zip(feature_names, coefficients, strict=False):
        score += float(coefficient) * float(features.get(feature_name, 0.0))
    return float(max(-1.0, min(1.0, score)))


def confidence_calibration(snapshot: dict[str, Any], priors: dict[str, float], model_record: dict[str, Any] | None) -> float:
    if not model_record or model_record.get("trainingExamples", 0) <= 0:
        return 0.0
    features = encode_training_features(snapshot, priors)
    return predict_reward(features, model_record)


def evidence_prior(snapshot: dict[str, Any], feature_stats: dict[str, dict[str, dict[str, Any]]]) -> float:
    stat = feature_stats["evidence_signature"].get(snapshot["evidenceSignature"])
    if not stat:
        return 0.0
    return float(stat["smoothedUtility"])


def adapt_suggestion(
    suggestion: dict[str, Any],
    snapshot: dict[str, Any],
    feature_stats: dict[str, dict[str, dict[str, Any]]],
    model_record: dict[str, Any] | None,
) -> dict[str, Any]:
    priors = build_training_priors(snapshot, feature_stats)
    fingerprint_stat = feature_stats["fingerprint"].get(snapshot["fingerprint"])
    template_stat = feature_stats["title_template"].get(snapshot["titleTemplate"])
    category_prior = priors["category_prior"]
    confidence_prior = confidence_calibration(snapshot, priors, model_record)
    evidence_score = evidence_prior(snapshot, feature_stats)
    base_confidence = float(snapshot["confidence"])
    adaptive_score = (
        ADAPTIVE_SCORE_WEIGHTS["base"] * float(snapshot["rankScore"])
        + ADAPTIVE_SCORE_WEIGHTS["fingerprint"] * priors["fingerprint_prior"]
        + ADAPTIVE_SCORE_WEIGHTS["template"] * priors["template_prior"]
        + ADAPTIVE_SCORE_WEIGHTS["category"] * category_prior
        + ADAPTIVE_SCORE_WEIGHTS["confidence"] * confidence_prior
        + ADAPTIVE_SCORE_WEIGHTS["evidence"] * evidence_score
    )
    adapted_confidence = max(
        0.0,
        min(
            1.0,
            base_confidence
            + CONFIDENCE_SIGNAL_WEIGHTS["fingerprint"] * priors["fingerprint_prior"]
            + CONFIDENCE_SIGNAL_WEIGHTS["template"] * priors["template_prior"]
            + CONFIDENCE_SIGNAL_WEIGHTS["category"] * category_prior
            + CONFIDENCE_SIGNAL_WEIGHTS["confidence"] * confidence_prior,
        ),
    )

    downgraded_by_feedback = bool(
        fingerprint_stat
        and int(fingerprint_stat["voteCount"]) >= 3
        and float(fingerprint_stat["smoothedUtility"]) <= -0.5
    )
    suppressed_by_feedback = bool(
        fingerprint_stat
        and int(fingerprint_stat["voteCount"]) >= 3
        and float(fingerprint_stat["smoothedUtility"]) <= -0.5
    )
    effective_delivery_mode = "summary" if downgraded_by_feedback else str(suggestion.get("deliveryMode") or snapshot["deliveryMode"])
    copied = dict(suggestion)
    copied["deliveryMode"] = effective_delivery_mode
    copied["confidence"] = adapted_confidence
    suggestion_meta = dict(copied.get("meta") or {})
    suggestion_meta["adaptation"] = {
        "baseConfidence": base_confidence,
        "adaptedConfidence": adapted_confidence,
        "baseRankScore": float(snapshot["rankScore"]),
        "adaptiveScore": float(adaptive_score),
        "feedbackPrior": float(priors["fingerprint_prior"]),
        "templatePrior": float(priors["template_prior"]),
        "modelVersion": (model_record or {}).get("version", "bootstrap"),
        "downgradedByFeedback": downgraded_by_feedback,
        "suppressedByFeedback": suppressed_by_feedback,
    }
    if template_stat:
        suggestion_meta["adaptation"]["templateVoteCount"] = int(template_stat["voteCount"])
    copied["meta"] = suggestion_meta
    copied["_adaptiveScore"] = adaptive_score
    copied["_suppressedByFeedback"] = suppressed_by_feedback
    return copied


def rerank_suggestions(
    suggestions: list[dict[str, Any]],
    suggestion_snapshots: dict[str, dict[str, Any]],
    feature_stats: dict[str, dict[str, dict[str, Any]]],
    model_record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    adapted = [
        adapt_suggestion(
            item,
            suggestion_snapshots.get(item["id"]) or feature_snapshot_from_suggestion(item, (model_record or {}).get("version", "bootstrap")),
            feature_stats,
            model_record,
        )
        for item in suggestions
    ]
    visible = [item for item in adapted if not item.get("_suppressedByFeedback", False)]
    ranked = sorted(
        visible,
        key=lambda item: (
            -(1 if item.get("deliveryMode", "inline") == "inline" else 0),
            -float(item.get("_adaptiveScore", 0.0)),
            -severity_weight(str(item.get("severity") or "info")),
            str(item.get("createdAt") or ""),
        ),
    )
    for item in ranked:
        item.pop("_adaptiveScore", None)
        item.pop("_suppressedByFeedback", None)
    return ranked
