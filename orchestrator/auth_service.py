"""
Autentikasi — FASE 1: pengguna, hashing password, login.

Lingkup fase ini sengaja sempit: membuat/memeriksa akun dan memverifikasi
password. Peran (`role`) sudah disimpan tetapi BELUM ditegakkan — izin per aksi
adalah Fase 2, antrean persetujuan Fase 3, registry dinamis Fase 4.

Hashing: ``hashlib.pbkdf2_hmac`` (PBKDF2-HMAC-SHA256) dari pustaka standar,
dengan salt acak 16 byte per pengguna dan 260.000 iterasi. Dipilih karena tidak
menambah dependensi baru (bcrypt/argon2 belum terpasang dan penambahan paket
berarti membangun ulang image Docker), sementara PBKDF2 tetap KDF password yang
diakui NIST. Format simpanan::

    pbkdf2_sha256$<iterasi>$<salt_hex>$<hash_hex>

Verifikasi memakai ``hmac.compare_digest`` (tahan timing attack). Password
mentah TIDAK PERNAH disimpan, dikembalikan, maupun dicatat ke log.

⚠️ IMPORT RESTRICTION: modul orchestrator boleh memakai database/db.py — dan
memang memakai ``get_connection`` di sana (WAL + busy_timeout + retry), bukan
membuat jalur koneksi sendiri.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3

from database.db import _retry_on_locked, get_connection
from database.models import (
    ALL_ROLES, ALL_USER_STATUSES, LEGACY_ROLE_MAP, ROLE_CONTRIBUTOR,
    ROLE_RESEARCH_ADMIN, STATUS_ACTIVE, STATUS_DISABLED, STATUS_PENDING,
    normalize_role, normalize_status, role_label, status_label,
)
from utils.timestamps import now_iso

logger = logging.getLogger(__name__)

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 8

# Env var untuk admin pertama. TIDAK ADA password default di dalam kode.
ADMIN_USERNAME_ENV = "ADMIN_USERNAME"
ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"
DEFAULT_ADMIN_USERNAME = "admin"


class AuthError(ValueError):
    """Kesalahan yang layak ditampilkan ke pengguna (validasi, duplikat)."""


class PermissionDenied(AuthError):
    """Aksi ditolak karena identitas/peran tidak berhak."""


# ── Izin (Fase 2) — SATU tempat, fungsi murni, mudah diuji ────────────────
# Model proteksi: PER-AKSI, bukan per-akses. Membaca hasil dan menjalankan
# eksperimen terbuka untuk semua (termasuk pengunjung / `user is None`). Yang
# dibatasi hanya menambah kode/data dan menyetujuinya.
#
# `user` adalah dict identitas dari session ({"username", "role"}) atau None
# untuk pengunjung. Semua pemeriksaan peran di seluruh platform HARUS lewat
# fungsi-fungsi ini — jangan menulis `if role == "..."` di berkas lain.

def is_logged_in(user: dict | None) -> bool:
    return isinstance(user, dict) and bool(user.get("username"))


def user_status(user: dict | None) -> str | None:
    """Status akun untuk KEPUTUSAN IZIN, atau None bila bukan identitas sah.

    Identitas tanpa status eksplisit dianggap ``active`` — bentuk itu dipakai
    oleh pemanggil lama/uji; status yang TIDAK dikenal justru diperlakukan
    sebagai ``pending`` (nol hak) lewat ``normalize_status``.
    """
    if not is_logged_in(user):
        return None
    raw = user.get("status")
    if raw is None:
        return STATUS_ACTIVE
    return normalize_status(raw)


def is_account_active(user: dict | None) -> bool:
    """Hanya akun berstatus ``active`` yang boleh melakukan aksi berisiko.

    Akun ``pending`` (hasil registrasi mandiri yang belum disetujui) dan
    ``disabled`` setara pengunjung: nol hak.
    """
    return user_status(user) == STATUS_ACTIVE


def user_role(user: dict | None) -> str | None:
    """Peran untuk KEPUTUSAN IZIN, atau None bila tidak berhak apa pun.

    Nama peran lama Fase 1 dipetakan ke nama baru. Peran yang TIDAK dikenal
    tidak pernah diperlakukan sebagai peran valid — identitas dengan role rusak
    diperlakukan setara pengunjung (hak paling kecil), bukan diberi hak
    kontributor. (``models.normalize_role`` yang memberi default kontributor
    hanya untuk penyimpanan/tampilan, bukan untuk izin.)
    """
    if not is_logged_in(user):
        return None
    role = (user.get("role") or "").strip()
    role = LEGACY_ROLE_MAP.get(role, role)
    return role if role in ALL_ROLES else None


def is_research_admin(user: dict | None) -> bool:
    return user_role(user) == ROLE_RESEARCH_ADMIN


def is_contributor(user: dict | None) -> bool:
    return user_role(user) == ROLE_CONTRIBUTOR


def can_upload(user: dict | None) -> bool:
    """Mengunggah dataset ATAU pipeline. Perlu akun AKTIF; kedua peran boleh.

    Akun yang menunggu persetujuan tidak lolos di sini — statusnya diperiksa
    bersama perannya, bukan hanya perannya.
    """
    return (is_account_active(user)
            and user_role(user) in (ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN))


def can_approve(user: dict | None) -> bool:
    """Menyetujui unggahan. Hanya Research Admin yang akun-nya aktif."""
    return is_account_active(user) and is_research_admin(user)


def can_manage_users(user: dict | None) -> bool:
    """Membuat/mengaktifkan/menonaktifkan akun. Hanya Research Admin aktif."""
    return is_account_active(user) and is_research_admin(user)


def can_run_experiment(user: dict | None) -> bool:
    """Menjalankan eksperimen TERBUKA untuk semua, termasuk pengunjung.

    Ada sebagai fungsi eksplisit supaya keputusan ini terbaca di kode (dan
    teruji), bukan tersirat dari ketiadaan pemeriksaan."""
    return True


def can_view_experiments(user: dict | None) -> bool:
    """Melihat eksperimen TERBUKA untuk semua — tidak ada filter kepemilikan."""
    return True


def _fresh_identity(user: dict | None, db_path: str | None = None) -> dict | None:
    """Identitas dengan status & peran TERKINI dari basis data.

    Sesi hanya menyimpan salinan; bila Research Admin menonaktifkan sebuah akun
    di tengah sesi, salinan itu menjadi basi. Penjaga lapis AKSI karena itu
    membaca ulang barisnya — dan baris DB selalu menang. Identitas yang tidak
    punya baris (fixture/uji) dipakai apa adanya.
    """
    if not is_logged_in(user):
        return user
    try:
        row = get_user(user["username"], db_path)
    except Exception:                      # pragma: no cover - DB belum siap
        logger.debug("Status akun tidak dapat diverifikasi ulang", exc_info=True)
        return user
    return row or user


def require_upload(user: dict | None, db_path: str | None = None) -> None:
    """Penjaga untuk fungsi AKSI. Raise PermissionDenied bila tidak berhak.

    Status diverifikasi ulang ke DB, jadi akun `pending`/`disabled` ditolak di
    sini walau sesinya masih menyimpan status lama.
    """
    current = _fresh_identity(user, db_path)
    if not can_upload(current):
        if user_status(current) == STATUS_PENDING:
            raise PermissionDenied(
                "Akun Anda masih menunggu persetujuan Research Admin, jadi "
                "belum dapat mengunggah.")
        raise PermissionDenied(
            "Masuk sebagai Kontributor atau Research Admin untuk mengunggah.")


def require_approve(user: dict | None, db_path: str | None = None) -> None:
    current = _fresh_identity(user, db_path)
    if not can_approve(current):
        raise PermissionDenied("Hanya Research Admin yang dapat menyetujui unggahan.")


def require_manage_users(user: dict | None, db_path: str | None = None) -> None:
    current = _fresh_identity(user, db_path)
    if not can_manage_users(current):
        raise PermissionDenied("Hanya Research Admin yang dapat mengelola pengguna.")


# ── Hashing ───────────────────────────────────────────────────────────────

def hash_password(plain: str, *, iterations: int = _ITERATIONS) -> str:
    """Hash password menjadi string bersalt yang aman disimpan.

    Salt diacak untuk SETIAP pemanggilan, jadi dua pengguna dengan password
    sama tetap menghasilkan hash berbeda.
    """
    if not isinstance(plain, str) or plain == "":
        raise AuthError("Password tidak boleh kosong.")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return f"{_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    """True bila `plain` cocok dengan `hashed`. Tidak pernah raise."""
    try:
        algorithm, iterations, salt_hex, digest_hex = str(hashed).split("$")
        if algorithm != _ALGORITHM:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", (plain or "").encode("utf-8"),
            bytes.fromhex(salt_hex), int(iterations),
        )
    except (ValueError, AttributeError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# ── Query pengguna ────────────────────────────────────────────────────────

def _row_to_user(row) -> dict:
    """Baris DB -> dict pengguna TANPA password_hash (jangan sampai bocor ke UI).

    Peran dinormalisasi supaya baris lama (mis. 'admin' dari Fase 1) tetap
    terbaca benar walau migrasi v5 belum sempat berjalan."""
    user = dict(row)
    user.pop("password_hash", None)
    user["role"] = normalize_role(user.get("role"))
    user["role_label"] = role_label(user["role"])
    user["status"] = normalize_status(user.get("status"))
    # `is_active` dipertahankan demi keaditifan skema dan selalu ditulis
    # bersama `status`. Bila keduanya sempat berbeda (mis. baris ditulis alat
    # lama yang hanya tahu is_active), menangkan yang PALING KECIL haknya.
    if "is_active" in user and not int(user.get("is_active") or 0):
        if user["status"] == STATUS_ACTIVE:
            user["status"] = STATUS_DISABLED
    user["status_label"] = status_label(user["status"])
    return user


def get_user(username: str, db_path: str | None = None) -> dict | None:
    """Pengguna berdasarkan username (tanpa password_hash), atau None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username or "",)
        ).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def list_users(db_path: str | None = None) -> list[dict]:
    """Semua pengguna (tanpa password_hash), diurutkan menurut username."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [_row_to_user(r) for r in rows]
    finally:
        conn.close()


@_retry_on_locked()
def create_user(username: str, password: str, role: str = ROLE_CONTRIBUTOR,
                db_path: str | None = None, *, status: str = STATUS_ACTIVE,
                requested_at: str | None = None, reason: str | None = None) -> dict:
    """Buat akun. Raise AuthError untuk masukan tidak sah atau username ganda.

    Tidak ada registrasi mandiri di platform ini — fungsi ini dipakai oleh
    Research Admin (dan oleh ``ensure_admin_seed``).
    """
    username = (username or "").strip()
    if not username:
        raise AuthError("Username tidak boleh kosong.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password minimal {MIN_PASSWORD_LENGTH} karakter.")
    if role not in ALL_ROLES:
        raise AuthError(f"Role tidak dikenal: {role}")
    if status not in ALL_USER_STATUSES:
        raise AuthError(f"Status tidak dikenal: {status}")

    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO users (username, password_hash, role, created_at,
                                  is_active, status, requested_at, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, hash_password(password), role, now_iso(),
             1 if status == STATUS_ACTIVE else 0, status, requested_at, reason),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise AuthError(f"Username '{username}' sudah dipakai.") from e
    finally:
        conn.close()

    logger.info("User dibuat: %s (role=%s)", username, role)   # tanpa password
    return get_user(username, db_path)


def authenticate(username: str, password: str, db_path: str | None = None) -> dict | None:
    """Kembalikan pengguna bila kredensial benar DAN akun aktif; selain itu None.

    Pemanggil sengaja tidak diberi tahu apakah yang salah username atau
    password — pesan gagal di UI harus tetap generik.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", ((username or "").strip(),)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        # Tetap jalankan satu hashing dummy supaya waktu respons untuk username
        # tidak dikenal mirip dengan yang dikenal (mengurangi kebocoran lewat waktu).
        verify_password(password or "", hash_password("dummy-timing-equaliser"))
        return None
    if not verify_password(password or "", row["password_hash"]):
        return None

    user = _row_to_user(row)
    if user["status"] == STATUS_DISABLED:
        # Akun dinonaktifkan tidak boleh masuk sama sekali. Pemanggil (UI)
        # tetap menampilkan pesan GENERIK — membedakan "dinonaktifkan" dari
        # "password salah" akan membocorkan keberadaan username.
        logger.warning("Login ditolak: akun %s dinonaktifkan", row["username"])
        return None
    # Akun `pending` SENGAJA boleh terautentikasi: pemiliknya perlu melihat
    # bahwa pendaftarannya sedang menunggu. Haknya tetap nol — seluruh
    # can_*/require_* memeriksa status, bukan hanya peran.
    return user


