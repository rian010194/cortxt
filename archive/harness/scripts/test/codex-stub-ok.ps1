# codex-stub-ok.ps1 — deterministic Codex stub (no model) for the adapter's
# e2e-via-test path. Spawned by codex-review-runner.ps1 via the .ps1 shim, which
# passes a clean named param (codex flags would collide with PS common
# parameters). Emulates the one output the adapter consumes: last_message.md,
# written as exact UTF-8 with a valid GODKÄND verdict. Exits 0.
#
# 'Ä' is built via [char]0xC4 so the emitted bytes are exact UTF-8 (C3 84)
# regardless of the active code page / script-file encoding.
param([string]$LastMessageOut =
    'C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane\.hermes\codex\stub-lastm.md')

if ($LastMessageOut) {
    $umlaut = [string][char]0xC4
    $lines = @(
        "- VERDICT: GODK$umlaut" + "ND",
        '- NOTERING: capability-PASS',
        '- Diff injesterad: ja - verifierad rad stub',
        '- FINDINGS:',
        '- KOSTNAD: unknown',
        '- SUMMERING: stub utfor godkanner transporten'
    )
    [System.IO.File]::WriteAllLines($LastMessageOut, $lines,
        (New-Object System.Text.UTF8Encoding($false)))
}

Write-Output 'STUB_OK_EXIT0'