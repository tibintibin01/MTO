# Reapprove only the installed R4 transport for this immutable app release and
# migrate the owned daily action to the same CLI used by the desktop job.
param([Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedCommit)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$project='C:\mto';$root='C:\ProgramData\MTO\portal-publication';$name='MTO Public Portal Publisher';$smokeName='MTO Public Portal App Bridge Smoke'
$common='C:\ProgramData\MTO\release-tools\portal-publication-20261007-r4\publication_common.ps1'
if((Get-FileHash -Algorithm SHA256 -LiteralPath $common).Hash -cne 'C44DF4A1F7C5D25967C980267CD4EF469D9AA87E4C0E81E459931884634BD46A'){throw 'Installed publication utility changed.'}
. $common

function Assert-TaskIdentity {
    param($Task,[string]$Execute,[string]$Arguments,[bool]$Daily)
    $a=@($Task.Actions)
    if($a.Count -ne 1 -or $a[0].Execute -cne $Execute -or $a[0].Arguments -cne $Arguments -or $a[0].WorkingDirectory -ne 'C:\mto' -or
        $Task.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or [string]$Task.Principal.LogonType -ne 'ServiceAccount' -or
        [string]$Task.Principal.RunLevel -ne 'Highest'){throw 'Publisher task identity mismatch.'}
    $triggers=@($Task.Triggers|Where-Object {$null -ne $_})
    if(-not $Daily){if($triggers.Count){throw 'Smoke must not have triggers.'};return}
    if($triggers.Count -ne 4){throw 'Publisher trigger count changed.'}
    $times=@();foreach($t in $triggers){if($t.DaysInterval -ne 1 -or -not $t.Enabled){throw 'Publisher trigger changed.'};$times+=([datetime]::Parse($t.StartBoundary)).ToString('HH:mm')}
    if(@(Compare-Object @('00:15','06:15','12:15','18:15') @($times|Sort-Object)).Count){throw 'Publisher daily times changed.'}
}
function Assert-Receipt {
    param($State,[datetime]$After)
    if($State.owner -ne 'MTO_PORTAL_PUBLICATION_20261007' -or $State.approved_source_commit -cne $ExpectedCommit -or
        $State.last_verified.status -ne 'VERIFIED' -or $State.last_verified.mode -ne 'scheduled' -or
        $State.last_verified.source_commit -cne $ExpectedCommit -or
        $State.last_verified.verification.checksum_readback_verified -ne $true -or
        $State.last_verified.verification.expanded_bytes_readback_verified -ne $true -or
        [datetime]::Parse($State.last_verified.published_at).ToUniversalTime() -lt $After.AddSeconds(-2)){throw 'Current SYSTEM bridge receipt not verified.'}
}
function Wait-Smoke {
    param([string]$TaskName,[datetime]$Before)
    $deadline=(Get-Date).AddMinutes(10)
    do{Start-Sleep -Seconds 2;$task=Get-ScheduledTask -TaskName $TaskName -TaskPath '\';$info=Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath '\';$done=([string]$task.State -ne 'Running' -and $info.LastRunTime -gt $Before)}while(-not $done -and (Get-Date) -lt $deadline)
    if(-not $done -or $info.LastTaskResult -ne 0){throw 'SYSTEM bridge publication blocked. Keep pending files, tasks and evidence.'}
    return $info
}
$statePath=Join-Path $root 'publisher-state.json';$markerPath=Join-Path $root 'schedule-state.json';$intentPath=Join-Path $root 'app-bridge-migration.json';$lock=$null
$oldExecute=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$oldArgs='-NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\MTO\release-tools\portal-publication-20261007-r4\Run-MTO-Portal-Publisher.ps1" -Scheduled'
$newExecute='C:\mto\venv\Scripts\python.exe';$newArgs='-B -m scripts.publish_guarded_portal --mode scheduled'
try{
    $identity=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if(-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run as Administrator on the API server.'}
    foreach($p in @($root,$project,$statePath,$markerPath,$intentPath,$common)){Assert-NoLinkedPath $p}
    Assert-ProtectedEvidenceRoot $root
    $helper='C:\ProgramData\MTO\release-tools\portal-publication-20261007-r4\publish_portal_snapshot.py';Assert-NoLinkedPath $helper
    if((Get-WorkflowSha256 $helper) -cne 'A9626C2731BC5502A71EB680441F0A7A5A66E245344BE5179997061658FC5FCA'){throw 'Installed R4 transport changed.'}
    $head=(& git -C $project rev-parse HEAD);if($LASTEXITCODE -ne 0 -or $head.Trim() -cne $ExpectedCommit){throw 'Approved app source is not active.'}
    $tag=(& git -C $project rev-parse 'refs/tags/v2.1.17^{commit}');if($LASTEXITCODE -ne 0 -or $tag.Trim() -cne $ExpectedCommit){throw 'Immutable app tag mismatch.'}
    $dirty=(& git -C $project status --porcelain --untracked-files=all|Out-String).Trim();if($LASTEXITCODE -ne 0 -or $dirty){throw 'App source is not clean.'}
    $lockPath=Join-Path $root 'schedule-upgrade.lock';Assert-NoLinkedPath $lockPath
    $lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    foreach($p in @('pending.json','pending.snapshot.json.gz')){if(Test-Path -LiteralPath (Join-Path $root $p)){throw 'Pending publication requires review before migration.'}}
    $state=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8|ConvertFrom-Json
    $marker=Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8|ConvertFrom-Json
    if($state.owner -ne 'MTO_PORTAL_PUBLICATION_20261007' -or $marker.owner -ne $state.owner -or $state.schedule_approved -ne $true -or $state.scheduled_tools_revision -ne '20261007-r4'){throw 'Verified R4 owner/approval missing.'}
    if($marker.status -ne 'INSTALLED' -or -not (($marker.executable -ceq $oldExecute -and $marker.arguments -ceq $oldArgs) -or ($marker.executable -ceq $newExecute -and $marker.arguments -ceq $newArgs))){throw 'Publisher schedule marker changed.'}
    $intent=$null;if(Test-Path -LiteralPath $intentPath){$intent=Get-Content -LiteralPath $intentPath -Raw -Encoding UTF8|ConvertFrom-Json;if($intent.owner -ne $state.owner -or $intent.expected_commit -cne $ExpectedCommit){throw 'Foreign migration intent exists.'}}
    $task=Get-ScheduledTask -TaskName $name -TaskPath '\';$actual=@($task.Actions)[0]
    if($actual.Execute -ceq $newExecute -and $actual.Arguments -ceq $newArgs){if(-not $intent){throw 'New action has no approved migration intent.'};Assert-TaskIdentity $task $newExecute $newArgs $true}
    else{Assert-TaskIdentity $task $oldExecute $oldArgs $true}
    if($intent -and $intent.status -eq 'VERIFIED'){
        Assert-TaskIdentity $task $newExecute $newArgs $true
        if($marker.executable -cne $newExecute -or $marker.arguments -cne $newArgs -or $state.approved_source_commit -cne $ExpectedCommit -or $state.approved_product_version -ne '2.1.17' -or $state.approved_bridge_revision -ne 'app-guarded-publish-v1'){throw 'Completed bridge approval does not match current state.'}
        Write-Host 'APP PORTAL BRIDGE MIGRATION: ALREADY VERIFIED. No new activation or upload.';exit 0
    }
    if([string]$task.State -eq 'Running'){throw 'Daily publisher is running. Wait; it was not stopped.'}
    Write-Host 'This approves only v2.1.17 source for the immutable R4 transport and migrates the owned daily publisher action.'
    Write-Host 'Four daily triggers, original tools/evidence, API, financial records, secrets, backup and operations tasks are preserved.'
    if((Read-Host 'Type APPROVE APP PORTAL BRIDGE v2.1.17').Trim() -cne 'APPROVE APP PORTAL BRIDGE v2.1.17'){throw 'Source migration approval not supplied.'}
    if(-not $intent){
        $folder=Join-Path $root ('app-bridge-v2.1.17-'+[datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8));Assert-NoLinkedPath $folder;New-Item -ItemType Directory -Path $folder|Out-Null
        [IO.File]::Copy($statePath,(Join-Path $folder 'publisher-state-before.json'),$false);[IO.File]::Copy($markerPath,(Join-Path $folder 'schedule-state-before.json'),$false)
        [IO.File]::WriteAllText((Join-Path $folder 'publisher-before.xml'),(Export-ScheduledTask -TaskName $name -TaskPath '\'),(New-Object Text.UTF8Encoding($false)))
        $intent=[pscustomobject]@{owner=$state.owner;expected_commit=$ExpectedCommit;status='IN_PROGRESS';approved_utc=[datetime]::UtcNow.ToString('o');evidence=$folder;smoke_owned=$false};Write-PublicationJson $intent $intentPath
    }
    $folder=[IO.Path]::GetFullPath($intent.evidence)
    if((Split-Path -Parent $folder) -ne $root -or (Split-Path -Leaf $folder) -notmatch '^app-bridge-v2\.1\.17-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$'){throw 'Migration evidence escaped its owned root.'};Assert-NoLinkedPath $folder
    foreach($pair in @(@('approved_source_commit',$ExpectedCommit),@('approved_product_version','2.1.17'),@('approved_bridge_revision','app-guarded-publish-v1'))){$state|Add-Member -NotePropertyName $pair[0] -NotePropertyValue $pair[1] -Force};Write-PublicationJson $state $statePath
    $smoke=Get-ScheduledTask -TaskName $smokeName -TaskPath '\' -ErrorAction SilentlyContinue
    if($smoke){if(-not $intent.smoke_owned){throw 'Foreign bridge smoke exists.'};Assert-TaskIdentity $smoke $newExecute $newArgs $false;if([string]$smoke.State -eq 'Running'){throw 'Owned smoke still running.'}}
    else{$intent.smoke_owned=$true;Write-PublicationJson $intent $intentPath;$action=New-ScheduledTaskAction -Execute $newExecute -Argument $newArgs -WorkingDirectory $project;$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10));Register-ScheduledTask -TaskName $smokeName -TaskPath '\' -Action $action -Principal $principal -Settings $settings|Out-Null}
    $before=(Get-ScheduledTaskInfo -TaskName $smokeName -TaskPath '\').LastRunTime;$started=[datetime]::UtcNow;Start-ScheduledTask -TaskName $smokeName -TaskPath '\';[void](Wait-Smoke $smokeName $before)
    Assert-Receipt (Get-Content -LiteralPath $statePath -Raw -Encoding UTF8|ConvertFrom-Json) $started
    $task=Get-ScheduledTask -TaskName $name -TaskPath '\';if([string]$task.State -eq 'Running'){throw 'Daily task started concurrently; preserve evidence and recheck.'}
    if(@($task.Actions)[0].Execute -ceq $newExecute){Assert-TaskIdentity $task $newExecute $newArgs $true}else{Assert-TaskIdentity $task $oldExecute $oldArgs $true}
    Set-ScheduledTask -TaskName $name -TaskPath '\' -Action (New-ScheduledTaskAction -Execute $newExecute -Argument $newArgs -WorkingDirectory $project)|Out-Null
    Assert-TaskIdentity (Get-ScheduledTask -TaskName $name -TaskPath '\') $newExecute $newArgs $true
    $before=(Get-ScheduledTaskInfo -TaskName $name -TaskPath '\').LastRunTime;$started=[datetime]::UtcNow;Start-ScheduledTask -TaskName $name -TaskPath '\';$info=Wait-Smoke $name $before
    Assert-Receipt (Get-Content -LiteralPath $statePath -Raw -Encoding UTF8|ConvertFrom-Json) $started
    $marker.executable=$newExecute;$marker.arguments=$newArgs;$marker|Add-Member -NotePropertyName bridge_revision -NotePropertyValue 'app-guarded-publish-v1' -Force;Write-PublicationJson $marker $markerPath
    $smoke=Get-ScheduledTask -TaskName $smokeName -TaskPath '\';Assert-TaskIdentity $smoke $newExecute $newArgs $false;if([string]$smoke.State -eq 'Running'){throw 'Smoke still running; not removed.'};Unregister-ScheduledTask -TaskName $smokeName -TaskPath '\' -Confirm:$false
    $intent.status='VERIFIED';Write-PublicationJson $intent $intentPath
    [pscustomobject]@{Status='V2.1.17 APP PORTAL BRIDGE: SYSTEM-VERIFIED';SourceCommit=$ExpectedCommit;LastTaskResult=$info.LastTaskResult;FourDailyTriggersPreserved=$true;OriginalR4ToolsPreserved=$true;FinancialRecordsChanged=$false;OtherTasksChanged=$false;Evidence=$folder}|Format-List
}catch{[Console]::Error.WriteLine('APP BRIDGE MIGRATION: BLOCKED - '+$_.Exception.Message);[Console]::Error.WriteLine('Keep pending files, tasks and evidence. No automatic rollback or financial repair was performed.');exit 2}finally{if($lock){$lock.Dispose()}}
