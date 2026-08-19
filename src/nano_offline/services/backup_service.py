from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nano_offline.core.database import Database, SCHEMA_VERSION

BACKUP_FORMAT = 1
PRIMARY_BACKUP_EXT = ".nanobackup"
LEGACY_BACKUP_EXT = ".qeidbackup"
PRIMARY_DB_ARCNAME = "nano.db"
LEGACY_DB_ARCNAME = "qeid.db"


@dataclass(slots=True, frozen=True)
class BackupValidation:
    valid: bool
    schema_version: int
    created_at: str
    db_sha256: str


class BackupService:
    """Verified local backup/restore.

    License data is device-bound and intentionally excluded from exported backups.
    Restore preserves the current device license and creates a safety backup first.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _schema_version(path: Path) -> int:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    @staticmethod
    def _integrity(path: Path) -> str:
        conn = sqlite3.connect(path)
        try:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            conn.close()

    def create_backup(self, destination: str | Path) -> Path:
        destination = Path(destination)
        if destination.suffix.lower() not in {PRIMARY_BACKUP_EXT, LEGACY_BACKUP_EXT}:
            destination = destination.with_suffix(destination.suffix + PRIMARY_BACKUP_EXT if destination.suffix else PRIMARY_BACKUP_EXT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.db.checkpoint()

        with tempfile.TemporaryDirectory(prefix="nano_backup_") as td:
            temp_db = Path(td) / PRIMARY_DB_ARCNAME
            source = self.db.connect()
            target = sqlite3.connect(temp_db)
            try:
                source.backup(target)
                target.execute("DELETE FROM license_state")
                target.commit()
            finally:
                target.close()
                source.close()

            integrity = self._integrity(temp_db)
            if integrity.lower() != "ok":
                raise RuntimeError(f"فشل فحص سلامة النسخة: {integrity}")
            db_hash = self._sha256(temp_db)
            created_at = datetime.now().astimezone().isoformat(timespec="seconds")
            manifest = {
                "format": BACKUP_FORMAT,
                "created_at": created_at,
                "schema_version": self._schema_version(temp_db),
                "db_sha256": db_hash,
                "license_included": False,
                "encrypted": False,
            }
            temp_zip = Path(td) / f"backup{PRIMARY_BACKUP_EXT}"
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_db, arcname=PRIMARY_DB_ARCNAME)
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            shutil.copy2(temp_zip, destination)
        return destination

    def validate_backup(self, backup_path: str | Path) -> BackupValidation:
        backup_path = Path(backup_path)
        if not backup_path.is_file():
            raise FileNotFoundError("ملف النسخة الاحتياطية غير موجود")
        with tempfile.TemporaryDirectory(prefix="nano_validate_") as td:
            out = Path(td)
            try:
                with zipfile.ZipFile(backup_path, "r") as zf:
                    names = set(zf.namelist())
                    db_arcname = PRIMARY_DB_ARCNAME if PRIMARY_DB_ARCNAME in names else LEGACY_DB_ARCNAME if LEGACY_DB_ARCNAME in names else None
                    if not db_arcname or "manifest.json" not in names:
                        raise ValueError("تنسيق النسخة الاحتياطية غير صحيح")
                    zf.extract(db_arcname, out)
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
                raise ValueError("ملف النسخة الاحتياطية تالف") from exc

            if int(manifest.get("format", 0)) != BACKUP_FORMAT:
                raise ValueError("إصدار تنسيق النسخة غير مدعوم")
            db_file = out / db_arcname
            expected = str(manifest.get("db_sha256", ""))
            actual = self._sha256(db_file)
            if not expected or not hmac.compare_digest(expected, actual):
                raise ValueError("بصمة قاعدة البيانات لا تطابق النسخة")
            integrity = self._integrity(db_file)
            if integrity.lower() != "ok":
                raise ValueError(f"قاعدة النسخة غير سليمة: {integrity}")
            schema = self._schema_version(db_file)
            if schema != int(manifest.get("schema_version", -1)):
                raise ValueError("إصدار قاعدة البيانات لا يطابق بيان النسخة")
            if schema > SCHEMA_VERSION:
                raise ValueError("النسخة أُنشئت بإصدار أحدث من التطبيق")
            return BackupValidation(True, schema, str(manifest.get("created_at", "")), actual)

    def restore_backup(self, backup_path: str | Path) -> Path:
        self.validate_backup(backup_path)
        self.db.checkpoint()

        with self.db.connect() as conn:
            current_license = conn.execute("SELECT * FROM license_state WHERE id=1").fetchone()
            current_license_dict = dict(current_license) if current_license else None

        safety_dir = self.db.path.parent / "backups"
        safety_dir.mkdir(parents=True, exist_ok=True)
        safety_path = safety_dir / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}{PRIMARY_BACKUP_EXT}"
        self.create_backup(safety_path)

        with tempfile.TemporaryDirectory(prefix="nano_restore_") as td:
            out = Path(td)
            with zipfile.ZipFile(backup_path, "r") as zf:
                names = set(zf.namelist())
                db_arcname = PRIMARY_DB_ARCNAME if PRIMARY_DB_ARCNAME in names else LEGACY_DB_ARCNAME
                zf.extract(db_arcname, out)
            source_db = out / db_arcname
            temp_target = self.db.path.with_suffix(self.db.path.suffix + ".restore")
            shutil.copy2(source_db, temp_target)

            # Migrate and validate the candidate before touching the live database.
            candidate = Database(temp_target)
            candidate.initialize()
            if candidate.integrity_check().lower() != "ok":
                raise RuntimeError("فشل فحص قاعدة الاسترجاع بعد الترحيل")
            candidate.checkpoint()
            for suffix in ("-wal", "-shm"):
                p = Path(str(temp_target) + suffix)
                if p.exists():
                    p.unlink()

            for suffix in ("-wal", "-shm"):
                p = Path(str(self.db.path) + suffix)
                if p.exists():
                    p.unlink()
            os.replace(temp_target, self.db.path)

        # Candidate is already migrated. Restore the device-bound license.
        self.db.initialize()
        if current_license_dict:
            columns = [
                "id", "license_key", "signed_token", "device_id", "activated_at",
                "last_verified_at", "expires_at",
            ]
            values = [current_license_dict.get(c) for c in columns]
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM license_state")
                conn.execute(
                    f"INSERT INTO license_state({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                    values,
                )
        if self.db.integrity_check().lower() != "ok":
            raise RuntimeError("فشل فحص قاعدة البيانات بعد الاسترجاع")
        return safety_path
