"""
Tahap 3C — laporan PDF dalam dua bahasa.

Yang paling mudah rusak di sini bukan terjemahannya, melainkan ANGKAnya:
laporan adalah artefak penelitian, dan satu nilai yang bergeser membuat seluruh
berkas tidak dapat dipercaya. Karena itu berkas ini dibuka dengan test kesamaan
angka, baru kemudian test bahasa.

Teks ditangkap saat laporan DIBANGUN (mencegat ``Paragraph`` dan ``Table``),
bukan dengan membaca kembali PDF-nya: membaca PDF memerlukan pustaka tambahan
dan isinya terkompresi.
"""
import re
from pathlib import Path

import pytest

import utils.report_generator as rg
from ui.i18n import CATALOG, untranslated_report
import ui.i18n.core as core

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFUSION = [[1200, 45], [80, 675]]
METRICS = {
    "accuracy": 0.9384, "precision": 0.9375, "recall": 0.8940,
    "f1_score": 0.9152, "roc_auc": 0.9712,
    "confusion_matrix": CONFUSION,
    "roc_curve": {"fpr": [0.0, 0.1, 1.0], "tpr": [0.0, 0.8, 1.0]},
    "per_class": {
        "0": {"precision": 0.94, "recall": 0.96, "f1-score": 0.95,
              "support": 1245},
        "1": {"precision": 0.94, "recall": 0.89, "f1-score": 0.92,
              "support": 755}},
}

_TAG = re.compile(r"<[^>]+>")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")


def _case(exp_id, pipeline, dtype, *, fi=None, lc=None, mode="official",
          overrides=None):
    metrics = dict(METRICS)
    if fi is not None:
        metrics["feature_importance"] = fi
    if lc is not None:
        metrics["learning_curve"] = lc
    meta = {"run_mode": mode}
    if overrides:
        meta["param_overrides"] = overrides
    return dict(
        experiment_id=exp_id, dataset_type=dtype,
        dataset_path=f"storage/datasets/{dtype}.csv",
        dataset_hash="a" * 64, pipeline_id=pipeline,
        pipeline_info={"paper": "Rayyan (2024)", "algorithm": "Decision Tree"},
        metrics=metrics, metadata=meta,
        label_mapping={"0": "Benign", "1": "Attack"},
    )


#: Empat eksperimen yang BERBEDA KARAKTER — dengan & tanpa kepentingan fitur,
#: kedua keluarga pipeline, mode resmi & eksplorasi.
CASES = {
    "hikari_resmi_dengan_fi": _case(
        "exp-001", "hikari2021.dt_pipeline", "HIKARI2021",
        fi=[{"feature": "flow_duration", "importance": 0.31},
            {"feature": "fwd_pkts_tot", "importance": 0.22}],
        lc={"train_sizes": [100, 500, 1000],
            "train_scores_mean": [0.99, 0.97, 0.96],
            "test_scores_mean": [0.80, 0.88, 0.91]}),
    "hikari_eksplorasi": _case(
        "exp-002", "hikari2021.dt_pipeline", "HIKARI2021",
        mode="exploration", overrides={"max_depth": 12}),
    "eve_tanpa_fi": _case("exp-003", "eve_cbr.cbr_pipeline", "EVE_SURICATA"),
    "hikari_tanpa_lc": _case("exp-004", "hikari2021.knn_pipeline", "HIKARI2021"),
}


def _capture(kw):
    """(teks, angka) sebuah laporan, ditangkap saat dibangun."""
    texts: list[str] = []
    real_paragraph, real_table = rg.Paragraph, rg.Table

    def spy_paragraph(text="", *a, **k):
        texts.append(str(text))
        return real_paragraph(text, *a, **k)

    def spy_table(data=None, *a, **k):
        for row in data or []:
            for cell in row:
                if isinstance(cell, str):
                    texts.append(cell)
        return real_table(data, *a, **k)

    rg.Paragraph, rg.Table = spy_paragraph, spy_table
    try:
        rg.generate_report(**kw)
    finally:
        rg.Paragraph, rg.Table = real_paragraph, real_table

    clean = [_STAMP.sub("<WAKTU>", _TAG.sub("", x)).strip() for x in texts]
    clean = [c for c in clean if c]
    numbers: list[str] = []
    for line in clean:
        numbers.extend(re.findall(r"\d+[.,]\d+|\d+", _STAMP.sub("", line)))
    return clean, numbers


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── ANGKA tidak berubah ──────────────────────────────────────────────────

