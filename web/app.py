"""
Servidor Web FastAPI - Intervals Fit Analytics Platform.
Proporciona endpoints REST y servicio de interfaz SPA para:
- Análisis de etapas y perfiles interactivos embebidos
- Informes de potencia (Power & Load Reports) con exportación a PDF y Word
- Consulta de récords (MMP) y métricas de fatiga previa (kJ)
- Gestión integral (CRUD) de ciclistas y carreras en CSV y SQLite
"""

import sys
import os
import re
import json
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

# Asegurar path raíz para importaciones
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request, Depends, status, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd

from src.auth_manager import (
    init_auth_db,
    autenticar_usuario,
    crear_sesion,
    validar_sesion,
    cerrar_sesion,
    listar_usuarios,
    obtener_usuario,
    crear_usuario,
    actualizar_usuario,
    cambiar_password,
    eliminar_usuario,
    ROL_ADMINISTRADOR,
    ROL_EDITOR,
    ROL_VISOR,
    ROLES_VALIDOS
)

from config import (
    cargar_roster,
    DEFAULT_ROSTER_PATH,
    OUTPUT_DIR,
    DATA_DIR,
    HISTORY_DB_PATH,
    DEFAULT_CRANK_LENGTH,
    normalizar_crank_length_m
)
from src.history_manager import (
    init_history_db,
    guardar_ciclista,
    obtener_mejores_numeros_temporada,
    obtener_curva_potencia_fatiga,
    obtener_ranking_equipo_pico,
    obtener_historico_carrera_etapas,
    obtener_resumen_acumulado_carrera,
    obtener_estadisticas_generales_bd,
    sincronizar_historico_desde_api,
    resolver_kj_picos_atleta,
    obtener_config_grupos_carrera,
    guardar_config_grupo_carrera,
    guardar_carrera,
    eliminar_carrera,
    asignar_convocados_carrera,
    obtener_convocados_carrera,
    obtener_carreras_calendario,
    obtener_carrera_detalle,
    obtener_carreras_activas_fecha,
    resolver_carrera,
    obtener_atletas_por_carrera,
    _conectar_db
)
from src.intervals_api import IntervalsClient
from src.power_peaks import (
    calcular_picos_potencia,
    generar_tabla_picos_comparativa,
    obtener_curvas_referencia_atleta
)
from src.load_metrics import calcular_metricas_carga
from src.wellness_hrv import descargar_wellness_atletas
from src.pdf_reports import (
    generar_informe_potencias_y_carga,
    generar_informe_etapa_pdf
)
from src.word_reports import (
    generar_informe_potencias_y_carga_word,
    generar_informe_etapa_word
)
from src.interactive_profile import (
    generar_dashboard_perfil_interactivo,
    descargar_o_recopilar_fits_etapa
)

# Inicializar Base de Datos
init_history_db()

# Inicializar Aplicación FastAPI
app = FastAPI(
    title="Intervals Fit Analytics Platform",
    description="Suite Integral de Rendimiento y Análisis de Ciclismo Pro",
    version="2.0.0"
)

# Habilitar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar recursos estáticos y templates
STATIC_DIR = _ROOT_DIR / "web" / "static"
TEMPLATES_DIR = _ROOT_DIR / "web" / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Estado global de tareas en segundo plano
_SYNC_STATUS = {"running": False, "message": "Inactivo", "last_run": None}


# =============================================================================
# Modelos de Datos Pydantic
# =============================================================================

class LoginRequest(BaseModel):
    username: str = Field(..., example="admin")
    password: str = Field(..., example="#siemprevalientes")


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, example="tecnico1")
    password: str = Field(..., min_length=4, example="clave123")
    rol: str = Field(..., example="editor")
    nombre_completo: Optional[str] = Field(None, example="Director Deportivo")


class UserUpdateRequest(BaseModel):
    rol: Optional[str] = None
    activo: Optional[bool] = None
    nombre_completo: Optional[str] = None


class UserPasswordChangeRequest(BaseModel):
    password: str = Field(..., min_length=4)


class AthleteCreate(BaseModel):
    name: str = Field(..., example="Mario Aparicio")
    intervals_id: str = Field(..., example="i554068")
    weight: float = Field(70.0, example=71.0)
    ftp: float = Field(380.0, example=440.0)
    carrera: int = Field(0, example=1)
    biela: float = Field(170.0, example=172.5)


class AthleteUpdate(BaseModel):
    name: Optional[str] = None
    weight: Optional[float] = None
    ftp: Optional[float] = None
    carrera: Optional[int] = None
    biela: Optional[float] = None


class RaceAssign(BaseModel):
    carrera_id: int = Field(..., example=1)
    athlete_ids: List[str] = Field(..., example=["i554068", "i495562"])


class StageAnalyzeRequest(BaseModel):
    fecha: Optional[str] = None
    carrera_id: Optional[str] = None
    grupo_carrera: Optional[Union[int, str]] = None
    todos: bool = False
    titulo: Optional[str] = None
    generar_pdf: bool = True
    generar_docx: bool = True


class PowerReportExportRequest(BaseModel):
    grupo: Optional[Union[int, str]] = None
    carrera_id: Optional[str] = None
    dias: int = 30
    dias_carga: int = 60
    titulo: Optional[str] = None
    formato: str = Field("ambos", example="ambos")  # 'pdf', 'docx', 'ambos'


class RaceCreateRequest(BaseModel):
    carrera_id: Optional[str] = None
    nombre_carrera: str
    categoria: Optional[str] = "UCI 2.Pro"
    pais: Optional[str] = "España"
    fecha_inicio: str
    fecha_fin: str
    total_etapas: Optional[int] = 1
    etapa_actual: Optional[int] = 0
    notas: Optional[str] = ""
    atletas_ids: Optional[List[str]] = []


class ConvocatoriaUpdateRequest(BaseModel):
    athlete_ids: List[str]


class RaceGroupUpdateRequest(BaseModel):
    nombre_carrera: str
    carrera_id_link: Optional[str] = None
    categoria: Optional[str] = "UCI 2.Pro"
    pais: Optional[str] = "España"
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    total_etapas: Optional[int] = 5
    etapa_actual: Optional[int] = 1
    notas: Optional[str] = ""


