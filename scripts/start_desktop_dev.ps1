param(
    [switch]$DryRun,
    [switch]$SelfTest,
    [switch]$ShowTauriConsole,
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceNeedle = $WorkspaceRoot.ToLowerInvariant()
$DebugExe = Join-Path $WorkspaceRoot "src-tauri\target\debug\anki-card-generator.exe"
$CurrentOut = Join-Path $WorkspaceRoot ".tauri-dev-current.out"
$CurrentErr = Join-Path $WorkspaceRoot ".tauri-dev-current.err"
$CurrentViteOut = Join-Path $WorkspaceRoot ".vite-dev-current.out"
$CurrentViteErr = Join-Path $WorkspaceRoot ".vite-dev-current.err"
$StartupJson = Join-Path $WorkspaceRoot ".tauri-startup-current.json"
$ExitJson = Join-Path $WorkspaceRoot ".tauri-exit-current.json"
$ExitMonitorScript = Join-Path $WorkspaceRoot ".tauri-exit-monitor-current.ps1"
$DevConfigOverride = Join-Path $WorkspaceRoot ".tauri-dev-no-before-command.json"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$StampedOut = Join-Path $WorkspaceRoot ".tauri-dev-$Stamp.out"
$StampedErr = Join-Path $WorkspaceRoot ".tauri-dev-$Stamp.err"
$StampedViteOut = Join-Path $WorkspaceRoot ".vite-dev-$Stamp.out"
$StampedViteErr = Join-Path $WorkspaceRoot ".vite-dev-$Stamp.err"
$PreferredDevPorts = @(5173, 5273, 5373, 5473, 5573, 5673, 5773, 5873, 5973)
$DevPort = $null


function Get-DevProcessSnapshot {
    try {
        $cimProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        Write-Warning ("Win32_Process snapshot unavailable; falling back to limited Get-Process data: {0}" -f $_.Exception.Message)
        return Get-Process | ForEach-Object {
            $path = ""
            try {
                $path = [string]$_.Path
            } catch {
                $path = ""
            }
            [PSCustomObject]@{
                ProcessId       = [int]$_.Id
                ParentProcessId = 0
                Name            = [string]$_.ProcessName + ".exe"
                ExecutablePath  = $path
                CommandLine     = ""
            }
        }
    }

    $cimProcesses | ForEach-Object {
        try {
            [PSCustomObject]@{
                ProcessId       = [int]$_.ProcessId
                ParentProcessId = [int]$_.ParentProcessId
                Name            = [string]$_.Name
                ExecutablePath  = [string]$_.ExecutablePath
                CommandLine     = [string]$_.CommandLine
            }
        } catch {
            $null
        }
    }
}

function Test-AnkiPathOrCommand {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $false
    }

    $value = $Text.ToLowerInvariant()
    if (-not [string]::IsNullOrWhiteSpace($WorkspaceNeedle)) {
        $value = $value.Replace($WorkspaceNeedle, "")
    }
    foreach ($needle in @(
        "\anki\",
        "\anki2\",
        "\ankiprogramfiles\",
        "/ankiprogramfiles/",
        "\program files\anki\",
        "\program files (x86)\anki\",
        "\appdata\local\programs\anki\",
        "\appdata\roaming\anki2\"
    )) {
        if ($value.Contains($needle)) {
            return $true
        }
    }
    return $false
}

function Test-ProtectedProcess {
    param([Parameter(Mandatory = $true)]$Process)

    $commandLine = if ($Process.CommandLine) { $Process.CommandLine.ToLowerInvariant() } else { "" }
    $path = if ($Process.ExecutablePath) { $Process.ExecutablePath.ToLowerInvariant() } else { "" }
    $name = if ($Process.Name) { $Process.Name.ToLowerInvariant() } else { "" }
    $combined = "$path $commandLine"

    if (@("anki.exe", "ankiw.exe", "anki-console.exe").Contains($name)) {
        return $true
    }
    if (Test-AnkiPathOrCommand $combined) {
        return $true
    }
    if (($name -eq "python.exe" -or $name -eq "pythonw.exe") -and $combined.Contains("anki")) {
        return $true
    }
    if ((@("qtwebengineprocess.exe", "mpv.exe", "msedgewebview2.exe").Contains($name)) -and (Test-AnkiPathOrCommand $combined)) {
        return $true
    }
    return $false
}

function Test-HasProtectedAncestor {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)]$ById
    )

    $cursor = $Process
    $guard = 0
    while ($ById.ContainsKey([int]$cursor.ParentProcessId) -and $guard -lt 64) {
        $cursor = $ById[[int]$cursor.ParentProcessId]
        if (Test-ProtectedProcess $cursor) {
            return $true
        }
        $guard += 1
    }
    return $false
}

function Test-WorkspaceCleanupCandidate {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)]$ById
    )

    if (Test-ProtectedProcess $Process) {
        return $false
    }
    if (Test-HasProtectedAncestor $Process $ById) {
        return $false
    }
    return $true
}

