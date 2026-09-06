"""Cari & saring bertingkat di katalog — mesinnya, tanpa Streamlit.

Katalog menggambar seluruh research pipeline berurutan. Dengan tiga itu belum
terasa; ia menjadi masalah tepat ketika kontribusi mulai berdatangan, yaitu
tujuan seluruh sistem ini.

Bentuknya: kategori dipilih DULU, nilainya menyusul. Enam kelompok kotak
centang sekaligus akan menenggelamkan katalog yang hendak disaringnya. Dan
karena pilihan dari kategori lain tetap berlaku saat berpindah kategori,
seluruh penyaring aktif harus tercetak terus-menerus — penyaring yang
menyembunyikan baris tanpa terbaca adalah cara tercepat membuat sebuah daftar
terasa rusak.

Seluruh aturannya fungsi MURNI, seperti antrean peninjauan: `search_text` →
`filter` → hitungan hasil. Tampilan hanya merangkainya.
"""
from __future__ import annotations

import pytest

from ui.components import pipeline_catalog as pc


def _group(dataset_type, *, title="", algorithms=("Random Forest",),
           uploaded=False, institution="", year="", short="", paper="",
           file_format=".csv"):
    return {
        "dataset_type": dataset_type,
        "title": title or dataset_type,
        "short": short,
        "paper": paper,
        "institution": institution,
        "year": year,
        "dataset_lines": [f"Format berkas: {file_format} — satu baris per flow"],
        "algorithms": [{"algorithm": a, "uploaded": uploaded, "info": {}}
                       for a in algorithms],
    }


@pytest.fixture
def catalog():
    return [
        _group("HIKARI2021", title="Rayyan (2024) — HIKARI2021",
               algorithms=("Random Forest", "Decision Tree", "SVC"),
               institution="Fakultas Teknik, Universitas Hasanuddin, Gowa",
               year="2024", short="Perbandingan enam algoritma"),
        _group("EVE_SURICATA", title="Niswar dkk. (2026) — EVE",
               algorithms=("XGBoost", "Random Forest"),
               institution="Departemen Informatika, Universitas Hasanuddin",
               year="2026", file_format=".ndjson"),
        _group("uploaded:kampus", title="Contoh (2026) — Trafik Kampus",
               algorithms=("Random Forest", "Decision Tree"), uploaded=True),
    ]


# ── Pencarian ────────────────────────────────────────────────────────────

def test_an_empty_query_hides_nothing(catalog):
    assert pc.filter_catalog(catalog, "") == catalog
    assert pc.filter_catalog(catalog, "   ") == catalog


@pytest.mark.parametrize("query, expected", [
    ("xgboost", ["EVE_SURICATA"]),                       # nama algoritma
    ("HASANUDDIN", ["HIKARI2021", "EVE_SURICATA"]),      # institusi, beda huruf
    ("2024", ["HIKARI2021"]),                            # tahun
    ("trafik kampus", ["uploaded:kampus"]),              # nama beratribusi
    ("enam algoritma", ["HIKARI2021"]),                  # cakupan
    ("tidak ada apa pun", []),
])
def test_the_query_reaches_every_fact_the_row_already_shows(catalog, query,
                                                            expected):
    assert [g["dataset_type"]
            for g in pc.filter_catalog(catalog, query)] == expected


def test_searching_opens_no_file_and_runs_no_query(catalog):
    """Teks cari disusun dari yang SUDAH ada di grup — sebuah pencarian yang
    membaca disk akan membayar ulang setiap ketikan."""
    text = pc.catalog_search_text(catalog[0])

    assert "hikari2021" in text and "random forest" in text
    assert text == text.lower()


# ── Kategori: hanya yang membedakan sesuatu ──────────────────────────────

def test_a_category_with_one_value_is_not_offered():
    """Penyaring dengan satu pilihan tidak menyaring apa pun."""
    same = [_group("A", institution="Universitas Hasanuddin", year="2026"),
            _group("B", institution="Universitas Hasanuddin", year="2026")]
    keys = {c["key"] for c in pc.catalog_categories(same)}

    assert pc.CATEGORY_INSTITUTION not in keys
    assert pc.CATEGORY_YEAR not in keys
    assert pc.CATEGORY_ORIGIN not in keys          # dua-duanya bawaan
    assert pc.CATEGORY_DATASET in keys             # A dan B berbeda


def test_the_offered_categories_follow_the_catalog(catalog):
    keys = [c["key"] for c in pc.catalog_categories(catalog)]

    assert keys == [pc.CATEGORY_ORIGIN, pc.CATEGORY_DATASET,
                    pc.CATEGORY_FORMAT, pc.CATEGORY_ALGORITHM,
                    pc.CATEGORY_INSTITUTION, pc.CATEGORY_YEAR]


def test_each_value_carries_how_many_it_would_show(catalog):
    algorithms = next(c for c in pc.catalog_categories(catalog)
                      if c["key"] == pc.CATEGORY_ALGORITHM)

    assert dict(algorithms["values"])["Random Forest"] == 3
    assert dict(algorithms["values"])["XGBoost"] == 1


def test_an_empty_catalog_offers_nothing():
    assert pc.catalog_categories([]) == []


