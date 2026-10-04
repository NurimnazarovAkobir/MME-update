# MME Ombor o'rnatuvchisi: dasturni kompyuterga ko'chiradi, yorliqlar qo'yadi va uni
# Windows ning "O'rnatilgan dasturlar" ro'yxatiga yozadi (u yerdan o'chirish mumkin bo'ladi).
# Administrator huquqi kerak emas: hammasi joriy foydalanuvchi uchun o'rnatiladi.
param(
    [string]$Target = (Join-Path $env:LOCALAPPDATA 'Programs\MME-Ombor'),
    [string]$ShortcutFolder = '',          # bo'sh bo'lsa: ish stoli va "Pusk" menyusi
    [string]$RegistryName = 'MME-Ombor',   # ro'yxatdagi kalit nomi (sinov uchun o'zgartiriladi)
    [switch]$Quiet                          # oxirida tugma bosilishini kutmaydi
)
$ErrorActionPreference = 'Stop'
$AppName = 'MME Ombor'
$Exe = 'MME-Ombor.exe'
$Source = $PSScriptRoot

function Finish([int]$code, [string]$message) {
    Write-Host ''
    Write-Host $message
    if (-not $Quiet) { Read-Host 'Yopish uchun Enter ni bosing' | Out-Null }
    exit $code
}

if (-not (Test-Path (Join-Path $Source $Exe))) { Finish 1 "XATO: $Exe shu papkada topilmadi." }
# Faqat o'rnatilayotgan papkadagi nusxa ochiq bo'lsa to'xtatiladi (boshqa joydan ochilgani xalaqit bermaydi).
$installed = Join-Path $Target $Exe
if (Get-Process -Name 'MME-Ombor' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $installed }) {
    Finish 1 'XATO: MME Ombor hozir ochiq. Uni yoping va qaytadan urinib ko''ring.'
}

Write-Host "$AppName o'rnatilmoqda: $Target"
try {
    New-Item -ItemType Directory -Force $Target | Out-Null
    foreach ($file in $Exe, 'OQING.txt', 'versiya.txt', 'Ochirish.bat', 'Ochirish.ps1') {
        $path = Join-Path $Source $file
        if (Test-Path $path) { Copy-Item $path $Target -Force }
    }
} catch {
    Finish 1 "XATO: fayllarni ko'chirib bo'lmadi. $($_.Exception.Message)"
}

$program = Join-Path $Target $Exe
$folders = if ($ShortcutFolder) { @($ShortcutFolder) } else {
    @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
}
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $folders) {
    try {
        New-Item -ItemType Directory -Force $folder | Out-Null
        $link = $shell.CreateShortcut((Join-Path $folder "$AppName.lnk"))
        $link.TargetPath = $program
        $link.WorkingDirectory = $Target
        $link.Save()
    } catch {
        Write-Host "Ogohlantirish: yorliq qo'yib bo'lmadi: $folder"
    }
}

$version = '1.0'
$versionFile = Join-Path $Source 'versiya.txt'
if (Test-Path $versionFile) { $version = (Get-Content $versionFile -TotalCount 1).Trim() }
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$RegistryName"
New-Item -Path $key -Force | Out-Null
$values = @{
    DisplayName     = $AppName
    DisplayVersion  = $version
    Publisher       = 'Metall Montaj Expert'
    InstallLocation = $Target
    DisplayIcon     = $program
    UninstallString = "`"$(Join-Path $Target 'Ochirish.bat')`""
}
foreach ($name in $values.Keys) { Set-ItemProperty -Path $key -Name $name -Value $values[$name] }
Set-ItemProperty -Path $key -Name 'NoModify' -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name 'NoRepair' -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name 'EstimatedSize' -Value ([int]((Get-Item $program).Length / 1KB)) -Type DWord

Finish 0 "Tayyor. Ish stolidagi `"$AppName`" yorlig'ini oching."
