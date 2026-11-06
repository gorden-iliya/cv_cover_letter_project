# ralph-hitl.ps1 - Ralph loop for the CV & Cover Letter Tailoring Agent, with a human gate
# between iterations.
#
# The agent works autonomously WITHIN an iteration; the human decides whether a
# NEXT iteration happens. Gating individual file edits does not work in a loop:
# the prompt would block forever with nobody at the keyboard.
#
# Gate modes:
#   'each'    pause after every iteration (review the commit, then continue)
#   'every:N' pause after every N iterations
#   'blocked' never pause; stop only on DONE, BLOCKED, failing tests, a stall, or MaxIterations
#
# Docs and code live in the same folder (this script's folder):
#   CLAUDE.md      conventions + prd.json / progress.txt rules (read automatically by claude)
#   prd.md         system design
#   AGENT_SPEC.md  agent tools, data, behavior
#   prd.json       feature list with "passes" flags
#   progress.txt   build log + build order

$ErrorActionPreference = 'Stop'

$Repo          = $PSScriptRoot
$Prd           = Join-Path $Repo 'prd.json'
$MaxIterations = 15
$Gate          = 'each'
$StallLimit    = 3          # consecutive iterations with no new commit before giving up
$AllowedTools  = 'Read,Edit,Write,Glob,Grep,Bash(python:*),Bash(pip:*),Bash(npx:*),Bash(git add:*),Bash(git commit:*),Bash(git status:*),Bash(git diff:*),Bash(git log:*)'

# Features verified by a human in the manual end-to-end slice (slice 9). The agent never
# sets these to passes=true; the loop stops with BLOCKED once only these remain.
$HitlFeatures = @(
    'Nothing is ever sent or submitted',
    'A run finishes within about 2 minutes per job (soft target)',
    'One manual end-to-end run succeeds on a real public job page'
)

# --- resolve gate -----------------------------------------------------------
$PauseEvery = 0
if ($Gate -eq 'each')          { $PauseEvery = 1 }
elseif ($Gate -like 'every:*') { $PauseEvery = [int]$Gate.Split(':')[1] }

# --- helpers ----------------------------------------------------------------

# prd.json has no ids, so items are shown as F<n> (1-based position in the file).
function Show-Remaining {
    # PS 5.1 emits a JSON array as ONE pipeline object; @(... | ConvertFrom-Json) would wrap it again.
    $items = Get-Content $Prd -Raw -Encoding UTF8 | ConvertFrom-Json
    $open  = @()
    for ($n = 0; $n -lt $items.Count; $n++) {
        if (-not $items[$n].passes) { $open += [pscustomobject]@{ Id = "F$($n + 1)"; Item = $items[$n] } }
    }
    Write-Host ("{0} of {1} items still open" -f $open.Count, $items.Count)
    foreach ($o in ($open | Select-Object -First 10)) {
        $tag = if ($HitlFeatures -contains $o.Item.description) { ' [HITL]' } else { '' }
        Write-Host ("  {0}  [{1}] {2}{3}" -f $o.Id, $o.Item.category, $o.Item.description, $tag)
    }
    if ($open.Count -gt 10) { Write-Host ("  ... and {0} more" -f ($open.Count - 10)) }
}

# Runs the whole test suite and returns $true when every test passes. The loop runs this
# itself after each iteration, so a pass is never taken on the agent's word alone.
# pytest exit code 5 = no tests collected (normal before slice 1 adds tests).
function Invoke-Tests {
    Write-Host "`n--- pytest ---" -ForegroundColor Cyan
    python -m pytest -q
    $code = $LASTEXITCODE
    if ($code -eq 5) { Write-Host 'No tests yet.' -ForegroundColor DarkGray; return $true }
    if ($code -eq 0) { Write-Host 'All tests pass.' -ForegroundColor Green; return $true }
    Write-Host 'TESTS FAILING.' -ForegroundColor Red
    return $false
}

# --- preflight --------------------------------------------------------------
$required = @('CLAUDE.md', 'AGENT_SPEC.md', 'prd.md', 'prd.json', 'progress.txt')
foreach ($f in $required) {
    if (-not (Test-Path (Join-Path $Repo $f))) { throw "Missing required file: $f" }
}
Set-Location $Repo

if (-not (Test-Path (Join-Path $Repo '.git'))) { throw "Not a git repo: $Repo. Run git init (or clone your GitHub repo) first." }
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -eq 'main' -or $branch -eq 'master') { throw "Refusing to run on '$branch'. Create a work branch first." }

