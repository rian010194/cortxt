[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({
        $parsedChannelId = [guid]::Empty
        [guid]::TryParse($_, [ref]$parsedChannelId)
    })]
    [string]$ChannelId,

    [string]$DefinitionsPath,

    [string]$BuzzExe,

    [switch]$Apply,

    [switch]$Enable
)

$ErrorActionPreference = 'Stop'

if (-not $DefinitionsPath) {
    $DefinitionsPath = Join-Path $PSScriptRoot '..\definitions'
}
if (-not $BuzzExe) {
    $BuzzExe = Join-Path $env:LOCALAPPDATA 'Buzz\buzz.exe'
}

function Get-WorkflowName {
    param([Parameter(Mandatory = $true)][string]$Content)

    $match = [regex]::Match($Content, '(?m)^name:\s*([^#\r\n]+?)\s*$')
    if (-not $match.Success) {
        throw 'Workflow definition is missing a top-level name.'
    }
    return $match.Groups[1].Value.Trim(' ', "'", '"')
}

function Test-WorkflowDefinition {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $content = Get-Content -Raw -LiteralPath $File.FullName
    $name = Get-WorkflowName -Content $content
    foreach ($required in @('enabled: false', 'on: message_posted', 'action: send_message')) {
        if (-not $content.Contains($required)) {
            throw "$($File.Name): missing required value '$required'."
        }
    }
    if (-not $content.Contains('filter:')) {
        throw "$($File.Name): an unfiltered message trigger is forbidden."
    }
    return [pscustomobject]@{ Name = $name; File = $File; Content = $content }
}

$definitionFiles = @(Get-ChildItem -LiteralPath $DefinitionsPath -Filter '*.yaml' -File | Sort-Object Name)
if ($definitionFiles.Count -eq 0) {
    throw "No workflow definitions found in $DefinitionsPath."
}

$definitions = @($definitionFiles | ForEach-Object { Test-WorkflowDefinition -File $_ })
$duplicateNames = @($definitions | Group-Object Name | Where-Object Count -gt 1)
if ($duplicateNames.Count -gt 0) {
    throw "Duplicate workflow names: $($duplicateNames.Name -join ', ')."
}

if (-not $Apply) {
    $definitions | ForEach-Object {
        [pscustomobject]@{ action = 'validate_only'; workflow = $_.Name; enabled = $false; file = $_.File.FullName }
    } | ConvertTo-Json
    exit 0
}

if ($env:BUZZ_WORKFLOW_APPLY_APPROVED -ne 'true') {
    throw 'Set BUZZ_WORKFLOW_APPLY_APPROVED=true through the approved operator environment before -Apply.'
}
if (-not $env:BUZZ_PRIVATE_KEY) {
    throw 'BUZZ_PRIVATE_KEY is required at runtime and must not be stored in the repository.'
}
if ($Enable -and $env:BUZZ_WORKFLOW_ENABLE_APPROVED -ne 'true') {
    throw 'Set BUZZ_WORKFLOW_ENABLE_APPROVED=true before using -Enable.'
}
if (-not (Test-Path -LiteralPath $BuzzExe -PathType Leaf)) {
    throw "Buzz CLI was not found at $BuzzExe."
}

$remoteJson = & $BuzzExe workflows list --channel $ChannelId
if ($LASTEXITCODE -ne 0) {
    throw "Buzz workflow listing failed with exit code $LASTEXITCODE."
}
$remoteWorkflows = @(($remoteJson | ConvertFrom-Json) | Where-Object { $null -ne $_ })
$remoteByName = @{}
foreach ($remote in $remoteWorkflows) {
    if ([string]::IsNullOrWhiteSpace([string]$remote.content)) {
        Write-Warning "Ignoring remote workflow '$([string]$remote.workflow_id)' because its content is empty."
        continue
    }
    try {
        $remoteName = Get-WorkflowName -Content ([string]$remote.content)
        if ($remoteByName.ContainsKey($remoteName)) {
            throw "Buzz contains duplicate workflows named '$remoteName'."
        }
        $remoteByName[$remoteName] = $remote
    } catch {
        Write-Warning "Ignoring an unreadable remote workflow: $($_.Exception.Message)"
    }
}

foreach ($definition in $definitions) {
    $content = $definition.Content
    if ($Enable) {
        $content = $content -replace '(?m)^enabled:\s*false\s*$', 'enabled: true'
    }

    # Buzz CLI's --yaml argument accepts inline YAML or '-' for stdin. A file
    # path is treated as literal YAML, so stream the definition explicitly.
    if ($remoteByName.ContainsKey($definition.Name)) {
        $workflowId = [string]$remoteByName[$definition.Name].workflow_id
        $content | & $BuzzExe workflows update --channel $ChannelId --workflow $workflowId --yaml -
        if ($LASTEXITCODE -ne 0) {
            throw "Updating '$($definition.Name)' failed with exit code $LASTEXITCODE."
        }
        Write-Output "updated $($definition.Name) ($workflowId)"
    } else {
        $content | & $BuzzExe workflows create --channel $ChannelId --yaml -
        if ($LASTEXITCODE -ne 0) {
            throw "Creating '$($definition.Name)' failed with exit code $LASTEXITCODE."
        }
        Write-Output "created $($definition.Name)"
    }
}