# ── Seed admin pertama ────────────────────────────────────────────────────

# ── Registrasi mandiri ────────────────────────────────────────────────────

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
MAX_REASON_LENGTH = 300


def register_account(username: str, password: str, confirm: str,
                     reason: str | None = None,
                     db_path: str | None = None) -> dict:
    """Pendaftaran mandiri. SELALU menghasilkan akun `contributor` + `pending`.

    Peran TIDAK PERNAH diambil dari masukan pengguna — mendaftar bukan jalan
    memperoleh Research Admin. Akun hasil fungsi ini nol hak sampai Research
    Admin mengaktifkannya.

    Raise AuthError dengan pesan spesifik untuk tiap kesalahan masukan;
    password mentah tidak pernah dicatat ke log.
    """
    username = (username or "").strip()
    if not username:
        raise AuthError("Username tidak boleh kosong.")
    if len(username) < MIN_USERNAME_LENGTH:
        raise AuthError(f"Username minimal {MIN_USERNAME_LENGTH} karakter.")
    if len(username) > MAX_USERNAME_LENGTH:
        raise AuthError(f"Username maksimal {MAX_USERNAME_LENGTH} karakter.")
    if not USERNAME_PATTERN.match(username):
        raise AuthError("Username hanya boleh huruf, angka, titik, garis bawah, "
                        "atau tanda hubung.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password minimal {MIN_PASSWORD_LENGTH} karakter.")
    if (password or "") != (confirm or ""):
        raise AuthError("Konfirmasi password tidak sama.")

    reason = (reason or "").strip()[:MAX_REASON_LENGTH] or None
    # Username ganda memang boleh disebut spesifik di PENDAFTARAN (pemohon
    # perlu tahu harus memilih nama lain); pesan gagal LOGIN tetap generik.
    if get_user(username, db_path) is not None:
        raise AuthError(f"Username '{username}' sudah dipakai.")

    user = create_user(username, password, ROLE_CONTRIBUTOR, db_path,
                       status=STATUS_PENDING, requested_at=now_iso(),
                       reason=reason)
    logger.info("Pendaftaran mandiri: %s (menunggu persetujuan)", username)
    return user


