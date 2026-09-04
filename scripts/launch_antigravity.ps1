<#
.SYNOPSIS
    Launch one correctly identified Antigravity IDE writer session for a Platform V2 study.

.DESCRIPTION
    The Platform V2 writer lease identifies a writer as user@host + agent + session
    (research_workflow.workspace.writer_identity). Antigravity IDE is a VS Code fork: its integrated
    terminals export only the generic vscode variables, so nothing native names the agent or a
    per-session id. This wrapper is the sanctioned launcher: it generates a fresh UUID, exports

        NT_RESEARCH_AGENT=antigravity
        NT_RESEARCH_AGENT_SESSION=<uuid>

    into the environment of the Antigravity IDE process it starts, and every terminal / agent
    command inside that instance inherits them. `python scripts/research.py ws whoami` in any
    terminal of that window then resolves agent=antigravity, session=<uuid>.

    One launch = one Antigravity IDE instance = one writer session. Antigravity IDE (like VS Code) is
    single-instance: if an instance is already running, a plain launch would open a window INSIDE the
    running instance and inherit ITS environment (the earlier session id), so a second independent
    writer session is impossible that way. Therefore:

      * default    : refuse when an Antigravity IDE instance is already running (ANTIGRAVITY_INSTANCE_ALREADY_RUNNING)
      * -Force     : open the folder as a new window of the running instance (shares its writer session; documented, recorded in the card)
      * -Isolated  : start a second, fully independent instance with its own --user-data-dir under
                     %LOCALAPPDATA%\nt_research\antigravity-sessions\<uuid> (shared extensions dir, user settings copied);
                     the new instance has its own UUID. Costs: separate window state and a fresh sign-in.

.PARAMETER Study
    Study id. The worktree ../<repo-name>-<id> (or the configured worktree_root) is opened. Mutually exclusive with -Path.
.PARAMETER Path
    Folder to open (a study worktree or a chore worktree). Default: the repository root (read-only browsing; never write studies there).
.PARAMETER Exe
    Path to "Antigravity IDE.exe". Default: %LOCALAPPDATA%\Programs\Antigravity IDE\Antigravity IDE.exe, else $env:NT_ANTIGRAVITY_EXE.

.EXAMPLE
    powershell -File scripts\launch_antigravity.ps1 -Study regime_breakout_context
    scripts\launch_antigravity.cmd -Study regime_breakout_context
#>
[CmdletBinding()]
param(
    [string]$Study,
    [string]$Path,
    [string]$Exe,
    [switch]$Force,
    [switch]$Isolated,
    [switch]$WhatIf
)
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoName = Split-Path $repoRoot -Leaf

function Card($obj) { $obj | ConvertTo-Json -Compress -Depth 4 }

# --- resolve the executable -------------------------------------------------------------------
if (-not $Exe) {
    $candidates = @(@(
        (Join-Path $env:LOCALAPPDATA "Programs\Antigravity IDE\Antigravity IDE.exe"),
        $env:NT_ANTIGRAVITY_EXE
    ) | Where-Object { $_ -and (Test-Path $_) })
    if ($candidates.Count -eq 0) { Card @{ STATUS = "FAIL"; blocker_code = "ANTIGRAVITY_EXE_NOT_FOUND"; looked_for = @((Join-Path $env:LOCALAPPDATA "Programs\Antigravity IDE\Antigravity IDE.exe"), "NT_ANTIGRAVITY_EXE") }; exit 2 }
    $Exe = $candidates[0]
}

# --- resolve the folder to open ---------------------------------------------------------------
if ($Study -and $Path) { Card @{ STATUS = "FAIL"; blocker_code = "ARGS_CONFLICT"; error = "pass -Study or -Path, not both" }; exit 2 }
if ($Study) {
    # 1) the worktree git registered for branch study/<id> (same rule as workspace._find_study_worktree)
    $Path = $null
    $wtPath = $null
    foreach ($line in (& git -C $repoRoot worktree list --porcelain 2>$null)) {
        if ($line -like "worktree *") { $wtPath = $line.Substring(9) }
        elseif ($line -eq "branch refs/heads/study/$Study" -and $wtPath) { $Path = $wtPath; break }
    }
    # 2) else the conventional path <worktree_root>/<repo-name>-<id>
    if (-not $Path) {
        $wtRoot = Split-Path $repoRoot -Parent
        $cfg = Join-Path $env:USERPROFILE ".nt_research\config.yaml"
        if (Test-Path $cfg) {
            $m = Select-String -Path $cfg -Pattern '^\s*worktree_root:\s*(.+)$' | Select-Object -First 1
            if ($m) { $wtRoot = $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'") }
        }
        $Path = Join-Path $wtRoot "$repoName-$Study"
    }
    if (-not (Test-Path $Path)) { Card @{ STATUS = "FAIL"; blocker_code = "WORKTREE_MISSING"; study_id = $Study; expected = $Path; next = "python scripts/research.py study new $Study --as antigravity (from a clean main in the canonical checkout, inside an Antigravity session)" }; exit 2 }
}
if (-not $Path) { $Path = $repoRoot }
$Path = (Resolve-Path $Path).Path

# --- identity ---------------------------------------------------------------------------------
$session = [guid]::NewGuid().ToString()
$running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "Antigravity IDE*" })
$mode = "new_instance"
$args = @("-n", "`"$Path`"")
if ($running.Count -gt 0) {
    if ($Isolated) {
        $mode = "isolated_instance"
        $udd = Join-Path $env:LOCALAPPDATA "nt_research\antigravity-sessions\$session"
        New-Item -ItemType Directory -Force (Join-Path $udd "User") | Out-Null
        $userSettings = Join-Path $env:APPDATA "Antigravity IDE\User\settings.json"
        if (Test-Path $userSettings) { Copy-Item $userSettings (Join-Path $udd "User\settings.json") -Force }
        $extDir = Join-Path $env:USERPROFILE ".antigravity-ide\extensions"
        $args = @("-n", "--user-data-dir", "`"$udd`"", "--extensions-dir", "`"$extDir`"", "`"$Path`"")
    } elseif ($Force) {
        $mode = "window_in_running_instance"
    } else {
        Card @{ STATUS = "FAIL"; blocker_code = "ANTIGRAVITY_INSTANCE_ALREADY_RUNNING"; running_pids = @($running | ForEach-Object { $_.Id });
                error = "an Antigravity IDE instance is running; a new window would inherit ITS writer session, not a fresh one";
                options = @("close the running instance and relaunch", "-Force: open as a window of the running instance (shares its session id)", "-Isolated: independent second instance with its own user-data-dir (fresh sign-in)") }
        exit 2
    }
}

$env:NT_RESEARCH_AGENT = "antigravity"
$env:NT_RESEARCH_AGENT_SESSION = $session
$card = [ordered]@{ STATUS = "OK"; agent = "antigravity"; session_id = $session; mode = $mode; path = $Path; exe = $Exe; study_id = $Study;
                    note = if ($mode -eq "window_in_running_instance") { "this window inherits the running instance's NT_RESEARCH_AGENT_SESSION; the UUID above is NOT in effect" } else { "verify inside the IDE terminal: python scripts/research.py ws whoami --expect antigravity" } }
if ($WhatIf) { $card["would_run"] = "$Exe $($args -join ' ')"; Card $card; exit 0 }
Start-Process -FilePath $Exe -ArgumentList $args | Out-Null
Card $card
