# codex-stub-hang.ps1 — deterministic Codex stub (no model) that never exits,
# used to verify the runner's PID-bound process-tree timeout + taskkill /T.
# Accepts (and ignores) the shim's -LastMessageOut param. Spawned via the .ps1
# shim in codex-review-runner.ps1.
param([string]$LastMessageOut = '')

Write-Output 'STUB_HANG_START'
while ($true) {
    Start-Sleep -Milliseconds 500
}