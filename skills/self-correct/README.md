# self-correct — a Claude Code skill

Wraps any structured-output task (JSON extraction, SQL, code, configs) in a
generate → validate → critique → repair loop: executable checks derived before
generation, targeted per-violation feedback, max 3 attempts, loud failure on
exhaustion. Built on this repo's benchmarked finding: targeted feedback lifts
invoice extraction 58.3% → 95.8% and text-to-SQL 25.0% → 91.7%, while a generic
"please fix it" critic matches no retries at all.

Install: `cp -r skills/self-correct ~/.claude/skills/`

Use: `/self-correct extract {vendor, subtotal, tax, total, line_items[]} from invoice.txt`

Parent repo (loop code, both domains, ablations): https://github.com/sugeerth/self-correcting-agents