Write-Host "Repo:   $Repo"   -ForegroundColor DarkGray
Write-Host "Branch: $branch" -ForegroundColor DarkGray
Write-Host "Gate:   $Gate"   -ForegroundColor DarkGray
Show-Remaining
if (-not (Invoke-Tests)) { throw 'Baseline tests fail before the loop started. Fix them first.' }

$hitlList = ($HitlFeatures | ForEach-Object { "  - $_" }) -join "`n"

$Prompt = @"
@CLAUDE.md
@prd.md
@AGENT_SPEC.md
@prd.json
@progress.txt

You are one iteration of a build loop. CLAUDE.md is authoritative for conventions and for
the prd.json and progress.txt rules.

Do exactly one iteration:
1. Read progress.txt (build order + notes from earlier iterations).
2. Pick the next unblocked slice from the build order, and within it the next prd.json
   feature with passes=false.
3. Implement it end to end, with pytest tests that fake Bedrock and the MCP server.
4. Run python -m pytest -q. Fix until it passes.
5. Run every step of that feature. Only if all steps work, set its passes to true.
6. Append an entry to progress.txt (format in CLAUDE.md).
7. git add and git commit locally with a short message naming the feature. Do not push.

These features are verified by a human. Never set them to passes=true:
$hitlList

Stop conditions. Print the sentinel alone on its own line, exactly as written:
- every prd.json feature has passes=true: DONE
- the next work needs a human (only the human-verified features remain, or a decision,
  credentials, a real CV or a missing .env value is required): BLOCKED - HUMAN INPUT REQUIRED
  and write what is needed in progress.txt before printing it.
If something is unclear in the specs, do not invent: write the question in progress.txt and
print the BLOCKED sentinel.
"@

$stall = 0

for ($i = 1; $i -le $MaxIterations; $i++) {
    Write-Host "`n=== Iteration $i of $MaxIterations ===" -ForegroundColor Cyan
    $before = (git rev-parse HEAD 2>$null)
    if ($before) { $before = $before.Trim() }

    # Prompt goes in on stdin. Tee-Object shows output live AND captures it; a bare
    # assignment would leave you staring at a blank console for minutes per iteration.
    $Prompt |
        claude -p --permission-mode acceptEdits --allowedTools $AllowedTools |
        Tee-Object -Variable outLines

    if ($LASTEXITCODE -ne 0) {
        Write-Host "claude exited with $LASTEXITCODE - stopping." -ForegroundColor Red
        break
    }

    $output = ($outLines -join "`n")

    # Independent check: run every test, not just the ones the agent says it ran.
    if (-not (Invoke-Tests)) {
        Write-Host 'Stopping: tests fail after this iteration. Review the last commit.' -ForegroundColor Red
        break
    }

    # -cmatch is case-SENSITIVE and anchored to its own line, so the words
    # "done" or "blocked" in ordinary prose never trigger a stop.
    if ($output -cmatch '(?m)^\s*DONE\s*$') {
        Write-Host "`nAll items complete." -ForegroundColor Green
        break
    }
    if ($output -cmatch '(?m)^\s*BLOCKED - HUMAN INPUT REQUIRED\s*$') {
        Write-Host "`nNext step needs a human. See the latest entry in progress.txt." -ForegroundColor Yellow
        break
    }

    $after = (git rev-parse HEAD 2>$null)
    if ($after) { $after = $after.Trim() }
    if ($before -eq $after) {
        $stall++
        Write-Host "No commit this iteration ($stall/$StallLimit)." -ForegroundColor Yellow
        if ($stall -ge $StallLimit) {
            Write-Host "Stalled - no progress in $StallLimit iterations. Stopping." -ForegroundColor Red
            break
        }
    }
    else {
        $stall = 0
        Write-Host ("Committed: " + (git log -1 --oneline)) -ForegroundColor Green
    }

    if ($PauseEvery -gt 0 -and ($i % $PauseEvery) -eq 0 -and $i -lt $MaxIterations) {
        Write-Host "`nReview the commit above."
        $answer = Read-Host "[Enter] continue  /  (s)top pausing  /  (q)uit"
        if ($answer -eq 'q') { Write-Host 'Stopped by user.' -ForegroundColor Yellow; break }
        if ($answer -eq 's') { $PauseEvery = 0; Write-Host 'Running unattended from here.' -ForegroundColor DarkGray }
    }
}

Write-Host "`n--- remaining ---" -ForegroundColor Cyan
Show-Remaining
