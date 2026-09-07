<#
.SYNOPSIS
    Genera el perfil interactivo HTML de la etapa para la fecha especificada o la fecha actual.
.DESCRIPTION
    Ejecuta el comando interactive-profile de Intervals Fit Analytics y abre el resultado en el navegador.
.PARAMETER Fecha
    Fecha en formato YYYY-MM-DD (por defecto la fecha actual).
.PARAMETER Titulo
    Titulo personalizado para el dashboard interactivo.
.PARAMETER Todos
    Incluir a todos los atletas del equipo (incluso los marcados con carrera=0).
.PARAMETER MantenerFits
    Conservar los archivos .fit descargados en disco.
.PARAMETER NoAbrir
    No abrir automaticamente el archivo HTML en el navegador al finalizar.
.EXAMPLE
    .\generar_perfil.ps1
.EXAMPLE
    .\generar_perfil.ps1 -Fecha 2026-08-26
.EXAMPLE
    .\generar_perfil.ps1 -Fecha 2026-08-26 -Titulo "Etapa 1 - Vuelta"
#>
param (
    [string]$Fecha = (Get-Date -Format "yyyy-MM-dd"),
    [string]$Titulo  = "",
    [string]$Titulo1 = "",
    [string]$Titulo2 = "",
    [string]$Titulo3 = "",
    [switch]$Todos,
    [switch]$MantenerFits,
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
Write-Host "GENERANDO PERFIL INTERACTIVO DE ETAPA" -ForegroundColor Cyan
Write-Host "Fecha objetivo: $Fecha" -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan

$argsList = @("cli.py", "interactive-profile", "--fecha", $Fecha)

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
if ($MantenerFits) {
    $argsList += "--mantener-fits"
}

# Ejecutar el comando
& $pythonExe @argsList

if ($LASTEXITCODE -eq 0 -and (-not $NoAbrir)) {
    $outputDir = Join-Path $scriptDir "output"

    # Buscar HTMLs con sufijo _carrera_N (uno por grupo de carrera)
    $htmlsGrupo = Get-ChildItem -Path $outputDir -Filter "etapa_$($Fecha)_carrera_*.html" -ErrorAction SilentlyContinue | Sort-Object Name

    if ($htmlsGrupo.Count -gt 0) {
        foreach ($html in $htmlsGrupo) {
            $pdf = [System.IO.Path]::ChangeExtension($html.FullName, ".pdf")
            if (Test-Path $pdf) {
                Write-Host "📄 PDF disponible: $pdf" -ForegroundColor Cyan
            }
            Write-Host ""
            Write-Host "Abriendo $($html.Name) en el navegador..." -ForegroundColor Green
            Start-Process $html.FullName
            Start-Sleep -Milliseconds 500
        }
    } else {
        # Fallback: perfil único sin sufijo de grupo
        $htmlFile = Join-Path $outputDir "etapa_$Fecha.html"
        $pdfFile  = Join-Path $outputDir "etapa_$Fecha.pdf"
        if (Test-Path $pdfFile) {
            Write-Host "📄 Informe PDF disponible: $pdfFile" -ForegroundColor Cyan
        }
        if (Test-Path $htmlFile) {
            Write-Host ""
            Write-Host "Abriendo $htmlFile en el navegador..." -ForegroundColor Green
            Start-Process $htmlFile
        }
    }
}
