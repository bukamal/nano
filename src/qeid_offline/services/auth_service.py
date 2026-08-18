from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from qeid_offline.core.database import Database

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"dashboard", "customers", "suppliers", "items", "invoices", "finance", "reports", "admin"}),
    "accountant": frozenset({"dashboard", "customers", "suppliers", "items", "invoices", "finance", "reports"}),
    "sales": frozenset({"dashboard", "customers", "items", "invoices"}),
    "viewer": frozenset({"dashboard", "reports"}),
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
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            310_000,
            dklen=32,
        )
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

    def create_user(
        self,
        *,
        username: str,
        full_name: str,
        password: str,
        role: str,
        _bootstrap: bool = False,
    ) -> int:
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

    def login(self, username: str, password: str) -> UserSession:
        username = self._normalize_username(username)
        conn = self.db.connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            if row is None:
                raise ValueError("اسم المستخدم أو كلمة المرور غير صحيحة")
            if not int(row["is_active"]):
                raise PermissionError("هذا المستخدم معطل")
            locked_until = self._parse_dt(row["locked_until"])
            now = self._now()
            if locked_until and locked_until > now:
                raise PermissionError("الحساب مقفل مؤقتًا بعد محاولات دخول فاشلة")

            expected, _ = self._hash_password(password or "", str(row["password_salt"]))
            if not hmac.compare_digest(expected, str(row["password_hash"])):
                failed = int(row["failed_attempts"] or 0) + 1
                lock_value = None
                if failed >= self.MAX_FAILED_ATTEMPTS:
                    lock_value = self._iso(now + timedelta(minutes=self.LOCK_MINUTES))
                    failed = 0
                conn.execute(
                    "UPDATE users SET failed_attempts=?,locked_until=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (failed, lock_value, row["id"]),
                )
                conn.commit()
                raise ValueError("اسم المستخدم أو كلمة المرور غير صحيحة")

            conn.execute(
                "UPDATE users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (self._iso(now), row["id"]),
            )
            conn.commit()
            session = UserSession(int(row["id"]), str(row["username"]), str(row["full_name"]), str(row["role"]))
        finally:
            conn.close()

        self._session = session
        self.db.set_actor(session.id, session.username)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('login','user',?,?)",
                (session.id, f"role={session.role}"),
            )
        return session

    def logout(self) -> None:
        session = self._session
        if session is not None:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES('logout','user',?,?)",
                    (session.id, f"role={session.role}"),
                )
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
                """UPDATE users SET password_hash=?,password_salt=?,failed_attempts=0,locked_until=NULL,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
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
