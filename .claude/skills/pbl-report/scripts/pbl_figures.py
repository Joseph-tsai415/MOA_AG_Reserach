"""Figure helpers for PBL reports. Build at print size, so a font size here is the printed point size."""
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

plt.rcParams["font.family"] = ["Microsoft JhengHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = True
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d3"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
BLUE_T, ORANGE_T, GREY_T = "#dceafb", "#fbe9e0", "#f4f3ef"
WIDTH = 6.6
FS = 8.6
FIG = pathlib.Path("figures")


def canvas(h):
    fig, ax = plt.subplots(figsize=(WIDTH, h))
    fig.subplots_adjust(0, 0, 1, 1)
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, text, fc="white", ec=MUTED, fs=FS, weight="normal", ls="-", lw=0.9, tc=INK):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.01,rounding_size=0.05",
                                fc=fc, ec=ec, lw=lw, ls=ls))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=tc, fontweight=weight, linespacing=1.2)


def arrow(ax, p, q, color=INK, lw=1.1, ls="-", rad=0.0, scale=8):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=scale, lw=lw, color=color, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=1))


def edge_label(ax, x, y, text, color=MUTED):
    ax.text(x, y, text, ha="center", va="center", fontsize=8, color=color,
            bbox=dict(fc="white", ec="none", pad=0.6))


def save(fig, name):
    fig.savefig(FIG / name, dpi=300, facecolor="white")
    plt.close(fig)
