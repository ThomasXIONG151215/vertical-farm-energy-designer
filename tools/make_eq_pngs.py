"""DEPRECATED — the appendix no longer uses equation images.

Since the 2026-10-26 revision the appendix writes every formula as plain text
(`P_HVAC = Q_cool / COP`), one font size, no math layout.  This script is kept
only as a fallback: it renders transparent mathtext PNGs into assets/ and an
eq_manifest.json, which gen_appendix_slides.py no longer reads.

--- original note ---
Render appendix equations to transparent PNGs for the VFED deck.

Why PNG: inline <svg> silently disappears from earlier pages after repeated
upsert-dsl calls; PNG survives (assets/ribbon.png is proof).

Sizing rule (important): every equation is rendered at ONE reference point size
and then scaled by ONE constant factor, so the glyph height is identical on
every row of every appendix page.  Never normalise per-image height — that was
what made fraction-heavy formulas render visibly smaller than plain ones.

Usage:  python tools/make_eq_pngs.py
Writes: docs/reports/VFED技术概览/assets/eq_*.png + assets/eq_manifest.json
"""

import json
import os

from matplotlib import mathtext
from matplotlib.font_manager import FontProperties
from PIL import Image

OUT = os.path.join(
    os.path.dirname(__file__), "..", "docs", "reports", "VFED技术概览", "assets"
)
OUT = os.path.abspath(OUT)
TMP = os.path.join(OUT, "_eq_tmp.png")
COLOR = "#16413E"
SCALE = 4  # asset px per logical slide px (deck is 1280x720)

# ── the one size knob ────────────────────────────────────────────────────
# EM = logical slide px per math "em".  Body text on the deck is 12.5-15 px,
# so 20 px guarantees every formula reads bigger than the prose around it.
SRC_PT = 40  # reference font size handed to mathtext
SRC_DPI = 220  # render dpi; SRC_PT/SRC_DPI only set the source resolution
EM = 19.0  # logical px per em  ← the only thing that changes glyph size
MAX_W = 618  # logical px; wider than the left card allows -> split the line