function Test-CommandLineUsesPreferredDevPort {
    param([string]$CommandLine)

    foreach ($port in $PreferredDevPorts) {
        if ($CommandLine.Contains("--port $port")) {
            return $true
        }
    }
    return $false
}
function Test-WorkspaceSeedProcess {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)]$ById
    )

    if (-not (Test-WorkspaceCleanupCandidate $Process $ById)) {
        return $false
    }

    $commandLine = if ($Process.CommandLine) { $Process.CommandLine.ToLowerInvariant() } else { "" }
    $path = if ($Process.ExecutablePath) { $Process.ExecutablePath.ToLowerInvariant() } else { "" }
    $name = if ($Process.Name) { $Process.Name.ToLowerInvariant() } else { "" }
    $debugExeLower = $DebugExe.ToLowerInvariant()

    if ($name -eq "anki-card-generator.exe" -and $path -eq $debugExeLower) {
        return $true
    }
    if (-not $commandLine.Contains($WorkspaceNeedle)) {
        return $false
    }
    if ($commandLine.Contains("run tauri:dev")) {
        return $true
    }
    if ($commandLine.Contains("npm.cmd run tauri:dev")) {
        return $true
    }
    if ($commandLine.Contains("vite") -and (Test-CommandLineUsesPreferredDevPort $commandLine)) {
        return $true
    }
    if ($commandLine.Contains("@tauri-apps") -and $commandLine.Contains(" dev")) {
        return $true
    }
    if ($commandLine.Contains("tauri") -and $commandLine.Contains(" dev")) {
        return $true
    }
    if ($commandLine.Contains("cargo") -and $commandLine.Contains(" run ")) {
        return $true
    }
    return $false
}

function Get-WorkspaceProcessTree {
    param([Parameter(Mandatory = $true)]$Snapshot)

    $byParent = @{}
    $byId = @{}
    foreach ($process in $Snapshot) {
        $processIdKey = [int]$process.ProcessId
        $parentIdKey = [int]$process.ParentProcessId
        $byId[$processIdKey] = $process
        if (-not $byParent.ContainsKey($parentIdKey)) {
            $byParent[$parentIdKey] = New-Object System.Collections.Generic.List[object]
        }
        $byParent[$parentIdKey].Add($process)
    }

    $selected = @{}
    $queue = New-Object System.Collections.Generic.Queue[object]
    foreach ($process in $Snapshot) {
        if (Test-WorkspaceSeedProcess $process $byId) {
            $selected[[int]$process.ProcessId] = $process
            $queue.Enqueue($process)
        }
    }

    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        $parentIdKey = [int]$parent.ProcessId
        if (-not $byParent.ContainsKey($parentIdKey)) {
            continue
        }
        foreach ($child in $byParent[$parentIdKey]) {
            if (-not (Test-WorkspaceCleanupCandidate $child $byId)) {
                continue
            }
            $childPid = [int]$child.ProcessId
            if (-not $selected.ContainsKey($childPid)) {
                $selected[$childPid] = $child
                $queue.Enqueue($child)
            }
        }
    }

    $selected.Values | Sort-Object ProcessId
}

function Assert-SelfTest {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw "SelfTest failed: $Message"
    }
}