def _calcular_metricas_grupo_carrera(
    grupo_id: int,
    config: Dict[str, Any],
    atletas: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Calcula las métricas de competición agregadas y el estado de carrera para un grupo."""
    atleta_ids = [str(a.get("intervals_id", "")).strip() for a in atletas if a.get("intervals_id")]

    nombre_carrera = config.get("nombre_carrera") or f"Grupo Carrera {grupo_id}"
    carrera_id_link = (config.get("carrera_id_link") or "").strip().lower()
    total_etapas = int(config.get("total_etapas") or 5)
    etapa_actual = int(config.get("etapa_actual") or 1)
    categoria = config.get("categoria") or "UCI 2.Pro"
    pais = config.get("pais") or "España"
    fecha_inicio = config.get("fecha_inicio") or ""
    fecha_fin = config.get("fecha_fin") or ""
    notas = config.get("notas") or ""

    stats = {
        "dist_total_km": 0.0,
        "desnivel_total_m": 0,
        "kj_totales": 0.0,
        "etapas_registradas": 0,
        "ultima_fecha": "",
        "ctl_medio": round(sum(a.get("ftp", 0) for a in atletas) / len(atletas), 0) if atletas else 0,
        "tsb_medio": 0.0
    }

    atletas_info = []
    for a in atletas:
        atletas_info.append({
            "name": a.get("name"),
            "intervals_id": a.get("intervals_id"),
            "weight": a.get("weight"),
            "ftp": a.get("ftp"),
            "carrera": grupo_id,
            "ultima_etapa_km": None,
            "ultima_etapa_kj": None,
            "ultima_etapa_num": None
        })

    if atleta_ids:
        with _conectar_db(HISTORY_DB_PATH) as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in atleta_ids)

            if carrera_id_link:
                cursor.execute(f"""
                    SELECT 
                        ROUND(SUM(distancia_km), 1),
                        SUM(desnivel_m),
                        ROUND(SUM(kj_total), 0),
                        COUNT(DISTINCT etapa_num),
                        MAX(fecha)
                    FROM etapas_resumen
                    WHERE atleta_id IN ({placeholders}) AND LOWER(carrera_id) = ?;
                """, (*atleta_ids, carrera_id_link))
                r = cursor.fetchone()
                if r and r[0] is not None:
                    stats["dist_total_km"] = r[0] or 0.0
                    stats["desnivel_total_m"] = r[1] or 0
                    stats["kj_totales"] = r[2] or 0.0
                    stats["etapas_registradas"] = r[3] or 0
                    stats["ultima_fecha"] = r[4] or ""
            else:
                cursor.execute(f"""
                    SELECT carrera_id, nombre_carrera, MAX(fecha), COUNT(DISTINCT etapa_num), ROUND(SUM(distancia_km), 1), SUM(desnivel_m), ROUND(SUM(kj_total), 0)
                    FROM etapas_resumen
                    WHERE atleta_id IN ({placeholders})
                    GROUP BY carrera_id
                    ORDER BY MAX(fecha) DESC
                    LIMIT 1;
                """, (*atleta_ids,))
                r = cursor.fetchone()
                if r and r[0]:
                    carrera_id_link = r[0]
                    if not config.get("nombre_carrera") or config.get("nombre_carrera").startswith("Grupo Carrera"):
                        nombre_carrera = r[1] or r[0].replace('_', ' ').title()
                    stats["dist_total_km"] = r[4] or 0.0
                    stats["desnivel_total_m"] = r[5] or 0
                    stats["kj_totales"] = r[6] or 0.0
                    stats["etapas_registradas"] = r[3] or 0
                    stats["ultima_fecha"] = r[2] or ""

            if carrera_id_link:
                for a_dict in atletas_info:
                    aid = a_dict["intervals_id"]
                    cursor.execute("""
                        SELECT etapa_num, distancia_km, kj_total
                        FROM etapas_resumen
                        WHERE atleta_id = ? AND LOWER(carrera_id) = ?
                        ORDER BY fecha DESC, etapa_num DESC
                        LIMIT 1;
                    """, (aid, carrera_id_link))
                    act_r = cursor.fetchone()
                    if act_r:
                        a_dict["ultima_etapa_num"] = act_r[0]
                        a_dict["ultima_etapa_km"] = round(act_r[1], 1) if act_r[1] else None
                        a_dict["ultima_etapa_kj"] = round(act_r[2], 0) if act_r[2] else None

            cursor.execute(f"""
                SELECT ROUND(AVG(ctl), 1), ROUND(AVG(tsb), 1)
                FROM (
                    SELECT atleta_id, ctl, tsb
                    FROM wellness_diario
                    WHERE atleta_id IN ({placeholders})
                    ORDER BY fecha DESC
                    LIMIT {len(atleta_ids)}
                );
            """, (*atleta_ids,))
            w_row = cursor.fetchone()
            if w_row and w_row[0] is not None:
                stats["ctl_medio"] = w_row[0] or stats["ctl_medio"]
                stats["tsb_medio"] = w_row[1] or 0.0

    if etapa_actual >= total_etapas and stats["etapas_registradas"] >= total_etapas:
        estado = "finalizada"
        estado_label = "Finalizada"
    elif etapa_actual > 0:
        estado = "en_curso"
        estado_label = f"En Curso - Etapa {etapa_actual}/{total_etapas}"
    else:
        estado = "proxima"
        estado_label = "Próxima"

    progreso_pct = min(100, int((etapa_actual / max(total_etapas, 1)) * 100))

    return {
        "grupo_id": grupo_id,
        "nombre_carrera": nombre_carrera,
        "carrera_id_link": carrera_id_link,
        "categoria": categoria,
        "pais": pais,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "total_etapas": total_etapas,
        "etapa_actual": etapa_actual,
        "progreso_pct": progreso_pct,
        "estado": estado,
        "estado_label": estado_label,
        "notas": notas,
        "stats": stats,
        "atletas": atletas_info
    }


# =============================================================================
# Dependencias de Autenticación y Control de Roles (RBAC)
# =============================================================================

def extraer_token_peticion(request: Request) -> Optional[str]:
    """Extrae el token de autenticación de cookies, cabecera Authorization o parámetro query."""
    # 1. Cookie 'ifa_session'
    token = request.cookies.get("ifa_session")
    if token:
        return token.strip()

    # 2. Header 'Authorization: Bearer <token>'
    auth_hdr = request.headers.get("Authorization")
    if auth_hdr and auth_hdr.startswith("Bearer "):
        return auth_hdr[7:].strip()

    # 3. Query param 'session_token'
    query_token = request.query_params.get("session_token")
    if query_token:
        return query_token.strip()

    return None


def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """Devuelve los datos del usuario autenticado o None si no hay sesión válida."""
    token = extraer_token_peticion(request)
    if not token:
        return None
    return validar_sesion(token)


def get_current_user(request: Request) -> Dict[str, Any]:
    """Dependencia obligatoria: Devuelve el usuario o lanza HTTP 401."""
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Por favor inicia sesión para acceder a la plataforma."
        )
    return user


def require_role(allowed_roles: List[str]):
    """Dependencia que valida que el usuario tenga uno de los roles permitidos."""
    def _role_checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        user_role = current_user.get("rol")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permisos insuficientes. Se requiere rol: {', '.join(allowed_roles)}. Tu rol actual es: '{user_role}'."
            )
        return current_user
    return _role_checker


# =============================================================================
# Rutas de Vistas y Templates
# =============================================================================

@app.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    """Sirve la pantalla de inicio de sesión o redirige al inicio si ya hay sesión activa."""
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    login_file = TEMPLATES_DIR / "login.html"
    if not login_file.exists():
        return HTMLResponse("<h1>Login</h1><p>Template login.html no encontrado.</p>")
    with open(login_file, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    """Sirve la Single Page Application (SPA) principal si está autenticado."""
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Intervals Fit Analytics Platform</h1><p>Template no encontrado.</p>")
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/view-profile/{filename}", response_class=HTMLResponse)
def view_profile_html(filename: str, request: Request):
    """Sirve los perfiles interactivos HTML generados en output/ si está autenticado."""
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.name.endswith(".html"):
        raise HTTPException(status_code=404, detail="Perfil interactivo no encontrado.")
    with open(file_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# =============================================================================
# Endpoints de Autenticación
# =============================================================================

@app.post("/api/auth/login")
def login_endpoint(payload: LoginRequest, response: Response):
    """Valida credenciales y genera sesión activa."""
    user = autenticar_usuario(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos, o cuenta inactiva."
        )

    token = crear_sesion(user["username"], user["rol"])
    # Establecer cookie segura HttpOnly por 7 días
    response.set_cookie(
        key="ifa_session",
        value=token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax"
    )
    return {
        "ok": True,
        "token": token,
        "user": user,
        "message": f"Bienvenido, {user['nombre_completo']}."
    }


@app.post("/api/auth/logout")
def logout_endpoint(request: Request, response: Response):
    """Cierra la sesión actual y purga la cookie."""
    token = extraer_token_peticion(request)
    if token:
        cerrar_sesion(token)
    response.delete_cookie("ifa_session")
    return {"ok": True, "message": "Sesión cerrada correctamente."}


@app.get("/api/auth/me")
def me_endpoint(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve los datos del usuario actualmente autenticado y su rol."""
    return current_user


# =============================================================================
# Endpoints de Gestión de Usuarios (Rol Administrador)
# =============================================================================

@app.get("/api/users")
def list_users_endpoint(current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))):
    """Lista todos los usuarios del sistema (solo Administrador)."""
    return listar_usuarios()


