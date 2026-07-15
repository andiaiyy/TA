"""
Research-source attribution — the SINGLE structured source of truth for the
human-facing *research pipeline* display names and for the reproduced-study
credits (author, title, institution, year, dataset source).

Keyed by ``dataset_type`` (``HIKARI2021`` / ``EVE_SURICATA``) because in this
platform a dataset_type is 1:1 with a reproduced research pipeline.

IMPORTANT — this module holds DISPLAY / ATTRIBUTION TEXT ONLY. It contains no
pipeline_ids, no registry keys, no hyperparameters, no seeds, and nothing that
affects computation. Editing it never changes a metric. It deliberately imports
nothing from ``pipelines`` or ``config.pipeline_registry``, so both the registry
and each pipeline's ``get_info()`` can import it without a circular import.

Adding attribution for a new research pipeline: add one entry here keyed by its
dataset_type. Do NOT scatter these strings across UI/pipeline files — read them
from the helpers below instead.
"""
from __future__ import annotations

# ── Structured attribution, keyed by dataset_type ─────────────────────────
# `display_name` is the label shown in the "Pilih research pipeline" dropdown
# (Opsi B). The nested `pipeline_source` / `dataset_source` / `scope` fields feed
# the read-only "Tentang Research Pipeline" expander. `paper_credit` is the short
# one-line credit reused for the registry / get_info() `paper` field and the PDF.
RESEARCH_ATTRIBUTION: dict[str, dict] = {
    "HIKARI2021": {
        "display_name": "Rayyan (2024) — Klasifikasi Trafik Terenkripsi HIKARI2021",
        "pipeline_source": {
            "type": "Skripsi",
            "authors": "A. Muh. Rayyan Eka Putra (NIM D121 19 1074)",
            "title": (
                "Aplikasi Klasifikasi Machine Learning untuk Mendeteksi "
                "Trafik Malicious di Jaringan Terenkripsi"
            ),
            "institution": (
                "Program Studi Sarjana Teknik Informatika, Fakultas Teknik, "
                "Universitas Hasanuddin, Gowa"
            ),
            "year": "2024",
        },
        # HIKARI's dataset provenance is DISTINCT from the pipeline author.
        "dataset_source": {
            "name": "HIKARI2021 (varian ALLFLOWMETER)",
            "attribution": "Ferriyan (2022)",
            "note": "Sumber DATASET — dibedakan dari sumber pipeline di atas.",
        },
        "scope": (
            "Perbandingan KNN, Random Forest, Decision Tree, Naive Bayes, "
            "SVC, dan Logistic Regression untuk deteksi trafik malicious pada "
            "jaringan terenkripsi."
        ),
        "paper_credit": (
            "Reproduksi skripsi A. Muh. Rayyan Eka Putra (2024), Universitas "
            "Hasanuddin — \"Aplikasi Klasifikasi Machine Learning untuk "
            "Mendeteksi Trafik Malicious di Jaringan Terenkripsi\". Dataset: "
            "HIKARI2021 (varian ALLFLOWMETER), Ferriyan (2022)."
        ),
    },
    "EVE_SURICATA": {
        "display_name": "Niswar dkk. — Feature Engineering Suricata EVE Logs",
        "pipeline_source": {
            "type": "Artikel/preprint (submitted to Elsevier)",
            "authors": (
                "Muhammad Niswar; A. Muh. Rayyan Eka Putra; Iqra Aswad; "
                "M. Fadhlu Rahman F.; Andrey Ferriyan; Shankar Karuppayah; "
                "Achmad Husni Thamrin"
            ),
            "title": (
                "Exploring Metadata-Rich Network Logs: Feature Engineering in "
                "Suricata EVE Logs for Malicious Network Traffic Detection"
            ),
            "institution": (
                "Departemen Informatika, Fakultas Teknik, Universitas "
                "Hasanuddin (afiliasi penulis pertama)"
            ),
            # Publication year NOT yet confirmed — do not invent one.
            # `None` renders as an explicit "belum dikonfirmasi" note in the UI.
            "year": None,
            "year_note": (
                "Tahun terbit BELUM DIKONFIRMASI — mohon dilengkapi penulis."
            ),
        },
        "scope": (
            "Rekayasa fitur pada Suricata EVE log dengan seleksi fitur Mutual "
            "Information (MI), Recursive Feature Elimination (RFE), dan "
            "Principal Component Analysis (PCA) untuk deteksi trafik malicious."
        ),
        "paper_credit": (
            "Reproduksi Niswar dkk. — \"Exploring Metadata-Rich Network Logs: "
            "Feature Engineering in Suricata EVE Logs for Malicious Network "
            "Traffic Detection\" (preprint, submitted to Elsevier). "
            "Tahun terbit belum dikonfirmasi."
        ),
    },
}


def get_research_attribution(dataset_type: str) -> dict:
    """Return the structured attribution entry for a dataset_type, or {}."""
    return RESEARCH_ATTRIBUTION.get(dataset_type, {})


def get_research_display_name(dataset_type: str) -> str:
    """Return the research pipeline display name (Opsi B) for a dataset_type.

    Falls back to the dataset_type itself for any unknown/future type, so the
    UI never crashes on a missing entry.
    """
    entry = RESEARCH_ATTRIBUTION.get(dataset_type)
    return entry["display_name"] if entry else dataset_type


def research_paper_credit(dataset_type: str) -> str:
    """Return the short one-line reproduced-study credit for a dataset_type.

    Used as the `paper` metadata field in the registry and each pipeline's
    ``get_info()`` so the credit lives in exactly one place. Falls back to a
    neutral string for unknown types.
    """
    entry = RESEARCH_ATTRIBUTION.get(dataset_type)
    return entry["paper_credit"] if entry else f"Research pipeline: {dataset_type}"
