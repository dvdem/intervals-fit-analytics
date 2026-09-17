<#
.SYNOPSIS
    Script de automatización para desplegar y gestionar Intervals Fit Analytics en un VPS Oracle desde Windows.

.DESCRIPTION
    Permite validar conectividad SSH, sincronizar el código del proyecto, aprovisionar el servidor Ubuntu
    en Oracle Cloud (Swap, cortafuegos iptables, dependencias, Nginx, Systemd) y actualizarlo en un solo comando.

.PARAMETER VpsIp
    Dirección IP pública o nombre de host del VPS Oracle.

.PARAMETER SshKeyPath
    Ruta local a la clave privada SSH (archivo .key o .pem descargado de Oracle Cloud).

.PARAMETER User
    Usuario SSH en la máquina remota (por defecto: 'ubuntu').

.PARAMETER RemoteDir
    Ruta remota de instalación (por defecto: '/var/www/intervals_fit_analytics').

.PARAMETER Action
    Acción a ejecutar:
    - 'Deploy' : Sincroniza código y ejecuta el aprovisionamiento completo (primera vez o reconfiguración).
    - 'Update' : Sincronización rápida de cambios de código y reinicio del servicio (despliegue continuo).
    - 'Status' : Muestra el estado del servicio systemd, Nginx, memoria y puertos.
    - 'Logs'   : Muestra los últimos logs del servidor web.
    - 'Restart': Reinicia el servicio intervals-web.

.EXAMPLE
    .\deploy_to_vps.ps1 -VpsIp "129.151.22.40" -SshKeyPath "$HOME\.ssh\oracle_key.key" -Action Deploy
    .\deploy_to_vps.ps1 -VpsIp "129.151.22.40" -SshKeyPath "$HOME\.ssh\oracle_key.key" -Action Update
    .\deploy_to_vps.ps1 -VpsIp "129.151.22.40" -SshKeyPath "$HOME\.ssh\oracle_key.key" -Action Status
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = "Dirección IP pública del VPS Oracle")]
    [string]$VpsIp,

    [Parameter(Mandatory = $false, HelpMessage = "Ruta a la clave privada SSH")]
    [string]$SshKeyPath = "",

    [Parameter(Mandatory = $false)]
    [string]$User = "ubuntu",

    [Parameter(Mandatory = $false)]
    [string]$RemoteDir = "/var/www/intervals_fit_analytics",

    [Parameter(Mandatory = $false)]
    [ValidateSet("Deploy", "Update", "Status", "Logs", "Restart")]
    [string]$Action = "Deploy"
)

$ErrorActionPreference = "Stop"

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "INTERVALS FIT ANALYTICS - GESTOR DE DESPLIEGUE ORACLE VPS" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

# 1. Validar herramientas locales requeridas
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Error "No se encontró el cliente 'ssh' en el sistema Windows."
    exit 1
}
if (-not (Get-Command tar -ErrorAction SilentlyContinue)) {
    Write-Error "No se encontró la utilidad 'tar' en Windows."
    exit 1
}

# 2. Función para normalizar permisos de clave SSH en Windows
function Fix-SshKeyPermissions([string]$KeyPath) {
    try {
        $SshDir = Join-Path $env:USERPROFILE ".ssh"
        if (-not (Test-Path $SshDir)) {
            New-Item -ItemType Directory -Path $SshDir -Force | Out-Null
        }
        $SafeKey = Join-Path $SshDir "oracle_vps_deploy.key"
        if (Test-Path $SafeKey) {
            & icacls $SafeKey /grant "${env:USERNAME}:F" *>$null
        }
        Copy-Item -Path $KeyPath -Destination $SafeKey -Force
        & icacls $SafeKey /inheritance:r *>$null
        & icacls $SafeKey /grant "${env:USERNAME}:F" *>$null
        return $SafeKey
    } catch {
        return $KeyPath
    }
}

# 3. Configurar argumentos SSH
$SshArgs = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10")
$CleanKeyPath = ""
if ($SshKeyPath -ne "") {
    if (-not (Test-Path $SshKeyPath)) {
        Write-Error "El archivo de clave SSH no existe en: $SshKeyPath"
        exit 1
    }
    $CleanKeyPath = Fix-SshKeyPermissions (Resolve-Path $SshKeyPath).Path
    $SshArgs += @("-i", $CleanKeyPath)
}

$RemoteTarget = "$User@$VpsIp"
Write-Host "Destino remoto: $RemoteTarget | Accion: $Action" -ForegroundColor Yellow

# 3. Probar conectividad SSH
Write-Host "Verificando conexion SSH..." -ForegroundColor Gray
$TestCmd = $SshArgs + @($RemoteTarget, "echo CONEXION_OK")
$TestOutput = & ssh @TestCmd 2>&1
if ($LASTEXITCODE -ne 0 -or ($TestOutput -notmatch "CONEXION_OK")) {
    Write-Host "Error al conectar por SSH con ${RemoteTarget}:" -ForegroundColor Red
    Write-Host "$TestOutput" -ForegroundColor Red
    Write-Host ""
    Write-Host "Revisa:" -ForegroundColor Yellow
    Write-Host "1. Que la IP sea correcta y el VPS este encendido en Oracle Cloud."
    Write-Host "2. Que la clave privada coincida con la usada al crear la instancia."
    Write-Host "3. Que el puerto 22 este permitido en la Security List de tu VCN."
    exit 1
}
Write-Host "Conexion SSH establecida correctamente." -ForegroundColor Green

