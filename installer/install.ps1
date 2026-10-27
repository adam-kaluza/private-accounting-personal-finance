# Private Accounting Personal Finance: per-user, versioned Windows installer.
# Release asset: this self-contained script is intentionally outside the app ZIP.
[CmdletBinding()]
param(
    [string]$ArchivePath,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'PrivateAccountingPersonalFinance'),
    [switch]$DesktopShortcut,
    [string]$ShortcutDirectory,
    [switch]$Launch,
    [switch]$FunctionsOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ReleaseVersion = '1.1.0'
$ArchiveSha256 = 'a49ee4459d3366eb8e2472b1e252a6e131bb616787380f3a2a77cebbc130e76e'
$ReleaseUrl = 'https://github.com/adam-kaluza/private-accounting-personal-finance/releases/download/v1.1.0/Private-Accounting-Personal-Finance-1.1.0-Windows-x64.zip'
$Edition = 'private-accounting-personal-finance'
$MaxArchiveBytes = 64MB
$MaxExpandedBytes = 256MB

function Initialize-InstallerTypes {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Add-Type -AssemblyName System.Net.Http
    if (-not ('PrivateAccountingInstaller.Native' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
namespace PrivateAccountingInstaller {
    public static class Native {
        [StructLayout(LayoutKind.Sequential)] struct Info {
            public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Creation;
            public System.Runtime.InteropServices.ComTypes.FILETIME Access;
            public System.Runtime.InteropServices.ComTypes.FILETIME Write;
            public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(IntPtr h, out Info info);
        public static uint LinkCount(string path) {
            using(var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
                Info info; if (!GetFileInformationByHandle(file.SafeFileHandle.DangerousGetHandle(), out info))
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                return info.Links;
            }
        }
    }
}
'@
    }
}

function Get-InstallerDriveType([string]$Path) {
    return (New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Path))).DriveType
}

