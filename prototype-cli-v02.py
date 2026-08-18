#!/usr/bin/env python3
"""
PROTOTYPE -- throwaway, not production. Answers: "what should the Cortxt
CLI status view look like?" No backend -- everything below is static fake
data grounded in this session's real events (Fas 5-8 merge, PromotionGate
candidate #14, PR #156).

v04 pass (this one): two corrections from the operator --
1. "should look like a real Windows app" -> Windows Terminal / PowerShell,
   not an invented instrument-panel palette. Uses the actual Campbell
   color-scheme hex values (Windows Terminal's default theme) and real
   PowerShell output shapes: Format-Table-style dashes, Format-List-style
   Name : Value blocks, a PS prompt line -- not custom box-drawn frames.
2. "waterfall should look like [ADW-style pipeline dashboard]" -> variant A
   is now a live multi-line per-agent progress view (docker-compose-pull /
   winget-install shape: name, stage, a filled/empty block bar, elapsed),
   mirroring the widget prototype's swimlane Gantt instead of a static list.

Run:
    python prototype-cli-v02.py --variant=A
    python prototype-cli-v02.py --variant=B
    python prototype-cli-v02.py --variant=C
    python prototype-cli-v02.py            # cycles all three

See docs/superpowers/specs/2026-08-18-v02-vision-admin-surface-and-distribution-design.md
for context. Capture the winner, then delete this file from main.
"""
import argparse
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RESET = "\033[0m"
BOLD = "\033[1m"


def fg(hexcode):
    r, g, b = int(hexcode[0:2], 16), int(hexcode[2:4], 16), int(hexcode[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


# Windows Terminal "Campbell" scheme (the actual default dark theme)
WHITE = fg("F2F2F2")
GREY = fg("767676")
BLUE = fg("3B78FF")
GREEN = fg("16C60C")
YELLOW = fg("C19C00")
RED = fg("C50F1F")
CYAN = fg("3A96DD")

SESSION = "#a4e0d9"
CANDIDATE = "PromotionGate candidate #14 -- routing-tröskel: eskalera till moln endast över 6k tokens komplexitet"

# name, model, stage, pct (0-100, None = not started), state
PIPELINE = [
    ("Hermes",      "GPT-5.1",  "test/PromotionGate", 96, "done"),
    ("Claude Code", "Sonnet 5", "merge Fas 5-8",       100, "done"),
    ("Codex",       "o4-mini",  "review PR #156",      45, "running"),
    ("Buzz",        "-",        "vantar pa nyckel",     0, "waiting"),
]

EVENTS = [
    ("14:41", "Hermes", "kor PromotionGate-tester for candidate #14 -- 6/9 klara"),
    ("14:39", "Claude", "mergade Fas 5-8 till main, 441 tester grona, 0 regressioner"),
    ("14:33", "fynd", "routing till lokal modell hade sparat ~18% tokens senaste timmen"),
    ("14:28", "Codex", "granskar PR #156 -- v.02 vision, admin-yta"),
]

COST_TODAY = "142,30 kr"
BUDGET_PCT = 30

STATE_COLOR = {"done": GREEN, "running": CYAN, "waiting": GREY}
STATE_LABEL = {"done": "Klar", "running": "Kor", "waiting": "Vantar"}


def bar(pct, width=24):
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def variant_a():
    """Live pipeline -- multirad progress per agent (docker compose/winget-form)."""
    print(f"{BLUE}PS C:\\Users\\rikar> {WHITE}cortxt pipeline --watch{RESET}  {GREY}session {SESSION}{RESET}\n")
    print(f"{WHITE}{CANDIDATE}{RESET}\n")
    for name, model, stage, pct, state in PIPELINE:
        color = STATE_COLOR[state]
        label = STATE_LABEL[state]
        print(f"  {color}{name:<13}{RESET}{GREY}{model:<10}{RESET} {color}{bar(pct)}{RESET} {WHITE}{pct:>3}%{RESET}  {color}{label:<7}{RESET}{GREY}{stage}{RESET}")
    print()
    print(f"  {GREY}kostnad {RESET}{WHITE}0,62 kr{RESET}   {GREY}tid {RESET}{WHITE}1m 58s{RESET}   {GREY}tokens {RESET}{WHITE}41,2k{RESET}")


def variant_b():
    """Format-List -- PowerShell-standardens objektdump: Namn : Varde per rad."""
    print(f"{BLUE}PS C:\\Users\\rikar> {WHITE}cortxt status | Format-List{RESET}\n")
    for name, model, stage, pct, state in PIPELINE:
        color = STATE_COLOR[state]
        print(f"{CYAN}Agent{RESET}   : {WHITE}{name}{RESET}")
        print(f"{CYAN}Modell{RESET}  : {GREY}{model}{RESET}")
        print(f"{CYAN}Status{RESET}  : {color}{STATE_LABEL[state]} ({pct}%){RESET}")
        print(f"{CYAN}Arbete{RESET}  : {GREY}{stage}{RESET}")
        print()
    print(f"{CYAN}Kostnad idag{RESET} : {WHITE}{COST_TODAY}{RESET}")
    print(f"{CYAN}Budget{RESET}       : {WHITE}{BUDGET_PCT}%{RESET}")


def variant_c():
    """Powerline-status -- en rad, segment-prompt (oh-my-posh-kansla)."""
    running = [p for p in PIPELINE if p[4] == "running"]
    done = sum(1 for p in PIPELINE if p[4] == "done")
    sep = f"{GREY} › {RESET}"
    seg1 = f"{BOLD} cortxt {RESET}"
    seg2 = f"{GREEN} {done}/{len(PIPELINE)} klara {RESET}"
    seg3 = f"{CYAN} {running[0][0]} kor {RESET}" if running else f"{GREY} idle {RESET}"
    seg4 = f"{YELLOW} {COST_TODAY} {RESET}"
    print(f"{seg1}{sep}{seg2}{sep}{seg3}{sep}{seg4}")
    print(f"{GREY}  candidate #14 -- eskalera till moln endast over 6k tokens{RESET}\n")
    for when, who, what in EVENTS[:2]:
        who_c = YELLOW if who == "fynd" else CYAN
        print(f"{GREY}{when}{RESET}  {who_c}{who}{RESET}  {GREY}{what}{RESET}")


VARIANTS = {"A": variant_a, "B": variant_b, "C": variant_c}
NAMES = {
    "A": "Live pipeline (multirad progress per agent)",
    "B": "Format-List (PS-objektdump)",
    "C": "Powerline-status (en rad, segment-prompt)",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "C"], help="visa bara en variant")
    args = parser.parse_args()

    if args.variant:
        print(f"{BOLD}{WHITE}=== Variant {args.variant} -- {NAMES[args.variant]} ==={RESET}\n")
        VARIANTS[args.variant]()
        return

    for key in ["A", "B", "C"]:
        print(f"{BOLD}{WHITE}=== Variant {key} -- {NAMES[key]} ==={RESET}\n")
        VARIANTS[key]()
        print("\n")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
