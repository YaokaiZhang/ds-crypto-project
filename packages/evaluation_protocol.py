"""Shared reporting rules for the train/validation-only offline protocol."""

PARTITIONS = ("train", "validation")
DEFAULT_RATIOS = (0.9, 0.1)
PROTOCOL_VERSION = "train-validation-90-10-v1"


def evaluation_policy():
    return {"protocol": PROTOCOL_VERSION, "primary_partition": "validation",
            "primary_metric": "accuracy", "independent_test_set": False,
            "validation_reused_for_model_selection": True,
            "interpretation": "validation performance after model/threshold selection; not an independent test estimate"}


def final_validation_report(metrics):
    return {**evaluation_policy(), "accuracy": metrics["accuracy"],
            "balanced_accuracy": metrics["balanced_accuracy"],
            "rows": metrics["rows"], "label_counts": metrics["label_counts"]}


def normalized_confusion(tn, fp, fn, tp):
    """Rows are actual labels 0/1; columns are predicted labels 0/1."""
    return {"confusion_matrix_labels": [0, 1],
            "confusion_matrix_axes": {"rows": "actual", "columns": "predicted"},
            "confusion_matrix_normalized_by_true_label": [
                [tn / (tn + fp), fp / (tn + fp)] if tn + fp else [None, None],
                [fn / (fn + tp), tp / (fn + tp)] if fn + tp else [None, None]]}
