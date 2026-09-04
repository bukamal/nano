from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nano_offline.core.database import Database

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"dashboard", "customers", "suppliers", "items", "invoices", "finance", "reports", "security", "admin"}),
    "accountant": frozenset({"dashboard", "customers", "suppliers", "items", "invoices", "finance", "reports", "security"}),
    "sales": frozenset({"dashboard", "customers", "items", "invoices", "security"}),
    "viewer": frozenset({"dashboard", "reports", "security"}),
}

ROLE_LABELS = {
    "admin": "مدير",
    "accountant": "محاسب",
    "sales": "مبيعات",
    "viewer": "مشاهدة فقط",
}


@dataclass(slots=True, frozen=True)
class UserSession:
    id: int
    username: str
    full_name: str
    role: str

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())


class AuthService:
    MIN_PASSWORD_LENGTH = 8
    MAX_FAILED_ATTEMPTS = 5
    LOCK_MINUTES = 5

    def __init__(self, db: Database):
        self.db = db
        self._session: UserSession | None = None
        self._prefs_path = self.db.path.parent / "login_prefs.json"
        self._quick_key_path = self.db.path.parent / ".nano_quick_auth_key"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000, dklen=32)
        return digest.hex(), salt.hex()

    @classmethod
    def _validate_password(cls, password: str) -> None:
        if len(password or "") < cls.MIN_PASSWORD_LENGTH:
            raise ValueError(f"كلمة المرور يجب ألا تقل عن {cls.MIN_PASSWORD_LENGTH} أحرف")

    @staticmethod
    def _normalize_username(username: str) -> str:
        value = (username or "").strip()
        if len(value) < 3:
            raise ValueError("اسم المستخدم يجب ألا يقل عن 3 أحرف")
        if any(ch.isspace() for ch in value):
            raise ValueError("اسم المستخدم لا يجوز أن يحتوي مسافات")
        return value

    def _load_prefs(self) -> dict:
        try:
            data = json.loads(self._prefs_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_prefs(self, prefs: dict) -> None:
        self._prefs_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._prefs_path.with_suffix(".tmp")
        temp.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self._prefs_path)
        try:
            os.chmod(self._prefs_path, 0o600)
        except OSError:
            pass

    def remembered_username(self) -> str:
        return str(self._load_prefs().get("remembered_username") or "")

    def saved_login_enabled(self, username: str | None = None) -> bool:
        prefs = self._load_prefs()
        saved_username = str(prefs.get("saved_username") or "")
        token = str(prefs.get("saved_token") or "")
        if not saved_username or not token:
            return False
        return not username or saved_username.casefold() == (username or "").casefold()

    def set_remembered_username(self, username: str | None) -> None:
        prefs = self._load_prefs()
        if username:
            prefs["remembered_username"] = self._normalize_username(username)
        else:
            prefs.pop("remembered_username", None)
        self._save_prefs(prefs)

    def _quick_key(self) -> bytes:
        try:
            raw = bytes.fromhex(self._quick_key_path.read_text(encoding="ascii").strip())
            if len(raw) == 32:
                return raw
        except (OSError, ValueError):
            pass
        raw = secrets.token_bytes(32)
        self._quick_key_path.write_text(raw.hex(), encoding="ascii")
        try:
            os.chmod(self._quick_key_path, 0o600)
        except OSError:
            pass
        return raw

    def _quick_key_id(self) -> str:
        return hashlib.sha256(self._quick_key()).hexdigest()[:24]

    def _hash_quick(self, secret: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        material = self._quick_key() + (secret or "").encode("utf-8")
        digest = hashlib.pbkdf2_hmac("sha256", material, salt, 310_000, dklen=32)
        return digest.hex(), salt.hex()

    @staticmethod
    def _validate_quick(kind: str, secret: str) -> str:
        value = (secret or "").strip()
        if kind == "pin":
            if not value.isdigit() or not 4 <= len(value) <= 8:
                raise ValueError("PIN يجب أن يتكون من 4 إلى 8 أرقام")
        elif kind == "pattern":
            if not 4 <= len(value) <= 9 or any(ch not in "123456789" for ch in value) or len(set(value)) != len(value):
                raise ValueError("النمط يجب أن يحتوي 4 إلى 9 نقاط مختلفة")
        else:
            raise ValueError("نوع الدخول السريع غير صحيح")
        return value

    def has_users(self) -> bool:
        with self.db.connect() as conn:
            return bool(conn.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def current(self) -> UserSession | None:
        return self._session

    def require(self, permission: str) -> UserSession:
        if self._session is None:
            raise PermissionError("يجب تسجيل الدخول")
        if not self._session.can(permission):
            raise PermissionError("ليست لديك صلاحية لتنفيذ هذه العملية")
        return self._session

    def create_initial_admin(self, username: str, full_name: str, password: str) -> int:
        if self.has_users():
            raise ValueError("تم إنشاء المستخدم الأول مسبقًا")
        return self.create_user(username=username, full_name=full_name, password=password, role="admin", _bootstrap=True)

    def create_user(self, *, username: str, full_name: str, password: str, role: str, _bootstrap: bool = False) -> int:
        if not _bootstrap:
            self.require("admin")
        username = self._normalize_username(username)
        full_name = (full_name or "").strip()
        if not full_name:
            raise ValueError("الاسم الكامل مطلوب")
        if role not in ROLE_PERMISSIONS:
            raise ValueError("الدور غير صحيح")
        self._validate_password(password)
        password_hash, salt = self._hash_password(password)
        with self.db.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO users(username,full_name,password_hash,password_salt,role)
                   VALUES(?,?,?,?,?)""",
                (username, full_name, password_hash, salt, role),
            )
            user_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details,user_id,username) VALUES('create','user',?,?,?,?)",
                (user_id, f"role={role}", self._session.id if self._session else user_id, self._session.username if self._session else username),
            )
            return user_id

    def _checked_user(self, conn, username: str):
        row = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if row is None:
            raise ValueError("بيانات الدخول غير صحيحة")
        if not int(row["is_active"]):
            raise PermissionError("هذا المستخدم معطل")
        locked_until = self._parse_dt(row["locked_until"])
        if locked_until and locked_until > self._now():
            raise PermissionError("الحساب مقفل مؤقتًا بعد محاولات دخول فاشلة")
        return row

    def _failed_attempt(self, conn, row) -> None:
        failed = int(row["failed_attempts"] or 0) + 1
        lock_value = None
        if failed >= self.MAX_FAILED_ATTEMPTS:
            lock_value = self._iso(self._now() + timedelta(minutes=self.LOCK_MINUTES))
            failed = 0
        conn.execute(
            "UPDATE users SET failed_attempts=?,locked_until=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (failed, lock_value, row["id"]),
        )
        conn.commit()

    def _establish_session(self, row, action: str) -> UserSession:
        session = UserSession(int(row["id"]), str(row["username"]), str(row["full_name"]), str(row["role"]))
        self._session = session
        self.db.set_actor(session.id, session.username)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES(?, 'user', ?, ?)",
                (action, session.id, f"role={session.role}"),
            )
        return session

    def _set_saved_login(self, session: UserSession, enabled: bool) -> None:
        prefs = self._load_prefs()
        if enabled:
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            with self.db.transaction() as conn:
                conn.execute("UPDATE users SET remember_token_hash=? WHERE id=?", (token_hash, session.id))
            prefs["saved_username"] = session.username
            prefs["saved_token"] = token
        else:
            with self.db.transaction() as conn:
                conn.execute("UPDATE users SET remember_token_hash=NULL WHERE id=?", (session.id,))
            prefs.pop("saved_username", None)
            prefs.pop("saved_token", None)
        self._save_prefs(prefs)

    def login(self, username: str, password: str, *, remember_login: bool = False, remember_username: bool = True) -> UserSession:
        username = self._normalize_username(username)
        conn = self.db.connect()
        try:
            row = self._checked_user(conn, username)
            expected, _ = self._hash_password(password or "", str(row["password_salt"]))
            if not hmac.compare_digest(expected, str(row["password_hash"])):
                self._failed_attempt(conn, row)
                raise ValueError("اسم المستخدم أو كلمة المرور غير صحيحة")
            conn.execute(
                "UPDATE users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (self._iso(self._now()), row["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        session = self._establish_session(row, "login")
        self.set_remembered_username(session.username if (remember_username or remember_login) else None)
        self._set_saved_login(session, remember_login)
        return session

    def restore_saved_session(self) -> UserSession | None:
        prefs = self._load_prefs()
        username = str(prefs.get("saved_username") or "")
        token = str(prefs.get("saved_token") or "")
        if not username or not token:
            return None
        conn = self.db.connect()
        try:
            row = self._checked_user(conn, self._normalize_username(username))
            expected = str(row["remember_token_hash"] or "")
            actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
            if not expected or not hmac.compare_digest(expected, actual):
                return None
            conn.execute(
                "UPDATE users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (self._iso(self._now()), row["id"]),
            )
            conn.commit()
        except Exception:
            return None
        finally:
            conn.close()
        return self._establish_session(row, "login_saved")

    def quick_auth_info(self, username: str) -> str | None:
        try:
            username = self._normalize_username(username)
        except ValueError:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT quick_auth_type,quick_auth_key_id,is_active FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone()
        if not row or not int(row["is_active"]):
            return None
        if str(row["quick_auth_key_id"] or "") != self._quick_key_id():
            return None
        kind = str(row["quick_auth_type"] or "")
        return kind if kind in {"pin", "pattern"} else None

    def verify_current_password(self, password: str) -> None:
        session = self.current()
        if session is None:
            raise PermissionError("يجب تسجيل الدخول")
        with self.db.connect() as conn:
            row = conn.execute("SELECT password_hash,password_salt FROM users WHERE id=?", (session.id,)).fetchone()
        expected, _ = self._hash_password(password or "", str(row["password_salt"]))
        if not hmac.compare_digest(expected, str(row["password_hash"])):
            raise ValueError("كلمة المرور الحالية غير صحيحة")

    def set_quick_auth(self, kind: str, secret: str, current_password: str) -> None:
        session = self.current()
        if session is None:
            raise PermissionError("يجب تسجيل الدخول")
        self.verify_current_password(current_password)
        value = self._validate_quick(kind, secret)
        digest, salt = self._hash_quick(value)
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE users SET quick_auth_type=?,quick_auth_hash=?,quick_auth_salt=?,quick_auth_key_id=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (kind, digest, salt, self._quick_key_id(), session.id),
            )
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('quick_auth_set','user',?,?)",
                (session.id, f"type={kind}"),
            )
        self.set_remembered_username(session.username)

    def clear_quick_auth(self, current_password: str) -> None:
        session = self.current()
        if session is None:
            raise PermissionError("يجب تسجيل الدخول")
        self.verify_current_password(current_password)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET quick_auth_type=NULL,quick_auth_hash=NULL,quick_auth_salt=NULL,quick_auth_key_id=NULL WHERE id=?",
                (session.id,),
            )
            conn.execute("INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('quick_auth_clear','user',?,'')", (session.id,))

    def login_quick(self, username: str, kind: str, secret: str) -> UserSession:
        username = self._normalize_username(username)
        value = self._validate_quick(kind, secret)
        conn = self.db.connect()
        try:
            row = self._checked_user(conn, username)
            if str(row["quick_auth_type"] or "") != kind or str(row["quick_auth_key_id"] or "") != self._quick_key_id():
                raise ValueError("الدخول السريع غير مفعّل لهذا المستخدم")
            expected, _ = self._hash_quick(value, str(row["quick_auth_salt"] or ""))
            if not hmac.compare_digest(expected, str(row["quick_auth_hash"] or "")):
                self._failed_attempt(conn, row)
                raise ValueError("PIN أو النمط غير صحيح")
            conn.execute(
                "UPDATE users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (self._iso(self._now()), row["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        session = self._establish_session(row, "login_quick")
        self.set_remembered_username(session.username)
        return session

    def logout(self, *, clear_saved: bool = True) -> None:
        session = self._session
        if session is not None:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('logout','user',?,?)",
                    (session.id, f"role={session.role}"),
                )
        if clear_saved:
            prefs = self._load_prefs()
            saved_username = str(prefs.get("saved_username") or "")
            if saved_username:
                with self.db.transaction() as conn:
                    conn.execute("UPDATE users SET remember_token_hash=NULL WHERE username=? COLLATE NOCASE", (saved_username,))
            prefs.pop("saved_username", None)
            prefs.pop("saved_token", None)
            self._save_prefs(prefs)
        self._session = None
        self.db.set_actor(None, None)

    def list_users(self) -> list[dict]:
        self.require("admin")
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id,username,full_name,role,is_active,last_login_at,created_at FROM users ORDER BY id"
            ).fetchall()]

    def set_active(self, user_id: int, active: bool) -> None:
        actor = self.require("admin")
        if actor.id == int(user_id) and not active:
            raise ValueError("لا يمكنك تعطيل المستخدم الحالي")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT username,role FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("المستخدم غير موجود")
            if row["role"] == "admin" and not active:
                admins = int(conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0])
                if admins <= 1:
                    raise ValueError("لا يمكن تعطيل آخر مدير نشط")
            conn.execute("UPDATE users SET is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if active else 0, user_id))
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('update','user',?,?)",
                (user_id, f"is_active={1 if active else 0}"),
            )

    def reset_password(self, user_id: int, new_password: str) -> None:
        self.require("admin")
        self._validate_password(new_password)
        password_hash, salt = self._hash_password(new_password)
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
                raise ValueError("المستخدم غير موجود")
            conn.execute(
                """UPDATE users SET password_hash=?,password_salt=?,failed_attempts=0,locked_until=NULL,
                   quick_auth_type=NULL,quick_auth_hash=NULL,quick_auth_salt=NULL,quick_auth_key_id=NULL,remember_token_hash=NULL,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (password_hash, salt, user_id),
            )
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('password_reset','user',?,'admin reset')",
                (user_id,),
            )

    def audit_entries(self, limit: int = 200) -> list[dict]:
        self.require("admin")
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT id,action,entity_type,entity_id,details,user_id,username,created_at
                   FROM audit_log ORDER BY id DESC LIMIT ?""",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()]
