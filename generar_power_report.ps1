<#
.SYNOPSIS
    Genera el informe ejecutivo de picos de potencia y carga (CTL/ATL/TSB).
.DESCRIPTION
    Ejecuta el comando power-report de Intervals Fit Analytics en formato PDF, Word (.docx) o ambos.
.PARAMETER Carrera
    Filtrar por competición o carrera específica (ej. 'huangsan', '1', nombre o slug). Si no se indica, procesa las carreras activas del calendario.
.PARAMETER Formato
    Formato del informe: 'pdf', 'docx' o 'ambos' (por defecto: 'pdf').
.PARAMETER Titulo
    Titulo base para el informe (ej. 'Vuelta a Espana').
.PARAMETER Titulo1
    Titulo especifico para Carrera 1.
.PARAMETER Titulo2
    Titulo especifico para Carrera 2.
.PARAMETER Titulo3
    Titulo especifico para Carrera 3.
.PARAMETER Dias
    Ventana de dias para picos de potencia recientes (por defecto 30).
.PARAMETER DiasCarga
    Ventana de dias para evolucion de CTL/ATL (por defecto 60).
.PARAMETER Todos
    Incluir a todos los atletas del equipo (sin filtro de convocatoria).
.PARAMETER NoAbrir
    No abrir automaticamente los archivos generados.
.EXAMPLE
    .\generar_power_report.ps1
.EXAMPLE
    .\generar_power_report.ps1 -Formato docx
.EXAMPLE
    .\generar_power_report.ps1 -Carrera huangsan -Formato ambos
#>
[CmdletBinding()]
param (
    [string]$Carrera = '',
    [ValidateSet('pdf', 'docx', 'ambos')]
    [string]$Formato = 'pdf',
    [string]$Titulo  = '',
    [string]$Titulo1 = '',
    [string]$Titulo2 = '',
    [string]$Titulo3 = '',
    [int]$Dias = 30,
    [int]$DiasCarga = 60,
    [switch]$Todos,
    [switch]$NoAbrir
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Detectar el ejecutable de Python en el entorno virtual
$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "GENERANDO INFORME DE POTENCIAS Y CARGA (POWER-REPORT)" -ForegroundColor Cyan
Write-Host "Formato seleccionado: $Formato" -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan

$argsList = @("cli.py", "power-report", "--formato", $Formato, "--dias", "$Dias", "--dias-carga", "$DiasCarga")

if ($Carrera) {
    $argsList += @("--carrera", "$Carrera")
}
if ($Titulo) {
    $argsList += @("--titulo", $Titulo)
}
if ($Titulo1) {
    $argsList += @("--titulo-1", $Titulo1)
}
if ($Titulo2) {
    $argsList += @("--titulo-2", $Titulo2)
}
if ($Titulo3) {
    $argsList += @("--titulo-3", $Titulo3)
}
if ($Todos) {
    $argsList += "--todos"
}

# Ejecutar el comando
& $pythonExe @argsList

if ($LASTEXITCODE -eq 0 -and (-not $NoAbrir)) {
    $outputDir = Join-Path $scriptDir "output"

    $patterns = @()
    if ($Formato -in 'pdf', 'ambos') {
        $patterns += "intervals_informe*.pdf"
    }
    if ($Formato -in 'docx', 'ambos') {
        $patterns += "intervals_informe*.docx"
    }

    $archivosRecientes = @()
    $ahora = (Get-Date).AddMinutes(-5)
    foreach ($p in $patterns) {
        $archivosRecientes += Get-ChildItem -Path $outputDir -Filter $p -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $ahora }
    }

    if ($archivosRecientes.Count -gt 0) {
        foreach ($archivo in $archivosRecientes) {
            Write-Host "Abriendo $($archivo.Name)..." -ForegroundColor Green
            Start-Process $archivo.FullName
            Start-Sleep -Milliseconds 400
        }
    }
}