function Invoke-LauncherSelfTest {
    $workspaceTauri = [PSCustomObject]@{
        ProcessId       = 1001
        ParentProcessId = 900
        Name            = "npm.cmd"
        ExecutablePath  = "C:\Windows\System32\cmd.exe"
        CommandLine     = "npm.cmd run tauri:dev --workspace $WorkspaceRoot"
    }
    $debugApp = [PSCustomObject]@{
        ProcessId       = 1002
        ParentProcessId = 1001
        Name            = "anki-card-generator.exe"
        ExecutablePath  = $DebugExe
        CommandLine     = $DebugExe
    }
    $webview = [PSCustomObject]@{
        ProcessId       = 1003
        ParentProcessId = 1002
        Name            = "msedgewebview2.exe"
        ExecutablePath  = "C:\Program Files (x86)\Microsoft\EdgeWebView\Application\msedgewebview2.exe"
        CommandLine     = "--webview-exe-name=anki-card-generator.exe --user-data-dir=$WorkspaceRoot"
    }
    $anki = [PSCustomObject]@{
        ProcessId       = 1004
        ParentProcessId = 1002
        Name            = "anki.exe"
        ExecutablePath  = "D:\Anki\anki.exe"
        CommandLine     = '"D:\Anki\anki.exe" "C:\AcgTestRuns\sample.apkg"'
    }
    $ankiWebview = [PSCustomObject]@{
        ProcessId       = 1005
        ParentProcessId = 1004
        Name            = "QtWebEngineProcess.exe"
        ExecutablePath  = "D:\Anki\QtWebEngineProcess.exe"
        CommandLine     = "D:\Anki\QtWebEngineProcess.exe --type=renderer"
    }
    $otherNode = [PSCustomObject]@{
        ProcessId       = 1006
        ParentProcessId = 900
        Name            = "node.exe"
        ExecutablePath  = "C:\Program Files\nodejs\node.exe"
        CommandLine     = "node C:\other-project\server.js"
    }

    $snapshot = @($workspaceTauri, $debugApp, $webview, $anki, $ankiWebview, $otherNode)
    $tree = @(Get-WorkspaceProcessTree $snapshot)
    $ids = @($tree | ForEach-Object { [int]$_.ProcessId })

    $idSummary = ($ids -join ",")
    Assert-SelfTest ($ids -contains 1001) "workspace tauri npm process should be selected; selected=$idSummary"
    Assert-SelfTest ($ids -contains 1002) "workspace debug app should be selected; selected=$idSummary"
    Assert-SelfTest ($ids -contains 1003) "workspace WebView child should be selected; selected=$idSummary"
    Assert-SelfTest (-not ($ids -contains 1004)) "Anki launched from the app must not be selected; selected=$idSummary"
    Assert-SelfTest (-not ($ids -contains 1005)) "Anki child processes must not be selected; selected=$idSummary"
    Assert-SelfTest (-not ($ids -contains 1006)) "unrelated Node process must not be selected; selected=$idSummary"

    $windows = @(
        [PSCustomObject]@{ Handle = "0xSTALE"; Pid = 2002; Title = "Anki 卡片生成器" },
        [PSCustomObject]@{ Handle = "0xDEBUG"; Pid = 1002; Title = "Anki 卡片生成器" }
    )
    $selectedWindow = Select-AppWindowForProcess -Windows $windows -ProcessId 1002
    Assert-SelfTest ($selectedWindow.Handle -eq "0xDEBUG") "visible app window must be selected by debug app PID, not title alone"

    $readyDetails = [PSCustomObject]@{
        vite_ready       = $true
        tauri_pid        = 1002
        webview_pid      = 1003
        tauri_process    = Select-ProcessIdentity $debugApp
        webview_process  = Select-ProcessIdentity $webview
        window           = $selectedWindow
        post_ready_probe = [PSCustomObject]@{
            tauri_still_running = $true
            vite_still_ready    = $true
        }
    }
    $readiness = New-LauncherReadinessEvidence -Status "ok" -Details $readyDetails
    Assert-SelfTest ([bool]$readiness.ready_for_release_matrix) "debug executable, WebView, PID-bound window, and stability probe should be release-matrix ready"
    Assert-SelfTest ($readiness.failed_checks.Count -eq 0) "ready launch should have no failed checks"

    $installedApp = [PSCustomObject]@{
        ProcessId       = 2002
        ParentProcessId = 1900
        Name            = "anki-card-generator.exe"
        ExecutablePath  = "C:\Users\Example\AppData\Local\Anki Card Generator\anki-card-generator.exe"
        CommandLine     = '"C:\Users\Example\AppData\Local\Anki Card Generator\anki-card-generator.exe"'
    }
    $staleDetails = [PSCustomObject]@{
        vite_ready       = $true
        tauri_pid        = 2002
        webview_pid      = 1003
        tauri_process    = Select-ProcessIdentity $installedApp
        webview_process  = Select-ProcessIdentity $webview
        window           = [PSCustomObject]@{ Handle = "0xSTALE"; Pid = 1002; Title = "Anki 卡片生成器" }
        post_ready_probe = [PSCustomObject]@{
            tauri_still_running = $true
            vite_still_ready    = $true
        }
    }
    $staleReadiness = New-LauncherReadinessEvidence -Status "ok" -Details $staleDetails
    Assert-SelfTest (-not [bool]$staleReadiness.ready_for_release_matrix) "installed app or stale title-only window evidence must not be release-matrix ready"
    Assert-SelfTest ($staleReadiness.failed_checks -contains "tauri_process_not_debug_executable") "installed app executable path must fail the readiness contract"
    Assert-SelfTest ($staleReadiness.failed_checks -contains "window_pid_mismatch") "title-only stale window evidence must fail the readiness contract"

    [PSCustomObject]@{
        status = "ok"
        selected_process_ids = $ids
        protected_process_ids = @(1004, 1005)
        selected_window_handle = $selectedWindow.Handle
        stale_window_pid = 2002
        debug_executable = Get-DebugExecutableIdentity
        readiness = $readiness
        stale_readiness_failed_checks = $staleReadiness.failed_checks
    }
}

function Test-WorkspaceViteProcess {
    param([Parameter(Mandatory = $true)]$Process)

    $commandLine = if ($Process.CommandLine) { $Process.CommandLine.ToLowerInvariant() } else { "" }
    return $commandLine.Contains($WorkspaceNeedle) -and
        $commandLine.Contains("vite") -and
        (Test-CommandLineUsesPreferredDevPort $commandLine)
}