def list_pending_accounts(db_path: str | None = None) -> list[dict]:
    """Akun yang menunggu persetujuan, terlama dulu."""
    return [u for u in list_users(db_path) if u["status"] == STATUS_PENDING]


@_retry_on_locked()
def set_user_status(username: str, status: str, *, actor: dict | None,
                    db_path: str | None = None) -> dict:
    """Ubah status akun (aktifkan / nonaktifkan). Hanya Research Admin.

    Mencatat ``activated_by``/``activated_at`` saat diaktifkan, dan menolak
    Research Admin menonaktifkan dirinya sendiri agar sistem tidak pernah
    terkunci tanpa admin aktif.
    """
    require_manage_users(actor, db_path)
    if status not in ALL_USER_STATUSES:
        raise AuthError(f"Status tidak dikenal: {status}")

    username = (username or "").strip()
    target = get_user(username, db_path)
    if target is None:
        raise AuthError(f"Pengguna '{username}' tidak ditemukan.")
    if status != STATUS_ACTIVE and (actor or {}).get("username") == username:
        raise AuthError("Anda tidak dapat menonaktifkan akun Anda sendiri.")

    conn = get_connection(db_path)
    try:
        if status == STATUS_ACTIVE:
            conn.execute(
                """UPDATE users SET status = ?, is_active = 1,
                       activated_by = ?, activated_at = ? WHERE username = ?""",
                (status, (actor or {}).get("username"), now_iso(), username))
        else:
            conn.execute(
                "UPDATE users SET status = ?, is_active = 0 WHERE username = ?",
                (status, username))
        conn.commit()
    finally:
        conn.close()
    logger.info("Status akun %s -> %s oleh %s", username, status,
                (actor or {}).get("username"))
    return get_user(username, db_path)


