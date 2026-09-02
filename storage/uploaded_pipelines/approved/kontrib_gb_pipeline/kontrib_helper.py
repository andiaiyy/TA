"""Berkas pendukung yang bersih — tanpa kelas pipeline (bukan titik masuk)."""
import numpy as np


def pilih_kolom_numerik(df, label_column):
    """Kembalikan matriks fitur numerik dan nama kolomnya."""
    X_df = df.drop(columns=[label_column]).select_dtypes(include=[np.number])
    return X_df.to_numpy(), list(X_df.columns)


def ringkas_kepentingan(feature_names, importances, top_n=20):
    pasangan = sorted(zip(feature_names, importances), key=lambda p: p[1], reverse=True)
    return [{"feature": n, "importance": float(v)} for n, v in pasangan[:top_n]]
