#requires -Version 5.1
<#
.SYNOPSIS
Samples CPU, private commit, and resident working sets for one or more process trees.
.DESCRIPTION
Run unelevated on Windows. OutputPath is an output directory; existing result
files are never overwritten. No process is modified, activated, stopped, or killed.
Only executable names are collected, never executable paths or command lines.

PIDs are paired with creation timestamps. Known descendants remain members after
their parent exits. New descendants are discovered from every live known member.
Sampling cannot see a process born and exited between snapshots or recover its
final CPU counters. Use ETW for complete lifecycle accounting. This collector
does not measure GPU use, VRAM, frame timing, input latency, or startup latency.
See ../docs/performance-methodology.md for those experiments.

Prepared and statically reviewed on macOS; Windows PowerShell execution is
unverified. Run a short controlled parent/child workload before baseline use.
.EXAMPLE
.\Measure-ProcessTree.ps1 -RootProcessId 1234,5678 -DurationSeconds 120 -IntervalMs 1000 -OutputPath .\results\legacy-idle-01
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [ValidateScript({ $_ -gt 0 })]
    [int[]] $RootProcessId,

    [ValidateRange(1, 86400)]
    [int] $DurationSeconds = 120,

    [ValidateRange(250, 60000)]
    [int] $IntervalMs = 1000,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $OutputPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$invariant = [System.Globalization.CultureInfo]::InvariantCulture
$utf8 = New-Object System.Text.UTF8Encoding($false)

function ConvertTo-UtcDate {
    param($Value)
    if ($Value -is [DateTime]) { return $Value.ToUniversalTime() }
    return [System.Management.ManagementDateTimeConverter]::ToDateTime([string] $Value).ToUniversalTime()
}

function Get-SafeError {
    param([System.Exception] $Exception)
    # Exception messages can contain local paths; retain only type and code.
    return ('{0}; HRESULT={1}' -f $Exception.GetType().FullName, $Exception.HResult)
}

function Get-TreeSnapshot {
    $entries = New-Object 'System.Collections.Generic.List[object]'
    $warnings = New-Object 'System.Collections.Generic.List[object]'
    $byId = @{}
    $rows = @(Get-CimInstance -ClassName Win32_Process -Property ProcessId, ParentProcessId, CreationDate, Name -ErrorAction Stop)
    foreach ($row in $rows) {
        $processId = [int] $row.ProcessId
        try {
            if ($null -eq $row.CreationDate) { throw 'CreationDate is unavailable.' }
            $created = ConvertTo-UtcDate $row.CreationDate
            # CIM timestamps have microsecond precision; PID alone is not identity.
            $creationTicks = $created.Ticks - ($created.Ticks % 10)
            $entry = [pscustomobject] @{
                Identity = ('{0}:{1}' -f $processId, $creationTicks)
                ProcessId = $processId
                ParentProcessId = [int] $row.ParentProcessId
                Name = [string] $row.Name
                CreatedUtc = $created
            }
            $entries.Add($entry)
            $byId[[string] $processId] = $entry
        }
        catch {
            $warnings.Add([pscustomobject] @{
                process_id = $processId
                status = 'creation_time_unavailable_excluded'
                error = Get-SafeError $_.Exception
            })
        }
    }
    return [pscustomobject] @{
        Entries = $entries.ToArray()
        ById = $byId
        Warnings = $warnings.ToArray()
    }
}

function Add-KnownMember {
    param($Entry, [bool] $IsRoot, [int] $SampleIndex, [string] $TimestampUtc)
    if ($known.ContainsKey($Entry.Identity)) { return }
    $known[$Entry.Identity] = [ordered] @{
        identity = $Entry.Identity
        process_id = $Entry.ProcessId
        parent_process_id_at_discovery = $Entry.ParentProcessId
        executable_name = $Entry.Name
        creation_utc = $Entry.CreatedUtc.ToString('o', $invariant)
        requested_root = $IsRoot
        first_seen_sample = $SampleIndex
        first_seen_utc = $TimestampUtc
        last_seen_utc = $TimestampUtc
        last_successful_sample = -1
        last_observed_cpu_core_seconds = $null
        observed_cpu_delta_core_seconds = 0.0
        state = 'live'
        counter_error_count = 0
    }
}

function ConvertTo-CsvField {
    param($Value)
    if ($null -eq $Value) { return '""' }
    if ($Value -is [System.IFormattable]) { $valueText = $Value.ToString($null, $invariant) }
    else { $valueText = [string] $Value }
    return ('"' + $valueText.Replace('"', '""') + '"')
}

