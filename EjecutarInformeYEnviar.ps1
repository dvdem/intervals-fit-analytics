#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('pdf', 'docx', 'ambos')]
    [string]$Formato = 'pdf'
)

$ErrorActionPreference = 'Stop'
$projectDir      = 'C:\Users\echav\OneDrive\Documentos\GitHub\procyclingstats\intervals_fit_analytics'
$credentialFile = Join-Path $projectDir '.gmail_smtp_credential.xml'
$logDir          = Join-Path $projectDir 'logs'
$logFile         = Join-Path $logDir ("informe_diario_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
$recipient       = 'davide@burgosproteam.com'

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Start-Transcript -Path $logFile -Append

try {
    $startedAt = Get-Date
    $today = Get-Date -Format 'yyyy-MM-dd'
    Set-Location -LiteralPath $projectDir

    $global:LASTEXITCODE = 0
    & (Join-Path $projectDir 'generar_perfil.ps1') -Fecha $today -Formato $Formato
    if ($LASTEXITCODE -ne 0) {
        throw "generar_perfil.ps1 finalizo con codigo $LASTEXITCODE"
    }

    # Adjunta los PDF, Word (.docx) y HTML creados o actualizados durante esta ejecucion.
    $attachments = @(Get-ChildItem -LiteralPath $projectDir -Recurse -File |
        Where-Object {
            $_.Extension -in '.pdf', '.docx', '.html' -and
            $_.LastWriteTime -ge $startedAt.AddSeconds(-2)
        } |
        Sort-Object FullName)

    if ($attachments.Count -eq 0) {
        throw 'El proceso termino, pero no se encontraron informes (PDF, Word o HTML) nuevos o actualizados.'
    }

    if (-not (Test-Path -LiteralPath $credentialFile -PathType Leaf)) {
        throw "No se encuentra la credencial de Gmail: $credentialFile"
    }

    $credential = Import-Clixml -LiteralPath $credentialFile
    $sender = $credential.UserName
    $networkCredential = $credential.GetNetworkCredential()

    $message = [System.Net.Mail.MailMessage]::new()
    $smtp = [System.Net.Mail.SmtpClient]::new('smtp.gmail.com', 587)
    try {
        $message.From = [System.Net.Mail.MailAddress]::new($sender)
        [void]$message.To.Add($recipient)
        $message.Subject = "Informe diario de perfil - $today"
        $formatosAdjuntos = ($attachments | Select-Object -ExpandProperty Extension -Unique | ForEach-Object { $_.TrimStart('.').ToUpper() }) -join ', '
        $message.Body = "Se adjuntan los informes ($formatosAdjuntos) generados el $today."
        $message.IsBodyHtml = $false
        $message.SubjectEncoding = [System.Text.Encoding]::UTF8
        $message.BodyEncoding = [System.Text.Encoding]::UTF8

        foreach ($file in $attachments) {
            [void]$message.Attachments.Add([System.Net.Mail.Attachment]::new($file.FullName))
        }

        $smtp.EnableSsl = $true
        $smtp.UseDefaultCredentials = $false
        $smtp.Credentials = $networkCredential
        $smtp.Timeout = 120000
        $smtp.Send($message)
    }
    finally {
        if ($message) { $message.Dispose() }
        if ($smtp) { $smtp.Dispose() }
    }

    Write-Host "Correo enviado desde $sender a $recipient con $($attachments.Count) archivo(s)."
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Stop-Transcript
}
