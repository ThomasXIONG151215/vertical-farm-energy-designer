"""Flow diagram of the Van Henten 3-state growth model (vfed/plants/van_henten_3state.py).

Pure matplotlib drawing (no graphviz dependency). English labels to avoid font issues.
Output: user-gym/benchmarks/plots/3state_flow.png
"""
from __future__ import annotations

import os
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(REPO, "user-gym", "benchmarks", "plots")
OUT_PNG = os.path.join(OUT_DIR, "3state_flow.png")

C_IN = "#e8f0fe"       # input boxes
C_CORE = "#fdf3e3"     # physics chain
C_STATE = "#e9f7ec"    # state boxes
C_OUT = "#f3e9f7"      # outputs
C_EDGE = "#37474f"


def box(ax, x, y, w, h, text, fc, fs=8.5, lw=1.2, style="round,pad=0.3"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style, fc=fc, ec=C_EDGE, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)


def arrow(ax, p0, p1, color=C_EDGE, ls="-", lw=1.3, rad=0.0, label=None,
          fs=7.5, dx=0, dy=0):
    ax.add_patch(FancyArrowPatch(
        p0, p1, arrowstyle="-|>", mutation_scale=13, color=color,
        linestyle=ls, lw=lw,
        connectionstyle=f"arc3,rad={rad}",
    ))
    if label:
        mx, my = (p0[0] + p1[0]) / 2 + dx, (p0[1] + p1[1]) / 2 + dy
        ax.text(mx, my, label, fontsize=fs, color="#555555", ha="center", va="center",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.0))