@app.post("/api/users")
def create_user_endpoint(payload: UserCreateRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))):
    """Crea un nuevo usuario en la plataforma (solo Administrador)."""
    try:
        user = crear_usuario(
            username=payload.username,
            password=payload.password,
            rol=payload.rol,
            nombre_completo=payload.nombre_completo
        )
        return {"ok": True, "user": user, "message": f"Usuario '{user['username']}' creado exitosamente."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/users/{username}")
def update_user_endpoint(
    username: str,
    payload: UserUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))
):
    """Actualiza el rol, nombre o estado de un usuario (solo Administrador)."""
    try:
        actualizar_usuario(
            username=username,
            rol=payload.rol,
            activo=payload.activo,
            nombre_completo=payload.nombre_completo
        )
        return {"ok": True, "message": f"Usuario '{username}' actualizado correctamente."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/users/{username}/password")
def change_user_password_endpoint(
    username: str,
    payload: UserPasswordChangeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Cambia la contraseña de un usuario (Administrador o el propio usuario)."""
    if current_user["rol"] != ROL_ADMINISTRADOR and current_user["username"].lower() != username.strip().lower():
        raise HTTPException(status_code=403, detail="No tienes permisos para cambiar la contraseña de otro usuario.")

    try:
        cambiar_password(username, payload.password)
        return {"ok": True, "message": f"Contraseña actualizada para '{username}'."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/users/{username}")
def delete_user_endpoint(
    username: str,
    current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))
):
    """Elimina un usuario del sistema (solo Administrador)."""
    if current_user["username"].lower() == username.strip().lower():
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta de administrador.")

    try:
        eliminar_usuario(username)
        return {"ok": True, "message": f"Usuario '{username}' eliminado con éxito."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# Endpoints de Dashboard y Resumen General
# =============================================================================

@app.get("/api/dashboard")
def get_dashboard_summary(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve los indicadores clave del equipo y estado de la base de datos."""
    db_stats = obtener_estadisticas_generales_bd()
    roster_df = cargar_roster()

    ciclistas = []
    if not roster_df.empty:
        for _, row in roster_df.iterrows():
            ciclistas.append({
                "name": str(row.get('Name', '')),
                "intervals_id": str(row.get('intervals_id', '')),
                "weight": float(row.get('weight', 70.0)),
                "ftp": float(row.get('FTP', 380.0)),
                "carrera": int(row.get('carrera', 0)),
                "biela": float(row.get('biela', 170.0))
            })

    carreras_calendario = obtener_carreras_calendario(db_path=HISTORY_DB_PATH)
    carreras_activas = [c for c in carreras_calendario if c['estado'] == 'en_curso']
    carreras_proximas = [c for c in carreras_calendario if c['estado'] == 'proxima']
    carreras_finalizadas = [c for c in carreras_calendario if c['estado'] == 'finalizada']
    proxima_carrera = carreras_proximas[0] if carreras_proximas else None
    ultima_carrera = carreras_finalizadas[0] if carreras_finalizadas else None

    # Ciclistas activos en carrera según CSV o convocatorias
    en_carrera_1 = [c for c in ciclistas if c['carrera'] == 1]
    en_carrera_2 = [c for c in ciclistas if c['carrera'] == 2]

    # Configuración de los grupos de carrera y cálculo de métricas (compatibilidad)
    configs_list = obtener_config_grupos_carrera()
    configs = {c["grupo_id"]: c for c in configs_list}
    grupo_1_info = _calcular_metricas_grupo_carrera(1, configs.get(1, {}), en_carrera_1)
    grupo_2_info = _calcular_metricas_grupo_carrera(2, configs.get(2, {}), en_carrera_2)

    # Si hay carreras activas en el calendario, asociarlas directamente a grupo 1 y 2
    if len(carreras_activas) >= 1:
        grupo_1_info["carrera_id_link"] = carreras_activas[0]["carrera_id"]
        grupo_1_info["nombre_carrera"] = carreras_activas[0]["nombre_carrera"]
    if len(carreras_activas) >= 2:
        grupo_2_info["carrera_id_link"] = carreras_activas[1]["carrera_id"]
    # Obtener ultimas etapas registradas
    ultimas_etapas = []
    try:
        conn = sqlite3.connect(HISTORY_DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT fecha, carrera_id, nom_carrera, etapa_num, COUNT(DISTINCT atleta_id) as num_ciclistas
            FROM resumen_etapas
            GROUP BY fecha, carrera_id
            ORDER BY fecha DESC
            LIMIT 10
        """)
        for row in cur.fetchall():
            ultimas_etapas.append({
                "fecha": row[0],
                "carrera_id": row[1] or "",
                "nombre_carrera": row[2] or row[1] or "Carrera",
                "etapa_num": row[3] or 1,
                "num_ciclistas": row[4]
            })
        conn.close()
    except Exception:
        pass

    return {
        "db_stats": db_stats,
        "total_ciclistas": len(ciclistas),
        "en_carrera_1": en_carrera_1,
        "en_carrera_2": en_carrera_2,
        "carreras_activas": carreras_activas,
        "proxima_carrera": proxima_carrera,
        "ultima_carrera": ultima_carrera,
        "total_carreras": len(carreras_calendario),
        "grupos": {
            "1": grupo_1_info,
            "2": grupo_2_info
        },
        "ciclistas": ciclistas,
        "ultimas_etapas": ultimas_etapas,
        "sync_status": _SYNC_STATUS
    }


# =============================================================================
# Endpoints de Gestión de Atletas (CRUD)
# =============================================================================

def _guardar_roster_csv(df: pd.DataFrame):
    """Escribe de vuelta el roster respetando el formato CSV nativo con delimitador punto y coma."""
    DEFAULT_ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_clean = df[['Name', 'intervals_id', 'weight', 'FTP', 'carrera', 'biela']].copy()
    df_clean.to_csv(DEFAULT_ROSTER_PATH, sep=';', index=False, encoding='utf-8')


@app.get("/api/athletes")
def list_athletes(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve la lista completa de ciclistas del equipo."""
    df = cargar_roster()
    if df.empty:
        return []
    res = []
    for _, row in df.iterrows():
        res.append({
            "name": str(row.get('Name', '')),
            "intervals_id": str(row.get('intervals_id', '')),
            "weight": float(row.get('weight', 70.0)),
            "ftp": float(row.get('FTP', 380.0)),
            "carrera": int(row.get('carrera', 0)),
            "biela": float(row.get('biela', 170.0)),
            "crank_length_m": float(row.get('crank_length_m', 0.170))
        })
    return res


@app.post("/api/athletes")
def create_athlete(athlete: AthleteCreate, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Registra un nuevo ciclista tanto en CSV como en la base de datos SQLite."""
    df = cargar_roster()
    aid = athlete.intervals_id.strip()

    if not df.empty and aid in df['intervals_id'].astype(str).str.strip().values:
        raise HTTPException(status_code=400, detail=f"El ciclista con ID '{aid}' ya existe.")

    crank_m = normalizar_crank_length_m(athlete.biela)

    # 1. Guardar en SQLite
    guardar_ciclista(
        atleta_id=aid,
        nombre=athlete.name.strip(),
        peso=athlete.weight,
        ftp=athlete.ftp,
        crank_length_mm=athlete.biela,
        db_path=HISTORY_DB_PATH
    )

    # 2. Guardar en CSV
    new_row = pd.DataFrame([{
        'Name': athlete.name.strip(),
        'intervals_id': aid,
        'weight': athlete.weight,
        'FTP': athlete.ftp,
        'carrera': athlete.carrera,
        'biela': athlete.biela,
        'crank_length_m': crank_m
    }])
    df_updated = pd.concat([df, new_row], ignore_index=True) if not df.empty else new_row
    _guardar_roster_csv(df_updated)

    return {"status": "ok", "message": f"Ciclista '{athlete.name}' dado de alta exitosamente."}


@app.put("/api/athletes/{athlete_id}")
def update_athlete(athlete_id: str, athlete: AthleteUpdate, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Actualiza la información de un ciclista existente."""
    df = cargar_roster()
    aid = str(athlete_id).strip()

    if df.empty or aid not in df['intervals_id'].astype(str).str.strip().values:
        raise HTTPException(status_code=404, detail="Ciclista no encontrado.")

    idx = df[df['intervals_id'].astype(str).str.strip() == aid].index[0]

    if athlete.name is not None:
        df.at[idx, 'Name'] = athlete.name.strip()
    if athlete.weight is not None:
        df.at[idx, 'weight'] = float(athlete.weight)
    if athlete.ftp is not None:
        df.at[idx, 'FTP'] = float(athlete.ftp)
    if athlete.carrera is not None:
        df.at[idx, 'carrera'] = int(athlete.carrera)
    if athlete.biela is not None:
        df.at[idx, 'biela'] = float(athlete.biela)
        df.at[idx, 'crank_length_m'] = normalizar_crank_length_m(athlete.biela)

    _guardar_roster_csv(df)

    # Actualizar en SQLite
    guardar_ciclista(
        atleta_id=aid,
        nombre=str(df.at[idx, 'Name']),
        peso=float(df.at[idx, 'weight']),
        ftp=float(df.at[idx, 'FTP']),
        crank_length_mm=float(df.at[idx, 'biela']),
        db_path=HISTORY_DB_PATH
    )

    return {"status": "ok", "message": f"Ciclista '{df.at[idx, 'Name']}' actualizado."}


@app.delete("/api/athletes/{athlete_id}")
def delete_athlete(athlete_id: str, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))):
    """Elimina un ciclista del roster y de la base de datos."""
    df = cargar_roster()
    aid = str(athlete_id).strip()

    if df.empty or aid not in df['intervals_id'].astype(str).str.strip().values:
        raise HTTPException(status_code=404, detail="Ciclista no encontrado.")

    nom = df.loc[df['intervals_id'].astype(str).str.strip() == aid, 'Name'].values[0]
    df_filtered = df[df['intervals_id'].astype(str).str.strip() != aid]
    _guardar_roster_csv(df_filtered)

    with _conectar_db(HISTORY_DB_PATH) as conn:
        conn.execute("DELETE FROM ciclistas WHERE atleta_id = ?;", (aid,))
        conn.commit()

    return {"status": "ok", "message": f"Ciclista '{nom}' eliminado con éxito."}


# =============================================================================
# Endpoints de Carreras y Convocatorias (Calendario Integral)
# =============================================================================

@app.get("/api/races")
def list_races(estado: Optional[str] = Query(None), current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve el calendario completo de carreras con su estado y convocatoria."""
    carreras = obtener_carreras_calendario(filtro_estado=estado, db_path=HISTORY_DB_PATH)

    # Compatibilidad hacia atrás con num_etapas y num_atletas
    for c in carreras:
        c["num_etapas"] = c.get("total_etapas", 1)
        c["num_atletas"] = c.get("num_convocados", 0)

    return carreras


@app.post("/api/races")
def create_race(payload: RaceCreateRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Da de alta o actualiza una carrera con sus fechas y su convocatoria."""
    datos = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    atletas = datos.pop("atletas_ids", [])
    cid = guardar_carrera(datos, atletas_ids=atletas, db_path=HISTORY_DB_PATH)
    return {
        "status": "ok",
        "carrera_id": cid,
        "message": f"Carrera '{payload.nombre_carrera}' registrada con éxito con {len(atletas or [])} ciclistas convocados."
    }


@app.get("/api/races/{carrera_id}")
def get_race_detail(carrera_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve el detalle de una carrera del calendario y su convocatoria."""
    c = obtener_carrera_detalle(carrera_id, db_path=HISTORY_DB_PATH)
    if not c:
        raise HTTPException(status_code=404, detail=f"Carrera '{carrera_id}' no encontrada.")
    return c


@app.put("/api/races/{carrera_id}")
def update_race_endpoint(carrera_id: str, payload: RaceCreateRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Actualiza los metadatos y convocatoria de una carrera existente."""
    datos = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    datos["carrera_id"] = carrera_id
    atletas = datos.pop("atletas_ids", None)
    cid = guardar_carrera(datos, atletas_ids=atletas, db_path=HISTORY_DB_PATH)
    return {
        "status": "ok",
        "carrera_id": cid,
        "message": f"Carrera '{payload.nombre_carrera}' actualizada con éxito."
    }


@app.delete("/api/races/{carrera_id}")
def delete_race_endpoint(carrera_id: str, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))):
    """Elimina una carrera y su convocatoria asociada."""
    eliminar_carrera(carrera_id, db_path=HISTORY_DB_PATH)
    return {"status": "ok", "message": f"Carrera '{carrera_id}' eliminada con éxito."}


@app.get("/api/races/{carrera_id}/convocatoria")
def get_race_convocatoria(carrera_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve la lista de ciclistas convocados para una carrera."""
    convocados = obtener_convocados_carrera(carrera_id, db_path=HISTORY_DB_PATH)
    return {
        "carrera_id": carrera_id,
        "total_convocados": len(convocados),
        "convocados": convocados
    }


@app.post("/api/races/{carrera_id}/convocatoria")
def set_race_convocatoria(carrera_id: str, payload: ConvocatoriaUpdateRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Actualiza la nómina de ciclistas convocados para una carrera."""
    asignar_convocados_carrera(carrera_id, payload.athlete_ids, db_path=HISTORY_DB_PATH)
    return {
        "status": "ok",
        "carrera_id": carrera_id,
        "total_convocados": len(payload.athlete_ids),
        "message": f"Convocatoria de {len(payload.athlete_ids)} ciclistas guardada correctamente."
    }


@app.post("/api/races/assign")
def assign_athletes_race(payload: RaceAssign, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Asigna masivamente ciclistas a un grupo de carrera (0, 1 o 2)."""
    df = cargar_roster()
    if df.empty:
        raise HTTPException(status_code=400, detail="El roster de ciclistas está vacío.")

    target_ids = set(str(i).strip() for i in payload.athlete_ids)
    df['intervals_id'] = df['intervals_id'].astype(str).str.strip()

    # Si se asigna al grupo 1 o 2, los atletas seleccionados pasan a ese grupo
    for idx, row in df.iterrows():
        aid = row['intervals_id']
        if aid in target_ids:
            df.at[idx, 'carrera'] = int(payload.carrera_id)

    _guardar_roster_csv(df)
    return {"status": "ok", "message": f"{len(target_ids)} ciclistas asignados al Grupo Carrera {payload.carrera_id}."}


@app.get("/api/race-groups")
def get_race_groups(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve la configuración y métricas enriquecidas de los grupos de carrera 1 y 2."""
    configs_list = obtener_config_grupos_carrera()
    configs = {c["grupo_id"]: c for c in configs_list}
    roster_df = cargar_roster()

    ciclistas = []
    if not roster_df.empty:
        for _, row in roster_df.iterrows():
            ciclistas.append({
                "name": str(row.get('Name', '')),
                "intervals_id": str(row.get('intervals_id', '')),
                "weight": float(row.get('weight', 70.0)),
                "ftp": float(row.get('FTP', 380.0)),
                "carrera": int(row.get('carrera', 0)),
                "biela": float(row.get('biela', 170.0))
            })

    c1 = [c for c in ciclistas if c['carrera'] == 1]
    c2 = [c for c in ciclistas if c['carrera'] == 2]

    grupo_1_info = _calcular_metricas_grupo_carrera(1, configs.get(1, {}), c1)
    grupo_2_info = _calcular_metricas_grupo_carrera(2, configs.get(2, {}), c2)

    return {
        "1": grupo_1_info,
        "2": grupo_2_info,
        "grupos": [grupo_1_info, grupo_2_info]
    }


@app.post("/api/race-groups/{grupo_id}")
def update_race_group(grupo_id: int, payload: RaceGroupUpdateRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Actualiza la carrera y metadatos de un grupo de competición."""
    if grupo_id not in [1, 2]:
        raise HTTPException(status_code=400, detail="Solo se pueden configurar los grupos de carrera 1 y 2.")

    datos = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    guardar_config_grupo_carrera(grupo_id, datos)
    return {"status": "ok", "message": f"Configuración de Carrera para Grupo {grupo_id} guardada correctamente."}


@app.get("/api/races/{carrera_id}/history")
def get_race_history(carrera_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve la evolución etapa por etapa y métricas acumuladas de una carrera."""
    df = obtener_historico_carrera_etapas(carrera_id)
    if df.empty:
        with _conectar_db(HISTORY_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT DISTINCT carrera_id FROM etapas_resumen WHERE LOWER(carrera_id) LIKE ? LIMIT 1;", (f"%{carrera_id.lower()}%",))
            m = c.fetchone()
            if m:
                df = obtener_historico_carrera_etapas(m[0])

    if df.empty:
        return {"carrera_id": carrera_id, "total_etapas": 0, "total_registros": 0, "ciclistas": [], "etapas": []}

    df_clean = df.where(pd.notnull(df), None)
    records = df_clean.to_dict(orient="records")
    for r in records:
        if "tss_acumulado" in r and "tss_acumulados" not in r:
            r["tss_acumulados"] = r["tss_acumulado"]
        if "nombre" in r and "atleta_nombre" not in r:
            r["atleta_nombre"] = r["nombre"]

    atletas_en_carrera = sorted(list({r["nombre"] for r in records if r.get("nombre")}))
    nombre_oficial = records[0].get("nombre_carrera") or carrera_id.replace('_', ' ').title()

    return {
        "carrera_id": carrera_id,
        "nombre_carrera": nombre_oficial,
        "total_registros": len(records),
        "ciclistas": atletas_en_carrera,
        "etapas": records
    }


@app.get("/api/races/{carrera_id}/summary")
def get_race_accumulated_summary(carrera_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve el balance consolidado por ciclista al término de la carrera."""
    df = obtener_resumen_acumulado_carrera(carrera_id)
    if df.empty:
        with _conectar_db(HISTORY_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT DISTINCT carrera_id FROM etapas_resumen WHERE LOWER(carrera_id) LIKE ? LIMIT 1;", (f"%{carrera_id.lower()}%",))
            m = c.fetchone()
            if m:
                df = obtener_resumen_acumulado_carrera(m[0])

    if df.empty:
        return {"carrera_id": carrera_id, "total_ciclistas": 0, "total_atletas": 0, "resumen": []}

    df_clean = df.where(pd.notnull(df), None)
    records = df_clean.to_dict(orient="records")
    for r in records:
        if "nombre" in r and "atleta_nombre" not in r:
            r["atleta_nombre"] = r["nombre"]
        if "total_kj" in r and "kj_totales" not in r:
            r["kj_totales"] = r["total_kj"]
        if "total_horas" in r and "horas_totales" not in r:
            r["horas_totales"] = r["total_horas"]
        if "total_tss" in r and "tss_total" not in r:
            r["tss_total"] = r["total_tss"]
        if "total_km" in r and "distancia_total_km" not in r:
            r["distancia_total_km"] = r["total_km"]
        if "total_desnivel_m" in r and "desnivel_total_m" not in r:
            r["desnivel_total_m"] = r["total_desnivel_m"]

    return {
        "carrera_id": carrera_id,
        "total_ciclistas": len(records),
        "total_atletas": len(records),
        "resumen": records
    }


# =============================================================================
# Endpoints de Récords de Temporada y Fatiga Previa (MMP + kJ)
# =============================================================================

@app.get("/api/season-bests/{athlete_id}")
def get_season_bests(
    athlete_id: str,
    temporada: Optional[int] = Query(None, description="Año de la temporada (ej. 2026)"),
    todas: bool = Query(False, description="Incluir todas las duraciones secundarias"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Devuelve la envolvente de potencia récord con kilojulios de fatiga previa y gasto total."""
    aid = str(athlete_id).strip()
    df = obtener_mejores_numeros_temporada(atleta_id=aid, temporada=temporada)
    if df.empty:
        # Resolver automáticamente si no hay datos
        resolver_kj_picos_atleta(atleta_id=aid, verbose=False)
        df = obtener_mejores_numeros_temporada(atleta_id=aid, temporada=temporada)

    if df.empty:
        return {"athlete_id": aid, "records": []}

    if not todas:
        duraciones_std = [1, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 18000]
        df = df[df['duracion_s'].isin(duraciones_std)]

    records = []
    for _, r in df.iterrows():
        records.append({
            "duracion_s": int(r['duracion_s']),
            "duracion_str": str(r['duracion_str']),
            "max_watts": int(r['max_watts']),
            "w_kg": float(r['w_kg']),
            "kj_previos": float(r['kj_previos']),
            "kjkg_previos": float(r['kjkg_previos']),
            "kj_esfuerzo": float(r['kj_esfuerzo']),
            "kj_totales": float(r['kj_totales']),
            "momento_carrera": str(r.get('momento_carrera', '00:00:00')),
            "fecha": str(r.get('fecha', '')),
            "nombre_carrera": str(r.get('nombre_carrera', ''))
        })

    return {"athlete_id": aid, "records": records}


@app.get("/api/fatigue-curve/{athlete_id}")
def get_fatigue_curve(
    athlete_id: str,
    umbral_kj: float = Query(2000.0, description="Umbral de kilojulios para fatiga"),
    temporada: Optional[int] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Devuelve la comparativa de potencia en fresco (< umbral_kj) frente a bajo fatiga (>= umbral_kj)."""
    aid = str(athlete_id).strip()
    df = obtener_curva_potencia_fatiga(atleta_id=aid, umbral_kj=umbral_kj, temporada=temporada)
    if df.empty:
        return {"athlete_id": aid, "comparison": []}

    duraciones_std = [1, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200]
    df = df[df['duracion_s'].isin(duraciones_std)]

    comparisons = []
    for _, r in df.iterrows():
        comparisons.append({
            "duracion_s": int(r['duracion_s']),
            "duracion_str": str(r['duracion_str']),
            "watts_fresco": int(r['watts_fresco']) if pd.notna(r['watts_fresco']) else None,
            "wkg_fresco": float(r['wkg_fresco']) if pd.notna(r['wkg_fresco']) else None,
            "watts_fatiga": int(r['watts_fatiga']) if pd.notna(r['watts_fatiga']) else None,
            "wkg_fatiga": float(r['wkg_fatiga']) if pd.notna(r['wkg_fatiga']) else None,
            "perdida_pct": float(r['perdida_pct']) if pd.notna(r['perdida_pct']) else None,
        })
    return {"athlete_id": aid, "umbral_kj": umbral_kj, "comparison": comparisons}


# =============================================================================
# Endpoints de Power Reports (Informes de Potencia y Carga)
# =============================================================================

@app.get("/api/power-report/data")
def get_power_report_data(
    grupo: Optional[Union[int, str]] = Query(None, description="Grupo o carrera (slug, ID o número). None para todos."),
    carrera_id: Optional[str] = Query(None, description="Filtrar por carrera del calendario"),
    dias: int = Query(30, description="Días para picos recientes"),
    dias_carga: int = Query(60, description="Días para métricas de carga"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Devuelve los datos procesados para el informe de potencias y carga."""
    client = IntervalsClient()
    roster_df = cargar_roster()

    c_target = carrera_id or grupo
    c_res = resolver_carrera(c_target) if c_target is not None else None

    solo_carrera = (c_target is not None)
    atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=solo_carrera)

    if c_res is not None and c_res.get('convocados'):
        convocados_ids = {str(c['atleta_id']).strip() for c in c_res['convocados'] if c.get('atleta_id')}
        filtrados = [a for a in atletas if str(a.get('athlete_id', '')).strip() in convocados_ids]
        if filtrados:
            atletas = filtrados
        elif grupo is not None:
            try:
                g_num = int(grupo)
                atletas = [a for a in atletas if int(a.get('carrera', 0)) == g_num]
            except (ValueError, TypeError):
                pass
    elif grupo is not None:
        try:
            g_num = int(grupo)
            atletas = [a for a in atletas if int(a.get('carrera', 0)) == g_num]
        except (ValueError, TypeError):
            pass

    if not atletas:
        return {"atletas": [], "peaks_table": [], "metrics_table": [], "load_timeseries": []}

    try:
        peaks_df_total = calcular_picos_potencia(
            client=client,
            atletas=atletas,
            roster_df=roster_df,
            dias_recientes=dias
        )
        nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
        metrics_df_total = calcular_metricas_carga(
            client=client,
            atletas=atletas,
            dias_historia=dias_carga,
            dias_plot=dias_carga,
            nombres_map=nombres_map
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al calcular informe de potencia: {e}")

    # Formatear tabla de picos para el frontend SPA (app.js) con comparativa de récord histórico
    peaks_json = []
    if not peaks_df_total.empty:
        for athlete_name, group_data in peaks_df_total.groupby('athlete_name'):
            row = {
                'Ciclista': athlete_name,
                'duraciones': {}
            }
            dur_map = {r['duration_label']: r for _, r in group_data.iterrows()}
            for dur in ['5s', '30s', '1m', '5m', '10m', '20m']:
                item = dur_map.get(dur)
                peak_w = float(item['peak_watts']) if (item is not None and pd.notna(item.get('peak_watts'))) else None
                peak_wkg = round(float(item['peak_wkg']), 2) if (item is not None and pd.notna(item.get('peak_wkg'))) else None
                peak_date = str(item.get('peak_date') or '') if item is not None else ''

                hist_w = float(item['all_time_watts']) if (item is not None and pd.notna(item.get('all_time_watts'))) else None
                hist_wkg = round(float(item['all_time_wkg']), 2) if (item is not None and pd.notna(item.get('all_time_wkg'))) else None
                hist_date = str(item.get('all_time_date') or '') if item is not None else ''

                pct_pr = None
                delta_w = None
                delta_wkg = None
                es_pr = False

                if peak_w is not None and hist_w is not None and hist_w > 0:
                    pct_pr = round((peak_w / hist_w) * 100.0, 1)
                    delta_w = round(peak_w - hist_w, 1)
                    if peak_wkg is not None and hist_wkg is not None:
                        delta_wkg = round(peak_wkg - hist_wkg, 2)
                    es_pr = bool(peak_w >= hist_w)
                elif peak_w is not None and (hist_w is None or hist_w == 0):
                    pct_pr = 100.0
                    delta_w = 0.0
                    delta_wkg = 0.0
                    es_pr = True

                dur_info = {
                    'peak_watts': int(round(peak_w)) if peak_w is not None else None,
                    'peak_wkg': peak_wkg,
                    'peak_date': peak_date,
                    'all_time_watts': int(round(hist_w)) if hist_w is not None else None,
                    'all_time_wkg': hist_wkg,
                    'all_time_date': hist_date,
                    'pct_pr': pct_pr,
                    'delta_watts': delta_w,
                    'delta_wkg': delta_wkg,
                    'es_pr': es_pr
                }
                row['duraciones'][dur] = dur_info

                # Mantener compatibilidad retroactiva con claves clásicas
                if peak_w is not None:
                    row[f"{dur} (W)"] = int(round(peak_w))
                    row[f"{dur} (W/kg)"] = peak_wkg if peak_wkg is not None else '-'
                elif hist_w is not None:
                    row[f"{dur} (W)"] = f"{int(round(hist_w))} (PR)"
                    row[f"{dur} (W/kg)"] = hist_wkg if hist_wkg is not None else '-'
                else:
                    row[f"{dur} (W)"] = '-'
                    row[f"{dur} (W/kg)"] = '-'

                # Claves planas de récord
                row[f"{dur} PR (W)"] = int(round(hist_w)) if hist_w is not None else '-'
                row[f"{dur} PR (W/kg)"] = hist_wkg if hist_wkg is not None else '-'
                row[f"{dur} (% PR)"] = pct_pr if pct_pr is not None else '-'

            peaks_json.append(row)

    # Formatear tabla de métricas de carga (un registro resumido actual por ciclista)
    metrics_json = []
    metrics_by_name = {}
    if not metrics_df_total.empty:
        for athlete_name, g in metrics_df_total.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            last_row = g_sorted.iloc[-1]
            ultimos_7 = g_sorted.iloc[-7:] if len(g_sorted) >= 7 else g_sorted
            weekly_tss = float(ultimos_7['daily_load'].sum()) if 'daily_load' in ultimos_7.columns else 0.0

            ctl_val = round(float(last_row['ctl']), 1) if pd.notna(last_row['ctl']) else '-'
            atl_val = round(float(last_row['atl']), 1) if pd.notna(last_row['atl']) else '-'
            tsb_val = round(float(last_row['tsb']), 1) if pd.notna(last_row['tsb']) else '-'
            rr_val = round(float(last_row['ramp_rate_7d']), 2) if pd.notna(last_row['ramp_rate_7d']) else '-'

            metrics_by_name[athlete_name] = {
                'athlete_name': athlete_name,
                'ctl': ctl_val,
                'atl': atl_val,
                'tsb': tsb_val,
                'ramp_rate': rr_val,
                'weekly_tss': round(weekly_tss, 1) if weekly_tss else '-'
            }

    # Asegurar que todos los atletas aparezcan en la tabla de métricas
    processed_names = set()
    for a in atletas:
        nom = a.get('athlete_name', '')
        processed_names.add(nom)
        if nom in metrics_by_name:
            metrics_json.append(metrics_by_name[nom])
        else:
            metrics_json.append({
                'athlete_name': nom,
                'ctl': '-',
                'atl': '-',
                'tsb': '-',
                'ramp_rate': '-',
                'weekly_tss': '-'
            })

    for nom, m in metrics_by_name.items():
        if nom not in processed_names:
            metrics_json.append(m)

    # Serializar serie temporal continua de carga (CTL, ATL, TSB, TSS) para gráficos
    load_timeseries = []
    if not metrics_df_total.empty:
        m_sorted = metrics_df_total.sort_values(['athlete_name', 'fecha']).copy()

        # Calcular serie promedio del equipo
        avg_df = (
            m_sorted.groupby('fecha', as_index=False)
            .agg({
                'ctl': 'mean',
                'atl': 'mean',
                'tsb': 'mean',
                'daily_load': 'mean',
                'ramp_rate_7d': 'mean'
            })
            .sort_values('fecha')
        )
        avg_puntos = []
        for _, r in avg_df.iterrows():
            f_obj = r['fecha']
            f_str = f_obj.strftime('%Y-%m-%d') if hasattr(f_obj, 'strftime') else str(f_obj)[:10]
            avg_puntos.append({
                'fecha': f_str,
                'ctl': round(float(r['ctl']), 1) if pd.notna(r['ctl']) else None,
                'atl': round(float(r['atl']), 1) if pd.notna(r['atl']) else None,
                'tsb': round(float(r['tsb']), 1) if pd.notna(r['tsb']) else None,
                'daily_load': round(float(r['daily_load']), 1) if pd.notna(r['daily_load']) else 0.0,
                'ramp_rate': round(float(r['ramp_rate_7d']), 2) if pd.notna(r['ramp_rate_7d']) else None
            })
        if avg_puntos:
            load_timeseries.append({
                'athlete_name': '⭐ Media del Equipo',
                'is_team_avg': True,
                'series': avg_puntos
            })

        for athlete_name, g in m_sorted.groupby('athlete_name'):
            puntos = []
            for _, r in g.iterrows():
                f_obj = r['fecha']
                f_str = f_obj.strftime('%Y-%m-%d') if hasattr(f_obj, 'strftime') else str(f_obj)[:10]
                puntos.append({
                    'fecha': f_str,
                    'ctl': round(float(r['ctl']), 1) if pd.notna(r['ctl']) else None,
                    'atl': round(float(r['atl']), 1) if pd.notna(r['atl']) else None,
                    'tsb': round(float(r['tsb']), 1) if pd.notna(r['tsb']) else None,
                    'daily_load': round(float(r['daily_load']), 1) if pd.notna(r['daily_load']) else 0.0,
                    'ramp_rate': round(float(r['ramp_rate_7d']), 2) if pd.notna(r['ramp_rate_7d']) else None
                })
            load_timeseries.append({
                'athlete_name': athlete_name,
                'is_team_avg': False,
                'series': puntos
            })

    return {
        "grupo": grupo,
        "carrera_id": carrera_id,
        "dias": dias,
        "dias_carga": dias_carga,
        "peaks_table": peaks_json,
        "metrics_table": metrics_json,
        "load_timeseries": load_timeseries,
        "total_atletas": len(atletas)
    }


@app.post("/api/power-report/export")
def export_power_report(payload: PowerReportExportRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Genera los archivos descargables en PDF y/o Word del informe de potencia."""
    client = IntervalsClient()
    roster_df = cargar_roster()

    grupo = payload.grupo
    carrera_id = payload.carrera_id
    c_target = carrera_id or grupo
    c_res = resolver_carrera(c_target) if c_target is not None else None

    solo_carrera = (c_target is not None)
    atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=solo_carrera)

    if c_res is not None and c_res.get('convocados'):
        convocados_ids = {str(c['atleta_id']).strip() for c in c_res['convocados'] if c.get('atleta_id')}
        filtrados = [a for a in atletas if str(a.get('athlete_id', '')).strip() in convocados_ids]
        if filtrados:
            atletas = filtrados
        elif grupo is not None:
            try:
                g_num = int(grupo)
                atletas = [a for a in atletas if int(a.get('carrera', 0)) == g_num]
            except (ValueError, TypeError):
                pass
    elif grupo is not None:
        try:
            g_num = int(grupo)
            atletas = [a for a in atletas if int(a.get('carrera', 0)) == g_num]
        except (ValueError, TypeError):
            pass

    if not atletas:
        raise HTTPException(status_code=400, detail="No hay atletas asignados a la carrera o grupo especificado.")

    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    peaks_df_total = calcular_picos_potencia(
        client=client,
        atletas=atletas,
        roster_df=roster_df,
        dias_recientes=payload.dias
    )
    tabla_g, _ = generar_tabla_picos_comparativa(peaks_df_total) if not peaks_df_total.empty else (pd.DataFrame(), None)
    metrics_df_total = calcular_metricas_carga(
        client=client,
        atletas=atletas,
        dias_historia=payload.dias_carga,
        dias_plot=payload.dias_carga,
        nombres_map=nombres_map
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if c_res:
        label = f"_{c_res['carrera_id']}"
        titulo = payload.titulo or f"Informe de Rendimiento - {c_res['nombre_carrera']}"
        c_id_param = c_res['carrera_id']
        c_nom_param = c_res['nombre_carrera']
    elif grupo is not None:
        label = f"_carrera_{grupo}"
        titulo = payload.titulo or f"Informe de Rendimiento - Grupo Carrera {grupo}"
        c_id_param = f"carrera_{grupo}"
        c_nom_param = f"Grupo Carrera {grupo}"
    else:
        label = "_general"
        titulo = payload.titulo or "Informe de Rendimiento General"
        c_id_param = None
        c_nom_param = None

    out_files = {}

    if payload.formato in ["pdf", "ambos"]:
        out_pdf = OUTPUT_DIR / f"informe_potencias{label}_{timestamp}.pdf"
        generar_informe_potencias_y_carga(
            peaks_df_total, tabla_g, metrics_df_total,
            output_pdf=out_pdf, titulo=titulo, grupo_carrera=grupo,
            carrera_id=c_id_param, nombre_carrera=c_nom_param
        )
        out_files["pdf"] = f"/api/download/output/{out_pdf.name}"

    if payload.formato in ["docx", "ambos"]:
        out_docx = OUTPUT_DIR / f"informe_potencias{label}_{timestamp}.docx"
        generar_informe_potencias_y_carga_word(
            peaks_df_total, tabla_g, metrics_df_total,
            output_docx=out_docx, titulo=titulo, grupo_carrera=grupo,
            carrera_id=c_id_param, nombre_carrera=c_nom_param
        )
        out_files["docx"] = f"/api/download/output/{out_docx.name}"

    return {
        "status": "ok",
        "titulo": titulo,
        "archivos": out_files
    }


# =============================================================================
# Endpoints de Análisis de Etapa y Perfil Interactivo
# =============================================================================

@app.get("/api/stage/list")
def list_stages_available(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve las etapas y perfiles HTML ya generados o disponibles en SQLite."""
    # 1. Buscar HTMLs generados en output/
    html_files = []
    for f in OUTPUT_DIR.glob("*.html"):
        if "perfil" in f.name.lower() or "etapa" in f.name.lower() or "stage" in f.name.lower():
            html_files.append({
                "filename": f.name,
                "title": f.stem.replace('_', ' ').title(),
                "created_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "view_url": f"/view-profile/{f.name}"
            })

    # 2. Buscar etapas registradas en SQLite
    etapas_db = []
    with _conectar_db(HISTORY_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT carrera_id, nombre_carrera, fecha, etapa_num, COUNT(DISTINCT atleta_id)
            FROM etapas_resumen
            GROUP BY carrera_id, fecha, etapa_num
            ORDER BY fecha DESC;
        """)
        for row in cursor.fetchall():
            etapas_db.append({
                "carrera_id": row[0],
                "nombre_carrera": row[1],
                "fecha": row[2],
                "etapa_num": row[3],
                "ciclistas": row[4]
            })

    return {
        "html_profiles": sorted(html_files, key=lambda x: x['created_at'], reverse=True),
        "etapas_db": etapas_db
    }


@app.post("/api/stage/analyze")
def analyze_stage(payload: StageAnalyzeRequest, current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR, ROL_EDITOR]))):
    """Ejecuta el análisis de etapa, genera el perfil interactivo y reportes ejecutivos."""
    client = IntervalsClient()
    roster_df = cargar_roster()

    fecha_str = payload.fecha or datetime.now().strftime("%Y-%m-%d")
    titulo_base = payload.titulo

    # Resolver carrera_id prioritario si viene carrera_id o grupo_carrera
    carrera_target = payload.carrera_id
    if not carrera_target and payload.grupo_carrera is not None and str(payload.grupo_carrera) != 'todos':
        c_res = resolver_carrera(payload.grupo_carrera, fecha=fecha_str)
        if c_res:
            carrera_target = c_res['carrera_id']
            if not titulo_base:
                titulo_base = c_res['nombre_carrera']
    elif carrera_target:
        c_res = resolver_carrera(carrera_target, fecha=fecha_str)
        if c_res and not titulo_base:
            titulo_base = c_res['nombre_carrera']

    if not titulo_base:
        titulo_base = f"Etapa {fecha_str}"

    fits_temporales = []
    try:
        fit_paths, fits_temporales = descargar_o_recopilar_fits_etapa(
            fecha_str=fecha_str,
            client=client,
            roster_df=roster_df,
            grupo_carrera=payload.grupo_carrera,
            carrera_id=carrera_target,
            todos=payload.todos,
            solo_carrera=(not payload.todos and payload.grupo_carrera is None and carrera_target is None)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al recopilar datos de la etapa: {e}")

    if not fit_paths:
        raise HTTPException(status_code=404, detail=f"No se encontraron actividades ni archivos FIT para la fecha '{fecha_str}'.")

    # Generar el perfil interactivo HTML
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug_file = f"_{carrera_target}" if carrera_target else ""
    out_html = OUTPUT_DIR / f"perfil_interactivo_{fecha_str}{slug_file}_{timestamp}.html"
    out_pdf = OUTPUT_DIR / f"informe_etapa_{fecha_str}{slug_file}_{timestamp}.pdf" if payload.generar_pdf else None
    out_docx = OUTPUT_DIR / f"informe_etapa_{fecha_str}{slug_file}_{timestamp}.docx" if payload.generar_docx else None

    try:
        html_res = generar_dashboard_perfil_interactivo(
            archivos_o_datos=fit_paths,
            roster_df=roster_df,
            client=client,
            output_html=out_html,
            output_pdf=out_pdf,
            output_docx=out_docx,
            generar_pdf=payload.generar_pdf,
            generar_docx=payload.generar_docx,
            titulo=titulo_base,
            carrera_id=carrera_target,
            grupo_carrera=payload.grupo_carrera,
            formato_informe="ambos" if (payload.generar_pdf and payload.generar_docx) else ("pdf" if payload.generar_pdf else ("docx" if payload.generar_docx else "solo_html")),
            fits_temporales_limpiar=fits_temporales
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar perfil interactivo: {e}")
    finally:
        for tmp in fits_temporales:
            try:
                p_tmp = Path(tmp)
                if p_tmp.exists():
                    p_tmp.unlink()
            except Exception:
                pass

    archivos = {
        "html": f"/view-profile/{out_html.name}",
    }
    if out_pdf and out_pdf.exists():
        archivos["pdf"] = f"/api/download/output/{out_pdf.name}"
    if out_docx and out_docx.exists():
        archivos["docx"] = f"/api/download/output/{out_docx.name}"

    return {
        "status": "ok",
        "mensaje": f"Etapa procesada con éxito para {len(fit_paths)} ciclistas.",
        "fecha": fecha_str,
        "titulo": titulo_base,
        "archivos": archivos
    }


# =============================================================================
# Endpoints de Sincronización y Descargas
# =============================================================================

def _run_background_sync(desde: str):
    """Tarea ejecutada en segundo plano para sincronizar la base de datos."""
    global _SYNC_STATUS
    _SYNC_STATUS["running"] = True
    _SYNC_STATUS["message"] = f"Sincronizando desde {desde}..."
    try:
        res = sincronizar_historico_desde_api(
            fecha_inicio=desde,
            verbose=False
        )
        _SYNC_STATUS["running"] = False
        _SYNC_STATUS["message"] = f"Sincronización completada: {res.get('total_actividades', 0)} actividades, {res.get('total_picos', 0)} picos guardados."
        _SYNC_STATUS["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        _SYNC_STATUS["running"] = False
        _SYNC_STATUS["message"] = f"Error en sincronización: {e}"


@app.post("/api/sync")
def trigger_sync(background_tasks: BackgroundTasks, desde: str = Query("2026-01-01"), current_user: Dict[str, Any] = Depends(require_role([ROL_ADMINISTRADOR]))):
    """Inicia la sincronización masiva con Intervals.icu en segundo plano."""
    global _SYNC_STATUS
    if _SYNC_STATUS["running"]:
        return {"status": "busy", "message": "Ya hay una sincronización en curso."}

    background_tasks.add_task(_run_background_sync, desde=desde)
    return {"status": "started", "message": f"Sincronización iniciada en segundo plano desde {desde}."}


@app.get("/api/sync/status")
def get_sync_status(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Devuelve el estado de la tarea de sincronización."""
    return _SYNC_STATUS


@app.get("/api/download/{folder}/{filename}")
def download_file(folder: str, filename: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Descarga de forma segura archivos generados (PDF, DOCX, HTML)."""
    if folder == "output":
        target_path = OUTPUT_DIR / filename
    elif folder == "data":
        target_path = DATA_DIR / filename
    else:
        raise HTTPException(status_code=400, detail="Carpeta no permitida.")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    # Sanitización de rutas para prevenir Path Traversal
    if not target_path.resolve().is_relative_to(OUTPUT_DIR.resolve()) and not target_path.resolve().is_relative_to(DATA_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Acceso denegado.")

    media_type = "application/octet-stream"
    if filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif filename.endswith(".html"):
        media_type = "text/html"

    return FileResponse(
        path=str(target_path),
        filename=filename,
        media_type=media_type
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)
