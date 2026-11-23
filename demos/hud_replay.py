#!/usr/bin/env python3
"""Split-pane telemetry HUD replaying QLean's recorded L4 semantic self-repair."""

import time
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

THEOREM = "theorem qlean_target : ∀ P Q R : Prop, (P → Q) → (Q → R) → P → R :="
ATTEMPT_1 = "fun hPQ hQR hP => hQR (hQR hP)"
ATTEMPT_2 = "fun P Q R hPQ hQR hP => hQR (hPQ hP)"


def ram_bar(kib: float, cap: float = 28.0, width: int = 18) -> str:
    filled = int(round((kib / cap) * width))
    return f"[{'█' * filled}{'░' * (width - filled)}] {kib:4.1f} / {cap:.0f} KiB"


def build_layout(
    left_lines: list[Text],
    status: str,
    status_style: str,
    tokens: int,
    wall: float,
    ram_kib: float,
    lean_status: str,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="qwen", ratio=3),
        Layout(name="cpu", ratio=2),
    )

    header = Text.assemble(
        (" QLean ", "bold black on cyan"),
        ("  Qwen3.5-4B + In-Weights RV32IM Lean 4 Kernel  ", "bold white"),
        ("│ Recorded L4 Replay (4×)", "dim white"),
    )
    layout["header"].update(Panel(header, border_style="bright_black"))

    left_body = Text("\n").join(left_lines) if left_lines else Text("")
    layout["qwen"].update(
        Panel(
            left_body,
            title="[bold cyan]Qwen3.5-4B[/bold cyan] [dim](Frozen Weights · Same KV Cache)[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    stats = Table.grid(padding=(0, 1))
    stats.add_column(style="dim white", width=15)
    stats.add_column()
    stats.add_row("Kernel State", Text(f" {status} ", style=status_style))
    stats.add_row("Trace Tokens", f"[bold white]{tokens:,}[/bold white]")
    stats.add_row("Wall Time", f"[bold white]{wall:5.1f} s[/bold white]")
    stats.add_row("DeltaNet RAM", f"[cyan]{ram_bar(ram_kib)}[/cyan]")
    stats.add_row("", "")
    stats.add_row("Frozen Tensors", "[green]738 / 738 bit-exact[/green]")
    stats.add_row("execve() Calls", "[bold green]0 (strace -f)[/bold green]")
    stats.add_row("Peak VRAM", "[white]9.14 GiB (L4)[/white]")
    stats.add_row("Lean 4.36.0", lean_status)

    layout["cpu"].update(
        Panel(
            stats,
            title="[bold green]P3 RV32IM CPU[/bold green] [dim](Compiled in Weights)[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    )

    footer = Text.assemble(
        (" Protocol: ", "dim"),
        ("QLEAN1", "bold white"),
        ("   •   ", "dim"),
        ("Idle Logits: ", "dim"),
        ("18/18 exact", "green"),
        ("   •   ", "dim"),
        ("External Lean Binary: ", "dim"),
        ("None", "bold green"),
    )
    layout["footer"].update(Panel(footer, border_style="bright_black"))
    return layout


def main() -> None:
    console = Console()
    lines: list[Text] = [
        Text(THEOREM, style="bold white"),
        Text(""),
    ]

    with Live(
        build_layout(lines, "IDLE", "bold black on white", 0, 0.0, 0.0, "[dim]Pending[/dim]"),
        console=console,
        refresh_per_second=24,
        screen=False,
    ) as live:
        time.sleep(0.7)

        # Attempt 1 typing
        lines.append(Text("Attempt 1:", style="bold cyan"))
        typed = Text("  ")
        lines.append(typed)
        for ch in ATTEMPT_1:
            typed.append(ch, style="white")
            live.update(
                build_layout(lines, "GENERATING", "bold black on cyan", 0, 0.0, 0.0, "[dim]Pending[/dim]")
            )
            time.sleep(0.03)

        # In-weights RV32IM execution for Attempt 1
        steps = 22
        for i in range(1, steps + 1):
            frac = i / steps
            live.update(
                build_layout(
                    lines,
                    "EXECUTING ELF",
                    "bold black on yellow",
                    int(82492 * frac),
                    25.3 * frac,
                    18.3 * frac,
                    "[dim]Checking...[/dim]",
                )
            )
            time.sleep(0.055)

        # Verdict 1: ERR_TYPE_MISMATCH
        lines.append(Text(""))
        lines.append(Text("← QLEAN1 ERR_TYPE_MISMATCH 107", style="bold red"))
        lines.append(Text('    expected="function type"  got="Prop"', style="red"))
        live.update(
            build_layout(
                lines,
                "ERR_TYPE_MISMATCH",
                "bold white on red",
                82492,
                25.3,
                18.3,
                "[red]Rejected[/red]",
            )
        )
        time.sleep(1.4)

        # Generic retry
        lines.append(Text(""))
        lines.append(Text("Retry header: Try again.  (same KV cache, 0 hints)", style="yellow"))
        lines.append(Text(""))
        live.update(
            build_layout(
                lines,
                "RETRYING",
                "bold black on yellow",
                82492,
                25.3,
                18.3,
                "[dim]Pending[/dim]",
            )
        )
        time.sleep(0.8)

        # Attempt 2 typing
        lines.append(Text("Attempt 2:", style="bold cyan"))
        typed2 = Text("  ")
        lines.append(typed2)
        for ch in ATTEMPT_2:
            typed2.append(ch, style="bright_white")
            live.update(
                build_layout(lines, "GENERATING", "bold black on cyan", 0, 0.0, 0.0, "[dim]Pending[/dim]")
            )
            time.sleep(0.03)

        # In-weights RV32IM execution for Attempt 2
        for i in range(1, steps + 1):
            frac = i / steps
            live.update(
                build_layout(
                    lines,
                    "EXECUTING ELF",
                    "bold black on yellow",
                    int(103364 * frac),
                    26.9 * frac,
                    18.6 * frac,
                    "[dim]Checking...[/dim]",
                )
            )
            time.sleep(0.055)

        # Verdict 2: QLEAN1 OK
        lines.append(Text(""))
        lines.append(Text("← QLEAN1 OK  (self-repaired in-weights)", style="bold green"))
        live.update(
            build_layout(
                lines,
                "QLEAN1 OK",
                "bold black on green",
                103364,
                26.9,
                18.6,
                "[bold green]Verified (0 axioms)[/bold green]",
            )
        )
        time.sleep(2.5)


if __name__ == "__main__":
    main()
