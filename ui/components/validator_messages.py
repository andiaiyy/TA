"""
Menyusun KALIMAT dari keputusan validator & diagnosa.

**Inilah pemisahan yang diminta Tahap 3.** Modul validator dan diagnosa berada
di ``orchestrator/`` dan tidak boleh bergantung pada Streamlit atau pada bahasa
antarmuka — keduanya menghasilkan KEPUTUSAN: status lolos/gagal/peringatan, nama
pemeriksaan, nomor baris, nama modul yang terdeteksi. Modul ini, yang hidup di
lapisan tampilan, mengubah keputusan itu menjadi kalimat pada bahasa aktif.

Tiga hal yang dijaga bentuk ini:

* **Keputusan tidak tersentuh.** ``name``, ``status``, dan ``line`` dibaca apa
  adanya; modul ini tidak pernah memutuskan apa pun.
* **Alasan penolakan tetap SPESIFIK.** Nama modul/pemanggilan yang terdeteksi
  dan nomor barisnya ikut sebagai nilai sisipan, jadi kalimatnya tidak mungkin
  menyusut menjadi "kode tidak aman" pada bahasa mana pun.
* **Nilai sisipan tidak diterjemahkan.** ``subprocess`` tetap ``subprocess``,
  baris 12 tetap 12. Yang berbahasa hanya kalimat pembungkusnya.

Bila sebuah pemeriksaan belum punya ``key`` (mis. pemeriksaan lama yang belum
disentuh), ``message`` bahasa Indonesianya dipakai apa adanya — antarmuka tetap
terbaca, tidak pernah kosong.
"""
from __future__ import annotations

from ui.i18n import t
from ui.i18n.core import CATALOG, current_lang

#: Sebab larangan → padanan Inggrisnya.
#:
#: Sebab ini datang dari tabel ``FORBIDDEN_MODULES`` / ``FORBIDDEN_CALLS`` milik
#: validator. KUNCI tabel itu (nama modul, nama fungsi) adalah KEPUTUSAN dan
#: tidak boleh disentuh; NILAInya hanyalah kalimat penjelas, jadi ia yang
#: diterjemahkan di sini — di lapisan tampilan, bukan di validator.
#:
#: Tanpa ini, kalimat Inggris akan berbunyi "is not allowed (menjalankan proses
#: lain)": separuh Inggris, separuh Indonesia, dan alasannya berhenti spesifik
#: bagi pembaca Inggris.
REASON_EN: dict[str, str] = {
    # Modul
    "akses sistem berkas & proses": "file-system and process access",
    "akses interpreter & manipulasi path/modul":
        "interpreter access and path/module manipulation",
    "menjalankan proses lain": "runs another process",
    "koneksi jaringan mentah": "raw network connections",
    "operasi berkas destruktif (copy/move/rmtree)":
        "destructive file operations (copy/move/rmtree)",
    "koneksi jaringan keluar": "outbound network connections",
    "pengiriman email": "sending email",
    "deserialisasi objek arbitrer (eksekusi kode)":
        "deserialising arbitrary objects (code execution)",
    "deserialisasi objek arbitrer": "deserialising arbitrary objects",
    "pemanggilan kode native": "calling native code",
    "memuat modul secara dinamis": "loading modules dynamically",
    "menjalankan modul lain": "running another module",
    "membuka terminal semu": "opening a pseudo-terminal",
    "mengirim sinyal ke proses": "sending signals to processes",
    "mengubah batas sumber daya proses": "changing process resource limits",
    "akses langsung ke builtins": "direct access to builtins",
    # Pemanggilan
    "mengeksekusi ekspresi arbitrer": "executes an arbitrary expression",
    "mengeksekusi kode arbitrer": "executes arbitrary code",
    "mengompilasi kode arbitrer": "compiles arbitrary code",
    "membuka namespace global": "exposes the global namespace",
    "membuka namespace lokal": "exposes the local namespace",
    "membuka namespace objek": "exposes an object's namespace",
    "menghentikan eksekusi ke debugger": "drops execution into a debugger",
    "meminta masukan interaktif (menggantung worker)":
        "asks for interactive input (hangs the worker)",
}


