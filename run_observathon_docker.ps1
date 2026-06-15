param(
    [ValidateSet("practice", "public")]
    [string]$Phase = "public",
    [string]$Out = "run_output.json",
    [string]$ScoreOut = "score.json",
    [string]$Team = "2A202600739-NguyenTranKien",
    [int]$Concurrency = 8,
    [switch]$Practice,
    [switch]$Score
)

$ErrorActionPreference = "Stop"

$labPath = (Get-Location).Path
$apiKey = $env:OPENAI_API_KEY

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $secure = Read-Host "OPENAI_API_KEY" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "OPENAI_API_KEY is required."
}

$openAiBaseUrl = $env:OPENAI_BASE_URL
if ([string]::IsNullOrWhiteSpace($openAiBaseUrl) -and $apiKey.StartsWith("sk-or-")) {
    $openAiBaseUrl = "https://openrouter.ai/api/v1"
}

$args = @(
    "run", "--rm",
    "-v", "${labPath}:/lab",
    "-e", "OPENAI_API_KEY=$apiKey"
)

if (-not [string]::IsNullOrWhiteSpace($openAiBaseUrl)) {
    $args += @("-e", "OPENAI_BASE_URL=$openAiBaseUrl")
}

if (-not [string]::IsNullOrWhiteSpace($env:LOCAL_BASE_URL)) {
    $args += @("-e", "LOCAL_BASE_URL=$env:LOCAL_BASE_URL")
}

$phaseDir = if ($Practice) { "practice" } else { $Phase }
$simPath = "bin/$phaseDir/observathon-sim"
$scorePath = "bin/$phaseDir/observathon-score"

$simArgs = "./$simPath --config solution/config.json --wrapper solution/wrapper.py --out $Out --concurrency $Concurrency"
if ($Practice -or $phaseDir -eq "practice") {
    $simArgs += " --practice"
}

if ($Score) {
    $bash = "cd /lab && chmod +x $simPath $scorePath && $simArgs && ./$scorePath --run $Out --findings solution/findings.json --team $Team --out $ScoreOut"
}
else {
    $bash = "cd /lab && chmod +x $simPath && $simArgs"
}
$args += @("python:3.12-slim", "bash", "-lc", $bash)

docker @args