def main() -> None:
    fig, ax = plt.subplots(figsize=(15.5, 10.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(50, 97.5, "Van Henten 3-State Growth Model — how one step works",
            ha="center", va="center", fontsize=14, weight="bold")
    ax.text(50, 94.2, "vfed/plants/van_henten_3state.py  |  states per m²: "
            r"$X_d$ (structural dry matter), $C_{buf}$ (carbon buffer), LAI",
            ha="center", va="center", fontsize=9.5, color="#555555")

    # ---------------- inputs (left column) ----------------
    ax.text(11.5, 89.5, "INPUTS (each step)", ha="center", fontsize=9.5,
            weight="bold", color="#1a5276")
    box(ax, 3, 79, 17, 6.5, "Air temp $T_z$\n(step, from engine)", C_IN)
    box(ax, 3, 68, 17, 6.5, "PAR light (W/m²)\n(LED canopy)", C_IN)
    box(ax, 3, 57, 17, 6.5, "CO$_2$ ppm\n(live attr)", C_IN)
    box(ax, 3, 46, 17, 6.5, "RH %\n(live attr)", C_IN)
    box(ax, 3, 35, 17, 6.5, "Density $\\rho_c$\n(plants/m², fixed)", C_IN)

    # ---------------- core physics chain (center) ----------------
    ax.text(49, 89.5, "PHYSICS CHAIN", ha="center", fontsize=9.5,
            weight="bold", color="#9c640c")

    box(ax, 30, 77.5, 38, 9.5,
        "1. Canopy interception — 3-layer Gauss quadrature\n"
        r"$PAR_a^{(i)} = k_{PAR}\,(1-c_{r,P})\,PAR\,e^{-k_{PAR}\,l_i}$,"
        "  $l_i$ = layer depth from LAI",
        C_CORE)

    box(ax, 30, 62.5, 38, 11.5,
        "2. Leaf assimilation capacity (per layer)\n"
        r"$A_{L,sat}$ = min(supply via stomata $r_{CO_2}(T, RH, CO_2)$,"
        " $J_{max}(T)$ limit)\n"
        r"light response:  $A = A_{L,sat}\,(1-e^{-\varepsilon\,PAR_a/A_{L,sat}})$,"
        r"  $\varepsilon = \varepsilon_0\frac{C-\gamma}{C+2\gamma}$",
        C_CORE)

    box(ax, 30, 49.5, 38, 9.0,
        "3. Canopy gross assimilation\n"
        r"$A_C = \frac{\sum w_i A_i}{3.6}\cdot LAI$   [kg CO$_2$/(m²·s)]",
        C_CORE)

    box(ax, 30, 36.5, 38, 9.0,
        "4. Buffer gate  $h_{buf}\\in(0,1]$\n"
        "soft-min(demand, assimilation); full buffer throttles photosynthesis",
        C_CORE)

    box(ax, 30, 21.5, 38, 11.0,
        "5. Respiration (maintenance, Q$_{10}$=2)\n"
        r"$R_d$ = ($R_{d25,s}(1-\sigma)$ + $R_{d25,r}\,\sigma$) $\cdot X_d \cdot Q_{10}^{(T-25)/10}$"
        "\n" r"$\sigma$ = root fraction = f($X_d$/$\rho_c$)",
        C_CORE)

    # ---------------- states (right column) ----------------
    ax.add_patch(FancyBboxPatch((74, 21), 24, 66, boxstyle="round,pad=0.4",
                                fc="#f7fcf8", ec="#2e7d32", lw=1.8, ls="--"))
    ax.text(86, 84.5, "STATES  (per m²)", ha="center", fontsize=10,
            weight="bold", color="#1e8449")

    box(ax, 76, 68, 20, 13.0,
        r"$X_d$  structural dry" "\n"
        r"dX$_d$/dt = $\beta\,(\alpha\,A_C\,h_{buf}$"
        "\n" r"$-\;R_d)$", C_STATE)

    box(ax, 76, 49, 20, 13.0,
        r"$C_{buf}$  carbon buffer" "\n"
        r"dC$_{buf}$/dt = $\alpha A_C h_{buf}$"
        "\n" r"$-\,R_d - RGR_{max}X_d/\beta$", C_STATE)

    box(ax, 76, 30, 20, 13.0,
        "LAI  leaf area\n"
        r"dLAI/dt = $\frac{dX_d}{dt}(1-\sigma)\,SLA$"
        "\n" r"SLA = $SLA_{rf}\,f_I(light)\,f_{Xh}(RH)$", C_STATE)

    # ---------------- outputs (bottom) ----------------
    ax.text(49, 12.5, "OUTPUTS", ha="center", fontsize=9.5, weight="bold",
            color="#6c3483")
    box(ax, 6, 3, 40, 8.0,
        "engine.step() every 600 s  →  $X_d$ to engine;\n"
        "harvest = ($X_d$ − $X_{d,0}$)·area;  fresh weight = "
        r"$X_d$/dry_frac/$\rho_c$", C_OUT)
    box(ax, 55, 3, 40, 8.0,
        "fluxes() = ($A_C\\,h_{buf}$, $R_d$)  →  M1 CO$_2$ balance\n"
        "(photosynthesis in CO$_2$ units; respiration × DM_TO_CO$_2$)", C_OUT)

    # ---------------- arrows: inputs -> chain ----------------
    arrow(ax, (11.5, 71.3), (30, 82.0), rad=-0.15)                 # PAR -> 1
    arrow(ax, (11.5, 80.8), (30, 68.0), rad=0.18)                  # T -> 2
    arrow(ax, (11.5, 60.3), (30, 66.5), rad=0.12)                  # CO2 -> 2
    arrow(ax, (11.5, 49.3), (30, 63.5), rad=0.10)                  # RH -> 2
    arrow(ax, (11.5, 38.3), (30, 25.0), rad=-0.12)                 # rho -> 5
    arrow(ax, (11.5, 79.0), (30, 23.5), rad=-0.30, label="Q$_{10}$", dx=-2, dy=26)  # T -> 5
    arrow(ax, (11.5, 47.8), (30, 6.0), rad=-0.25)                  # RH -> SLA (via LAI box)

    # chain internal
    arrow(ax, (49, 77.5), (49, 74.0))                              # 1 -> 2
    arrow(ax, (49, 62.5), (49, 58.5))                              # 2 -> 3
    arrow(ax, (49, 49.5), (49, 45.5))                              # 3 -> 4
    arrow(ax, (49, 36.5), (49, 32.5))                              # 4 -> 5

    # gate -> states
    arrow(ax, (68, 41.0), (76, 73.0), rad=-0.25,
          label=r"$\alpha A_C h_{buf}$", dx=3.5, dy=-3)            # gate -> X_d
    arrow(ax, (68, 39.0), (76, 55.0), rad=-0.15)                   # gate -> C_buf
    arrow(ax, (68, 24.0), (76, 34.0), rad=-0.15, label="− $R_d$", dx=2, dy=1)

    # feedback: LAI -> interception (dashed, strong)
    arrow(ax, (76, 78.0), (49, 87.0), rad=0.35, ls="--", lw=1.8,
          color="#2e7d32", label="LAI drives interception", dx=0, dy=5.5)

    # C_buf -> gate (fullness signal)
    arrow(ax, (76, 52.0), (68, 44.0), rad=0.2, ls="--",
          color="#2e7d32", label="fullness", dx=6.5, dy=0.5)

    # X_d -> sigma (root fraction) already inside box 5 text; light arrow
    arrow(ax, (86, 68.0), (68, 29.5), rad=-0.35, ls=":",
          label=r"$\sigma(X_d)$", dx=2, dy=14)

    # states -> outputs
    arrow(ax, (80, 68.0), (26, 11.0), rad=0.22, lw=1.6)            # X_d -> harvest
    arrow(ax, (49, 21.5), (70, 11.0), rad=0.1)                     # fluxes out

    ax.text(50, 0.5,
            "Greenhouse-calibrated defaults (BJAAF MATLAB port); "
            r"$\varepsilon_0$ needs re-anchoring per facility "
            "(PFAL: 17e-9 → ~7.3e-9).  Units: all rates per second.",
            ha="center", fontsize=8, color="#777777")

    os.makedirs(OUT_DIR, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(OUT_PNG)
    print("size_kb", round(os.path.getsize(OUT_PNG) / 1024.0, 1))


if __name__ == "__main__":
    sys.exit(main())