# 4. Ejecución según la acción solicitada
switch ($Action) {

    "Status" {
        Write-Host "Consultando estado del servidor remoto..." -ForegroundColor Cyan
        $StatusScript = "echo '--- Servicio intervals-web ---'; sudo systemctl status intervals-web --no-pager || true; echo ''; echo '--- Memoria y Swap ---'; free -h; echo ''; echo '--- Puertos en Escucha ---'; sudo ss -tlpn | grep -E ':(80|443|8000)' || true"
        $Cmd = $SshArgs + @($RemoteTarget, $StatusScript)
        & ssh @Cmd
    }

    "Restart" {
        Write-Host "Reiniciando servicio intervals-web..." -ForegroundColor Yellow
        $RestartScript = "sudo systemctl restart intervals-web && sudo systemctl is-active intervals-web"
        $Cmd = $SshArgs + @($RemoteTarget, $RestartScript)
        & ssh @Cmd
        Write-Host "Servicio reiniciado correctamente." -ForegroundColor Green
    }

    "Logs" {
        Write-Host "Mostrando logs recientes del portal web (Ctrl+C para salir)..." -ForegroundColor Cyan
        $Cmd = $SshArgs + @($RemoteTarget, "sudo journalctl -u intervals-web -n 50 -f")
        & ssh @Cmd
    }

    { $_ -in "Deploy", "Update" } {
        Write-Host "Empaquetando codigo fuente local..." -ForegroundColor Cyan
        $BundleFile = Join-Path $PSScriptRoot "deploy_bundle.tar.gz"

        if (Test-Path $BundleFile) {
            Remove-Item -Force $BundleFile
        }

        # Generar archivo tarball excluyendo directorios innecesarios
        & tar -czf $BundleFile `
            --exclude=".venv" `
            --exclude="node_modules" `
            --exclude="__pycache__" `
            --exclude=".git" `
            --exclude="scratch" `
            --exclude="*.zip" `
            --exclude="*.exe" `
            --exclude="*.tar.gz" `
            --exclude="output/*" `
            --exclude="logs/*" `
            -C $PSScriptRoot .

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $BundleFile)) {
            Write-Error "Error al generar el archivo comprimido local."
            exit 1
        }

        $BundleSizeMb = [math]::Round(((Get-Item $BundleFile).Length / 1MB), 2)
        Write-Host "Transfiriendo paquete ($BundleSizeMb MB) al VPS..." -ForegroundColor Cyan

        # Subir mediante SCP
        $ScpArgs = @("-o", "StrictHostKeyChecking=accept-new")
        if ($CleanKeyPath -ne "") {
            $ScpArgs += @("-i", $CleanKeyPath)
        }
        $ScpArgs += @($BundleFile, "${RemoteTarget}:/tmp/deploy_bundle.tar.gz")

        & scp @ScpArgs
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -Force $BundleFile
            Write-Error "Error durante la transferencia SCP."
            exit 1
        }
        Remove-Item -Force $BundleFile

        # Descomprimir en destino y asignar permisos
        Write-Host "Extrayendo codigo en $RemoteDir..." -ForegroundColor Cyan
        $ExtractScript = "sudo mkdir -p $RemoteDir && sudo tar -xzf /tmp/deploy_bundle.tar.gz -C $RemoteDir && sudo rm -f /tmp/deploy_bundle.tar.gz && sudo chown -R ${User}:${User} $RemoteDir && sudo chmod +x $RemoteDir/deploy/*.sh"
        $Cmd = $SshArgs + @($RemoteTarget, $ExtractScript)
        & ssh @Cmd

        if ($Action -eq "Deploy") {
            Write-Host "Ejecutando aprovisionamiento del servidor (setup_vps.sh)..." -ForegroundColor Yellow
            $DeployScript = "sudo bash $RemoteDir/deploy/setup_vps.sh"
            $Cmd = $SshArgs + @($RemoteTarget, $DeployScript)
            & ssh @Cmd
        }
        else {
            Write-Host "Actualizando dependencias de Python y reiniciando servicio..." -ForegroundColor Yellow
            $UpdateScript = "cd $RemoteDir && if [ -d .venv ]; then .venv/bin/pip install --quiet --upgrade -r requirements.txt; fi && sudo systemctl restart intervals-web && sudo systemctl is-active intervals-web"
            $Cmd = $SshArgs + @($RemoteTarget, $UpdateScript)
            & ssh @Cmd
        }

        Write-Host ""
        Write-Host "====================================================================" -ForegroundColor Green
        Write-Host "OPERACION COMPLETADA CON EXITO!" -ForegroundColor Green
        Write-Host "Accede al portal en: http://$VpsIp" -ForegroundColor Green
        Write-Host "====================================================================" -ForegroundColor Green
    }
}