function Write-CsvRecord {
    param([System.IO.StreamWriter] $Writer, [string[]] $Columns, $Record)
    $fields = foreach ($column in $Columns) { ConvertTo-CsvField $Record[$column] }
    $Writer.WriteLine(($fields -join ','))
}

$outputDirectory = [System.IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath))
if (Test-Path -LiteralPath $outputDirectory) {
    if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
        throw 'OutputPath must be a filesystem directory.'
    }
}
else { [void] (New-Item -ItemType Directory -Path $outputDirectory) }

$reportPath = Join-Path $outputDirectory 'report.json'
$jsonLinesPath = Join-Path $outputDirectory 'samples.jsonl'
$sampleCsvPath = Join-Path $outputDirectory 'samples.csv'
$processCsvPath = Join-Path $outputDirectory 'processes.csv'
foreach ($resultPath in @($reportPath, $jsonLinesPath, $sampleCsvPath, $processCsvPath)) {
    if (Test-Path -LiteralPath $resultPath) { throw ('Result already exists: {0}' -f $resultPath) }
}

$logicalCpuCount = [Environment]::ProcessorCount
$logicalCpuSource = 'Environment.ProcessorCount_fallback'
$metadataWarnings = New-Object 'System.Collections.Generic.List[string]'
$osMetadata = [ordered] @{ version = [Environment]::OSVersion.VersionString }
try {
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem -Property NumberOfLogicalProcessors
    if ([int] $computer.NumberOfLogicalProcessors -gt 0) {
        $logicalCpuCount = [int] $computer.NumberOfLogicalProcessors
        $logicalCpuSource = 'Win32_ComputerSystem.NumberOfLogicalProcessors'
    }
}
catch { $metadataWarnings.Add(('logical_cpu_query: ' + (Get-SafeError $_.Exception))) }
try {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -Property Caption, Version, BuildNumber, OSArchitecture
    $osMetadata = [ordered] @{
        caption = [string] $os.Caption
        version = [string] $os.Version
        build_number = [string] $os.BuildNumber
        architecture = [string] $os.OSArchitecture
    }
}
catch { $metadataWarnings.Add(('os_query: ' + (Get-SafeError $_.Exception))) }

$sampleColumns = @('sample_index', 'timestamp_utc', 'elapsed_seconds', 'interval_elapsed_seconds',
    'live_process_count', 'readable_process_count', 'private_commit_bytes_sum', 'resident_working_set_bytes_sum',
    'memory_complete_for_visible_members', 'cpu_delta_core_seconds', 'cpu_core_equivalent_percent',
    'cpu_machine_normalized_percent', 'cpu_delta_complete_for_visible_members',
    'observed_cpu_delta_core_seconds_since_baseline', 'known_identity_count', 'collection_elapsed_ms',
    'snapshot_identity_warning_count', 'counter_error_count')
$processColumns = @('sample_index', 'timestamp_utc', 'identity', 'process_id', 'parent_process_id',
    'executable_name', 'creation_utc', 'counter_timestamp_utc', 'status', 'private_commit_bytes',
    'resident_working_set_bytes', 'cpu_total_core_seconds', 'cpu_delta_core_seconds', 'handle_count',
    'thread_count', 'error')

$known = @{}
$rootIds = @($RootProcessId | Select-Object -Unique)
$rootMetadata = New-Object 'System.Collections.Generic.List[object]'
$sampleWriter = $null
$processWriter = $null
$jsonWriter = $null
$sampleCount = 0
$counterErrors = 0
$identityWarnings = 0
$observedCpuDelta = 0.0
$previousSampleSeconds = $null
$previousSampleUtc = $null
$fatalError = $null
$startedUtc = [DateTime]::UtcNow
$clock = [System.Diagnostics.Stopwatch]::StartNew()
$nextDueSeconds = 0.0

