import os
import matplotlib.pyplot as plt

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

LABELS = ["GPT-5.4-nano", "GPT-5.4-mini", "GPT-5.4", "Opus 4.7"]
COLORS = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b"]

FIGURES = [
    ("fig1_composite.png",
     "Figure 1: Composite score by tutor (higher = better teaching)",
     "Composite score",
     [0.635, 0.618, 0.596, 0.635]),
    ("fig2_firehosing.png",
     "Figure 2: Firehosing (higher = more concise and focused)",
     "Score",
     [0.29, 0.22, 0.15, 0.27]),
    ("fig3_sycophancy.png",
     "Figure 3: Sycophancy (higher = less sycophantic)",
     "Score",
     [0.70, 0.87, 0.90, 0.60]),
]


def render(filename, title, ylabel, values):
    fig, ax = plt.subplots(figsize=(7.5, 4.0), dpi=180)
    bars = ax.bar(LABELS, values, color=COLORS, edgecolor="#111", linewidth=0.6, width=0.65)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=12, pad=12)
    ax.yaxis.grid(True, color="#ddd", linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.015, f"{v:.2f}",
                ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    out_path = os.path.join(OUT_DIR, filename)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    for args in FIGURES:
        render(*args)