def reason_text(reason: str) -> str:
    """Sebab larangan pada bahasa aktif; tidak dikenal → apa adanya."""
    if current_lang() == "id":
        return reason
    return REASON_EN.get((reason or "").strip(), reason)


def _resolve(values: dict) -> dict:
    """Sisipan yang isinya POTONGAN katalog ikut diterjemahkan.

    Sebuah nilai boleh berupa daftar ``{"key", "values"}`` — dipakai ketika
    satu pesan merangkum beberapa temuan sekaligus (mis. beberapa masalah pada
    signature ``run()``). Menyambung potongan berbahasa Indonesia ke dalam
    kalimat Inggris justru yang harus dicegah, jadi potongannya diterjemahkan
    dulu, satu per satu, dari katalog yang sama.
    """
    out = {}
    for name, value in (values or {}).items():
        if (isinstance(value, (list, tuple)) and value
                and all(isinstance(v, dict) and "key" in v for v in value)):
            out[name] = "; ".join(
                t(v["key"], **(v.get("values") or {})) for v in value)
        else:
            out[name] = value
    return out


def check_message(check) -> str:
    """Kalimat untuk satu ``ValidationCheck``, pada bahasa aktif.

    Menerima objek dataclass maupun bentuk dict (``to_dict()``), karena hasil
    validasi kadang sudah diratakan menjadi JSON sebelum sampai ke tampilan.
    """
    if isinstance(check, dict):
        key = check.get("key") or ""
        values = check.get("values") or {}
        fallback = check.get("message") or ""
    else:
        key = getattr(check, "key", "") or ""
        values = getattr(check, "values", None) or {}
        fallback = getattr(check, "message", "") or ""

    if not key or key not in CATALOG:
        # Belum punya kunci: kalimat Indonesianya tetap dipakai. Lebih baik
        # terbaca dalam satu bahasa daripada kosong.
        return fallback

    # `reason` adalah SATU-SATUNYA nilai sisipan yang berupa kalimat; sisanya
    # (nama modul, nama kelas, nomor baris) adalah pengenal & angka yang memang
    # harus tetap apa adanya.
    if "reason" in values:
        values = dict(values, reason=reason_text(values["reason"]))
    return t(key, **_resolve(values))


#: Nama pemeriksaan yang masih berbahasa → kunci label. Nama aslinya adalah
#: PENGENAL: ia dicocokkan dengan `_CAUSE_PRIORITY` dan `ENTRY_ONLY_CHECKS`,
#: jadi ia tidak pernah berubah — hanya labelnya yang mengikuti bahasa.
CHECK_NAME_KEYS = {
    "sintaks Python": "err.name_python_syntax",
    "penulisan berkas": "err.name_file_write",
}


def check_name(check) -> str:
    """Nama pemeriksaan pada bahasa aktif; tanpa kunci → namanya apa adanya."""
    name = (check.get("name") if isinstance(check, dict)
            else getattr(check, "name", "")) or ""
    key = CHECK_NAME_KEYS.get(name)
    return t(key) if key else name


def check_messages(checks) -> list[str]:
    """Kalimat untuk sederet pemeriksaan, urut sama dengan masukannya."""
    return [check_message(c) for c in (checks or [])]


# ── Diagnosa kecocokan dataset ───────────────────────────────────────────
#
# `key` pada DiagnosticCheck ("format", "label", …) adalah PENGENAL keputusan —
# dipakai untuk mencocokkan dan mengurutkan pemeriksaan, jadi ia tidak pernah
# diterjemahkan. Judul yang tampil dipetakan darinya di sini.