# ── Yang tidak menyebutkan tetap terlihat ────────────────────────────────

def test_a_group_without_the_fact_gets_its_own_option(catalog):
    """Tanpa pilihan ini, menyaring institusi membuat setiap pipeline
    kontribusi lama lenyap tanpa sebab yang terbaca."""
    values = dict(next(c for c in pc.catalog_categories(catalog)
                       if c["key"] == pc.CATEGORY_INSTITUTION)["values"])

    assert values[pc.UNSPECIFIED] == 1
    assert [g["dataset_type"] for g in
            pc.apply_filters(catalog, {pc.CATEGORY_INSTITUTION:
                                       {pc.UNSPECIFIED}})] == ["uploaded:kampus"]


def test_the_unspecified_option_sorts_last(catalog):
    values = [v for v, _n in next(c for c in pc.catalog_categories(catalog)
                                  if c["key"] == pc.CATEGORY_YEAR)["values"]]

    assert values[-1] == pc.UNSPECIFIED


# ── Nama lembaga, bukan nama kota ────────────────────────────────────────

def test_the_institution_label_finds_the_institution_not_the_city():
    assert pc.institution_label(
        "Program Studi …, Fakultas Teknik, Universitas Hasanuddin, Gowa"
    ) == "Universitas Hasanuddin"


def test_a_parenthetical_note_is_not_part_of_the_name():
    assert pc.institution_label(
        "Departemen Informatika, Universitas Hasanuddin (afiliasi pertama)"
    ) == "Universitas Hasanuddin"


def test_two_affiliations_of_one_institution_become_one_checkbox(catalog):
    """Dua kotak berlabel sama berdampingan tidak dapat dibedakan siapa pun."""
    values = dict(next(c for c in pc.catalog_categories(catalog)
                       if c["key"] == pc.CATEGORY_INSTITUTION)["values"])

    assert values["Universitas Hasanuddin"] == 2


def test_a_value_with_no_institution_word_keeps_its_last_part():
    assert pc.institution_label("Jalan Poros, Gowa") == "Gowa"
    assert pc.institution_label("UNHAS") == "UNHAS"
    assert pc.institution_label("") == ""


# ── Perangkaian: DAN antar kategori, ATAU di dalamnya ────────────────────

def test_two_values_of_one_category_widen_the_result(catalog):
    got = pc.apply_filters(catalog, {pc.CATEGORY_ALGORITHM:
                                     {"XGBoost", "SVC"}})

    assert {g["dataset_type"] for g in got} == {"HIKARI2021", "EVE_SURICATA"}


def test_two_categories_narrow_it(catalog):
    got = pc.apply_filters(catalog, {pc.CATEGORY_ALGORITHM: {"Random Forest"},
                                     pc.CATEGORY_YEAR: {"2026"}})

    assert [g["dataset_type"] for g in got] == ["EVE_SURICATA"]


def test_an_empty_selection_filters_nothing(catalog):
    assert pc.apply_filters(catalog, {pc.CATEGORY_YEAR: set()}) == catalog
    assert pc.apply_filters(catalog, {}) == catalog


def test_search_and_filters_compose(catalog):
    got = pc.apply_filters(pc.filter_catalog(catalog, "hasanuddin"),
                           {pc.CATEGORY_FORMAT: {".ndjson"}})

    assert [g["dataset_type"] for g in got] == ["EVE_SURICATA"]


# ── Penyaring yang tersembunyi tidak boleh ada ───────────────────────────

def test_every_active_filter_is_named(catalog):
    text = pc.active_filter_text({pc.CATEGORY_ORIGIN: {"kontribusi"},
                                  pc.CATEGORY_YEAR: {"2024", "2026"}})

    assert "Asal = kontribusi" in text
    assert "Tahun = 2024, 2026" in text


def test_nothing_active_says_nothing():
    assert pc.active_filter_text({}) == ""
    assert pc.active_filter_text({pc.CATEGORY_YEAR: set()}) == ""


def test_the_unspecified_filter_is_named_in_words():
    assert "tidak disebutkan" in pc.active_filter_text(
        {pc.CATEGORY_INSTITUTION: {pc.UNSPECIFIED}})


@pytest.mark.parametrize("key", [
    "re.cat_search", "re.cat_search_ph", "re.cat_filter_by",
    "re.cat_filter_none", "re.cat_by_origin", "re.cat_by_dataset",
    "re.cat_by_format", "re.cat_by_algorithm", "re.cat_by_institution",
    "re.cat_by_year", "re.cat_origin_builtin", "re.cat_origin_uploaded",
    "re.cat_value_unspecified", "re.cat_active_filters",
    "re.cat_clear_filters", "re.cat_shown", "re.cat_empty_filtered",
])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── Tanpa kueri tambahan ─────────────────────────────────────────────────

def test_the_facts_come_from_the_group_not_a_new_read():
    """Institusi & tahun diambil di dalam `build_catalog`, di tempat atribusi
    grup itu SUDAH dibaca sekali untuk kalimat penjelasannya."""
    import ast
    from pathlib import Path

    source = Path(pc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "catalog_categories")
    body = ast.get_source_segment(source, fn)

    for forbidden in ("attribution_for", "get_connection", "list_registered"):
        assert forbidden not in body, forbidden
