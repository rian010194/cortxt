#!/usr/bin/env python3
"""
PROTOTYPE -- throwaway, not production. Answers: "what should the Cortxt
CLI status view look like?" Three structurally different variants of the
same fake data (connected agents, live build waterfall, cost, orchestrator
findings). No backend -- everything below is static fake data.

Run:
    python prototype-cli-v02.py --variant=A
    python prototype-cli-v02.py --variant=B
    python prototype-cli-v02.py --variant=C
    python prototype-cli-v02.py            # cycles all three with a pause

See docs/superpowers/specs/2026-08-18-v02-vision-admin-surface-and-distribution-design.md
for context. Capture the winner, then delete this file from main.
"""
import argparse
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
CYAN = "\033[36m"

AGENTS = [
    ("Hermes", "active", "2 jobb igång"),
    ("Claude Code", "active", "refaktorerar Fas 8"),
    ("Codex", "idle", "vilande"),
    ("Buzz", "warn", "väntar på nyckel"),
]

EVENTS = [
    ("nu", "Hermes", "kör PromotionGate-tester för candidate #14"),
    ("2 min", "Claude", "mergade Fas 5-8 till main, 441 tester gröna"),
    ("6 min", "fynd", "routing till lokal modell hade sparat ~18% tokens"),
    ("11 min", "Codex", "granskar PR #156"),
]

COST_TODAY = "142,30 kr"
SAVINGS = "18%"


def dot(status):
    return {
        "active": GREEN + "●" + RESET,
        "idle": DIM + "●" + RESET,
        "warn": YELLOW + "●" + RESET,
    }[status]


def variant_a():
    """Dashboard-style single refreshing screen (k9s/htop-liknande)."""
    print(f"{BOLD}CORTXT{RESET}  {DIM}fleet status -- 6 agenter anslutna, 3 aktiva{RESET}\n")
    print(f"{BOLD}{'AGENT':<14}{'STATUS':<10}{'DETALJ'}{RESET}")
    for name, status, detail in AGENTS:
        print(f"{name:<14}{dot(status)} {status:<8}{detail}")
    print(f"\n{BOLD}WATERFALL (senaste){RESET}")
    for when, who, what in EVENTS:
        print(f"  {DIM}{when:>7}{RESET}  {CYAN}{who:<10}{RESET}{what}")
    print(f"\n{DIM}{'-'*50}{RESET}")
    print(f"Kostnad idag: {BOLD}{COST_TODAY}{RESET}   Besparing via routing: {GREEN}{SAVINGS}{RESET}")


def variant_b():
    """Statisk, rik statussnapshot (docker ps + git log --graph-känsla)."""
    print(f"{BOLD}$ cortxt status{RESET}\n")
    print(f"{BOLD}{'ID':<4}{'AGENT':<14}{'STATE':<8}{'WORK'}{RESET}")
    for i, (name, status, detail) in enumerate(AGENTS, 1):
        state_color = {"active": GREEN, "idle": DIM, "warn": YELLOW}[status]
        print(f"{i:<4}{name:<14}{state_color}{status:<8}{RESET}{detail}")
    print()
    print(f"{BOLD}* {RESET}{CYAN}Hermes{RESET}  {DIM}nu{RESET}      kör PromotionGate-tester för candidate #14")
    print(f"{BOLD}|{RESET}\\")
    print(f"{BOLD}| *{RESET} {CYAN}Claude{RESET}  {DIM}2 min{RESET}   mergade Fas 5-8 till main (441 gröna)")
    print(f"{BOLD}|/{RESET}")
    print(f"{BOLD}* {RESET}{YELLOW}fynd{RESET}    {DIM}6 min{RESET}   routing → lokal modell: ~18% tokenbesparing")
    print(f"{BOLD}* {RESET}{CYAN}Codex{RESET}   {DIM}11 min{RESET}  granskar PR #156")
    print()
    print(f"{DIM}cost.today={RESET}{COST_TODAY}  {DIM}savings.routing={RESET}{GREEN}{SAVINGS}{RESET}")


def variant_c():
    """Minimalistisk notis-ström (tail -f-känsla, terse)."""
    icon = {"active": GREEN + "▸" + RESET, "idle": DIM + "·" + RESET, "warn": YELLOW + "!" + RESET}
    print(f"{DIM}cortxt · {COST_TODAY} idag · -{SAVINGS} via routing{RESET}")
    print(f"{DIM}{'-'*42}{RESET}")
    for name, status, detail in AGENTS:
        print(f" {icon[status]} {name}")
    print(f"{DIM}{'-'*42}{RESET}")
    for when, who, what in EVENTS:
        tag = f"{YELLOW}fynd{RESET}" if who == "fynd" else f"{CYAN}{who}{RESET}"
        print(f" {DIM}{when:>6}{RESET}  {tag}  {what}")


VARIANTS = {"A": variant_a, "B": variant_b, "C": variant_c}
NAMES = {
    "A": "Dashboard (k9s/htop-liknande, hela skärmen)",
    "B": "Statisk rik snapshot (docker ps + git log --graph)",
    "C": "Minimal notis-ström (tail -f, terse)",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "C"], help="visa bara en variant")
    args = parser.parse_args()

    if args.variant:
        print(f"{BOLD}=== Variant {args.variant} -- {NAMES[args.variant]} ==={RESET}\n")
        VARIANTS[args.variant]()
        return

    for key in ["A", "B", "C"]:
        print(f"{BOLD}=== Variant {key} -- {NAMES[key]} ==={RESET}\n")
        VARIANTS[key]()
        print("\n")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
