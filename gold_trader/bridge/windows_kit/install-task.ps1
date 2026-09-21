# Registers the AURUM bridge as a scheduled task, every 15 minutes.
#
# Written in PowerShell rather than schtasks because the two settings that
# matter cannot be set from the schtasks command line at all:
#
#   MultipleInstances    Windows defaults to IgnoreNew, so ONE run that never
#                        registers as finished blocks every run behind it,
#                        permanently and silently. That is what stopped the
#                        bridge at 07:24 on 2026-09-21: a perfect 15-minute
#                        cadence, then nothing, with the machine, MT5, git and
#                        the network all healthy.
#
#   ExecutionTimeLimit   without it a hung run hangs forever, which is how an
#                        instance wedges in the first place.
#
# On the policy: StopExisting is the ideal -- kill the stuck run, start the
# new one -- but New-ScheduledTaskSettingsSet's enum only accepts Parallel,
# Queue and IgnoreNew. So the task is created with Parallel and then upgraded
# to StopExisting through the task XML, which does support it. If that upgrade
# fails, Parallel stands, and Parallel never wedges either: a new run starts
# regardless of what the last one is doing. Queue was rejected precisely
# because a stuck run stalls the queue, which is the failure being fixed.
#
# Whatever ends up in force is READ BACK FROM WINDOWS and printed. An earlier
# version of the installer described protections in its comments and set none
# of them, so nothing here is reported unless Windows confirms it.

param(
    [string]$TaskName = 'AURUM bridge',
    [Parameter(Mandatory = $true)][string]$Folder
)

$ErrorActionPreference = 'Stop'
$launcher = Join-Path $Folder 'RUN-BRIDGE.bat'

if (-not (Test-Path $launcher)) {
    Write-Output "RUN-BRIDGE.bat not found in $Folder"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $Folder

# Repeat forever from now.
#
# Note what is NOT here: -RepetitionDuration. Two attempts at it both failed.
# Omitting it was supposed to mean indefinitely and did not -- the task ran
# three times and the repetition expired. Then TimeSpan::MaxValue rendered as
# P99999999DT23H59M59S, which Task Scheduler rejects outright as out of range,
# and the fallback never fired because it caught failures from building the
# trigger while the value is only refused at registration.
#
# "Indefinitely" is not a big number in this schema. It is the ABSENCE of a
# <Duration> element inside <Repetition>, which the cmdlet cannot express at
# all. So the duration is stripped from the XML below, where it can be.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances Parallel `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# Interactive, as the logged-on user: the task then sees the same git
# credentials your own shell does. The cost is that it does not run while
# nobody is logged in, which INSTALL.md states plainly.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

# Two things the cmdlets cannot express, both done in the task XML.
#
#   MultipleInstancesPolicy  StopExisting is absent from the cmdlet's enum.
#   Repetition/Duration      its absence is what "indefinitely" means, and
#                            the cmdlet always writes something.
#
# Failure here is not fatal: the task registered above already runs and
# already cannot wedge. What it would lose is the guarantee against expiry,
# and the verification below refuses to call that a success.
try {
    $xml = Export-ScheduledTask -TaskName $TaskName
    $upgraded = $xml -replace '<MultipleInstancesPolicy>[A-Za-z]+</MultipleInstancesPolicy>', '<MultipleInstancesPolicy>StopExisting</MultipleInstancesPolicy>'

    # Scoped to the Repetition block on purpose: IdleSettings carries a
    # <Duration> of its own, and stripping that one would change something
    # entirely unrelated.
    $upgraded = [regex]::Replace(
        $upgraded,
        '(?s)<Repetition>.*?</Repetition>',
        { param($m) ($m.Value -replace '\s*<Duration>[^<]*</Duration>', '') })

    Register-ScheduledTask -TaskName $TaskName -Xml $upgraded `
        -User "$env:USERDOMAIN\$env:USERNAME" -Force | Out-Null
} catch {
    Write-Output "  (XML upgrade did not apply: $($_.Exception.Message))"
}

# Verify rather than assume. Register-ScheduledTask can succeed and still
# leave a task that never fires, and assuming a schedule took is the mistake
# that started all of this.
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output 'The task was not registered.'
    exit 1
}

$info = Get-ScheduledTaskInfo -TaskName $TaskName
$repeat = $task.Triggers[0].Repetition.Interval
$duration = $task.Triggers[0].Repetition.Duration

# Read the policy from the task XML, not from the cmdlet object.
#
# The cmdlet's enum has no StopExisting, so a task that actually holds it
# reads back as an empty value -- and on 2026-09-21 this script printed a
# blank policy followed by "a stuck run cannot block the runs behind it",
# asserting the very protection it had failed to read. The XML is the
# authoritative source and knows all four values.
$policy = ''
try {
    $policy = ([xml](Export-ScheduledTask -TaskName $TaskName)).Task.Settings.MultipleInstancesPolicy
} catch {
    $policy = ''
}

Write-Output ''
Write-Output "  Task           $TaskName"
Write-Output "  Runs           $launcher"
Write-Output "  State          $($task.State)"
Write-Output "  Repeats every  $repeat"
if ($duration) {
    Write-Output "  Repeats until  $duration after the start"
} else {
    Write-Output '  Repeats until  indefinitely'
}
Write-Output "  Next run       $($info.NextRunTime)"
Write-Output "  Time limit     $($task.Settings.ExecutionTimeLimit)"
if (-not $policy) {
    # Unknown is not the same as fine. Saying nothing reassuring here is the
    # whole point: an unread value must never be reported as a good one.
    Write-Output '  If wedged      COULD NOT READ -- unverified'
    Write-Output ''
    Write-Output '  Check it by pasting THIS ONE LINE, on its own, into PowerShell:'
    Write-Output ''
    # Printed flush left and alone. Indented under a label, it reads as part
    # of a block, and pasting the block made PowerShell parse the label "If
    # wedged" as an if statement -- a parse error where a one-word answer was
    # wanted. A command someone is meant to run has to look like a command.
    Write-Output "([xml](Export-ScheduledTask -TaskName '$TaskName')).Task.Settings.MultipleInstancesPolicy"
    Write-Output ''
} elseif ($policy -eq 'IgnoreNew') {
    Write-Output "  If wedged      $policy"
    Write-Output '                 ^ BAD: a stuck run would block every run behind it.'
} else {
    Write-Output "  If wedged      $policy"
    Write-Output '                 a stuck run cannot block the runs behind it.'
}
Write-Output ''

if ($repeat -ne 'PT15M') {
    Write-Output '  WARNING: the repetition interval is not 15 minutes.'
    exit 1
}
# An absent duration is the goal: it means the repetition never expires. A
# present one means it stops on its own at some point with nothing wrong,
# which is what happened at 09:21 today. Checked because it was not -- the
# interval was verified and the duration ignored, and the duration is what
# ran out.
if ($duration) {
    try {
        $span = [System.Xml.XmlConvert]::ToTimeSpan($duration)
        if ($span.TotalDays -lt 365) {
            Write-Output "  WARNING: the repetition stops after $duration. It must not expire."
            exit 1
        }
    } catch {
        Write-Output "  WARNING: could not read the repetition duration ($duration)."
        exit 1
    }
}
if (-not $info.NextRunTime) {
    Write-Output '  WARNING: no next run time, so the schedule did not take.'
    exit 1
}
if ($policy -eq 'IgnoreNew') {
    Write-Output '  WARNING: the instance policy is the one that caused the outage.'
    exit 1
}
exit 0
