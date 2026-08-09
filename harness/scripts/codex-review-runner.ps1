# codex-review-runner.ps1 - PROVEN PID-bound Codex diff-inline runnner
#
# THE single supported way to run a review on this host (Windows, codex-cli
# 0.147). General `codex exec` + prompt on stdin + `--skip-git-repo-check`
# reads the embedded diff WITHOUT needing the broken pwsh/git sandbox. This
# runner is the ONLY code path the shell adapter (`codex-review-adapter.sh`)
# may use to spawn Codex - there is no silent fallback.
#
# Safety contract (operator standing policy, 2026-08-09):
#   * run_id generated in the SHELL, never by a model (see adapter).
#   * read-only sandbox + --ephemeral; nothing persisted to a session.
#   * PID-bound process-tree timeout (Start-Process win PID + taskkill /T):
#     never matches by process name, never orphans a child.
#   * honest cost/usage: reported 'unknown' unless measured (never 0).
#   * verdict is a capability result (KRÄVER ÄNDRINGAR = PASS), NOT commit
#     approval; merge/Done stays operator-only.
#
# The transport bug this fixes (root cause, 2026-08-09): the old adapter embedded
# this loop inline via `powershell -Command` with `$MAX=$MAX_RUNTIME`, where the
# heredoc escaping left `$MAX_RUNTIME` unset in PowerShell => `$MAX=$null` =>
# `Elapsed.TotalSeconds -ge $null` is immediately true => taskkill fired ~1s after
# spawn, 0 tokens, empty files ("helper exits after a second"). Here the deadline
# is a real [int] parameter defaulting to 540.
#
# Exit code contract (2026-08-09 security rework, #70):
#   0                  child finished and exited 0 (success path for a real review
#                      = an actual model verdict, validated by the adapter)
#   <child exit code>  child finished with that exit code
#   124                child was KILLED by the process-tree timeout (distinct so
#                      the adapter maps this to envelope status "timed_out", never
#                      "succeeded"/"failed"). The verdict lives in <LastMessageOut>.
param(
    [Parameter(Mandatory=$true)][string]$CodexPath,
    [Parameter(Mandatory=$true)][string]$PromptFile,
    [Parameter(Mandatory=$true)][string]$LastMessageOut,
    [Parameter(Mandatory=$true)][string]$StdoutJson,
    [Parameter(Mandatory=$true)][string]$StderrLog,
    [Parameter(Mandatory=$false)][int]$MaxSec = 540
)

$ErrorActionPreference = 'Stop'
Remove-Item $LastMessageOut, $StdoutJson, $StderrLog -ErrorAction SilentlyContinue

# Fixed codex invocation (exec-level flags BEFORE the review path; the prompt is
# '@','-' so the brief+diff flow in on stdin).
$argsList = [System.Collections.ArrayList]@(
    'exec','--skip-git-repo-check','-m','gpt-5.6-sol','-s','read-only',
    '--ephemeral','--json','-o',$LastMessageOut,'-'
)

# Non-exe CODEX path is a stub/test wrapper (never a real review route — a real
# review always uses the .exe CLI). Launch it through a real Win32 process so
# Start-Process redirect works: a .ps1 stub via powershell -File, anything else
# via cmd.exe /c. Both are visible, tested launcher shims, NOT a silent fallback
# to another review route.
$exe = $CodexPath
if ($exe.EndsWith('.ps1', [System.StringComparison]::OrdinalIgnoreCase)) {
    # Test-stub contract (these are NEVER real reviews): the stub declares a
    # clean named param instead of parsing codex flags (which collide with
    # PS common parameters like '-o'). Real reviews always use the .exe CLI.
    $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $exe,
              '-LastMessageOut', $LastMessageOut)
    $exe = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
} elseif (-not $exe.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase)) {
    # cmd-hosted stub/wrapper (non-exe, non-ps1). Visible, tested shim.
    $argv = @('/c', $exe) + $argsList
    $exe = 'C:\Windows\System32\cmd.exe'
} else {
    $argv = $argsList
}

