<#
.SYNOPSIS
  List / clean up Clarivo voice-agent processes.

.DESCRIPTION
  More than one agent process must NEVER run at the same time. They all register
  with LiveKit under the same agent_name ("clarivo-inbound"), so LiveKit hands an
  incoming call to WHICHEVER one it picks. A stale process then answers using its
  own (old) .env config, and its logs go to a terminal you may have already closed,
  which looks like "the call cut itself" or "my changes did nothing".

  The usual cause: the run wrapper
      while ($true) { & '.venv\Scripts\python.exe' main.py dev; Start-Sleep 2 }
  keeps living in a closed terminal. Killing only python.exe makes the wrapper
  relaunch it about 2s later, so the wrapper (the parent shell) must go too.

.PARAMETER Kill
  Terminate the agent processes found (and their parent wrapper shells).

.PARAMETER KeepNewest
  With -Kill, keep the most recently started agent and kill only the older ones.
  Use this when a good agent is already running and you just want the orphans gone.

.EXAMPLE
  # Just look (safe, changes nothing)
  powershell -ExecutionPolicy Bypass -File agent\agent-procs.ps1

.EXAMPLE
  # Kill every agent, then start a fresh one yourself
  powershell -ExecutionPolicy Bypass -File agent\agent-procs.ps1 -Kill

.EXAMPLE
  # Keep the newest agent, remove the stale ones
  powershell -ExecutionPolicy Bypass -File agent\agent-procs.ps1 -Kill -KeepNewest
#>
[CmdletBinding()]
param(
  [switch]$Kill,
  [switch]$KeepNewest
)

$ErrorActionPreference = 'Stop'

function Get-AgentProcs {
  # Matches the agent worker only: python running "main.py" from the agent folder.
  # The backend (uvicorn backend.app:app) is python too, so it is excluded on purpose.
  @(
    Get-CimInstance Win32_Process |
      Where-Object {
        $_.Name -eq 'python.exe' -and
        $_.CommandLine -and
        $_.CommandLine -match 'main\.py' -and
        $_.CommandLine -notmatch 'uvicorn'
      } |
      Sort-Object CreationDate
  )
}

$startCmd = "  cd agent; while (`$true) { & '.venv\Scripts\python.exe' main.py dev; Start-Sleep -Seconds 2 }"

# @() is required: a function returning a single object gets unwrapped by PowerShell,
# and .Count would then be blank instead of 1.
$agents = @(Get-AgentProcs)

if ($agents.Count -eq 0) {
  Write-Host "No voice-agent process is running." -ForegroundColor Yellow
  Write-Host "Start one with:"
  Write-Host $startCmd
  return
}

Write-Host ""
Write-Host ("Found {0} agent process(es):" -f $agents.Count) -ForegroundColor Cyan
$i = 0
foreach ($a in $agents) {
  $i++
  $tag = ''
  if ($i -eq $agents.Count) { $tag = '   <-- newest' }
  Write-Host ("  [{0}] PID {1}  parent(shell) {2}  started {3}{4}" -f $i, $a.ProcessId, $a.ParentProcessId, $a.CreationDate, $tag)
}

if ($agents.Count -gt 1) {
  Write-Host ""
  Write-Host "WARNING: more than one agent is registered with LiveKit." -ForegroundColor Red
  Write-Host "         Calls will be answered by an unpredictable one. Clean this up." -ForegroundColor Red
}

if (-not $Kill) {
  Write-Host ""
  Write-Host "Nothing changed (no -Kill given)." -ForegroundColor DarkGray
  Write-Host "  -Kill              stop all agents"
  Write-Host "  -Kill -KeepNewest  stop only the stale ones"
  return
}

# Decide what to remove.
if ($KeepNewest) {
  if ($agents.Count -gt 1) {
    $targets = $agents[0..($agents.Count - 2)]   # all except the newest
  } else {
    $targets = @()                               # only one agent, told to keep it
  }
} else {
  $targets = $agents
}

if ($targets.Count -eq 0) {
  Write-Host ""
  Write-Host "Only the newest agent is running. Nothing to clean up." -ForegroundColor Green
  return
}

Write-Host ""
foreach ($t in $targets) {
  # Kill the PARENT shell first so its `while ($true)` wrapper cannot relaunch the
  # agent, then the agent itself. /T also takes any child job processes. The parent
  # is only touched when it really is a shell, so nothing unrelated is killed.
  $parent = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $t.ParentProcessId }
  if ($parent -and $parent.Name -match '^(powershell|pwsh|cmd)\.exe$') {
    Write-Host ("Stopping wrapper shell PID {0} ({1}) ..." -f $parent.ProcessId, $parent.Name)
    & taskkill /PID $parent.ProcessId /T /F 2>&1 | Out-Null
  }

  if (Get-Process -Id $t.ProcessId -ErrorAction SilentlyContinue) {
    Write-Host ("Stopping agent PID {0} ..." -f $t.ProcessId)
    & taskkill /PID $t.ProcessId /T /F 2>&1 | Out-Null
  }
}

# A surviving wrapper respawns about 2s after its child dies, so verify after that.
Start-Sleep -Seconds 4
$left = @(Get-AgentProcs)

Write-Host ""
if ($left.Count -eq 0) {
  Write-Host "Done. No agent running now. Start a fresh one:" -ForegroundColor Green
  Write-Host $startCmd
} elseif ($left.Count -eq 1) {
  Write-Host ("Done. Exactly 1 agent running (PID {0}, started {1})." -f $left[0].ProcessId, $left[0].CreationDate) -ForegroundColor Green
} else {
  Write-Host ("Still {0} agents running. A wrapper shell is probably respawning them." -f $left.Count) -ForegroundColor Red
  foreach ($l in $left) {
    Write-Host ("  PID {0}  parent {1}  started {2}" -f $l.ProcessId, $l.ParentProcessId, $l.CreationDate)
  }
  Write-Host "Close those terminal tabs in the IDE, then re-run this script." -ForegroundColor Yellow
}