@_retry_on_locked()
def set_user_role(username: str, role: str, *, actor: dict | None,
                  db_path: str | None = None) -> dict:
    """Ubah peran akun. Hanya Research Admin — SATU-SATUNYA jalan memperoleh
    peran Research Admin (pendaftaran mandiri tidak pernah bisa)."""
    require_manage_users(actor, db_path)
    if role not in ALL_ROLES:
        raise AuthError(f"Role tidak dikenal: {role}")
    username = (username or "").strip()
    if get_user(username, db_path) is None:
        raise AuthError(f"Pengguna '{username}' tidak ditemukan.")

    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE users SET role = ? WHERE username = ?",
                     (role, username))
        conn.commit()
    finally:
        conn.close()
    logger.info("Peran akun %s -> %s oleh %s", username, role,
                (actor or {}).get("username"))
    return get_user(username, db_path)


def set_user_active(username: str, active: bool, *, actor: dict | None,
                    db_path: str | None = None) -> dict:
    """Bentuk boolean lama dari ``set_user_status`` (dipertahankan agar
    pemanggil/uji lama tetap jalan). `status` adalah sumber kebenarannya."""
    return set_user_status(username, STATUS_ACTIVE if active else STATUS_DISABLED,
                           actor=actor, db_path=db_path)


