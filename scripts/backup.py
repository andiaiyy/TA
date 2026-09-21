"""Cadangkan basis data + artefak platform, KONSISTEN dan dapat diulang.

Dijalankan dari host, dengan stack menyala maupun mati:

    python scripts/backup.py                      # ke storage/../backups/
    python scripts/backup.py --out D:/cadangan    # ke tempat lain
    python scripts/backup.py --keep 7             # simpan 7 cadangan terakhir

Yang dicadangkan:

* ``storage/experiments.db`` lewat **API backup sqlite3**, bukan salinan
  berkas. Ini yang menentukan: basis data berjalan dengan `journal_mode=WAL`,
  jadi menyalin berkas `.db` saat ada penulisan menghasilkan salinan yang
  kehilangan transaksi yang masih di `-wal`. `Connection.backup()` menyalin
  SNAPSHOT yang konsisten tanpa menghentikan aplikasi.
* ``storage/uploaded_pipelines/`` — kode kontribusi beserta versinya.
* ``storage/artifacts/`` — metrics.json & model.pkl tiap eksperimen. Inilah
  satu-satunya bagian yang TIDAK dapat dibuat ulang: menjalankan ulang sebuah
  eksperimen menghasilkan baris baru, bukan mengembalikan artefak yang hilang.

Yang TIDAK dicadangkan: ``storage/datasets/`` (berukuran giga dan berasal dari
sumber aslinya) dan ``storage/tmp/``. Keduanya disebut di ringkasan supaya
ketiadaannya adalah keputusan yang terbaca, bukan kelalaian yang tak terlihat.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
STORAGE = AKAR / "storage"
DB = STORAGE / "experiments.db"

#: Folder yang ikut diarsipkan, relatif terhadap `storage/`.
FOLDER = ("uploaded_pipelines", "artifacts")

#: Folder yang SENGAJA dilewati, beserta alasannya.
DILEWATI = {
    "datasets": "berukuran giga dan berasal dari sumber aslinya",
    "tmp": "ruang kerja sementara; isinya dibuang tiap run",
}


def stempel() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def salin_db(sumber: Path, tujuan: Path) -> int:
    """Salin basis data lewat API backup sqlite3. Kembalikan ukurannya."""
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{sumber}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(tujuan)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return tujuan.stat().st_size


def ukuran(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def manusiawi(n: int) -> str:
    satuan = ["B", "KB", "MB", "GB", "TB"]
    nilai = float(n)
    for s in satuan:
        if nilai < 1024 or s == satuan[-1]:
            return f"{nilai:.1f} {s}"
        nilai /= 1024
    return f"{nilai:.1f} TB"


def buat(out_dir: Path) -> Path:
    """Buat satu cadangan. Kembalikan jalur arsipnya."""
    if not DB.is_file():
        raise SystemExit(f"Basis data tidak ditemukan: {DB}")

    nama = f"cadangan_{stempel()}"
    kerja = out_dir / nama
    kerja.mkdir(parents=True, exist_ok=False)

    print(f"Cadangan: {kerja}")
    n = salin_db(DB, kerja / "experiments.db")
    print(f"  experiments.db      {manusiawi(n)}  (snapshot sqlite3, aman saat WAL)")

    for f in FOLDER:
        asal = STORAGE / f
        if not asal.exists():
            print(f"  {f:<20}(tidak ada)")
            continue
        shutil.copytree(asal, kerja / f)
        print(f"  {f:<20}{manusiawi(ukuran(asal))}")

    for f, alasan in DILEWATI.items():
        asal = STORAGE / f
        if asal.exists():
            print(f"  {f:<20}DILEWATI ({manusiawi(ukuran(asal))}) - {alasan}")

    arsip = out_dir / f"{nama}.tar.gz"
    with tarfile.open(arsip, "w:gz") as tar:
        tar.add(kerja, arcname=nama)
    shutil.rmtree(kerja)
    print(f"\nSelesai: {arsip}  ({manusiawi(arsip.stat().st_size)})")
    return arsip


def pangkas(out_dir: Path, keep: int) -> None:
    """Sisakan `keep` arsip terbaru. Tidak pernah menyentuh berkas lain."""
    arsip = sorted(out_dir.glob("cadangan_*.tar.gz"))
    buang = arsip[:-keep] if keep > 0 else []
    for p in buang:
        p.unlink()
        print(f"dibuang (melebihi --keep {keep}): {p.name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(AKAR / "backups"),
                    help="folder tujuan (bawaan: ./backups)")
    ap.add_argument("--keep", type=int, default=0,
                    help="sisakan N cadangan terbaru; 0 = jangan pangkas")
    args = ap.parse_args(argv)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    buat(out_dir)
    if args.keep:
        pangkas(out_dir, args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
