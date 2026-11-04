# Capability router launcher (Windows).
#
# Reads the hook payload from stdin, hands it to router.py untouched, and
# writes the router's stdout back. Both directions are byte-exact: the payload
# is read as raw UTF-8 and never passes through a console code page.
#
# The router logic lives in router.py. This file is a launcher only, so the
# Windows path and the POSIX path cannot drift apart.

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$routerPy = Join-Path $scriptDir 'router.py'

function Resolve-Python {
    $candidates = @()
    if ($env:ROUTING_PYTHON) { $candidates += $env:ROUTING_PYTHON }
    $candidates += 'C:\Users\ADMIN\AppData\Local\Programs\Python\Python313\python.exe'
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    foreach ($name in @('python.exe', 'python')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found -and $found.Source) { return $found.Source }
    }
    return $null
}

$python = Resolve-Python
if (-not $python) { exit 0 }

# Read stdin as raw bytes so no code page can corrupt the payload.
$inputStream = [Console]::OpenStandardInput()
$memory = New-Object System.IO.MemoryStream
$inputStream.CopyTo($memory)
$payload = $memory.ToArray()
if ($payload.Length -eq 0) { exit 0 }

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $python
$startInfo.Arguments = '"' + $routerPy + '"'
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.CreateNoWindow = $true

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo
$null = $process.Start()

$process.StandardInput.BaseStream.Write($payload, 0, $payload.Length)
$process.StandardInput.Close()

$outMemory = New-Object System.IO.MemoryStream
$buffer = [byte[]]::new(8192)
$stdout = $process.StandardOutput.BaseStream
while (($read = $stdout.Read($buffer, 0, $buffer.Length)) -gt 0) {
    $outMemory.Write($buffer, 0, $read)
}
$null = $process.StandardError.ReadToEnd()
$process.WaitForExit()

$outBytes = $outMemory.ToArray()
if ($outBytes.Length -gt 0) {
    $target = [Console]::OpenStandardOutput()
    $target.Write($outBytes, 0, $outBytes.Length)
    $target.Flush()
}

exit 0