# name, tex.  Order matters: pages pull them by name.
EQS = [
    # ── A · 传热传质 ─────────────────────────────────────────────────
    ("a1_energy1",
     r"$C_z\,\dfrac{dT_z}{dt}=Q_{HVAC}+Q_{DEH}+Q_{LED}"
     r"+UA\,(T_{ext}-T_z)+\eta_s A_w I$"),
    ("a1_energy2",
     r"$\qquad+\dot{m}_{inf}c_p\,(T_{ext}-T_z)"
     r"+\dot{m}_{inf}(W_{ext}-W_z)L_v-E\,L_v$"),
    ("a1_moist",
     r"$\rho_{air}V_z\,\dfrac{dW_z}{dt}=E-M_{deh}-M_{hvac}"
     r"+\dot{m}_{inf}(W_{ext}-W_z)+\Psi\,(W_{ext}-W_z)$"),
    ("a1_co2",
     r"$\rho_{air}V_z\,\dfrac{dc_z}{dt}=S_{inj}+R_{resp}"
     r"+\dot{m}_{inf}(c_{ext}-c_z)-\Phi_{phot}$"),
    ("a1_terms",
     r"$UA=\sum_i U_iA_i,\qquad \dot{m}_{inf}=\dfrac{ACH\cdot V_z\rho_{air}}{3600},"
     r"\qquad Q_{LED}=P_{LED}$"),
    ("a1_psychro1",
     r"$e_s(T)=0.6108\exp\!\left(\dfrac{17.27\,T}{T+237.3}\right)\;\;[\mathrm{kPa}]$"),
    ("a1_psychro2",
     r"$W=0.622\,\dfrac{p_v}{P-p_v},\qquad W_{sat}=0.622\,\dfrac{e_s}{P-e_s},"
     r"\qquad p_v=\dfrac{W\,P}{0.622+W}$"),
    ("a1_lvpv",
     r"$L_v(T)=2501-2.36\,T\;\;[\mathrm{kJ/kg}],\qquad "
     r"VPD=e_s(T)\,\left(1-RH/100\right)$"),
    # ── B · 作物 ─────────────────────────────────────────────────────
    ("a2_phot",
     r"$\Phi_{phot}=\left(1-e^{-c_{pl}\cdot X_d}\right)"
     r"\dfrac{c_{rad}I\cdot C_{co_2}(T)\,(C_a-\Gamma)}"
     r"{c_{rad}I+C_{co_2}(T)\,(C_a-\Gamma)}$"),
    ("a2_co2resp",
     r"$C_{co_2}(T)=-c_{co_2,1}T^2+c_{co_2,2}T-c_{co_2,3}$"),
    ("a2_resp",
     r"$R_{resp}=c_{resp}\,X_d\,Q_{10}^{(T-25)/10},\qquad Q_{10}=2$"),
    ("a2_growth",
     r"$\dfrac{dX_d}{dt}=\alpha\,\Phi_{phot}-R_{resp},\qquad "
     r"X_{fresh}=\dfrac{X_d}{f_{dm}}$"),
    ("a2_trans",
     r"$E=k\,X_d\,VPD\,A_{can}\,f_{light},\qquad "
     r"f_{light}=1\ (\mathrm{light}),\ 0.15\ (\mathrm{dark})$"),
    ("a2_ca",
     r"$C_a=\dfrac{\mathrm{ppm}\cdot10^{-6}\cdot 44}{V_m},\qquad "
     r"V_m=22.414\,\dfrac{T+273.15}{273.15}\cdot\dfrac{101.325}{P}$"),
    # ── C · 设备与能源 ───────────────────────────────────────────────
    ("a3_cop",
     r"$COP=\min\!\left(\eta_{II}\dfrac{T_{evap}}{\max(T_{cond}-T_{evap},\,5)},\ 4.5\right),"
     r"\qquad P_{HVAC}=\dfrac{Q_{cool}}{COP}$"),
    ("a3_smer1",
     r"$P_{DEH}=\dfrac{M\cdot3.6\times10^{6}}{SMER_{eff}}$"),
    ("a3_smer2",
     r"$SMER_{eff}=SMER\cdot\mathrm{clamp}\!\left(0.25+0.75\left(\dfrac{W_z}{W_{nom}}\right)^{0.7}\!\!,\ 0.25,\ 1\right)$"),
    ("a3_led",
     r"$P_{LED}=\dfrac{PPFD\cdot A_{cov}}{\eta_{lamp}},\qquad Q_{LED}=P_{LED}$"),
    ("a3_pv",
     r"$T_{cell}=T_{amb}+\dfrac{NOCT-20}{800}\,I,\qquad "
     r"P_{PV}=P_{stc}\,\dfrac{I}{1000}\left[1+\gamma\,(T_{cell}-25)\right]\eta_{inv}$"),
    ("a3_bat",
     r"$net=P_{PV}-P_{load};\quad "
     r"E_{bat,k+1}=E_{bat,k}+\eta_{ch}P_{ch}\Delta t-\dfrac{P_{dis}\Delta t}{\eta_{dis}}$"),
    ("a3_cost",
     r"$C_{kg}=\dfrac{CRF\cdot CAPEX+OPEX+C_{grid}}{Y_{fresh}}$"),
    # ── D · 数值实现 ─────────────────────────────────────────────────
    ("a4_temp",
     r"$T^{n+1}=T^n+\dfrac{Q_{tot}\,\Delta t}{3600\,C_z}$"),
    ("a4_moist",
     r"$W^{n+1}=\min\!\left(W^n+\dfrac{M_{tot}\,\Delta t}{\rho_{air}V_z},\ W_{sat}(T^{n+1})\right)$"),
    ("a4_co2",
     r"$c^{n+1}=\max\!\left(c^n+\dfrac{S_{tot}\,\Delta t}{\rho_{air}V_z},\ c_\Gamma\right)$"),
    ("a4_qcorr",
     r"$q_{corr}=\left(m_{sat,clip}-m_{floor,clip}\right)L_v$"),
    ("a4_time",
     r"$\Delta t=600\,\mathrm{s}:\ \ n_{sub}=6,\ \ N_{step}=8760\times6=52560$"),
]


def render(name, tex):
    mathtext.math_to_image(
        tex, TMP, prop=FontProperties(size=SRC_PT), dpi=SRC_DPI,
        format="png", color=COLOR,
    )
    src = Image.open(TMP).convert("RGBA")
    w0, h0 = src.size
    k = EM / (SRC_PT / 72.0 * SRC_DPI)  # logical px per source px (constant!)
    w, h = max(8, round(w0 * k)), max(8, round(h0 * k))
    target = (w * SCALE, h * SCALE)
    canvas = Image.new("RGBA", target, (0, 0, 0, 0))
    canvas.alpha_composite(src.resize(target, Image.LANCZOS), (0, 0))
    canvas.save(os.path.join(OUT, f"eq_{name}.png"))
    return w, h


def main():
    manifest = {}
    too_wide = []
    for name, tex in EQS:
        w, h = render(name, tex)
        manifest[name] = {"w": w, "h": h}
        flag = ""
        if w > MAX_W:
            flag = "   <-- TOO WIDE, split this line"
            too_wide.append(name)
        print(f"{name:12s} w={w:4d} h={h:3d}{flag}")
    if os.path.exists(TMP):
        os.remove(TMP)
    with open(os.path.join(OUT, "eq_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"\nEM={EM} px/em, {len(EQS)} images")
    if too_wide:
        print("WARNING: over MAX_W =", MAX_W, "->", too_wide)


if __name__ == "__main__":
    main()
