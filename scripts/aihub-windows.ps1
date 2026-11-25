param(
    [ValidateSet('start','stop','restart','status','doctor','install')][string]$Action = 'start',
    [string]$ApiGatewayRoot, [string]$IamServiceRoot,
    [string]$Distro, [string]$User, [string]$PublicHost, [string]$ConfigFile
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$stateDir = Join-Path $root '.local-launch'
$settings = @{ Distro=''; User=''; ApiGatewayRoot='../api-gateway'; IamServiceRoot='../iam-service'; PublicHost='localhost'; Ports=@{frontend=15173;backend=15174;gateway=8080;iam=9001}; RouteTargetOverrides=@{} }

function Merge-LauncherConfig([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $config = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    foreach ($property in $config.PSObject.Properties) {
        if (-not $settings.ContainsKey($property.Name)) { throw "Unknown launcher setting: $($property.Name)" }
        $settings[$property.Name] = $property.Value
    }
}
# The committed example is the shareable default. The ignored local file is an
# optional personal overlay for paths, ports, distro and route overrides.
Merge-LauncherConfig (Join-Path $root 'aihub-local.example.json')
$configPath = if ($ConfigFile) { $ConfigFile } else { Join-Path $root 'aihub-local.json' }
Merge-LauncherConfig $configPath
# Stop/status refer to the distribution and ports actually started, even if the
# user has since edited or removed their personal launch configuration.
$savedLaunch = Join-Path $stateDir 'launch.json'
if ($Action -in @('stop','status') -and (Test-Path -LiteralPath $savedLaunch)) {
    $saved = Get-Content -LiteralPath $savedLaunch -Raw | ConvertFrom-Json
    foreach ($property in $saved.PSObject.Properties) { $settings[$property.Name] = $property.Value }
}
foreach ($key in @('ApiGatewayRoot','IamServiceRoot','Distro','User','PublicHost')) {
    if ($PSBoundParameters.ContainsKey($key)) { $settings[$key] = $PSBoundParameters[$key] }
}
foreach ($key in @('ApiGatewayRoot','IamServiceRoot')) {
    if (-not [IO.Path]::IsPathRooted($settings[$key])) {
        $settings[$key] = Join-Path $root $settings[$key]
    }
    $settings[$key] = [IO.Path]::GetFullPath($settings[$key])
}
if ($settings.PublicHost -notmatch '^[a-zA-Z0-9.-]+$') { throw 'PublicHost must be a hostname or IPv4 address, without scheme or port.' }
$ports = @{}
foreach ($name in @('frontend','backend','gateway','iam')) {
    $value = if ($settings.Ports -is [hashtable]) { $settings.Ports[$name] } else { $settings.Ports.$name }
    if ($value -isnot [int] -and $value -isnot [long]) { throw "Ports.$name must be an integer." }
    if ($value -lt 1 -or $value -gt 65535) { throw "Invalid port: $name" }
    $ports[$name] = [int]$value
}
if (@($ports.Values | Select-Object -Unique).Count -ne 4) { throw 'The four service ports must be distinct.' }
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$launcherLock = [IO.File]::Open((Join-Path $stateDir 'windows.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$utf8 = New-Object Text.UTF8Encoding($false)
$frontendState = Join-Path $stateDir 'frontend.json'
$launchState = Join-Path $stateDir 'launch.json'

function Read-Frontend {
    if (-not (Test-Path -LiteralPath $frontendState)) { return $null }
    $record = Get-Content -LiteralPath $frontendState -Raw | ConvertFrom-Json
    $process = Get-Process -Id $record.Pid -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'node' -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.StartTicks) {
        return @{ Record=$record; Process=$process }
    }
    return $null
}

function Stop-Frontend {
    $item = Read-Frontend
    if ($item) {
        Stop-Process -Id $item.Process.Id -Force
        $item.Process.WaitForExit(10000) | Out-Null
        Write-Host "[OK] Frontend stopped PID=$($item.Record.Pid)"
    }
    if (Test-Path -LiteralPath $frontendState) { Remove-Item -LiteralPath $frontendState }
}

function Invoke-Wsl([string[]]$WslArguments) {
    & wsl.exe @WslArguments
    if ($LASTEXITCODE -ne 0) { throw "WSL command failed (exit $LASTEXITCODE). Follow the installation/configuration message above." }
}

function Wsl-Path([string]$WindowsPath) {
    $result = & wsl.exe -d $settings.Distro -u root --exec wslpath -a -u $WindowsPath.Replace('\','/')
    if ($LASTEXITCODE -ne 0) { throw "Cannot translate path for WSL: $WindowsPath" }
    return ($result -join '').Trim()
}

function Ensure-ProjectEnv([string]$ProjectRoot, [string]$Label) {
    $target = Join-Path $ProjectRoot '.env'
    if (Test-Path -LiteralPath $target) { return }
    $source = Join-Path $ProjectRoot '.env.local'
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Missing $Label configuration: neither '$target' nor '$source' exists. Add the project's .env.local, then retry."
    }
    [IO.File]::Copy($source, $target, $false)
    Write-Host "[INIT] Created $target from .env.local"
}

function Wait-Url([string]$Url) {
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "Host cannot reach $Url. Check WSL localhost forwarding, VPN and port conflicts; no portproxy/firewall rules were changed."
}

function Show-Addresses {
    $wslIps = (& wsl.exe -d $settings.Distro -u $settings.User --exec hostname -I) -join ' '
    $wslIp = ($wslIps.Trim() -split '\s+')[0]
    Write-Host "`nService              Windows host URL                         WSL URL"
    Write-Host "Frontend (Windows)   http://$($settings.PublicHost):$($ports.frontend)"
    foreach ($entry in @(@('Backend','backend'), @('IAM','iam'), @('API Gateway','gateway'))) {
        $port = $ports[$entry[1]]
        Write-Host ("{0,-20} http://{1}:{2,-8}                   http://{3}:{2}" -f $entry[0], $settings.PublicHost, $port, $wslIp)
    }
    Write-Host "WSL IPv4 addresses: $($wslIps.Trim()) (diagnostic only; never persisted in routes)"
    $hostIps = [Net.Dns]::GetHostAddresses([Net.Dns]::GetHostName()) | Where-Object { $_.AddressFamily -eq 'InterNetwork' -and -not [Net.IPAddress]::IsLoopback($_) }
    Write-Host "Windows IPv4 addresses: $($hostIps -join ', ')"
    Write-Host "Open: http://$($settings.PublicHost):$($ports.frontend)"
    Write-Host "OAuth callback required in IAM: http://$($settings.PublicHost):$($ports.frontend)/oauth/callback"
    Write-Host "Logs: $stateDir"
}

try {
    if ($Action -in @('start','restart','doctor','install')) {
        $missing = @(
            if (-not (Test-Path -LiteralPath (Join-Path $settings.ApiGatewayRoot 'app\main.py'))) { "api-gateway ($($settings.ApiGatewayRoot))" }
            if (-not (Test-Path -LiteralPath (Join-Path $settings.IamServiceRoot 'app\main.py'))) { "iam-service ($($settings.IamServiceRoot))" }
        )
        if ($missing) {
            throw "Missing projects: $($missing -join ', '). Set ApiGatewayRoot/IamServiceRoot in aihub-local.json or use -ApiGatewayRoot/-IamServiceRoot. Projects are never downloaded from an assumed repository URL."
        }
        if ($Action -in @('start','restart','install')) {
            Ensure-ProjectEnv $root 'AI Hub'
            Ensure-ProjectEnv $settings.ApiGatewayRoot 'api-gateway'
            Ensure-ProjectEnv $settings.IamServiceRoot 'iam-service'
        } elseif (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) {
            throw 'Missing AI Hub .env. Run start/install once to initialize it from .env.local.'
        }
    }
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        if ($Action -in @('start','restart','install')) {
            Write-Host '[INSTALL] Attempting Windows Subsystem for Linux installation...'
            & dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
        }
        throw 'WSL is unavailable. Run an administrator terminal: wsl --install -d Ubuntu-24.04. Reboot if requested, initialize its Linux user, then retry.'
    }
    $distroOutput = & wsl.exe --list --quiet
    if ($LASTEXITCODE -ne 0) {
        $wslError = ($distroOutput -join '').Replace([string][char]0,'')
        if ($Action -in @('start','restart','install') -and $wslError -notmatch 'E_ACCESSDENIED') {
            $installDistro = if ($settings.Distro) { $settings.Distro } else { 'Ubuntu-24.04' }
            & wsl.exe --install -d $installDistro --no-launch
            throw "WSL installation was attempted. Complete any requested administrator setup/reboot, initialize $installDistro and its Linux user, then retry."
        }
        throw 'WSL enumeration failed. Run this launcher from your normal Windows user terminal; check wsl --status. Automatic installation is unavailable while WSL access is denied.'
    }
    $installed = @(($distroOutput -join "`n").Replace([string][char]0,'').Split("`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if (-not $settings.Distro) {
        $candidates = @('Ubuntu-24.04') + @($installed | Where-Object { $_ -ne 'Ubuntu-24.04' -and $_ -notmatch '^docker-' })
        foreach ($candidate in $candidates) {
            if ($candidate -notin $installed) { continue }
            $probe = & wsl.exe -d $candidate --exec bash -lc 'test "$(id -u)" != 0 && sudo -n true 2>/dev/null && id -un' 2>$null
            if ($LASTEXITCODE -eq 0) { $settings.Distro=$candidate; $settings.User=($probe -join '').Trim(); break }
        }
        if (-not $settings.Distro) {
            $settings.Distro = @($installed | Where-Object { $_ -match '^Ubuntu' } | Sort-Object -Descending | Select-Object -First 1)[0]
            if (-not $settings.Distro) { $settings.Distro = 'Ubuntu-24.04' }
        }
    }
    if ($settings.Distro -notin $installed) {
        if ($Action -in @('start','restart','install')) {
            & wsl.exe --install -d $settings.Distro --no-launch
            if ($LASTEXITCODE -ne 0) { throw "WSL installation incomplete. Finish Windows feature setup/reboot, then retry: wsl --install -d $($settings.Distro) --no-launch" }
            $distroOutput = & wsl.exe --list --quiet
            $installed = @(($distroOutput -join "`n").Replace([string][char]0,'').Split("`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            if ($settings.Distro -notin $installed) {
                throw "WSL distribution '$($settings.Distro)' was installed or is pending Windows setup. Finish any requested reboot, then retry aihub.bat start."
            }
        } else { throw "WSL distribution '$($settings.Distro)' is not installed. Run start/install first." }
    }
    if (-not $settings.User) {
        $settings.User = 'aihub'
    }
    Write-Host "WSL: $($settings.Distro), user: $($settings.User)"
    Write-Host "Projects: api-gateway=$($settings.ApiGatewayRoot); iam-service=$($settings.IamServiceRoot)"
    $linuxRoot = Wsl-Path $root
    $linuxGateway = Wsl-Path $settings.ApiGatewayRoot
    $linuxIam = Wsl-Path $settings.IamServiceRoot
    if ($Action -in @('start','restart','install')) {
        Invoke-Wsl @('-d',$settings.Distro,'-u','root','--exec','bash',"$linuxRoot/scripts/aihub-wsl-bootstrap.sh",$settings.User)
    }
    $portJson = ConvertTo-Json -InputObject $ports -Compress
    # Base64 keeps structured arguments intact through Windows PowerShell 5.1.
    $transaction = [guid]::NewGuid().ToString()
    $request = @{ action=$Action; root=$linuxRoot; gateway=$linuxGateway; iam=$linuxIam; ports=$ports; host=$settings.PublicHost; overrides=$settings.RouteTargetOverrides; transaction=$transaction }
    $encoded = [Convert]::ToBase64String($utf8.GetBytes(($request | ConvertTo-Json -Depth 8 -Compress)))
    $dispatch = 'import base64,json,os,sys; p=json.loads(base64.b64decode(sys.argv[1])); os.execv("/bin/bash",["bash",p["root"]+"/scripts/aihub-stack.sh",p["action"],"--gateway-root",p["gateway"],"--iam-root",p["iam"],"--ports",json.dumps(p["ports"]),"--public-host",p["host"],"--overrides",json.dumps(p["overrides"]),"--transaction",p["transaction"]])'
    $dispatch64 = [Convert]::ToBase64String($utf8.GetBytes($dispatch))
    $pythonDispatch = "exec(__import__('base64').b64decode('$dispatch64'))"
    $wslArgs = @('-d',$settings.Distro,'-u',$settings.User,'--exec','python3','-c',$pythonDispatch,$encoded)
    if ($Action -eq 'stop') { Stop-Frontend }
    if ($Action -in @('start','restart','install')) {
        if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
            if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
                & winget.exe install --id OpenJS.NodeJS.LTS --exact --silent --accept-package-agreements --accept-source-agreements
                $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
            }
            if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) { throw 'Automatic Node installation unavailable. Install Node.js >=22.12 (or 20.19+) from https://nodejs.org, reopen your terminal and retry.' }
        }
        & node.exe -e 'const [a,b]=process.versions.node.split(/\./).map(Number);process.exit((a===20&&b>=19)||(a===22&&b>=12)||a>22?0:1)'
        if ($LASTEXITCODE -ne 0) {
            if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
                & winget.exe upgrade --id OpenJS.NodeJS.LTS --exact --silent --accept-package-agreements --accept-source-agreements
                $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
                & node.exe -e 'const [a,b]=process.versions.node.split(/\./).map(Number);process.exit((a===20&&b>=19)||(a===22&&b>=12)||a>22?0:1)'
            }
            if ($LASTEXITCODE -ne 0) { throw 'Automatic Node upgrade did not provide a supported version. Install Node.js >=22.12 (or 20.19+) and retry.' }
        }
        $npm = Join-Path (Split-Path (Get-Command node.exe).Source -Parent) 'npm.cmd'
        if (-not (Test-Path -LiteralPath $npm)) {
            $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
            if (-not $npmCommand) { throw 'npm.cmd is missing. Repair/install Node.js LTS (including npm), then retry.' }
            $npm = $npmCommand.Source
        }
        $lockFile = Join-Path $root 'frontend\package-lock.json'
        $packageFile = Join-Path $root 'frontend\package.json'
        $hash = (Get-FileHash -LiteralPath $packageFile -Algorithm SHA256).Hash
        if (Test-Path -LiteralPath $lockFile) { $hash += (Get-FileHash -LiteralPath $lockFile -Algorithm SHA256).Hash }
        $stamp = Join-Path $stateDir 'frontend-deps.sha256'
        if (-not (Test-Path (Join-Path $root 'frontend\node_modules\vite\bin\vite.js')) -or -not (Test-Path $stamp) -or (Get-Content $stamp -Raw) -ne $hash) {
            Write-Host '[INSTALL] Frontend dependencies...'
            Push-Location (Join-Path $root 'frontend')
            try {
                if (Test-Path -LiteralPath $lockFile) { & $npm ci --no-audit --no-fund } else { & $npm install --no-audit --no-fund }
                if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed to install. Check npm registry/network and run npm install in frontend.' }
                [IO.File]::WriteAllText($stamp,$hash,$utf8)
            } finally { Pop-Location }
        }
    }
    if ($Action -in @('start','restart')) {
        $existing = Read-Frontend
        $signature = "$portJson|$($settings.PublicHost)"
        if ($Action -eq 'start' -and $existing -and $existing.Record.Config -ne $signature) {
            throw 'Frontend has different settings. Use restart.'
        }
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $ports.frontend -ErrorAction SilentlyContinue)
        foreach ($listener in $listeners) {
            if (-not $existing -or $listener.OwningProcess -ne $existing.Process.Id) {
                throw "Frontend port $($ports.frontend) is occupied by an unmanaged process. Stop it explicitly."
            }
        }
        # Load the actual Vite configuration before disrupting any service.
        $oldPorts = $env:AIHUB_LOCAL_PORTS; $oldHost = $env:AIHUB_PUBLIC_HOST
        try {
            $env:AIHUB_LOCAL_PORTS=$portJson; $env:AIHUB_PUBLIC_HOST=$settings.PublicHost
            & node.exe --input-type=module -e "const {pathToFileURL}=await import('node:url');const {default:configure}=await import(pathToFileURL(process.argv[1]).href);configure({command:'serve'})" (Join-Path $root 'frontend\vite.config.js')
            if ($LASTEXITCODE -ne 0) { throw 'Frontend configuration preflight failed; existing services were kept running.' }
        } finally { $env:AIHUB_LOCAL_PORTS=$oldPorts; $env:AIHUB_PUBLIC_HOST=$oldHost }
    }
    Invoke-Wsl $wslArgs
    if ($Action -in @('start','restart')) {
        $rollbackNeeded = $true
        foreach ($entry in @(@('iam','/health'),@('backend','/'),@('gateway','/gateway/health'))) {
            Wait-Url "http://127.0.0.1:$($ports[$entry[0]])$($entry[1])"
        }
        # WSL performs its full preflight before restart. Keep the old frontend
        # until the new backend stack is reachable from Windows as well.
        if ($Action -eq 'restart') { Stop-Frontend }
        $existing = Read-Frontend
        $signature = "$portJson|$($settings.PublicHost)"
        if ($existing -and $existing.Record.Config -ne $signature) { throw 'Frontend has different settings. Use restart.' }
        if (-not $existing) {
            $oldPorts = $env:AIHUB_LOCAL_PORTS; $oldHost = $env:AIHUB_PUBLIC_HOST
            try {
                $env:AIHUB_LOCAL_PORTS=$portJson; $env:AIHUB_PUBLIC_HOST=$settings.PublicHost
                $node = (Get-Command node.exe).Source
                $vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'
                $process = Start-Process -FilePath $node -ArgumentList @(('"'+$vite+'"'),'--host','0.0.0.0','--strictPort') -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $stateDir 'frontend.log') -RedirectStandardError (Join-Path $stateDir 'frontend.stderr.log') -PassThru
                [IO.File]::WriteAllText($frontendState,(@{Pid=$process.Id;StartTicks=$process.StartTime.ToUniversalTime().Ticks.ToString();Config=$signature} | ConvertTo-Json -Compress),$utf8)
            } finally { $env:AIHUB_LOCAL_PORTS=$oldPorts; $env:AIHUB_PUBLIC_HOST=$oldHost }
        }
        try { Wait-Url "http://127.0.0.1:$($ports.frontend)" } catch { if (-not $existing) { Stop-Frontend }; throw }
        [IO.File]::WriteAllText($launchState,($settings | ConvertTo-Json -Depth 8),$utf8)
        Write-Host '[OK] All four services are reachable from Windows.'
        $rollbackNeeded = $false
        $transactionFile = Join-Path $stateDir ('transaction-' + $transaction.Replace('-','') + '.json')
        if (Test-Path -LiteralPath $transactionFile) { Remove-Item -LiteralPath $transactionFile }
        Show-Addresses
    } elseif ($Action -eq 'status') {
        $frontend = Read-Frontend
        Write-Host ('Frontend: ' + $(if ($frontend) { "running PID=$($frontend.Record.Pid)" } else { 'stopped' }))
        Show-Addresses
    }
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    if ($rollbackNeeded) {
        if (-not $existing) { Stop-Frontend }
        $request.action = 'rollback'
        $rollbackEncoded = [Convert]::ToBase64String($utf8.GetBytes(($request | ConvertTo-Json -Depth 8 -Compress)))
        & wsl.exe -d $settings.Distro -u $settings.User --exec python3 -c $pythonDispatch $rollbackEncoded
    }
    exit 1
} finally {
    if ($launcherLock) { $launcherLock.Dispose() }
}
