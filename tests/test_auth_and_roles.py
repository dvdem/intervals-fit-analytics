"""
Pruebas exhaustivas para el sistema de autenticación, control de accesos RBAC
(Administrador, Editor, Visor) y gestión de usuarios en Intervals Fit Analytics.
"""

import sys
import unittest
from pathlib import Path

# Asegurar path raíz
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from web.app import app
from src.auth_manager import (
    autenticar_usuario,
    listar_usuarios,
    crear_usuario,
    eliminar_usuario,
    ROL_ADMINISTRADOR,
    ROL_EDITOR,
    ROL_VISOR
)


class TestAuthAndRoles(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_default_admin_exists(self):
        """Verifica que el usuario admin inicial exista con la contraseña #siemprevalientes."""
        admin_user = autenticar_usuario("admin", "#siemprevalientes")
        self.assertIsNotNone(admin_user)
        self.assertEqual(admin_user["username"].lower(), "admin")
        self.assertEqual(admin_user["rol"], ROL_ADMINISTRADOR)

    def test_login_success_and_cookie(self):
        """Verifica login exitoso y emisión de cookie de sesión."""
        res = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "#siemprevalientes"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertIn("token", data)
        self.assertEqual(data["user"]["rol"], ROL_ADMINISTRADOR)
        self.assertIn("ifa_session", self.client.cookies)

    def test_login_invalid_password(self):
        """Verifica que contraseñas erróneas sean rechazadas con 401."""
        res = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrongpassword123"
        })
        self.assertEqual(res.status_code, 401)
        self.assertIn("detail", res.json())

    def test_unauthenticated_redirect_and_401(self):
        """Verifica que un cliente no autenticado sea redirigido en vistas y reciba 401 en APIs."""
        unauth_client = TestClient(app)
        # Vista principal debe redirigir a /login
        r_view = unauth_client.get("/", follow_redirects=False)
        self.assertEqual(r_view.status_code, 302)
        self.assertEqual(r_view.headers.get("location"), "/login")

        # API debe devolver 401
        r_api = unauth_client.get("/api/dashboard")
        self.assertEqual(r_api.status_code, 401)

    def test_auth_me_endpoint(self):
        """Verifica el endpoint /api/auth/me tras autenticarse."""
        self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "#siemprevalientes"
        })
        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 200)
        user = res.json()
        self.assertEqual(user["username"].lower(), "admin")
        self.assertEqual(user["rol"], ROL_ADMINISTRADOR)

    def test_admin_user_crud(self):
        """Verifica el ciclo completo de gestión de usuarios por un administrador."""
        # 1. Login como admin
        self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "#siemprevalientes"
        })

        test_user = "test_entrenador"
        # Limpieza previa si existía
        try:
            eliminar_usuario(test_user)
        except Exception:
            pass

        # 2. Crear usuario
        r_create = self.client.post("/api/users", json={
            "username": test_user,
            "password": "Password123!",
            "rol": ROL_EDITOR,
            "nombre_completo": "Entrenador Jefe"
        })
        self.assertEqual(r_create.status_code, 200)
        self.assertTrue(r_create.json()["ok"])

        # 3. Listar usuarios
        r_list = self.client.get("/api/users")
        self.assertEqual(r_list.status_code, 200)
        usernames = [u["username"].lower() for u in r_list.json()]
        self.assertIn(test_user.lower(), usernames)

        # 4. Cambiar contraseña
        r_pwd = self.client.put(f"/api/users/{test_user}/password", json={
            "password": "NuevaPassword456!"
        })
        self.assertEqual(r_pwd.status_code, 200)

        # 5. Probar login con nueva contraseña
        client_test = TestClient(app)
        r_login_test = client_test.post("/api/auth/login", json={
            "username": test_user,
            "password": "NuevaPassword456!"
        })
        self.assertEqual(r_login_test.status_code, 200)

        # 6. Actualizar rol y nombre
        r_upd = self.client.put(f"/api/users/{test_user}", json={
            "rol": ROL_VISOR,
            "nombre_completo": "Observador Técnico"
        })
        self.assertEqual(r_upd.status_code, 200)

        # 7. Eliminar usuario
        r_del = self.client.delete(f"/api/users/{test_user}")
        self.assertEqual(r_del.status_code, 200)

    def test_admin_cannot_delete_self(self):
        """Verifica que un administrador conectado no pueda eliminar su propia cuenta."""
        self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "#siemprevalientes"
        })
        res = self.client.delete("/api/users/admin")
        self.assertEqual(res.status_code, 400)

    def test_role_permissions_visor(self):
        """Verifica que el rol Visor tenga acceso de solo lectura y reciba 403 en modificaciones."""
        # 1. Crear usuario visor
        visor_user = "test_visor"
        try:
            eliminar_usuario(visor_user)
        except Exception:
            pass
        crear_usuario(visor_user, "visorpass123", ROL_VISOR, "Usuario Visor")

        # 2. Login como visor
        client_visor = TestClient(app)
        client_visor.post("/api/auth/login", json={
            "username": visor_user,
            "password": "visorpass123"
        })

        # 3. Acceso permitido a lectura (Dashboard y Atletas)
        r_dash = client_visor.get("/api/dashboard")
        self.assertEqual(r_dash.status_code, 200)

        r_ath = client_visor.get("/api/athletes")
        self.assertEqual(r_ath.status_code, 200)

        # 4. Acceso prohibido a creación o edición (403 Forbidden)
        r_create_ath = client_visor.post("/api/athletes", json={
            "name": "Ciclista Fantasma",
            "intervals_id": "i999999",
            "weight": 68.0,
            "ftp": 400.0,
            "carrera": 1,
            "biela": 170.0
        })
        self.assertEqual(r_create_ath.status_code, 403)

        # 5. Acceso prohibido a gestión de usuarios (403)
        r_users = client_visor.get("/api/users")
        self.assertEqual(r_users.status_code, 403)

        # 6. Acceso prohibido a sincronización API (403)
        r_sync = client_visor.post("/api/sync")
        self.assertEqual(r_sync.status_code, 403)

        # Limpieza
        eliminar_usuario(visor_user)

    def test_role_permissions_editor(self):
        """Verifica que el rol Editor pueda crear datos de carreras/atletas pero no borrar ni gestionar usuarios."""
        editor_user = "test_editor"
        try:
            eliminar_usuario(editor_user)
        except Exception:
            pass
        crear_usuario(editor_user, "editorpass123", ROL_EDITOR, "Usuario Editor")

        client_editor = TestClient(app)
        client_editor.post("/api/auth/login", json={
            "username": editor_user,
            "password": "editorpass123"
        })

        # 1. Editor NO puede acceder a gestión de usuarios (403)
        r_users = client_editor.get("/api/users")
        self.assertEqual(r_users.status_code, 403)

        # 2. Editor NO puede eliminar ciclistas (403)
        r_del_ath = client_editor.delete("/api/athletes/i554068")
        self.assertEqual(r_del_ath.status_code, 403)

        # 3. Editor NO puede ejecutar sync con API (403)
        r_sync = client_editor.post("/api/sync")
        self.assertEqual(r_sync.status_code, 403)

        # Limpieza
        eliminar_usuario(editor_user)

    def test_logout(self):
        """Verifica que tras cerrar sesión, el token quede invalidado y la cookie eliminada."""
        self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "#siemprevalientes"
        })
        r_me = self.client.get("/api/auth/me")
        self.assertEqual(r_me.status_code, 200)

        # Logout
        r_logout = self.client.post("/api/auth/logout")
        self.assertEqual(r_logout.status_code, 200)

        # Siguiente petición debe ser 401
        r_me2 = self.client.get("/api/auth/me")
        self.assertEqual(r_me2.status_code, 401)


if __name__ == "__main__":
    unittest.main()
