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
# Encrypted backups (phase 10) hide the plain SQLite bytes behind this entry
# and describe the crypto in manifest.json (cipher/kdf/salt/nonce).
ENCRYPTED_DB_ARCNAME = "nano.db.enc"


def _aes_gcm_encrypt(key: bytes, nonce: bytes, data: bytes) -> bytes:
    # Imported lazily so unencrypted backups never require the extra package.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key).encrypt(nonce, data, None)


def _aes_gcm_decrypt(key: bytes, nonce: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key).decrypt(nonce, data, None)


@dataclass(slots=True, frozen=True)
class BackupValidation:
    valid: bool
    schema_version: int
    created_at: str
    db_sha256: str
    encrypted: bool = False


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

    def create_backup(self, destination: str | Path, password: str | None = None) -> Path:
        """Create a verified backup; pass ``password`` to encrypt it (AES-256-GCM,
        key derived via PBKDF2-HMAC-SHA256)."""
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
            manifest: dict = {
                "format": BACKUP_FORMAT,
                "created_at": created_at,
                "schema_version": self._schema_version(temp_db),
                "db_sha256": db_hash,
                "license_included": False,
                "encrypted": bool(password),
            }
            payload_arc = PRIMARY_DB_ARCNAME
            if password:
                salt = os.urandom(16)
                iterations = 200_000
                key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
                nonce = os.urandom(12)
                ciphertext = _aes_gcm_encrypt(key, nonce, temp_db.read_bytes())
                payload_arc = ENCRYPTED_DB_ARCNAME
                manifest.update(
                    {
                        "cipher": "aes-256-gcm",
                        "kdf": "pbkdf2-sha256",
                        "kdf_iterations": iterations,
                        "salt": salt.hex(),
                        "nonce": nonce.hex(),
                    }
                )
            temp_zip = Path(td) / f"backup{PRIMARY_BACKUP_EXT}"
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if password:
                    zf.writestr(payload_arc, ciphertext)
                else:
                    zf.write(temp_db, arcname=payload_arc)
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            shutil.copy2(temp_zip, destination)
        return destination

    @staticmethod
    def prune_backups(directory: str | Path, keep: int) -> list[Path]:
        """Delete the oldest local backup files beyond ``keep``, newest first.

        ``keep <= 0`` means unlimited -- a no-op, matching the app's
        behavior before backup_settings.retention_count existed. Only
        touches files in ``directory`` itself (not subfolders), and only
        the two backup extensions this app writes, so a stray unrelated
        file dropped in the same folder is never at risk.
        """
        if keep <= 0:
            return []
        directory = Path(directory)
        if not directory.is_dir():
            return []
        files = sorted(
            list(directory.glob(f"*{PRIMARY_BACKUP_EXT}")) + list(directory.glob(f"*{LEGACY_BACKUP_EXT}")),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        deleted: list[Path] = []
        for stale in files[keep:]:
            try:
                stale.unlink()
                deleted.append(stale)
            except OSError:
                continue
        return deleted

    def _extract_plain_db(
        self, backup_path: Path, out_dir: Path, password: str | None = None
    ) -> tuple[Path, dict]:
        """Open a backup, decrypt if needed, and place the plain SQLite file in
        ``out_dir``. Returns ``(db_path, manifest)``. Never writes into the
        archive itself."""
        try:
            with zipfile.ZipFile(backup_path, "r") as zf:
                names = set(zf.namelist())
                if "manifest.json" not in names:
                    raise ValueError("تنسيق النسخة الاحتياطية غير صحيح")
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                encrypted = bool(manifest.get("encrypted", False))
                if encrypted:
                    if ENCRYPTED_DB_ARCNAME not in names:
                        raise ValueError("تنسيق النسخة الاحتياطية غير صحيح")
                    if not password:
                        raise ValueError("النسخة مشفرة — أدخل كلمة المرور")
                    try:
                        salt = bytes.fromhex(str(manifest["salt"]))
                        nonce = bytes.fromhex(str(manifest["nonce"]))
                        iterations = int(manifest.get("kdf_iterations", 200_000))
                        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
                        plain = _aes_gcm_decrypt(key, nonce, zf.read(ENCRYPTED_DB_ARCNAME))
                    except Exception as exc:
                        raise ValueError("كلمة المرور غير صحيحة أو النسخة تالفة") from exc
                    db_file = out_dir / PRIMARY_DB_ARCNAME
                    db_file.write_bytes(plain)
                else:
                    db_arcname = (
                        PRIMARY_DB_ARCNAME
                        if PRIMARY_DB_ARCNAME in names
                        else LEGACY_DB_ARCNAME
                        if LEGACY_DB_ARCNAME in names
                        else None
                    )
                    if not db_arcname:
                        raise ValueError("تنسيق النسخة الاحتياطية غير صحيح")
                    zf.extract(db_arcname, out_dir)
                    db_file = out_dir / db_arcname
        except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("ملف النسخة الاحتياطية تالف") from exc
        return db_file, manifest

    def validate_backup(
        self, backup_path: str | Path, password: str | None = None
    ) -> BackupValidation:
        backup_path = Path(backup_path)
        if not backup_path.is_file():
            raise FileNotFoundError("ملف النسخة الاحتياطية غير موجود")
        with tempfile.TemporaryDirectory(prefix="nano_validate_") as td:
            out = Path(td)
            db_file, manifest = self._extract_plain_db(backup_path, out, password=password)
            if int(manifest.get("format", 0)) != BACKUP_FORMAT:
                raise ValueError("إصدار تنسيق النسخة غير مدعوم")
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
            return BackupValidation(
                True,
                schema,
                str(manifest.get("created_at", "")),
                actual,
                encrypted=bool(manifest.get("encrypted", False)),
            )

    def restore_backup(
        self, backup_path: str | Path, password: str | None = None
    ) -> Path:
        self.validate_backup(backup_path, password=password)
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
            source_db, _manifest = self._extract_plain_db(
                Path(backup_path), out, password=password
            )
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
