$scriptPath = Join-Path $PSScriptRoot '..\scripts\Sync-BuzzWorkflows.ps1'
$channelId = '11111111-1111-1111-1111-111111111111'

Describe 'Sync-BuzzWorkflows dry run' {
    It 'validates every repository definition without requiring Buzz credentials' {
        $oldPrivateKey = $env:BUZZ_PRIVATE_KEY
        try {
            Remove-Item Env:BUZZ_PRIVATE_KEY -ErrorAction SilentlyContinue
            $result = & $scriptPath -ChannelId $channelId | ConvertFrom-Json
            $result.Count | Should Be 6
            @($result | Where-Object enabled).Count | Should Be 0
            @($result.workflow | Sort-Object -Unique).Count | Should Be 6
        } finally {
            if ($null -ne $oldPrivateKey) { $env:BUZZ_PRIVATE_KEY = $oldPrivateKey }
        }
    }

    It 'refuses apply without explicit operator approval' {
        $oldApproval = $env:BUZZ_WORKFLOW_APPLY_APPROVED
        try {
            Remove-Item Env:BUZZ_WORKFLOW_APPLY_APPROVED -ErrorAction SilentlyContinue
            { & $scriptPath -ChannelId $channelId -Apply } |
                Should Throw
        } finally {
            if ($null -ne $oldApproval) { $env:BUZZ_WORKFLOW_APPLY_APPROVED = $oldApproval }
        }
    }
}
