"""
Módulo de Autenticación, Sesiones y Control de Acceso Basado en Roles (RBAC).
Gestiona usuarios, contraseñas hash con salt criptográfico, sesiones de usuario y
permisos para la plataforma Intervals Fit Analytics.
"""

import sys
import os
import hmac
import hashlib
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

# Asegurar path raíz para importaciones
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

try:
    from config import HISTORY_DB_PATH
except (ImportError, ValueError):
    from ..config import HISTORY_DB_PATH

import sqlite3
from contextlib import contextmanager

# Constantes de Roles
ROL_ADMINISTRADOR = "administrador"
ROL_EDITOR = "editor"
ROL_VISOR = "visor"
ROLES_VALIDOS = [ROL_ADMINISTRADOR, ROL_EDITOR, ROL_VISOR]

# Configuración de Hashing
HASH_ITERATIONS = 100_000
HASH_ALGORITHM = "sha256"

# Duración de sesión en días
SESSION_DURATION_DAYS = 7


def _obtener_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    """Devuelve la ruta resuelta a la base de datos SQLite."""
    if db_path is not None:
        p = Path(db_path)
    else:
        p = Path(HISTORY_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def _conectar_db(path: Path):
    """Context manager para conexión SQLite."""
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Genera el hash seguro de una contraseña usando PBKDF2-HMAC-SHA256 y un salt aleatorio.
    Devuelve la tupla (hex_hash, hex_salt).
    """
    if salt is None:
        salt_bytes = secrets.token_bytes(16)
        salt = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)

    derived = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM,
        password.encode("utf-8"),
        salt_bytes,
        HASH_ITERATIONS
    )
    return derived.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Verifica si la contraseña ingresada coincide con el hash esperado en tiempo constante."""
    try:
        calc_hash, _ = hash_password(password, salt)
        return hmac.compare_digest(calc_hash, expected_hash)
    except Exception:
        return False


def init_auth_db(db_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Crea las tablas de usuarios y sesiones si no existen, y asegura
    la existencia del usuario administrador por defecto ('admin' / '#siemprevalientes').
    """
    path = _obtener_db_path(db_path)

    with _conectar_db(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        # 1. Tabla de Usuarios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                rol TEXT NOT NULL CHECK(rol IN ('administrador', 'editor', 'visor')),
                nombre_completo TEXT,
                activo INTEGER NOT NULL DEFAULT 1,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ultimo_acceso TIMESTAMP
            );
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios(username);")

        # 2. Tabla de Sesiones
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sesiones (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE,
                rol TEXT NOT NULL,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expira_en TIMESTAMP NOT NULL,
                FOREIGN KEY (username) REFERENCES usuarios(username) ON DELETE CASCADE
            );
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_token ON sesiones(token);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_expira ON sesiones(expira_en);")

        conn.commit()

    # Asegurar la existencia del admin por defecto
    asegurar_admin_por_defecto(path)
    return path


def asegurar_admin_por_defecto(db_path: Optional[Union[str, Path]] = None) -> bool:
    """
    Verifica si existe el usuario 'admin'. Si no existe, lo crea con la contraseña
    '#siemprevalientes' y rol 'administrador'. Si existe pero está inactivo o rol cambiado, lo reactiva.
    """
    path = _obtener_db_path(db_path)
    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, rol, activo FROM usuarios WHERE LOWER(username) = 'admin';")
        row = cursor.fetchone()

        if not row:
            # Crear admin inicial
            pwd_hash, salt = hash_password("#siemprevalientes")
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, salt, rol, nombre_completo, activo)
                VALUES ('admin', ?, ?, ?, 'Administrador del Sistema', 1);
            """, (pwd_hash, salt, ROL_ADMINISTRADOR))
            conn.commit()
            return True
        else:
            # Asegurar que esté activo y con rol administrador
            user_id, uname, rol, activo = row
            if rol != ROL_ADMINISTRADOR or activo != 1:
                cursor.execute("""
                    UPDATE usuarios SET rol = ?, activo = 1 WHERE id = ?;
                """, (ROL_ADMINISTRADOR, user_id))
                conn.commit()
            return False


def autenticar_usuario(username: str, password: str, db_path: Optional[Union[str, Path]] = None) -> Optional[Dict[str, Any]]:
    """
    Verifica las credenciales de un usuario.
    Devuelve un diccionario con los datos del usuario si es válido y está activo, o None si no.
    """
    if not username or not password:
        return None

    path = _obtener_db_path(db_path)
    with _conectar_db(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, password_hash, salt, rol, nombre_completo, activo, creado_en, ultimo_acceso
            FROM usuarios
            WHERE LOWER(username) = LOWER(?);
        """, (username.strip(),))
        row = cursor.fetchone()

        if not row:
            return None

        if not bool(row["activo"]):
            return None

        if verify_password(password, row["salt"], row["password_hash"]):
            now_iso = datetime.now().isoformat()
            cursor.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?;", (now_iso, row["id"]))
            conn.commit()

            return {
                "id": row["id"],
                "username": row["username"],
                "rol": row["rol"],
                "nombre_completo": row["nombre_completo"] or row["username"],
                "creado_en": row["creado_en"],
                "ultimo_acceso": now_iso
            }

    return None


def crear_sesion(username: str, rol: str, dias_validez: int = SESSION_DURATION_DAYS, db_path: Optional[Union[str, Path]] = None) -> str:
    """Crea una nueva sesión en base de datos para el usuario y devuelve el token único."""
    path = _obtener_db_path(db_path)
    token = secrets.token_urlsafe(32)
    expira_dt = datetime.now() + timedelta(days=dias_validez)
    expira_iso = expira_dt.isoformat()

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sesiones (token, username, rol, expira_en)
            VALUES (?, ?, ?, ?);
        """, (token, username.strip().lower(), rol, expira_iso))
        conn.commit()

    return token


def validar_sesion(token: str, db_path: Optional[Union[str, Path]] = None) -> Optional[Dict[str, Any]]:
    """
    Comprueba si un token de sesión es válido y no ha expirado.
    Devuelve los datos del usuario si es válido, o None.
    """
    if not token:
        return None

    path = _obtener_db_path(db_path)
    with _conectar_db(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.token, s.username, s.rol, s.expira_en,
                   u.id as user_id, u.nombre_completo, u.activo
            FROM sesiones s
            JOIN usuarios u ON LOWER(s.username) = LOWER(u.username)
            WHERE s.token = ?;
        """, (token.strip(),))
        row = cursor.fetchone()

        if not row:
            return None

        if not bool(row["activo"]):
            cursor.execute("DELETE FROM sesiones WHERE token = ?;", (token.strip(),))
            conn.commit()
            return None

        expira_str = row["expira_en"]
        try:
            expira_dt = datetime.fromisoformat(expira_str)
            if datetime.now() > expira_dt:
                cursor.execute("DELETE FROM sesiones WHERE token = ?;", (token.strip(),))
                conn.commit()
                return None
        except Exception:
            pass

        return {
            "token": row["token"],
            "id": row["user_id"],
            "username": row["username"],
            "rol": row["rol"],
            "nombre_completo": row["nombre_completo"] or row["username"]
        }


def cerrar_sesion(token: str, db_path: Optional[Union[str, Path]] = None) -> bool:
    """Elimina la sesión correspondiente al token dado."""
    if not token:
        return False

    path = _obtener_db_path(db_path)
    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sesiones WHERE token = ?;", (token.strip(),))
        conn.commit()
        return cursor.rowcount > 0


def limpiar_sesiones_expiradas(db_path: Optional[Union[str, Path]] = None) -> int:
    """Elimina todas las sesiones que hayan superado su fecha de expiración."""
    path = _obtener_db_path(db_path)
    now_iso = datetime.now().isoformat()
    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sesiones WHERE expira_en < ?;", (now_iso,))
        conn.commit()
        return cursor.rowcount


# =============================================================================
# Operaciones CRUD de Usuarios (Para rol Administrador)
# =============================================================================

def listar_usuarios(db_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Devuelve la lista de todos los usuarios registrados (sin hashes ni salts)."""
    path = _obtener_db_path(db_path)
    with _conectar_db(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, rol, nombre_completo, activo, creado_en, ultimo_acceso
            FROM usuarios
            ORDER BY
                CASE rol
                    WHEN 'administrador' THEN 1
                    WHEN 'editor' THEN 2
                    WHEN 'visor' THEN 3
                    ELSE 4
                END,
                username ASC;
        """)
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "username": r["username"],
                "rol": r["rol"],
                "nombre_completo": r["nombre_completo"] or r["username"],
                "activo": bool(r["activo"]),
                "creado_en": r["creado_en"],
                "ultimo_acceso": r["ultimo_acceso"]
            }
            for r in rows
        ]


def obtener_usuario(username: str, db_path: Optional[Union[str, Path]] = None) -> Optional[Dict[str, Any]]:
    """Devuelve la información pública de un usuario por su nombre de usuario."""
    path = _obtener_db_path(db_path)
    with _conectar_db(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, rol, nombre_completo, activo, creado_en, ultimo_acceso
            FROM usuarios
            WHERE LOWER(username) = LOWER(?);
        """, (username.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "rol": row["rol"],
            "nombre_completo": row["nombre_completo"] or row["username"],
            "activo": bool(row["activo"]),
            "creado_en": row["creado_en"],
            "ultimo_acceso": row["ultimo_acceso"]
        }


def crear_usuario(
    username: str,
    password: str,
    rol: str,
    nombre_completo: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """
    Crea un nuevo usuario en la base de datos con contraseña encriptada.
    Lanza ValueError si los datos son inválidos o si el usuario ya existe.
    """
    username_clean = username.strip()
    if not username_clean:
        raise ValueError("El nombre de usuario no puede estar vacío.")

    if len(username_clean) < 3:
        raise ValueError("El nombre de usuario debe tener al menos 3 caracteres.")

    if not password or len(password) < 4:
        raise ValueError("La contraseña debe tener al menos 4 caracteres.")

    rol_clean = rol.strip().lower()
    if rol_clean not in ROLES_VALIDOS:
        raise ValueError(f"Rol inválido: '{rol}'. Los roles permitidos son: {', '.join(ROLES_VALIDOS)}.")

    path = _obtener_db_path(db_path)
    pwd_hash, salt = hash_password(password)

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE LOWER(username) = LOWER(?);", (username_clean,))
        if cursor.fetchone():
            raise ValueError(f"El usuario '{username_clean}' ya existe.")

        cursor.execute("""
            INSERT INTO usuarios (username, password_hash, salt, rol, nombre_completo, activo)
            VALUES (?, ?, ?, ?, ?, 1);
        """, (username_clean, pwd_hash, salt, rol_clean, (nombre_completo or "").strip() or username_clean))
        conn.commit()
        user_id = cursor.lastrowid

    return {
        "id": user_id,
        "username": username_clean,
        "rol": rol_clean,
        "nombre_completo": (nombre_completo or "").strip() or username_clean,
        "activo": True
    }


def actualizar_usuario(
    username: str,
    rol: Optional[str] = None,
    activo: Optional[bool] = None,
    nombre_completo: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> bool:
    """
    Actualiza el rol, estado activo o nombre de un usuario existente.
    Protege para no desactivar ni desgradar al último administrador activo.
    """
    path = _obtener_db_path(db_path)
    username_clean = username.strip().lower()

    with _conectar_db(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT id, username, rol, activo FROM usuarios WHERE LOWER(username) = ?;", (username_clean,))
        user = cursor.fetchone()
        if not user:
            raise ValueError(f"Usuario '{username}' no encontrado.")

        if user["rol"] == ROL_ADMINISTRADOR and (
            (rol is not None and rol != ROL_ADMINISTRADOR) or
            (activo is not None and not activo)
        ):
            cursor.execute("""
                SELECT COUNT(*) as count FROM usuarios
                WHERE rol = 'administrador' AND activo = 1 AND LOWER(username) != ?;
            """, (username_clean,))
            otros_admins = cursor.fetchone()["count"]
            if otros_admins == 0:
                raise ValueError("No se puede desactivar ni cambiar el rol al único Administrador activo del sistema.")

        updates = []
        params = []

        if rol is not None:
            rol_clean = rol.strip().lower()
            if rol_clean not in ROLES_VALIDOS:
                raise ValueError(f"Rol inválido: '{rol}'.")
            updates.append("rol = ?")
            params.append(rol_clean)

        if activo is not None:
            updates.append("activo = ?")
            params.append(1 if activo else 0)

        if nombre_completo is not None:
            updates.append("nombre_completo = ?")
            params.append(nombre_completo.strip())

        if not updates:
            return True

        params.append(username_clean)
        query = f"UPDATE usuarios SET {', '.join(updates)} WHERE LOWER(username) = ?;"
        cursor.execute(query, tuple(params))
        conn.commit()

        if rol is not None:
            cursor.execute("UPDATE sesiones SET rol = ? WHERE LOWER(username) = ?;", (rol.strip().lower(), username_clean))
            conn.commit()

        if activo is False:
            cursor.execute("DELETE FROM sesiones WHERE LOWER(username) = ?;", (username_clean,))
            conn.commit()

        return True


def cambiar_password(username: str, nueva_password: str, db_path: Optional[Union[str, Path]] = None) -> bool:
    """Cambia la contraseña de un usuario."""
    if not nueva_password or len(nueva_password) < 4:
        raise ValueError("La nueva contraseña debe tener al menos 4 caracteres.")

    path = _obtener_db_path(db_path)
    pwd_hash, salt = hash_password(nueva_password)
    username_clean = username.strip().lower()

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE usuarios
            SET password_hash = ?, salt = ?
            WHERE LOWER(username) = ?;
        """, (pwd_hash, salt, username_clean))
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Usuario '{username}' no encontrado.")
        return True


def eliminar_usuario(username: str, db_path: Optional[Union[str, Path]] = None) -> bool:
    """
    Elimina un usuario de la base de datos.
    Impide eliminar al único administrador activo.
    """
    path = _obtener_db_path(db_path)
    username_clean = username.strip().lower()

    with _conectar_db(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT id, username, rol FROM usuarios WHERE LOWER(username) = ?;", (username_clean,))
        user = cursor.fetchone()
        if not user:
            raise ValueError(f"Usuario '{username}' no encontrado.")

        if user["rol"] == ROL_ADMINISTRADOR:
            cursor.execute("""
                SELECT COUNT(*) as count FROM usuarios
                WHERE rol = 'administrador' AND activo = 1 AND LOWER(username) != ?;
            """, (username_clean,))
            otros_admins = cursor.fetchone()["count"]
            if otros_admins == 0:
                raise ValueError("No es posible eliminar al único Administrador activo del sistema.")

        cursor.execute("DELETE FROM sesiones WHERE LOWER(username) = ?;", (username_clean,))
        cursor.execute("DELETE FROM usuarios WHERE LOWER(username) = ?;", (username_clean,))
        conn.commit()
        return True
