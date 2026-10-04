# MME Ombor ni o'chiradi: dastur papkasi, yorliqlar va "O'rnatilgan dasturlar" ro'yxatidagi yozuv.
# Ma'lumotlar (%APPDATA%\MetallMontajExpert) ataylab qoldiriladi.
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$ShortcutFolder = '',
    [string]$RegistryName = 'MME-Ombor',
    [switch]$Quiet
)
$ErrorActionPreference = 'Stop'
$AppName = 'MME Ombor'
$Target = (Resolve-Path $Target).Path

function Finish([int]$code, [string]$message) {
    Write-Host ''
    Write-Host $message
    if (-not $Quiet) { Read-Host 'Yopish uchun Enter ni bosing' | Out-Null }
    exit $code
}

if (-not (Test-Path (Join-Path $Target 'MME-Ombor.exe'))) { Finish 1 "XATO: bu papkada MME Ombor topilmadi: $Target" }
if (-not $Quiet) {
    $answer = Read-Host "$AppName o'chirilsinmi? Ma'lumotlar saqlanib qoladi. (ha / yo'q)"
    if ($answer -notmatch '^(ha|h|y|yes|da)$') { Finish 0 'Bekor qilindi.' }
}
$installed = Join-Path $Target 'MME-Ombor.exe'
if (Get-Process -Name 'MME-Ombor' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $installed }) {
    Finish 1 'XATO: MME Ombor hozir ochiq. Uni yoping va qaytadan urinib ko''ring.'
}

$folders = if ($ShortcutFolder) { @($ShortcutFolder) } else {
    @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
}
foreach ($folder in $folders) {
    Remove-Item (Join-Path $folder "$AppName.lnk") -Force -ErrorAction SilentlyContinue
}
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$RegistryName" -Recurse -Force -ErrorAction SilentlyContinue
try {
    Remove-Item $Target -Recurse -Force
} catch {
    Finish 1 "Dastur papkasini to'liq o'chirib bo'lmadi: $Target"
}
Finish 0 "$AppName o'chirildi. Ma'lumotlar joyida qoldi: $env:APPDATA\MetallMontajExpert"
