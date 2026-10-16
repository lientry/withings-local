#!/bin/zsh
# Run a project tool inside Terminal.app so macOS attributes Bluetooth access to Terminal
# (processes launched by the claude CLI are killed: it has no Bluetooth usage description).
# Output is mirrored to captures/terminal-run.log; a final "__EXIT <code>" line marks completion.
# Usage: tools/terminal_run.sh tools/ble_scan.py 90
set -u
ROOT="${0:A:h:h}"
LOG="$ROOT/captures/terminal-run.log"
mkdir -p "$ROOT/captures"
: > "$LOG"
CMD="cd ${(q)ROOT} && uv run ${(j: :)${(q)@}} 2>&1 | tee -a ${(q)LOG}; echo \"__EXIT \${pipestatus[1]}\" >> ${(q)LOG}"
RUNNER="$ROOT/captures/.terminal-run.command"
print -r -- "#!/bin/zsh
$CMD" > "$RUNNER"
chmod +x "$RUNNER"
open -a Terminal "$RUNNER"
echo "Launched in Terminal; log: $LOG"