DIAGNOSTIC_TITLE_KEYS = {
    "format": "dx.title_format",
    "label": "dx.title_label",
    "features": "dx.title_features",
    "dtype": "dx.title_dtype",
    "classes": "dx.title_classes",
}


def diagnostic_title(check) -> str:
    """Judul pemeriksaan diagnosa pada bahasa aktif."""
    if isinstance(check, dict):
        key, fallback = check.get("key") or "", check.get("title") or ""
    else:
        key = getattr(check, "key", "") or ""
        fallback = getattr(check, "title", "") or ""
    catalog_key = DIAGNOSTIC_TITLE_KEYS.get(key)
    return t(catalog_key) if catalog_key else fallback


def diagnostic_message(check) -> str:
    """Kalimat diagnosa pada bahasa aktif; tanpa kunci → kalimat aslinya."""
    if isinstance(check, dict):
        key = check.get("msg_key") or ""
        values = check.get("values") or {}
        fallback = check.get("message") or ""
    else:
        key = getattr(check, "msg_key", "") or ""
        values = getattr(check, "values", None) or {}
        fallback = getattr(check, "message", "") or ""

    if not key or key not in CATALOG:
        return fallback
    return t(key, **values)


# ── Mode eksekusi ────────────────────────────────────────────────────────
#
# Konstanta di ``orchestrator/run_mode`` tetap apa adanya — ia lapisan logika
# dan tidak boleh tahu soal bahasa. Pemetaan ke kamus dilakukan di sini.

_MODE_KEYS = {
    "official": ("mode.official_label", "mode.official_badge",
                 "mode.official_hint"),
    "exploration": ("mode.exploration_label", "mode.exploration_badge",
                    "mode.exploration_hint"),
}


def run_mode_label(mode: str) -> str:
    """Nama mode eksekusi pada bahasa aktif."""
    keys = _MODE_KEYS.get(mode)
    return t(keys[0]) if keys else (mode or "")


def run_mode_badge_text(mode: str) -> str:
    """Lencana mode — pendek, dipakai di sel tabel & ekspor."""
    keys = _MODE_KEYS.get(mode)
    return t(keys[1]) if keys else (mode or "")


def run_mode_hint(mode: str) -> str:
    """Satu baris penjelas mode eksekusi."""
    keys = _MODE_KEYS.get(mode)
    return t(keys[2]) if keys else ""


# ── Pesan kesalahan pada jalur galat ─────────────────────────────────────
#
# Pengecualian yang tampil ke pengguna membawa `key` + `values` (lihat
# ``orchestrator.user_errors.UserFacingMixin``). Yang TIDAK punya kunci — dan
# itu termasuk seluruh pengecualian internal — tetap ditampilkan lewat
# `str(exc)` apa adanya. Tidak ada jalur yang menjadi diam.

def error_message(exc) -> str:
    """Kalimat kesalahan pada bahasa aktif; tanpa kunci → teks aslinya.

    Dipakai lapisan tampilan menggantikan ``str(e)``. Bila pengecualiannya
    belum diberi kunci, hasilnya IDENTIK dengan sebelumnya — itulah yang
    membuat penggantian ini aman di jalur galat.
    """
    key = getattr(exc, "key", "") or ""
    values = getattr(exc, "values", None) or {}
    if not key or key not in CATALOG:
        return str(exc)
    return t(key, **values)


def stored_error_message(text: str) -> str:
    """Pesan kegagalan yang TERSIMPAN pada catatan eksperimen.

    Dikembalikan apa adanya, TIDAK PERNAH diterjemahkan. Catatan lama adalah
    rekaman apa yang benar-benar terjadi saat itu; menerjemahkannya ulang
    berarti menulis ulang riwayat, dan pesan itu mungkin dibuat oleh versi
    platform yang kalimatnya sudah berbeda.

    Fungsi ini sengaja ada meski isinya sepele: ia menandai di kode mana yang
    pesan BARU (lewat :func:`error_message`) dan mana yang pesan TERSIMPAN.
    """
    return text or ""