function Get-ProcessDepth {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)]$ById
    )

    $depth = 0
    $cursor = $Process
    while ($ById.ContainsKey([int]$cursor.ParentProcessId)) {
        $depth += 1
        $cursor = $ById[[int]$cursor.ParentProcessId]
    }
    return $depth
}

function Stop-WorkspaceProcesses {
    param([Parameter(Mandatory = $true)]$Processes)

    $byId = @{}
    foreach ($process in $Processes) {
        $byId[$process.ProcessId] = $process
    }

    $ordered = $Processes | Sort-Object @{ Expression = { Get-ProcessDepth $_ $byId }; Descending = $true }, ProcessId
    foreach ($process in $ordered) {
        if (Test-ProtectedProcess $process) {
            Write-Host ("Skipping protected process {0} {1}" -f $process.ProcessId, $process.Name)
            continue
        }
        if ($DryRun) {
            Write-Host ("Would stop workspace process {0} {1}" -f $process.ProcessId, $process.Name)
        } else {
            Write-Host ("Stopping workspace process {0} {1}" -f $process.ProcessId, $process.Name)
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-VisibleWindowInfo {
    if (-not ("DesktopWindowProbe" -as [type])) {
        Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public static class DesktopWindowProbe {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
}
"@ -ErrorAction SilentlyContinue
    }

    $windows = New-Object System.Collections.Generic.List[object]
    [DesktopWindowProbe]::EnumWindows({
        param($hWnd, $lParam)
        if ([DesktopWindowProbe]::IsWindowVisible($hWnd)) {
            $length = [DesktopWindowProbe]::GetWindowTextLength($hWnd)
            if ($length -gt 0) {
                $text = New-Object System.Text.StringBuilder ($length + 1)
                [void][DesktopWindowProbe]::GetWindowText($hWnd, $text, $text.Capacity)
                [uint32]$windowPid = 0
                [void][DesktopWindowProbe]::GetWindowThreadProcessId($hWnd, [ref]$windowPid)
                $windows.Add([PSCustomObject]@{
                    Handle = ("0x{0:X}" -f $hWnd.ToInt64())
                    Pid    = [int]$windowPid
                    Title  = $text.ToString()
                })
            }
        }
        return $true
    }, [IntPtr]::Zero) | Out-Null

    $windows | Where-Object { $_.Title -like "*Anki 卡片生成器*" }
}

function Select-AppWindowForProcess {
    param(
        [Parameter(Mandatory = $true)]$Windows,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )

    $Windows |
        Where-Object { [int]$_.Pid -eq $ProcessId -and [string]$_.Title -like "*Anki 卡片生成器*" } |
        Select-Object -First 1
}

function Test-LocalPortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)

    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Select-DevPort {
    foreach ($candidate in $PreferredDevPorts) {
        if (Test-LocalPortAvailable -Port $candidate) {
            return $candidate
        }
    }
    throw "No available local dev port found from candidates: $($PreferredDevPorts -join ', ')."
}

function Get-DevUrl {
    if ($null -eq $DevPort) {
        throw "Dev port has not been selected."
    }
    return "http://127.0.0.1:$DevPort"
}
function Test-ViteReady {
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $DevPort -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1
    if ($listener) {
        return $true
    }

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$(Get-DevUrl)/" -TimeoutSec 2 -Proxy $null
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-DebugExecutableIdentity {
    $identity = [ordered]@{
        expected_path = $DebugExe
        exists = Test-Path -LiteralPath $DebugExe
    }
    if (-not $identity.exists) {
        return $identity
    }

    $item = Get-Item -LiteralPath $DebugExe
    $version = $item.VersionInfo
    $identity.length = $item.Length
    $identity.last_write_time = $item.LastWriteTime.ToString("o")
    $identity.sha256 = (Get-FileHash -LiteralPath $DebugExe -Algorithm SHA256).Hash
    $identity.product_version = $version.ProductVersion
    $identity.file_version = $version.FileVersion
    $identity.product_name = $version.ProductName
    $identity.file_description = $version.FileDescription
    $identity.company_name = $version.CompanyName
    return $identity
}

function Select-ProcessIdentity {
    param([object]$Process)

    if ($null -eq $Process) {
        return $null
    }

    [ordered]@{
        process_id = [int]$Process.ProcessId
        parent_process_id = [int]$Process.ParentProcessId
        name = [string]$Process.Name
        executable_path = [string]$Process.ExecutablePath
        command_line = [string]$Process.CommandLine
    }
}

function Test-SameResolvedPath {
    param(
        [string]$Actual,
        [string]$Expected
    )

    if ([string]::IsNullOrWhiteSpace($Actual) -or [string]::IsNullOrWhiteSpace($Expected)) {
        return $false
    }
    return $Actual.Trim().ToLowerInvariant() -eq $Expected.Trim().ToLowerInvariant()
}

function New-LauncherReadinessEvidence {
    param(
        [string]$Status,
        [object]$Details
    )

    $failed = New-Object System.Collections.Generic.List[string]
    $debugIdentity = Get-DebugExecutableIdentity
    $expectedPath = [string]$debugIdentity.expected_path
    $tauriProcess = $Details.tauri_process
    $webviewProcess = $Details.webview_process
    $window = $Details.window
    $postReadyProbe = $Details.post_ready_probe

    if ($Status -ne "ok") {
        $failed.Add("launcher_status_not_ok")
    }
    if (-not [bool]$debugIdentity.exists) {
        $failed.Add("debug_executable_missing")
    }
    if (-not [bool]$Details.vite_ready) {
        $failed.Add("vite_not_ready")
    }
    if ($null -eq $tauriProcess) {
        $failed.Add("debug_tauri_process_missing")
    } else {
        if (-not (Test-SameResolvedPath -Actual ([string]$tauriProcess.executable_path) -Expected $expectedPath)) {
            $failed.Add("tauri_process_not_debug_executable")
        }
        if ($null -eq $Details.tauri_pid -or [int]$tauriProcess.process_id -ne [int]$Details.tauri_pid) {
            $failed.Add("tauri_pid_mismatch")
        }
    }
    if ($null -eq $webviewProcess -or $null -eq $Details.webview_pid) {
        $failed.Add("webview_process_missing")
    }
    if ($null -eq $window) {
        $failed.Add("pid_bound_window_missing")
    } else {
        if ($null -eq $Details.tauri_pid -or [int]$window.Pid -ne [int]$Details.tauri_pid) {
            $failed.Add("window_pid_mismatch")
        }
        if (-not ([string]$window.Title -like "*Anki 卡片生成器*")) {
            $failed.Add("window_title_mismatch")
        }
    }
    if ($null -eq $postReadyProbe) {
        $failed.Add("post_ready_probe_missing")
    } else {
        if (-not [bool]$postReadyProbe.tauri_still_running) {
            $failed.Add("tauri_not_running_after_probe")
        }
        if (-not [bool]$postReadyProbe.vite_still_ready) {
            $failed.Add("vite_not_ready_after_probe")
        }
    }

    [ordered]@{
        schema_version = 1
        ready_for_release_matrix = ($failed.Count -eq 0)
        failed_checks = @($failed)
        expected_debug_executable = $expectedPath
        debug_executable_exists = [bool]$debugIdentity.exists
        debug_executable_sha256 = if ($debugIdentity.Contains("sha256")) { $debugIdentity.sha256 } else { $null }
        vite_ready = [bool]$Details.vite_ready
        vite_still_ready = if ($postReadyProbe) { [bool]$postReadyProbe.vite_still_ready } else { $false }
        tauri_pid = $Details.tauri_pid
        tauri_executable_path = if ($tauriProcess) { [string]$tauriProcess.executable_path } else { $null }
        tauri_is_expected_debug_executable = if ($tauriProcess) { Test-SameResolvedPath -Actual ([string]$tauriProcess.executable_path) -Expected $expectedPath } else { $false }
        tauri_still_running = if ($postReadyProbe) { [bool]$postReadyProbe.tauri_still_running } else { $false }
        webview_pid = $Details.webview_pid
        window_pid = if ($window) { [int]$window.Pid } else { $null }
        window_title = if ($window) { [string]$window.Title } else { $null }
        window_bound_to_tauri_pid = if ($window -and $Details.tauri_pid) { [int]$window.Pid -eq [int]$Details.tauri_pid } else { $false }
    }
}

function Write-LauncherSummary {
    param(
        [string]$Status,
        [object]$Details
    )

    $summary = [ordered]@{
        schema_version = 1
        source = "scripts/start_desktop_dev.ps1"
        status = $Status
        workspace = $WorkspaceRoot
        timestamp = (Get-Date).ToString("o")
        debug_executable = Get-DebugExecutableIdentity
        readiness = New-LauncherReadinessEvidence -Status $Status -Details $Details
        details = $Details
    }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $WorkspaceRoot ".tauri-launch-current.json") -Encoding UTF8
}

function Update-StampedLogs {
    Copy-Item -LiteralPath $CurrentOut -Destination $StampedOut -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $CurrentErr -Destination $StampedErr -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $CurrentViteOut -Destination $StampedViteOut -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $CurrentViteErr -Destination $StampedViteErr -Force -ErrorAction SilentlyContinue
}

trap {
    Update-StampedLogs
    Write-LauncherSummary "error" @{
        message = $_.Exception.Message
        script_line = $_.InvocationInfo.ScriptLineNumber
        command = $_.InvocationInfo.Line
    }
    if (-not $DryRun) {
        try {
            $snapshot = Get-DevProcessSnapshot
            $workspaceProcesses = @(Get-WorkspaceProcessTree $snapshot)
            if ($workspaceProcesses.Count -gt 0) {
                Stop-WorkspaceProcesses $workspaceProcesses
            }
        } catch {
            Write-Warning ("Failed to clean workspace process tree after launcher error: {0}" -f $_.Exception.Message)
        }
    }
    Write-Error $_
    exit 1
}

if ($SelfTest) {
    $result = Invoke-LauncherSelfTest
    $result | ConvertTo-Json -Depth 4
    exit 0
}

function Repair-ProcessPathEnvironment {
    $processEnvironment = [System.Environment]::GetEnvironmentVariables("Process")
    $pathEntries = @()
    foreach ($key in $processEnvironment.Keys) {
        $keyText = [string]$key
        if ($keyText.Equals("Path", [System.StringComparison]::OrdinalIgnoreCase)) {
            $pathEntries += [PSCustomObject]@{
                Key = $keyText
                Value = [string]$processEnvironment[$key]
            }
        }
    }

    if ($pathEntries.Count -le 1) {
        return
    }

    $preferred = $pathEntries | Where-Object { $_.Key -ceq "Path" } | Select-Object -First 1
    if ($null -eq $preferred) {
        $preferred = $pathEntries | Select-Object -First 1
    }

    foreach ($entry in $pathEntries) {
        [System.Environment]::SetEnvironmentVariable($entry.Key, $null, "Process")
    }
    [System.Environment]::SetEnvironmentVariable("Path", $preferred.Value, "Process")
}

Repair-ProcessPathEnvironment

Write-Host "Workspace: $WorkspaceRoot"

$DevPort = Select-DevPort
$DevUrl = Get-DevUrl
Write-Host "Initial dev server candidate: $DevUrl"

$snapshot = Get-DevProcessSnapshot
$workspaceProcesses = @(Get-WorkspaceProcessTree $snapshot)

$portConnections = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $DevPort -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" -or $_.State -eq "Established" })

$blocked = @()
foreach ($connection in $portConnections) {
    $owner = $snapshot | Where-Object { $_.ProcessId -eq [int]$connection.OwningProcess } | Select-Object -First 1
    if ($null -eq $owner -or -not (Test-WorkspaceViteProcess $owner)) {
        $blocked += [PSCustomObject]@{
            OwningProcess = [int]$connection.OwningProcess
            State = $connection.State
            ProcessName = if ($owner) { $owner.Name } else { "<unknown>" }
            CommandLine = if ($owner) { $owner.CommandLine } else { "<not visible>" }
        }
    }
}

if ($blocked.Count -gt 0) {
    Write-LauncherSummary "blocked_by_non_workspace_port_owner" $blocked
    $blocked | Format-Table -AutoSize
    throw "Port 127.0.0.1:$DevPort is owned by a non-workspace process. Close it manually or choose another port."
}

if ($workspaceProcesses.Count -gt 0) {
    Write-Host "Workspace dev processes:"
    $workspaceProcesses | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-Table -AutoSize
    Stop-WorkspaceProcesses $workspaceProcesses
    if (-not $DryRun) {
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host "No workspace dev processes found."
}

if ($DryRun) {
    Write-LauncherSummary "dry_run" @{
        workspace_process_count = $workspaceProcesses.Count
        workspace_processes = @($workspaceProcesses | ForEach-Object { Select-ProcessIdentity $_ })
    }
    Write-Host "DryRun complete. No processes were stopped and the app was not started."
    exit 0
}

$DevPort = Select-DevPort
$DevUrl = Get-DevUrl
Write-Host "Using dev server: $DevUrl"

"" | Set-Content -LiteralPath $CurrentOut -Encoding UTF8
"" | Set-Content -LiteralPath $CurrentErr -Encoding UTF8
"" | Set-Content -LiteralPath $CurrentViteOut -Encoding UTF8
"" | Set-Content -LiteralPath $CurrentViteErr -Encoding UTF8
"" | Set-Content -LiteralPath $StartupJson -Encoding UTF8

$devConfigJson = @"
{
  "build": {
    "beforeDevCommand": null,
    "devUrl": "$DevUrl"
  }
}
"@
$devConfigJson | Set-Content -LiteralPath $DevConfigOverride -Encoding UTF8

$viteArgs = @("exec", "vite", "--", "--host", "127.0.0.1", "--port", [string]$DevPort, "--strictPort")
Write-Host "Starting npm.cmd exec vite on $DevUrl"
$viteProcess = Start-Process -FilePath "npm.cmd" `
    -ArgumentList $viteArgs `
    -WorkingDirectory $WorkspaceRoot `
    -RedirectStandardOutput $CurrentViteOut `
    -RedirectStandardError $CurrentViteErr `
    -WindowStyle Hidden `
    -PassThru

$viteDeadline = (Get-Date).AddSeconds([Math]::Min($TimeoutSeconds, 30))
while ((Get-Date) -lt $viteDeadline -and -not (Test-ViteReady)) {
    Start-Sleep -Seconds 1
    if ($viteProcess.HasExited) {
        Update-StampedLogs
        Write-LauncherSummary "vite_failed" @{
            vite_pid = $viteProcess.Id
            exit_code = $viteProcess.ExitCode
            stdout = $CurrentViteOut
            stderr = $CurrentViteErr
        }
        throw "Vite dev server exited before becoming ready. Check .vite-dev-current.out and .vite-dev-current.err."
    }
}

if (-not (Test-ViteReady)) {
    Update-StampedLogs
    Write-LauncherSummary "vite_timeout" @{
        vite_pid = $viteProcess.Id
        stdout = $CurrentViteOut
        stderr = $CurrentViteErr
    }
    throw "Vite dev server did not become ready on $(Get-DevUrl) within the startup timeout."
}

$tauriArgs = @("exec", "tauri", "dev", "--", "--config", $DevConfigOverride)
$tauriWindowStyle = if ($ShowTauriConsole) { "Normal" } else { "Hidden" }
Write-Host "Starting npm.cmd exec tauri dev with detached Vite"
if ($ShowTauriConsole) {
    Write-Host "Tauri console window is visible for this debug run."
} else {
    Write-Host "Tauri console window is hidden; logs are still written to .tauri-dev-current.out/.err."
}
$process = Start-Process -FilePath "npm.cmd" `
    -ArgumentList $tauriArgs `
    -WorkingDirectory $WorkspaceRoot `
    -RedirectStandardOutput $CurrentOut `
    -RedirectStandardError $CurrentErr `
    -WindowStyle $tauriWindowStyle `
    -PassThru

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$viteReady = $false
$tauriProcess = $null
$webviewProcess = $null
$windowInfo = $null

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $snapshot = Get-DevProcessSnapshot

    if (-not $viteReady) {
        $viteReady = Test-ViteReady
    }

    $tauriProcess = $snapshot |
        Where-Object {
            $processPath = if ($_.ExecutablePath) { $_.ExecutablePath.ToLowerInvariant() } else { "" }
            $_.Name -eq "anki-card-generator.exe" -and
            ($processPath -eq $DebugExe.ToLowerInvariant())
        } |
        Select-Object -First 1

    if ($tauriProcess) {
        $webviewProcess = $snapshot |
            Where-Object {
                $processCommandLine = if ($_.CommandLine) { $_.CommandLine } else { "" }
                $_.Name -eq "msedgewebview2.exe" -and
                (($_.ParentProcessId -eq $tauriProcess.ProcessId) -or $processCommandLine.Contains("--webview-exe-name=anki-card-generator.exe"))
            } |
            Select-Object -First 1
    }

    $visibleWindows = @(Get-VisibleWindowInfo)
    if ($tauriProcess) {
        $windowInfo = Select-AppWindowForProcess -Windows $visibleWindows -ProcessId ([int]$tauriProcess.ProcessId)
    }
    if ($viteReady -and $tauriProcess -and $webviewProcess -and $windowInfo) {
        break
    }
}

$details = [ordered]@{
    npm_pid = $process.Id
    vite_pid = $viteProcess.Id
    vite_ready = [bool]$viteReady
    tauri_pid = if ($tauriProcess) { $tauriProcess.ProcessId } else { $null }
    webview_pid = if ($webviewProcess) { $webviewProcess.ProcessId } else { $null }
    tauri_process = Select-ProcessIdentity $tauriProcess
    webview_process = Select-ProcessIdentity $webviewProcess
    window = if ($windowInfo) { $windowInfo } else { $null }
    stdout = $CurrentOut
    stderr = $CurrentErr
    vite_stdout = $CurrentViteOut
    vite_stderr = $CurrentViteErr
    timestamp_stdout = $StampedOut
    timestamp_stderr = $StampedErr
    timestamp_vite_stdout = $StampedViteOut
    timestamp_vite_stderr = $StampedViteErr
    startup_diagnostics = $StartupJson
}

if (-not ($viteReady -and $tauriProcess -and $webviewProcess -and $windowInfo)) {
    Update-StampedLogs
    Write-LauncherSummary "failed" $details
    Write-Warning "Desktop startup did not reach a visible window within $TimeoutSeconds seconds."
    Write-Warning "Check .tauri-dev-current.out, .tauri-dev-current.err, .tauri-startup-current.json, and .tauri-launch-current.json."

    $snapshot = Get-DevProcessSnapshot
    $workspaceProcesses = @(Get-WorkspaceProcessTree $snapshot)
    if ($workspaceProcesses.Count -gt 0) {
        Stop-WorkspaceProcesses $workspaceProcesses
    }
    exit 1
}

Start-Sleep -Seconds 10
$postReadySnapshot = Get-DevProcessSnapshot
$tauriStillRunning = $false
$viteStillReady = Test-ViteReady
if ($tauriProcess) {
    $tauriStillRunning = [bool]($postReadySnapshot | Where-Object { $_.ProcessId -eq $tauriProcess.ProcessId } | Select-Object -First 1)
}

if (-not ($tauriStillRunning -and $viteStillReady)) {
    Update-StampedLogs
    $details.post_ready_probe = @{
        tauri_still_running = $tauriStillRunning
        vite_still_ready = $viteStillReady
    }
    Write-LauncherSummary "failed_after_ready_probe" $details
    Write-Warning "Desktop app became ready but did not survive the 10 second stability probe."

    $snapshot = Get-DevProcessSnapshot
    $workspaceProcesses = @(Get-WorkspaceProcessTree $snapshot)
    if ($workspaceProcesses.Count -gt 0) {
        Stop-WorkspaceProcesses $workspaceProcesses
    }
    exit 1
}

$details.post_ready_probe = @{
    tauri_still_running = $tauriStillRunning
    vite_still_ready = $viteStillReady
}

$monitorScript = @'
param(
    [Parameter(Mandatory = $true)][int]$TauriPid,
    [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
    [Parameter(Mandatory = $true)][string]$ExitJson,
    [Parameter(Mandatory = $true)][string]$TauriStdout,
    [Parameter(Mandatory = $true)][string]$TauriStderr,
    [Parameter(Mandatory = $true)][string]$ViteStdout,
    [Parameter(Mandatory = $true)][string]$ViteStderr
)
$ErrorActionPreference = "SilentlyContinue"
function Get-TextTail {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Lines = 80
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    return @(Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue)
}

function Get-JsonContent {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    } catch {
        return [ordered]@{
            parse_error = $_.Exception.Message
            raw_tail = Get-TextTail -Path $Path -Lines 40
        }
    }
}

$exitCode = $null
$wait_error = $null
try {
    $process = [System.Diagnostics.Process]::GetProcessById($TauriPid)
    $process.WaitForExit()
    $exitCode = $process.ExitCode
} catch {
    $wait_error = $_.Exception.Message
    while ($true) {
        Start-Sleep -Seconds 5
        $process = Get-Process -Id $TauriPid -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            break
        }
    }
}

$jobBreadcrumbPath = Join-Path $WorkspaceRoot ".tauri-job-current.json"
$rendererErrorPath = Join-Path $WorkspaceRoot ".renderer-error-current.json"
$workerProgressPath = Join-Path $WorkspaceRoot ".worker-progress-current.log"
$workerStderrPath = Join-Path $WorkspaceRoot ".worker-stderr-current.log"
$workerStdoutPath = Join-Path $WorkspaceRoot ".worker-stdout-current.log"
$payload = [ordered]@{
    schema_version = 1
    source = "scripts/start_desktop_dev.ps1 monitor"
    status = "tauri_exited"
    tauri_pid = $TauriPid
    exit_code = $exitCode
    wait_error = $wait_error
    recorded_at = (Get-Date).ToString("o")
    workspace = $WorkspaceRoot
    logs = [ordered]@{
        tauri_stdout = $TauriStdout
        tauri_stderr = $TauriStderr
        vite_stdout = $ViteStdout
        vite_stderr = $ViteStderr
        job_breadcrumb = $jobBreadcrumbPath
        renderer_error = $rendererErrorPath
        worker_progress = $workerProgressPath
        worker_stderr = $workerStderrPath
        worker_stdout = $workerStdoutPath
    }
    job_breadcrumb_exists = Test-Path -LiteralPath $jobBreadcrumbPath
    renderer_error_exists = Test-Path -LiteralPath $rendererErrorPath
    worker_progress_tail = Get-TextTail -Path $workerProgressPath -Lines 40
    worker_stderr_tail = Get-TextTail -Path $workerStderrPath -Lines 80
    worker_stdout_tail = Get-TextTail -Path $workerStdoutPath -Lines 40
    job_breadcrumb = Get-JsonContent -Path $jobBreadcrumbPath
    renderer_error = Get-JsonContent -Path $rendererErrorPath
}
$payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ExitJson -Encoding UTF8
'@
$monitorScript | Set-Content -LiteralPath $ExitMonitorScript -Encoding UTF8
$monitorProcess = Start-Process -FilePath "powershell" `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $ExitMonitorScript,
        "-TauriPid",
        [string]$tauriProcess.ProcessId,
        "-WorkspaceRoot",
        $WorkspaceRoot,
        "-ExitJson",
        $ExitJson,
        "-TauriStdout",
        $CurrentOut,
        "-TauriStderr",
        $CurrentErr,
        "-ViteStdout",
        $CurrentViteOut,
        "-ViteStderr",
        $CurrentViteErr
    ) `
    -WindowStyle Hidden `
    -PassThru
$details.exit_monitor_pid = $monitorProcess.Id

Update-StampedLogs
Write-LauncherSummary "ok" $details
Write-Host "Desktop app is ready."
Write-Host ("Window: {0} PID {1}" -f $windowInfo.Title, $windowInfo.Pid)
Write-Host "Tauri logs: $CurrentOut / $CurrentErr"
Write-Host "Vite logs: $CurrentViteOut / $CurrentViteErr"