function Assert-SafePath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path.StartsWith('\\') -or $Path.StartsWith('//')) {
        throw 'Use an absolute path on a local Windows drive.'
    }
    $full = [IO.Path]::GetFullPath($Path)
    if ((Get-InstallerDriveType $full) -notin @([IO.DriveType]::Fixed,[IO.DriveType]::Removable,[IO.DriveType]::Ram)) {
        throw 'The installer requires a local writable drive; mapped network drives are refused.'
    }
    foreach ($part in $full.Substring(3).Split('\')) {
        if ($part -match '[<>:"|?*\x00-\x1f]' -or $part.EndsWith('.') -or $part.EndsWith(' ')) {
            throw 'The installation path contains unsupported Windows filename characters.'
        }
    }
    $cursor = $full
    while ($cursor) {
        try { $attributes = [IO.File]::GetAttributes($cursor) }
        catch [IO.FileNotFoundException] { $attributes = $null }
        catch [IO.DirectoryNotFoundException] { $attributes = $null }
        if ($null -ne $attributes) {
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked or redirected installation paths are refused.' }
            if (($attributes -band [IO.FileAttributes]::Directory) -eq 0 -and [PrivateAccountingInstaller.Native]::LinkCount($cursor) -gt 1) {
                throw 'Hardlinked installation files are refused.'
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
    return $full
}

function Write-NewText([string]$Path, [string]$Text) {
    $null = Assert-SafePath $Path
    $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($Text)
    $file = New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $file.Write($bytes, 0, $bytes.Length); $file.Flush($true) } finally { $file.Dispose() }
}

function Get-StreamSha256([IO.Stream]$Stream) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}

function Get-PathSha256([string]$Path) {
    $stream = New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try { return Get-StreamSha256 $stream } finally { $stream.Dispose() }
}

function Read-SmallJson([string]$Path) {
    $null = Assert-SafePath $Path
    if (-not [IO.File]::Exists($Path) -or (New-Object IO.FileInfo($Path)).Length -gt 1MB) { throw 'The installation ownership record is missing or invalid.' }
    try { return ([IO.File]::ReadAllText($Path) | ConvertFrom-Json) }
    catch { throw 'The installation ownership record is invalid; existing files were preserved.' }
}

function Assert-ExistingText([string]$Path, [string]$Text) {
    $null = Assert-SafePath $Path
    if ([IO.Directory]::Exists($Path)) { throw 'A directory occupies the proposed launcher filename.' }
    if ([IO.File]::Exists($Path)) {
        if ((New-Object IO.FileInfo($Path)).Length -gt 16384 -or [IO.File]::ReadAllText($Path) -cne $Text) {
            throw 'An existing launcher differs from this release and was preserved. Use a separate installation folder.'
        }
    }
}

function Receive-ReleaseArchive([Uri]$Uri, [string]$Destination) {
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object Net.Http.HttpClient($handler)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('PrivateAccountingPersonalFinanceInstaller/1.1.0')
    $cancel = New-Object Threading.CancellationTokenSource
    $cancel.CancelAfter(180000)
    $response = $null
    try {
        for ($redirect = 0; $redirect -le 5; $redirect++) {
            if ($Uri.Scheme -cne 'https' -or $Uri.Host -notin @('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com')) {
                throw 'The download redirected outside the supported HTTPS GitHub release hosts.'
            }
            $response = $client.GetAsync($Uri, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cancel.Token).GetAwaiter().GetResult()
            $status = [int]$response.StatusCode
            if ($status -in @(301,302,303,307,308)) {
                if ($null -eq $response.Headers.Location -or $redirect -eq 5) { throw 'The release download redirected too many times.' }
                $Uri = New-Object Uri($Uri, $response.Headers.Location)
                $response.Dispose(); $response = $null
                continue
            }
            if ($status -ne 200) { throw 'The release download failed. Try again later or use the portable ZIP.' }
            $declared = $response.Content.Headers.ContentLength
            if ($null -ne $declared -and ($declared -lt 1 -or $declared -gt $MaxArchiveBytes)) { throw 'The release download has an unsupported size.' }
            $input = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $output = New-Object IO.FileStream($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $buffer = New-Object byte[] 65536
                [long]$total = 0
                while (($read = $input.ReadAsync($buffer, 0, $buffer.Length, $cancel.Token).GetAwaiter().GetResult()) -gt 0) {
                    $total += $read
                    if ($total -gt $MaxArchiveBytes) { throw 'The release download exceeds the supported size.' }
                    $output.Write($buffer, 0, $read)
                }
                if ($total -lt 1 -or ($null -ne $declared -and $total -ne $declared)) { throw 'The release download was incomplete.' }
                $output.Flush($true)
            } finally { $output.Dispose(); $input.Dispose() }
            return
        }
        throw 'The release download did not complete.'
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $cancel.Dispose(); $client.Dispose(); $handler.Dispose()
    }
}

function Expand-VerifiedArchive([IO.Stream]$ArchiveStream, [string]$Destination, [string]$FinalDirectory) {
    $zip = New-Object IO.Compression.ZipArchive($ArchiveStream, [IO.Compression.ZipArchiveMode]::Read, $true)
    try {
        if ($zip.Entries.Count -lt 5 -or $zip.Entries.Count -gt 512) { throw 'The release archive has an unsupported member count.' }
        $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $realFiles = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $files = New-Object Collections.Generic.List[object]
        [long]$total = 0
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            if ($name.Contains('\') -or $name -match '[<>:"|?*\x00-\x1f]' -or $name.StartsWith('/')) { throw 'An unsafe archive path was refused.' }
            $parts = $name.TrimEnd('/').Split('/')
            if ($parts.Count -lt 2 -or $parts[0] -cne 'PrivateAccounting') { throw 'The archive must contain only the PrivateAccounting application folder.' }
            foreach ($part in $parts) {
                if (-not $part -or $part -in @('.','..') -or $part.EndsWith('.') -or $part.EndsWith(' ') -or $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])(?:\..*)?$') { throw 'An unsafe Windows archive filename was refused.' }
            }
            $relative = ($parts[1..($parts.Count-1)] -join '\')
            if ($parts[1] -in @('data','workspace','exports','browser-profile','.build','.git') -or -not $seen.Add($relative)) { throw 'A private-data path or duplicate archive member was refused.' }
            $unixType = ($entry.ExternalAttributes -shr 16) -band 0xf000
            if ($unixType -notin @(0,0x8000,0x4000) -or ($entry.ExternalAttributes -band 0x400) -ne 0) { throw 'Linked or special archive entries are refused.' }
            if ($name.EndsWith('/')) { if ($entry.Length -ne 0) { throw 'An archive directory contains unexpected data.' }; continue }
            if ($unixType -eq 0x4000 -or ($entry.ExternalAttributes -band 0x10) -ne 0) { throw 'An archive directory has inconsistent metadata.' }
            if ($entry.Length -gt 64MB -or ($entry.Length -gt 0 -and ($entry.CompressedLength -eq 0 -or $entry.Length / $entry.CompressedLength -gt 200))) { throw 'An archive member exceeds the expansion limits.' }
            $total += $entry.Length
            if ($total -gt $MaxExpandedBytes) { throw 'The archive exceeds the total expansion limit.' }
            $output = [IO.Path]::GetFullPath((Join-Path $Destination $relative))
            if (-not $output.StartsWith($Destination + '\', [StringComparison]::OrdinalIgnoreCase) -or $output.Length -gt 245 -or (Join-Path $FinalDirectory $relative).Length -gt 245) { throw 'The installation path is too long or leaves its staging folder. Choose a shorter local folder.' }
            $files.Add([pscustomobject]@{ Entry=$entry; Relative=$relative; Path=$output })
            $null = $realFiles.Add($relative)
        }
        foreach ($required in @('app\launch.py','app\server.py','runtime\pythonw.exe','README.md','LICENSE')) {
            if (-not $realFiles.Contains($required)) { throw 'The release archive is missing a required application component file.' }
        }
        $null = [IO.Directory]::CreateDirectory($Destination)
        $manifest = New-Object Collections.Generic.List[object]
        foreach ($file in $files) {
            $null = Assert-SafePath $file.Path
            $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($file.Path))
            $input = $file.Entry.Open()
            $output = New-Object IO.FileStream($file.Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $buffer = New-Object byte[] 65536
                [long]$copied = 0
                while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $copied += $read
                    if ($copied -gt $file.Entry.Length -or $copied -gt 64MB) { throw 'Archive expansion exceeded the declared member size.' }
                    $output.Write($buffer, 0, $read)
                }
                if ($copied -ne $file.Entry.Length) { throw 'An archive member was incomplete.' }
                $output.Flush($true)
            } finally { $output.Dispose(); $input.Dispose() }
            $manifest.Add([pscustomobject]@{ path=$file.Relative; bytes=$copied; sha256=(Get-PathSha256 $file.Path) })
        }
        return $manifest.ToArray()
    } finally { $zip.Dispose() }
}

function Remove-OwnedStage([string]$Stage, [string]$Root) {
    $full = Assert-SafePath $Stage
    $parent = [IO.Path]::GetDirectoryName($full)
    if ($parent -ine $Root -or [IO.Path]::GetFileName($full) -notmatch '^\.install-[0-9a-f]{32}$') { throw 'Temporary cleanup refused an unexpected location.' }
    if (-not [IO.Directory]::Exists($full)) { return }
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($full)
    while ($pending.Count) {
        foreach ($path in [IO.Directory]::EnumerateFileSystemEntries($pending.Pop())) {
            $null = Assert-SafePath $path
            if ([IO.Directory]::Exists($path)) { $pending.Push($path) }
        }
    }
    Remove-Item -LiteralPath $full -Recurse -Force
}

function New-EditionShortcut([string]$Directory, [string]$Root, [string]$Version, [string]$Launcher) {
    $directory = Assert-SafePath $Directory
    if (-not [IO.Directory]::Exists($directory)) { throw 'The selected shortcut folder does not exist.' }
    $path = Join-Path $directory ("Private Accounting Personal Finance $Version.lnk")
    $null = Assert-SafePath $path
    if ([IO.File]::Exists($path) -or [IO.Directory]::Exists($path)) { return 'existing-name-preserved' }
    $shell = New-Object -ComObject WScript.Shell
    $link = $null
    try {
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = $Launcher
        $link.WorkingDirectory = $Root
        $link.Description = 'Private Accounting Personal Finance - separate local records'
        $link.Save()
        return 'created'
    } finally {
        if ($null -ne $link) { $null = [Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) }
        $null = [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
    }
}

function Move-VersionDirectory([string]$Source, [string]$Target) {
    [IO.Directory]::Move($Source, $Target)
}

function Commit-VersionDirectory([string]$Source, [string]$Target) {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $null = Assert-SafePath $Source
        $null = Assert-SafePath $Target
        if ([IO.File]::Exists($Target) -or [IO.Directory]::Exists($Target)) { throw 'The version destination appeared during installation and was preserved.' }
        try { Move-VersionDirectory $Source $Target; return }
        catch [IO.IOException] { if ($attempt -eq 19) { throw } }
        catch [UnauthorizedAccessException] { if ($attempt -eq 19) { throw } }
        Start-Sleep -Milliseconds 100
    }
}

function Invoke-PersonalFinanceInstall {
    param([string]$Root, [string]$Archive, [string]$Version, [string]$ExpectedHash, [string]$Url, [switch]$CreateShortcut, [string]$ShortcutFolder, [switch]$OpenApp)
    Initialize-InstallerTypes
    if ($Version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$' -or $ExpectedHash -notmatch '^[0-9a-fA-F]{64}$') { throw 'This installer does not contain complete release verification pins. Download the published installer.' }
    $root = (Assert-SafePath $Root).TrimEnd('\')
    if ($root.Length -lt 4 -or (Join-Path $root 'data').Length -gt 155) { throw 'Choose a shorter local installation folder so its data path is at most 155 characters.' }
    $marker = Join-Path $root '.private-accounting-install.json'
    if ([IO.Directory]::Exists($root) -and -not [IO.File]::Exists($marker)) {
        $entries = [IO.Directory]::EnumerateFileSystemEntries($root).GetEnumerator()
        try { if ($entries.MoveNext()) { throw 'The destination is not an empty folder or an owned Personal Finance installation. Existing files were preserved.' } } finally { $entries.Dispose() }
    }
    $null = [IO.Directory]::CreateDirectory($root)
    if (-not [IO.File]::Exists($marker)) { Write-NewText $marker (([ordered]@{schema=1;edition=$Edition;kind='managed-install'} | ConvertTo-Json) + "`r`n") }
    $ownership = Read-SmallJson $marker
    if ($ownership.schema -ne 1 -or $ownership.edition -cne $Edition -or $ownership.kind -cne 'managed-install') { throw 'This installation folder belongs to a different application and was preserved.' }
    $lockPath = Join-Path $root '.install.lock'
    $null = Assert-SafePath $lockPath
    $lock = New-Object IO.FileStream($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $stage = $null
    try {
        $versions = Assert-SafePath (Join-Path $root 'versions')
        $target = Assert-SafePath (Join-Path $versions $Version)
        $data = Assert-SafePath (Join-Path $root 'data')
        if ([IO.File]::Exists($data)) { throw 'A file occupies the persistent data folder name.' }
        if ($ShortcutFolder -and -not $CreateShortcut) { throw 'A shortcut folder requires the DesktopShortcut option.' }
        $launcher = Join-Path $root ("Start Personal Finance $Version.cmd")
        $launcherText = "@echo off`r`nsetlocal DisableDelayedExpansion`r`ncd /d `"%~dp0`"`r`nstart `"`" `"%~dp0versions\$Version\runtime\pythonw.exe`" `"%~dp0versions\$Version\app\launch.py`" --data-dir `"%~dp0data`"`r`nexit /b 0`r`n"
        Assert-ExistingText $launcher $launcherText
        $stage = Join-Path $root ('.install-' + [Guid]::NewGuid().ToString('N'))
        $null = Assert-SafePath $stage
        $null = [IO.Directory]::CreateDirectory($stage)
        if ($Archive) { $source = Assert-SafePath $Archive }
        else {
            $uri = [Uri]$Url
            if ($uri.Scheme -cne 'https' -or $uri.Host -cne 'github.com' -or $uri.AbsolutePath -notmatch '^/[^/]+/[^/]+/releases/download/') { throw 'The pinned release URL is invalid.' }
            $source = Join-Path $stage 'download.zip'
            Receive-ReleaseArchive $uri $source
        }
        $unpacked = Join-Path $stage 'app'
        $archiveStream = New-Object IO.FileStream($source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            if ($archiveStream.Length -gt $MaxArchiveBytes) { throw 'The release ZIP exceeds the supported size.' }
            if ((Get-StreamSha256 $archiveStream) -ine $ExpectedHash) { throw 'The release ZIP checksum does not match. Nothing was extracted or launched.' }
            $archiveStream.Position = 0
            $files = @(Expand-VerifiedArchive $archiveStream $unpacked $target)
        } finally { $archiveStream.Dispose() }
        $releaseRecord = [ordered]@{schema=1;edition=$Edition;version=$Version;archive_sha256=$ExpectedHash.ToLowerInvariant();files=$files}
        $status = 'installed'
        if ([IO.Directory]::Exists($target) -or [IO.File]::Exists($target)) {
            $record = Read-SmallJson (Join-Path $target '.installed-release.json')
            if ($record.schema -ne 1 -or $record.edition -cne $Edition -or $record.version -cne $Version -or $record.archive_sha256 -ine $ExpectedHash) { throw 'This version directory has different ownership or release contents and was preserved.' }
            foreach ($file in $files) {
                $existing = Assert-SafePath (Join-Path $target $file.path)
                if (-not [IO.File]::Exists($existing) -or (Get-PathSha256 $existing) -ine $file.sha256) { throw 'An installed application file differs from the verified release and was preserved. Use a separate installation folder.' }
            }
            $status = 'already-installed'
        } else {
            Write-NewText (Join-Path $unpacked '.installed-release.json') (($releaseRecord | ConvertTo-Json -Depth 6) + "`r`n")
            $null = [IO.Directory]::CreateDirectory($versions)
            $null = Assert-SafePath $target
            Commit-VersionDirectory $unpacked $target
        }
        if (-not [IO.File]::Exists($launcher)) { Write-NewText $launcher $launcherText }
        $null = [IO.Directory]::CreateDirectory($data)
        $shortcutStatus = 'not-requested'
        if ($CreateShortcut) {
            if (-not $ShortcutFolder) { $ShortcutFolder = [Environment]::GetFolderPath('DesktopDirectory') }
            $shortcutStatus = New-EditionShortcut $ShortcutFolder $root $Version $launcher
        }
        if ($OpenApp) {
            $python = Assert-SafePath (Join-Path $target 'runtime\pythonw.exe')
            $main = Assert-SafePath (Join-Path $target 'app\launch.py')
            $null = Start-Process -FilePath $python -ArgumentList @(('"'+$main+'"'),'--data-dir',('"'+$data+'"')) -WorkingDirectory $target -WindowStyle Hidden -PassThru
        }
        [pscustomobject]@{status=$status;version=$Version;install_dir=$target;data_dir=$data;launcher=$launcher;shortcut=$shortcutStatus;launch_requested=[bool]$OpenApp;archive_verified=$true}
    } finally {
        try { if ($stage) { Remove-OwnedStage $stage $root } } finally { $lock.Dispose() }
    }
}

if (-not $FunctionsOnly) {
    try {
        Invoke-PersonalFinanceInstall -Root $InstallRoot -Archive $ArchivePath -Version $ReleaseVersion -ExpectedHash $ArchiveSha256 -Url $ReleaseUrl -CreateShortcut:$DesktopShortcut -ShortcutFolder $ShortcutDirectory -OpenApp:$Launch
    } catch {
        [Console]::Error.WriteLine('Installation stopped: ' + $_.Exception.Message)
        exit 1
    }
}
