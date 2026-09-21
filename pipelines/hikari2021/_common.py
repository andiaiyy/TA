"""Shared preprocessing for all HIKARI2021 pipelines."""
import numpy as np
import pandas as pd

_DROP_COLS = [
    "Unnamed: 0.1", "Unnamed: 0",
    "uid", "originh", "responh",
    "traffic_category",
]

_LABEL_NAMES = ["Benign", "Malicious"]


def common_preprocess(df: pd.DataFrame, label_col: str):
    """
    Drop artifact columns, separate features/labels, remove non-numeric columns and NaN rows.
    Returns (X, y, feature_names, label_mapping) with reset indices.
    """
    df = df.copy()
    df.drop(columns=[c for c in _DROP_COLS if c in df.columns], inplace=True, errors="ignore")

    y = df[label_col].copy()
    X = df.drop(columns=[label_col])

    non_numeric = X.select_dtypes(exclude=[np.number]).columns.tolist()
    if non_numeric:
        X.drop(columns=non_numeric, inplace=True)

    mask = X.notna().all(axis=1)
    X = X[mask].reset_index(drop=True)
    y = y[mask].reset_index(drop=True)

    return X, y, X.columns.tolist(), {0: "Benign", 1: "Malicious"}