try {
    $sampleWriter = New-Object System.IO.StreamWriter($sampleCsvPath, $false, $utf8)
    $processWriter = New-Object System.IO.StreamWriter($processCsvPath, $false, $utf8)
    $jsonWriter = New-Object System.IO.StreamWriter($jsonLinesPath, $false, $utf8)
    $sampleWriter.WriteLine(($sampleColumns -join ','))
    $processWriter.WriteLine(($processColumns -join ','))

    while ($true) {
        $waitSeconds = [Math]::Min($nextDueSeconds, [double] $DurationSeconds) - $clock.Elapsed.TotalSeconds
        if ($waitSeconds -gt 0) { Start-Sleep -Milliseconds ([int] [Math]::Ceiling($waitSeconds * 1000.0)) }
        if ($sampleCount -gt 0 -and $clock.Elapsed.TotalSeconds -ge $DurationSeconds) { break }

        $sampleStartSeconds = $clock.Elapsed.TotalSeconds
        $sampleUtc = [DateTime]::UtcNow
        $timestamp = $sampleUtc.ToString('o', $invariant)
        $snapshot = Get-TreeSnapshot
        $identityWarnings += $snapshot.Warnings.Count
        $selected = @{}

        if ($sampleCount -eq 0) {
            foreach ($rootId in $rootIds) {
                $key = [string] $rootId
                if (-not $snapshot.ById.ContainsKey($key)) {
                    throw ('Root process {0} is absent or its creation time is inaccessible. Supply live roots/helpers.' -f $rootId)
                }
                $entry = $snapshot.ById[$key]
                Add-KnownMember $entry $true $sampleCount $timestamp
                $rootMetadata.Add([pscustomobject] @{
                    process_id = $entry.ProcessId
                    identity = $entry.Identity
                    executable_name = $entry.Name
                    creation_utc = $entry.CreatedUtc.ToString('o', $invariant)
                })
            }
        }

        # Seed from all surviving identities, including children of exited roots.
        foreach ($member in @($known.Values)) {
            $current = $snapshot.ById[[string] $member.process_id]
            if ($null -ne $current -and $current.Identity -eq $member.identity) {
                $selected[$current.Identity] = $current
                $member.state = 'live'
                $member.last_seen_utc = $timestamp
            }
            elseif ($null -ne $current) { $member.state = 'pid_reused_by_different_creation_time' }
            else { $member.state = 'exited_or_absent_from_snapshot' }
        }

        # Transitive closure over all roots, deduplicated by PID + creation time.
        do {
            $added = $false
            foreach ($entry in $snapshot.Entries) {
                if ($selected.ContainsKey($entry.Identity)) { continue }
                $parent = $snapshot.ById[[string] $entry.ParentProcessId]
                if ($null -ne $parent -and $selected.ContainsKey($parent.Identity) -and
                    $entry.CreatedUtc -ge $parent.CreatedUtc) {
                    $selected[$entry.Identity] = $entry
                    Add-KnownMember $entry $false $sampleCount $timestamp
                    $added = $true
                }
            }
        } while ($added)

        $privateSum = [long] 0
        $workingSetSum = [long] 0
        $cpuDeltaSum = 0.0
        $readableCount = 0
        $sampleErrors = 0
        $cpuComplete = $sampleCount -gt 0
        $intervalSeconds = $null
        if ($null -ne $previousSampleSeconds) { $intervalSeconds = $sampleStartSeconds - $previousSampleSeconds }
        $processRows = New-Object 'System.Collections.Generic.List[object]'

        foreach ($entry in @($selected.Values | Sort-Object ProcessId)) {
            $member = $known[$entry.Identity]
            $member.last_seen_utc = $timestamp
            $counters = [ordered] @{
                sample_index = $sampleCount; timestamp_utc = $timestamp
                identity = $entry.Identity; process_id = $entry.ProcessId
                parent_process_id = $entry.ParentProcessId; executable_name = $entry.Name
                creation_utc = $entry.CreatedUtc.ToString('o', $invariant)
                counter_timestamp_utc = $null; status = 'unread'; private_commit_bytes = $null
                resident_working_set_bytes = $null; cpu_total_core_seconds = $null
                cpu_delta_core_seconds = $null; handle_count = $null; thread_count = $null; error = $null
            }
            $processObject = $null
            $identityMismatch = $false
            try {
                $processObject = [System.Diagnostics.Process]::GetProcessById($entry.ProcessId)
                $processObject.Refresh()
                $actualCreated = $processObject.StartTime.ToUniversalTime()
                if ([Math]::Abs(($actualCreated - $entry.CreatedUtc).TotalMilliseconds) -gt 1.0) {
                    $identityMismatch = $true
                    throw 'Process identity changed between CIM and counter read.'
                }
                $privateBytes = [long] $processObject.PrivateMemorySize64
                $workingSetBytes = [long] $processObject.WorkingSet64
                $totalCpu = [double] $processObject.TotalProcessorTime.TotalSeconds
                $handles = [int] $processObject.HandleCount
                $threads = [int] $processObject.Threads.Count
                $counters.counter_timestamp_utc = [DateTime]::UtcNow.ToString('o', $invariant)
                $delta = $null
                if ($member.last_successful_sample -eq ($sampleCount - 1) -and $sampleCount -gt 0) {
                    $delta = $totalCpu - [double] $member.last_observed_cpu_core_seconds
                }
                elseif ($sampleCount -gt 0 -and $entry.CreatedUtc -ge $previousSampleUtc) {
                    $delta = $totalCpu
                }
                if ($null -ne $delta -and $delta -lt 0) { $delta = $null }
                if ($null -eq $delta) { $cpuComplete = $false }
                else {
                    $cpuDeltaSum += $delta
                    $member.observed_cpu_delta_core_seconds += $delta
                }
                $member.last_observed_cpu_core_seconds = $totalCpu
                $member.last_successful_sample = $sampleCount
                $counters.status = 'ok'
                $counters.private_commit_bytes = $privateBytes
                $counters.resident_working_set_bytes = $workingSetBytes
                $counters.cpu_total_core_seconds = $totalCpu
                $counters.cpu_delta_core_seconds = $delta
                $counters.handle_count = $handles
                $counters.thread_count = $threads
                $privateSum += $privateBytes
                $workingSetSum += $workingSetBytes
                $readableCount++
            }
            catch {
                $counterException = $_.Exception
                $counters.status = 'counter_read_failed_or_process_exited'
                $cause = $counterException
                while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
                if ($identityMismatch) { $counters.status = 'identity_changed_pid_reused' }
                elseif ($cause -is [System.ComponentModel.Win32Exception] -and $cause.NativeErrorCode -eq 5) {
                    $counters.status = 'access_denied'
                }
                elseif ($cause -is [System.ArgumentException]) { $counters.status = 'process_exited_before_counter_read' }
                elseif ($null -ne $processObject) {
                    try {
                        if ($processObject.HasExited) { $counters.status = 'process_exited_during_counter_read' }
                    }
                    catch { } # Preserve the original counter failure below.
                }
                $counters.error = Get-SafeError $counterException
                $member.counter_error_count++
                $sampleErrors++
                $cpuComplete = $false
            }
            finally { if ($null -ne $processObject) { $processObject.Dispose() } }
            $processRows.Add([pscustomobject] $counters)
            Write-CsvRecord $processWriter $processColumns $counters
        }

        # No final CPU read is available for members that exited since last snapshot.
        if (@($known.Values | Where-Object {
            $_.state -ne 'live' -and $_.last_successful_sample -eq ($sampleCount - 1)
        }).Count -gt 0) { $cpuComplete = $false }
        $counterErrors += $sampleErrors
        $observedCpuDelta += $cpuDeltaSum
        $corePercent = $null
        $machinePercent = $null
        if ($null -ne $intervalSeconds -and $intervalSeconds -gt 0) {
            $corePercent = 100.0 * $cpuDeltaSum / $intervalSeconds
            $machinePercent = $corePercent / $logicalCpuCount
        }
        if ($selected.Count -gt 0 -and $readableCount -eq 0) {
            $privateSum = $null; $workingSetSum = $null
            $corePercent = $null; $machinePercent = $null
        }
        $reportedCpuDelta = $null
        if ($sampleCount -gt 0 -and ($selected.Count -eq 0 -or $readableCount -gt 0)) {
            $reportedCpuDelta = $cpuDeltaSum
        }
        $sample = [ordered] @{
            sample_index = $sampleCount; timestamp_utc = $timestamp
            elapsed_seconds = $sampleStartSeconds; interval_elapsed_seconds = $intervalSeconds
            live_process_count = $selected.Count; readable_process_count = $readableCount
            private_commit_bytes_sum = $privateSum; resident_working_set_bytes_sum = $workingSetSum
            memory_complete_for_visible_members = ($readableCount -eq $selected.Count)
            cpu_delta_core_seconds = $reportedCpuDelta
            cpu_core_equivalent_percent = $corePercent; cpu_machine_normalized_percent = $machinePercent
            cpu_delta_complete_for_visible_members = $cpuComplete
            observed_cpu_delta_core_seconds_since_baseline = $observedCpuDelta
            known_identity_count = $known.Count
            collection_elapsed_ms = ($clock.Elapsed.TotalSeconds - $sampleStartSeconds) * 1000.0
            snapshot_identity_warning_count = $snapshot.Warnings.Count; counter_error_count = $sampleErrors
        }
        Write-CsvRecord $sampleWriter $sampleColumns $sample
        $jsonRecord = [ordered] @{
            sample = $sample; processes = $processRows.ToArray(); snapshot_warnings = $snapshot.Warnings
        }
        $jsonWriter.WriteLine((ConvertTo-Json -InputObject $jsonRecord -Depth 8 -Compress))
        $sampleWriter.Flush(); $processWriter.Flush(); $jsonWriter.Flush()
        $previousSampleSeconds = $sampleStartSeconds
        $previousSampleUtc = $sampleUtc
        $sampleCount++
        $intervalSecondsRequested = $IntervalMs / 1000.0
        # Skip missed deadlines; do not burst several expensive snapshots to catch up.
        $nextDueSeconds = [Math]::Max($nextDueSeconds + $intervalSecondsRequested,
            ([Math]::Floor($clock.Elapsed.TotalSeconds / $intervalSecondsRequested) + 1) * $intervalSecondsRequested)
    }
}
catch {
    $fatalError = Get-SafeError $_.Exception
    throw
}
finally {
    $clock.Stop()
    if ($null -ne $sampleWriter) { $sampleWriter.Dispose() }
    if ($null -ne $processWriter) { $processWriter.Dispose() }
    if ($null -ne $jsonWriter) { $jsonWriter.Dispose() }
    $report = [ordered] @{
        schema_version = 1
        collector = 'Measure-ProcessTree.ps1'
        verification = 'Statically reviewed on macOS; Windows execution unverified.'
        started_utc = $startedUtc.ToString('o', $invariant)
        finished_utc = [DateTime]::UtcNow.ToString('o', $invariant)
        requested_duration_seconds = $DurationSeconds
        actual_elapsed_seconds = $clock.Elapsed.TotalSeconds
        requested_interval_ms = $IntervalMs
        logical_cpu_count = $logicalCpuCount
        logical_cpu_count_source = $logicalCpuSource
        operating_system = $osMetadata
        powershell_version = $PSVersionTable.PSVersion.ToString()
        roots = $rootMetadata.ToArray()
        sample_count = $sampleCount
        known_process_identities = @($known.Values | Sort-Object process_id, creation_utc)
        observed_cpu_delta_core_seconds_since_baseline = $observedCpuDelta
        counter_error_count = $counterErrors
        snapshot_identity_warning_count = $identityWarnings
        metadata_warnings = $metadataWarnings.ToArray()
        fatal_error = $fatalError
        output_files = @('samples.csv', 'processes.csv', 'samples.jsonl', 'report.json')
        units = [ordered] @{
            private_commit_bytes = 'Process.PrivateMemorySize64; committed private virtual memory, not resident RAM.'
            resident_working_set_bytes = 'Process.WorkingSet64; summed process working sets may double-count shared pages.'
            cpu_core_seconds = 'Cumulative user + kernel CPU time; one core running for one second equals one core-second.'
            cpu_core_equivalent_percent = '100 * sum(observed CPU delta core-seconds) / actual elapsed sample seconds.'
            cpu_machine_normalized_percent = 'Core-equivalent percentage divided by logical CPU count.'
        }
        limitations = @(
            'First sample establishes CPU baseline; processes first seen later contribute lifetime CPU only when born after the previous sample.',
            'Exited identities and last observed CPU counters remain in this report, but CPU after their final read is unavailable.',
            'Transient processes between snapshots and unknown descendants of already-exited parents can be missed; use ETW for full lifecycle accounting.',
            'PID reuse is checked against creation time; inaccessible or racing counter reads are excluded and marked, not treated as zero.',
            'Partial sums cover readable visible members only; inspect completeness flags and warnings.',
            'CIM enumeration, counter reads, and output serialization add collector overhead; record it with the experiment.',
            'No GPU/VRAM, display frame time, input-to-visible-response, or startup measurement is produced.',
            'The collector itself and unrelated system processes are excluded unless explicitly supplied as roots.'
        )
    }
    [System.IO.File]::WriteAllText($reportPath, (ConvertTo-Json -InputObject $report -Depth 10), $utf8)
}

Write-Output ('Saved {0} process-tree samples to {1}' -f $sampleCount, $outputDirectory)