# Spawn via System.Diagnostics.Process (not Start-Process): the Start-Process
# cmdlet returns a NULL ExitCode whenever standard streams are redirected to
# files (verified 2026-08-09), which made the exit code unreliable and could
# turn a nonzero child into a false "0". .NET Process reads ExitCode correctly
# with redirection, and supports the same pass-through PID for taskkill /T.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
# P1 fix: never join argv with raw spaces — paths containing spaces or special
# chars would be split. Quote each argument (Windows CommandLineToArgvW rule:
# surround in double quotes, escape inner quotes by doubling) and join with a
# single space so $exe's path and every file argument survive unchanged.
function Quote-Arg([string]$a) {
    if ($a -eq '') { return '""' }
    if ($a -notmatch '[ "]') { return $a }          # no space/quote => safe as-is
    return '"' + ($a -replace '"', '""') + '"'
}
$psi.Arguments = (($argv | ForEach-Object { Quote-Arg $_ }) -join ' ')
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
$p = New-Object System.Diagnostics.Process
$p.StartInfo = $psi
$null = $p.Start()

# Feed the review brief (the embedded diff) to Codex stdin, then drain stdout
# and stderr to the run files asynchronously so a chatty model never deadlocks.
try { $p.StandardInput.AutoFlush = $true; } catch {}
try {
    $promptLines = [System.IO.File]::ReadAllLines($PromptFile)
} catch { $promptLines = @() }
if ($promptLines.Count -gt 0) {
    $p.StandardInput.Write(($promptLines -join "`n"))
}
$p.StandardInput.Close()
$outWriter = [System.IO.StreamWriter]::new($StdoutJson, $false, (New-Object System.Text.UTF8Encoding($false)))
$errWriter = [System.IO.StreamWriter]::new($StderrLog, $false, (New-Object System.Text.UTF8Encoding($false)))
$outTask  = $p.StandardOutput.BaseStream.CopyToAsync($outWriter.BaseStream)
$errTask  = $p.StandardError.BaseStream.CopyToAsync($errWriter.BaseStream)

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$timedOut = $false
while (-not $p.HasExited) {
    if ($sw.Elapsed.TotalSeconds -ge $MaxSec) {
        $timedOut = $true
        # A child can already be exiting when we kill, so taskkill's non-zero
        # exit must NOT abort the runner (which runs under 'Stop').
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & taskkill.exe /PID $p.Id /T /F 2>$null | Out-Null
        $ErrorActionPreference = $prevEAP
        Start-Sleep -Milliseconds 500
        break
    }
    Start-Sleep -Milliseconds 400
}
if (-not $p.HasExited) { $p.WaitForExit() }
$p.WaitForExit()   # flush; ensures ExitCode + async copies settle
$outTask.Wait(1000) | Out-Null; $errTask.Wait(1000) | Out-Null
$outWriter.Dispose(); $errWriter.Dispose()

$code = $null
try {
    $code = $p.ExitCode
    if ($null -eq $code -or [string]::IsNullOrEmpty("$code")) {
        $code = 1   # exit code unknown => nonsuccess (fail-closed)
    }
} catch {
    $code = 1
}

# treeGone determination, race-free: a just-exited PID can still be listed by
# Get-Process briefly, so pause and re-check twice before concluding the tree is
# gone. Never conclude "still present" from the first call alone.
Start-Sleep -Milliseconds 300
$stillPresent = [bool](Get-Process -Id $p.Id -ErrorAction SilentlyContinue)
if ($stillPresent) {
    Start-Sleep -Milliseconds 500
    $stillPresent = [bool](Get-Process -Id $p.Id -ErrorAction SilentlyContinue)
}
$treeGone = -not $stillPresent

Write-Output ("[run] pid={0} exit={1} secs={2} timeout={3} treeGone={4}" -f `
              $p.Id, $code, [int]$sw.Elapsed.TotalSeconds, $timedOut, $treeGone)

if ($timedOut) { exit 124 }   # distinct: envelope status -> timed_out (never succeeded)
exit $code