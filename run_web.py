"""
Lanzador de la Plataforma Web de Intervals Fit Analytics.
Inicia el servidor local FastAPI con Uvicorn y abre automáticamente el navegador.
"""

import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import subprocess
from pathlib import Path

# Auto-detección y re-ejecución transparente con el entorno virtual del proyecto (.venv)
_ROOT_DIR = Path(__file__).resolve().parent
_VENV_BIN = "Scripts" if sys.platform == "win32" else "bin"
_PYTHON_EXE = "python.exe" if sys.platform == "win32" else "python"
_VENV_PYTHON = _ROOT_DIR / ".venv" / _VENV_BIN / _PYTHON_EXE
if _VENV_PYTHON.exists():
    try:
        if Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
            res = subprocess.run([str(_VENV_PYTHON)] + sys.argv, cwd=str(_ROOT_DIR))
            sys.exit(res.returncode)
    except Exception:
        pass

import time
import argparse
import webbrowser
import threading

if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

import uvicorn


def abrir_navegador(url: str, delay: float = 1.2):
    """Abre el navegador web tras un breve retardo para asegurar que el servidor esté listo."""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"ℹ️ Abre en tu navegador: {url}")


def main():
    parser = argparse.ArgumentParser(
        prog="run_web",
        description="Lanza la plataforma web de análisis de ciclismo Intervals Fit Analytics"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host de escucha (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Puerto de escucha (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="No abrir automáticamente el navegador")
    parser.add_argument("--reload", action="store_true", help="Habilitar autoreload para desarrollo")

    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    print("=" * 65)
    print("🚴 INTERVALS FIT ANALYTICS - PLATAFORMA PRO CYCLING")
    print("=" * 65)
    print(f"🚀 Servidor iniciado en: {url}")
    print("📊 Dashboard, Perfiles Interactivos, Power Reports y Gestión de Equipo.")
    print("💡 Pulsa Ctrl+C en cualquier momento para detener el servidor.")
    print("=" * 65 + "\n")

    if not args.no_browser:
        t = threading.Thread(target=abrir_navegador, args=(url,), daemon=True)
        t.start()

    uvicorn.run(
        "web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
