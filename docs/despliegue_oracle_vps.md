# Guía Definitiva de Despliegue en Oracle Cloud VPS
## Intervals Fit Analytics Platform

Esta guía describe paso a paso cómo desplegar, poner en producción y mantener la plataforma web **Intervals Fit Analytics** en un servidor virtual privado (VPS) de **Oracle Cloud Infrastructure (OCI)** utilizando el nivel gratuito permanente (**Always Free Tier**).

---

## 📋 Índice
1. [Requisitos Previos](#1-requisitos-previos)
2. [Creación de la Instancia en Oracle Cloud](#2-creación-de-la-instancia-en-oracle-cloud)
3. [Configuración del Cortafuegos en la Consola OCI](#3-configuración-del-cortafuegos-en-la-consola-oci)
4. [Despliegue Automatizado desde Windows (1 Clic)](#4-despliegue-automatizado-desde-windows-1-clic)
5. [Configuración de Credenciales (.env)](#5-configuración-de-credenciales-env)
6. [Dominio Propio y Certificado SSL HTTPS](#6-dominio-propio-y-certificado-ssl-https)
7. [Mantenimiento y Actualizaciones Continuas](#7-mantenimiento-y-actualizaciones-continuas)
8. [Resolución de Problemas Frecuentes](#8-resolución-de-problemas-frecuentes)

---

## 1. Requisitos Previos

- Una cuenta activa en [Oracle Cloud](https://cloud.oracle.com/).
- Terminal de **PowerShell** en Windows (con `ssh` y `tar` activos por defecto en Windows 10/11).
- El repositorio local de `intervals_fit_analytics`.

---

## 2. Creación de la Instancia en Oracle Cloud

1. Inicia sesión en la consola de Oracle Cloud y ve a **Compute** → **Instances** → **Create Instance**.
2. **Nombre:** Asigna un nombre (ejemplo: `intervals-analytics-vps`).
3. **Image and Shape (Imagen y Forma):**
   - **Imagen:** Selecciona **Canonical Ubuntu 22.04** o **Ubuntu 24.04**.
   - **Forma (Shape):**
     - **Opción A (Recomendada):** `Ampere` (ARM) `VM.Standard.A1.Flex` con **2 a 4 OCPUs** y **12 a 24 GB de RAM** (100% gratuito en Always Free).
     - **Opción B:** `AMD` `VM.Standard.E2.1.Micro` (1 OCPU, 1 GB RAM). *Nota: Nuestro script configurará automáticamente 2GB de Swap para garantizar estabilidad en esta opción.*
4. **Networking (Red):**
   - Selecciona la VCN por defecto.
   - Asegúrate de marcar: **Assign a public IPv4 address** (Asignar dirección IPv4 pública).
5. **Add SSH keys (Claves SSH):**
   - Selecciona **Generate a key pair for me** (Generar un par de claves para mí) y descarga la **clave privada** (archivo `.key` o `.pem`).
   - Guarda este archivo en tu equipo (ejemplo: `C:\Users\tu_usuario\.ssh\oracle_vps.key`).
6. Haz clic en **Create**. En unos minutos el estado pasará a **Running** y verás la **Public IP Address** (ejemplo: `129.151.22.40`).

---

## 3. Configuración del Cortafuegos en la Consola OCI

Por defecto, Oracle bloquea todos los puertos entrantes excepto el 22 (SSH). Para permitir tráfico web:

1. En la página de detalles de tu instancia, haz clic en el enlace de la **Subnet** (Subred) o ve a **Networking** → **Virtual Cloud Networks**.
2. Entra en tu VCN y haz clic en **Security Lists** → **Default Security List for...**.
3. En la sección **Ingress Rules** (Reglas de entrada), haz clic en **Add Ingress Rules**:
   - **Source Type:** `CIDR`
   - **Source CIDR:** `0.0.0.0/0` *(sin espacios al inicio ni al final)*
   - **IP Protocol:** `TCP`
   - **Source Port Range:** *(Dejar completamente en blanco)*
   - **Destination Port Range:** `80` *(Oracle NO admite comas como 80,443; pon solo 80)*
   - **Description:** `Permitir trafico HTTP Intervals Platform`
4. Haz clic en **Add Ingress Rules**.
*(Opcional: Si vas a usar HTTPS con dominio, añade otra regla idéntica pero con Destination Port `443`)*.

---

## 4. Despliegue Automatizado desde Windows (1 Clic)

El repositorio incluye un script en PowerShell que se encarga de todo el proceso de empaquetado, transferencia, desbloqueo del firewall interno de la VM, instalación de librerías, configuración de Nginx y del servicio Systemd.

Abre PowerShell en la raíz del proyecto y ejecuta:

```powershell
.\deploy_to_vps.ps1 -VpsIp "158.179.214.147" -SshKeyPath "C:\ssh-key-2026-09-16.key" -Action Deploy
```

### ¿Qué hace este comando automáticamente?
1. Verifica la conexión SSH con el servidor.
2. Empaqueta el código fuente excluyendo archivos locales pesados (`.venv`, cachés, logs).
3. Transfiere el código por SCP y lo descomprime en `/var/www/intervals_fit_analytics`.
4. Si la instancia tiene menos de 2.5 GB de RAM, activa **2 GB de memoria Swap** en `/swapfile`.
5. Abre los puertos 80 y 443 en las reglas `iptables` de Ubuntu y las persiste con `netfilter-persistent`.
6. Instala los paquetes nativos de Ubuntu (`python3-venv`, `libjpeg-dev`, `nginx`, `certbot`, `chromium`).
7. Crea el entorno virtual de Python e instala todas las dependencias de [requirements.txt](file:///c:/Users/echav/OneDrive/Documentos/GitHub/procyclingstats/intervals_fit_analytics/requirements.txt).
8. Registra e inicia el servicio de sistema `intervals-web` (FastAPI + Uvicorn).
9. Configura Nginx como proxy inverso con soporte para subida de FITs de hasta 50MB y timeouts de 300s.

Al finalizar, verás un mensaje verde indicando:
`🌐 Accede al portal en: http://TU_IP_PUBLICA`

---

## 5. Configuración de Credenciales (.env)

El script de instalación crea un archivo `.env` en el servidor con los valores base. Para configurar tus credenciales reales de Intervals.icu:

1. Conéctate al VPS por SSH:
   ```bash
   ssh -i "C:\ruta\hacia\tu_clave.key" ubuntu@TU_IP_PUBLICA
   ```
2. Edita el archivo `.env`:
   ```bash
   nano /var/www/intervals_fit_analytics/.env
   ```
3. Revisa y completa las variables críticas:
   ```ini
   INTERVALS_API_KEY=tu_api_key_de_intervals
   INTERVALS_ATHLETE_ID=0
   INTERVALS_BASE_URL=https://intervals.icu/api/v1

   # Opcionales para descarga de FITs directos de Strava vía sesión
   INTERVALS_LOGIN_EMAIL=tu_correo@gmail.com
   INTERVALS_LOGIN_PASSWORD=tu_password
   ```
4. Guarda los cambios con `Ctrl + O`, luego `Enter` y sal con `Ctrl + X`.
5. Reinicia el servicio para aplicar los cambios:
   ```bash
   sudo systemctl restart intervals-web
   ```

---

## 6. Dominio Propio y Certificado SSL HTTPS

Para disponer de un enlace seguro con candado verde (`https://tu-dominio.com`):

1. En tu proveedor de dominio (Cloudflare, Namecheap, GoDaddy, etc.), crea un registro DNS de tipo **A**:
   - **Tipo:** `A`
   - **Nombre:** `@` o `intervals` (ej: `intervals.tudominio.com`)
   - **Valor / IP:** Tu dirección IP pública de Oracle Cloud.
2. En el archivo `/etc/nginx/sites-available/intervals` del servidor, edita la directiva `server_name`:
   ```nginx
   server_name intervals.tudominio.com;
   ```
3. Recarga Nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
4. Emite el certificado SSL gratuito con Certbot:
   ```bash
   sudo certbot --nginx -d intervals.tudominio.com
   ```
   Certbot configurará automáticamente la renovación periódica y el desvío de HTTP a HTTPS.

---

## 7. Mantenimiento y Actualizaciones Continuas

Puedes gestionar el servidor en cualquier momento desde tu terminal local de Windows:

### Subir actualizaciones de código (Fast Update)
Si realizas cambios en el código de la web o scripts en tu ordenador:
```powershell
.\deploy_to_vps.ps1 -VpsIp "TU_IP_PUBLICA" -SshKeyPath "C:\ruta\clave.key" -Action Update
```
*Sincroniza los archivos modificados, actualiza dependencias si cambió `requirements.txt` y reinicia el servicio en 5 segundos.*

### Consultar estado de salud del servidor
```powershell
.\deploy_to_vps.ps1 -VpsIp "TU_IP_PUBLICA" -SshKeyPath "C:\ruta\clave.key" -Action Status
```
*Muestra el estado del servicio systemd, uso de CPU/RAM, memoria Swap y puertos abiertos.*

### Ver logs en tiempo real
```powershell
.\deploy_to_vps.ps1 -VpsIp "TU_IP_PUBLICA" -SshKeyPath "C:\ruta\clave.key" -Action Logs
```

### Copias de seguridad de la Base de Datos
La base de datos SQLite con el histórico del equipo se encuentra en:
`/var/www/intervals_fit_analytics/data/historico_equipo.db`

Para descargar un respaldo a tu equipo local:
```powershell
scp -i "C:\ruta\clave.key" ubuntu@TU_IP_PUBLICA:/var/www/intervals_fit_analytics/data/historico_equipo.db .\backup_historico.db
```

---

## 8. Resolución de Problemas Frecuentes

### La página web no carga (Timeout de conexión)
- **Causa 1:** Olvidaste agregar los puertos `80` y `443` en la **Security List** de la VCN en la consola web de Oracle.
- **Causa 2:** El cortafuegos `iptables` de Ubuntu en Oracle está bloqueando el tráfico. Ejecuta en el servidor:
  ```bash
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save
  ```

### Error 502 Bad Gateway en Nginx
- Significa que Uvicorn (FastAPI) no está corriendo. Comprueba el log con:
  ```bash
  sudo journalctl -u intervals-web -n 30 --no-pager
  ```
  Normalmente se debe a un error de sintaxis en `.env` o una ruta inexistente.

### Error 413 "Request Entity Too Large" al subir archivos FIT
- Nginx tiene por defecto un límite de 1MB. En nuestra configuración `deploy/nginx_intervals.conf` ya hemos establecido `client_max_body_size 50M;`. Asegúrate de no haber modificado esa directiva.