@pytest.mark.parametrize("case", sorted(CASES))
def test_the_numbers_are_identical_in_both_languages(case):
    """Bahasa mengubah KALIMAT, tidak pernah satu angka pun.

    Ini test terpenting berkas ini: laporan adalah artefak penelitian, dan satu
    nilai yang bergeser membuat seluruhnya tidak dapat dipercaya.
    """
    core.st.session_state[core.LANG_KEY] = "id"
    _, indonesian_numbers = _capture(CASES[case])
    core.st.session_state[core.LANG_KEY] = "en"
    _, english_numbers = _capture(CASES[case])

    assert indonesian_numbers == english_numbers, case


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_report_structure_does_not_change_with_the_language(case):
    """Jumlah blok teks sama — urutan & jumlah bagian tidak bergeser."""
    core.st.session_state[core.LANG_KEY] = "id"
    indonesian_texts, _ = _capture(CASES[case])
    core.st.session_state[core.LANG_KEY] = "en"
    english_texts, _ = _capture(CASES[case])

    assert len(indonesian_texts) == len(english_texts), case


# ── Terbentuk pada kedua bahasa, semua karakter ──────────────────────────

@pytest.mark.parametrize("lang", ["id", "en"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_the_report_builds_for_every_character(case, lang):
    """Termasuk kasus khusus: tanpa kepentingan fitur, tanpa kurva belajar."""
    core.st.session_state[core.LANG_KEY] = lang
    pdf = rg.generate_report(**CASES[case])
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 1000, (case, lang)
    assert pdf[:4] == b"%PDF"


# ── Bahasa DICATAT pada laporannya sendiri ───────────────────────────────

@pytest.mark.parametrize("lang,expected", [("id", "Indonesia"),
                                           ("en", "English")])
def test_the_report_records_its_own_language(lang, expected):
    core.st.session_state[core.LANG_KEY] = lang
    texts, _ = _capture(CASES["hikari_eksplorasi"])
    assert expected in texts


def test_the_language_is_fixed_once_per_report():
    """Satu laporan tidak boleh separuh Indonesia separuh Inggris.

    Bahasanya dibaca SEKALI ke dalam `ctx`; membacanya berulang saat menggambar
    akan membuat laporan berubah di tengah bila pengguna mengganti bahasa.
    """
    src = (REPO_ROOT / "utils" / "report_generator.py").read_text(encoding="utf-8")
    assert 'ctx["lang"] = current_lang()' in src
    assert src.count("current_lang()") == 1


# ── Judul & kepala mengikuti bahasa ──────────────────────────────────────

def test_the_title_and_section_headings_follow_the_language():
    core.st.session_state[core.LANG_KEY] = "id"
    indonesian, _ = _capture(CASES["hikari_resmi_dengan_fi"])
    core.st.session_state[core.LANG_KEY] = "en"
    english, _ = _capture(CASES["hikari_resmi_dengan_fi"])

    assert "Laporan Eksperimen Deteksi Intrusi" in indonesian
    assert "Intrusion Detection Experiment Report" in english
    # Judul bagian ikut (nomornya ditambahkan penyaji, jadi dicari sebagian).
    assert any("Konfigurasi Eksperimen" in x for x in indonesian)
    assert any("Experiment Configuration" in x for x in english)


# ── Yang TIDAK diterjemahkan ─────────────────────────────────────────────

@pytest.mark.parametrize("lang", ["id", "en"])
def test_technical_names_are_never_translated(lang):
    """Nama pipeline, atribusi, istilah metrik, dan hash tetap sama."""
    core.st.session_state[core.LANG_KEY] = lang
    texts, _ = _capture(CASES["hikari_resmi_dengan_fi"])
    joined = " ".join(texts)

    assert "hikari2021.dt_pipeline" in joined      # identitas pipeline
    assert "Rayyan (2024)" in joined               # atribusi penelitian
    assert "HIKARI2021" in joined                  # nama dataset
    assert "a" * 64 in joined or "a" * 12 in joined  # hash dataset
    # Nama teknis pada kepala laporan sengaja tetap.
    assert "Experiment ID" in texts
    assert "Pipeline" in texts


@pytest.mark.parametrize("lang", ["id", "en"])
def test_metric_terms_are_never_translated(lang):
    core.st.session_state[core.LANG_KEY] = lang
    texts, _ = _capture(CASES["hikari_resmi_dengan_fi"])
    joined = " ".join(texts).lower()
    for term in ("accuracy", "precision", "recall"):
        assert term in joined, (lang, term)


# ── Keterangan WAJIB ─────────────────────────────────────────────────────

def test_the_exploration_warning_keeps_its_meaning():
    """Penanda run eksplorasi tidak boleh melemah."""
    for lang, ideas in (("id", ["diubah", "terkunci", "tidak", "replikasi"]),
                        ("en", ["changed", "locked", "not", "replicating"])):
        text = CATALOG["rpt.exploration_warning"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


def test_the_exploration_report_is_flagged_on_the_first_page():
    """Laporan bisa beredar terpisah — penandanya harus terbaca lebih dulu."""
    for lang, badge in (("id", "Run eksplorasi."), ("en", "Exploration run.")):
        core.st.session_state[core.LANG_KEY] = lang
        texts, _ = _capture(CASES["hikari_eksplorasi"])
        assert any(badge in x for x in texts[:20]), lang


def test_an_official_report_is_not_flagged_as_exploration():
    """Kondisi pemicunya tidak bergeser."""
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        texts, _ = _capture(CASES["hikari_resmi_dengan_fi"])
        joined = " ".join(texts).lower()
        assert "run eksplorasi." not in joined
        assert "exploration run." not in joined


def test_reproducibility_is_spelled_the_same_in_both_languages():
    """Istilah baku dalam penulisan ilmiah Indonesia di bidang ini.

    Padanan seperti "keterulangan" justru lebih sulit dikenali pembacanya, jadi
    istilah aslinya dipertahankan — bukan padanan yang maknanya bergeser.
    """
    entry = CATALOG["rpt.sec_reproducibility"]
    assert entry["id"] == entry["en"] == "Reproducibility"


# ── Kamus ────────────────────────────────────────────────────────────────

def test_the_catalog_stays_complete():
    report = untranslated_report()
    assert report["id"]["missing"] == []
    assert report["en"]["missing"] == []


# ═══════════════════════════════════════════════════════════════════════
# TAHAP 4C — isi bagian laporan
# ═══════════════════════════════════════════════════════════════════════

def test_no_raw_key_ever_reaches_the_report():
    """Kunci mentah di laporan = cacat, bukan sekadar belum diterjemahkan.

    Ini penjaga atas kekeliruan nyata: fungsi verdict diubah agar
    mengembalikan KUNCI, dan sempat ada titik pemanggil yang masih mencetaknya
    apa adanya.
    """
    for case in CASES:
        for lang in ("id", "en"):
            core.st.session_state[core.LANG_KEY] = lang
            texts, _ = _capture(CASES[case])
            for line in texts:
                assert "vd." not in line, (case, lang, line[:60])
                assert "rpt." not in line, (case, lang, line[:60])


def test_the_verdict_thresholds_are_untouched():
    """AMBANGNYA keputusan; hanya kalimatnya yang berbahasa."""
    assert rg._recall_verdict(0.96)[1] == "vd.excellent"
    assert rg._recall_verdict(0.90)[1] == "vd.good"
    assert rg._recall_verdict(0.70)[1] == "vd.attention"
    assert rg._recall_verdict(0.10)[1] == "vd.weak"
    assert rg._recall_verdict(None)[1] == "vd.unavailable"
    # Batasnya persis di 0.95 / 0.85 / 0.60 seperti semula.
    assert rg._recall_verdict(0.95)[1] == "vd.excellent"
    assert rg._recall_verdict(0.85)[1] == "vd.good"
    assert rg._recall_verdict(0.60)[1] == "vd.attention"


def test_every_verdict_key_exists_in_the_catalog():
    for fn in (rg._recall_verdict, rg._precision_verdict, rg._f1_verdict,
               rg._auc_verdict):
        for value in (None, 0.99, 0.88, 0.65, 0.10):
            _colour, label, clause = fn(value)
            assert label in CATALOG, (fn.__name__, label)
            if clause:
                assert clause in CATALOG, (fn.__name__, clause)


# ── Keterangan WAJIB ─────────────────────────────────────────────────────

def test_the_metric_semantics_footnote_keeps_both_halves():
    """Harus menyatakan metrik mana DAN bahwa keduanya bukan hal yang sama."""
    for lang, hikari, eve in (
            ("id", ["rata-rata berbobot", "bukan"], ["kelas attack", "bukan"]),
            ("en", ["weighted average", "not"], ["attack-class", "not"])):
        h = CATALOG["rpt.foot_metric_hikari"][lang].lower()
        e = CATALOG["rpt.foot_metric_eve"][lang].lower()
        for idea in hikari:
            assert idea.lower() in h, (lang, "hikari", idea)
        for idea in eve:
            assert idea.lower() in e, (lang, "eve", idea)


def test_the_missed_attack_quadrant_is_never_softened():
    """"Lolos" berarti TIDAK terdeteksi sama sekali — bukan "salah klasifikasi"."""
    for lang, ideas in (("id", ["tidak terdeteksi", "paling kritis"]),
                        ("en", ["undetected", "most critical"])):
        text = CATALOG["rpt.quad_fn_note"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


def test_the_false_alarm_quadrant_names_its_cost():
    for lang, idea in (("id", "alert fatigue"), ("en", "alert fatigue")):
        assert idea in CATALOG["rpt.quad_fp_note"][lang].lower(), lang


def test_the_reproducibility_seed_is_read_from_recorded_params():
    """Menuliskan "42" apa adanya akan berbohong pada run eksplorasi."""
    src = (REPO_ROOT / "utils" / "report_generator.py").read_text(encoding="utf-8")
    body = src.split("def _section_8_reproducibility(")[1].split("\ndef ")[0]
    assert 'ctx["params_used"]' in body
    assert "random_state" in body
    # Nilainya masuk sebagai sisipan, bukan tertulis di dalam kalimat.
    assert 'seed=seed' in body or "seed=42" in body
    for key in ("rpt.seed_locked", "rpt.seed_adjusted"):
        for lang in ("id", "en"):
            assert "{seed}" in CATALOG[key][lang], (key, lang)


def test_an_exploration_seed_is_reported_as_adjusted():
    """Run eksplorasi yang mengubah seed harus terbaca begitu."""
    kw = dict(CASES["hikari_eksplorasi"])
    kw["metadata"] = dict(kw["metadata"],
                          params_used={"random_state": 7},
                          params_changed=["random_state"],
                          params_locked={"random_state": 42})
    for lang, marker in (("id", "disesuaikan"), ("en", "adjusted")):
        core.st.session_state[core.LANG_KEY] = lang
        texts, _ = _capture(kw)
        joined = " ".join(texts)
        assert "7" in joined, lang
        assert marker in joined.lower(), lang


def test_the_reproducibility_table_keeps_its_technical_labels():
    """Nama pustaka & platform adalah nilai teknis — tidak diterjemahkan."""
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        texts, _ = _capture(CASES["hikari_resmi_dengan_fi"])
        for label in ("Dataset SHA-256", "Python", "scikit-learn", "Platform"):
            assert label in texts, (lang, label)