def create_user_as(actor: dict | None, username: str, password: str,
                   role: str = ROLE_CONTRIBUTOR, db_path: str | None = None) -> dict:
    """``create_user`` dengan penjaga izin — dipakai oleh UI kelola pengguna."""
    require_manage_users(actor, db_path)
    return create_user(username, password, role, db_path)


def ensure_admin_seed(db_path: str | None = None) -> dict | None:
    """Buat Research Admin pertama dari env var bila belum ada. Idempoten.

    Perilaku:
      - sudah ada akun dengan username itu  -> TIDAK diapa-apakan (password
        lama tidak pernah ditimpa), kembalikan pengguna tersebut;
      - ``ADMIN_PASSWORD`` tidak diset       -> TIDAK membuat akun apa pun,
        catat peringatan jelas, kembalikan None. Password lemah bawaan tidak
        pernah dibuat;
      - password terlalu pendek              -> tidak dibuat + peringatan.
    """
    username = (os.environ.get(ADMIN_USERNAME_ENV) or DEFAULT_ADMIN_USERNAME).strip()
    password = os.environ.get(ADMIN_PASSWORD_ENV) or ""

    existing = get_user(username, db_path)
    if existing:
        return existing

    if not password:
        logger.warning(
            "%s belum diset — admin pertama TIDAK dibuat. Setel %s (dan "
            "opsional %s) lalu jalankan ulang aplikasi agar dapat masuk.",
            ADMIN_PASSWORD_ENV, ADMIN_PASSWORD_ENV, ADMIN_USERNAME_ENV,
        )
        return None

    try:
        user = create_user(username, password, ROLE_RESEARCH_ADMIN, db_path)
    except AuthError as e:
        logger.warning("Admin pertama tidak dibuat: %s", e)   # pesan, bukan password
        return None
    logger.info("Admin pertama dibuat dari environment: %s", username)
    return user


def has_any_user(db_path: str | None = None) -> bool:
    """True bila sudah ada minimal satu akun — dipakai UI untuk memberi
    petunjuk yang tepat ketika belum ada admin sama sekali."""
    conn = get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    finally:
        conn.close()
