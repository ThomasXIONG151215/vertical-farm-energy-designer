"""Generate appendix slides (05-08) for the VFED deck.

Design rules (user-locked):
  * at most FIVE equations per page — appendix is a reminder, not a derivation
  * every equation is written in WORDS:  `室温变化 ＝ 空调冷量 ＋ 除湿显热 ＋ …`
    Chinese term names on both sides, full-width operators, ONE font size,
    no math layout (no fractions, no sub/superscript glyphs, no <Math>, no PNG).
    Nothing on these pages should require decoding a variable name.
  * the right-hand table is reduced to "key parameter / typical value"

Layout tokens are inherited from pages 01-04: 62 header + 92 ribbon + 500
content + 66 bar.  Gaps between rows are distributed over the leftover height
with a cap, so a page never ends with a hole above the footer bar.
"""

import os

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                    "docs", "reports", "VFED技术概览"))

W, H = 1280, 720
BODY = 500
PAD_Y = 16
LEFT_W, RIGHT_W, GAP = 736, 440, 16

C_INK = "#123B38"
C_SUB = "#46554F"
C_MUTE = "#5E6E6B"
C_DEEP = "#16413E"
C_LINE = "#CBD7D5"
C_ROW = "#E3EDEB"

EQ_FS = 16      # the single font size for every equation row
EQ_LH = 30      # MEASURED rendered height of one main line (16px / 1.5)
NOTE_FS = 13    # helper line: the "how this term is computed" gloss
NOTE_LH = 22    # measured height of a 13px line
SEC_H = 17
ROW_CAP = 30
SEC_CAP = 48
SLACK = 6       # safety margin so the last row never kisses the footer bar

EQ_MAX_W = LEFT_W - 48 - 26   # text column width inside the left card


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_w(s, fs=EQ_FS):
    """Rough advance width: CJK is 1 em, latin/punct ~0.55 em."""
    w = 0.0
    for ch in s:
        if ch in "×÷−":
            w += fs * 0.75
        elif ord(ch) >= 0x2E80 or ch in "，；：（）「」":
            w += fs * 1.0
        else:
            w += fs * 0.55
    return w


def header(title, tag):
    return f'''
  <Box style={{{{ width: {W}, height: 62, background: '#CEE9E6', padding: '0 44px', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #A9C6C2' }}}}>
    <Text style={{{{ fontSize: 27, fontWeight: 'bold', color: '{C_INK}' }}}}>{esc(title)}</Text>
    <Text style={{{{ fontSize: 13, color: '#4E7C78' }}}}>{esc(tag)}</Text>
  </Box>'''


def ribbon(text):
    return f'''
  <Box style={{{{ width: {W}, height: 92, padding: '8px 40px 0 40px' }}}}>
    <Box style={{{{ width: 1200, height: 76, position: 'relative' }}}}>
      <Image src="assets/ribbon.png" style={{{{ position: 'absolute', left: 0, top: 0, width: 1200, height: 76 }}}} />
      <Box style={{{{ position: 'absolute', left: 0, top: 0, width: 1200, height: 76, alignItems: 'center', justifyContent: 'center', padding: '0 70px' }}}}>
        <Text style={{{{ fontSize: 23, color: '#FFFFFF' }}}}>{esc(text)}</Text>
      </Box>
    </Box>
  </Box>'''


# ── blocks ───────────────────────────────────────────────────────────────
def blk_sec(label):
    return {"h": SEC_H, "w_before": 2.6,
            "html": f'''<Box style={{{{ flexDirection: 'row', alignItems: 'center', gap: 9 }}}}>
          <Box style={{{{ width: 16, height: 2, background: '{C_DEEP}' }}}} />
          <Text style={{{{ fontSize: 12.5, fontWeight: 'bold', color: '{C_MUTE}' }}}}>{esc(label)}</Text>
        </Box>'''}


def blk_eq(num, lines):
    """One equation, as plain text.  `lines` allows a wrapped continuation."""
    if isinstance(lines, str):
        lines = (lines,)
    norm = [ln if isinstance(ln, tuple) else (ln, "main") for ln in lines]
    for ln, _ in norm:
        if text_w(ln) > EQ_MAX_W:
            print(f"  !! eq {num} line too wide: {text_w(ln):.0f}px > {EQ_MAX_W}px -> {ln[:40]}…")
    h = sum(EQ_LH if k == "main" else NOTE_LH for _, k in norm)
    body = ""
    for ln, k in norm:
        fs, col = (EQ_FS, C_DEEP) if k == "main" else (NOTE_FS, C_MUTE)
        body += (f'''\n            <Text style={{{{ fontSize: {fs}, color: '{col}', '''
                 f'''lineHeight: 1.5 }}}}>{esc(ln)}</Text>''')
    html = f'''<Box style={{{{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}}}>
          <Text style={{{{ width: 18, fontSize: 12, color: '#8AA09C', marginTop: 4 }}}}>{esc(num)}</Text>
          <Box style={{{{ flexDirection: 'column', flex: 1 }}}}>{body}
          </Box>
        </Box>'''
    return {"h": h, "w_before": 1.0, "html": html}


def blk_custom(h, w_before, html):
    return {"h": h, "w_before": w_before, "html": html}


def left_card(blocks):
    avail = BODY - 2 * PAD_Y - SLACK
    total = sum(b["h"] for b in blocks)
    wsum = sum(blocks[i]["w_before"] for i in range(1, len(blocks)))
    spare = avail - total
    base = spare / wsum if wsum else 0
    gaps = []
    for i in range(1, len(blocks)):
        cap = SEC_CAP if blocks[i]["w_before"] >= 2.0 else ROW_CAP
        gaps.append(max(0, min(round(base * blocks[i]["w_before"]), cap)))
    pad = PAD_Y + max(0, (avail - total - sum(gaps)) // 2)
    pad = min(pad, 44)
    if spare < 0:
        print(f"  !! OVERFLOW by {-spare}px (blocks {total}, avail {avail})")
    print(f"  rows={len(blocks)} h={total} spare={spare} pad={pad} gaps={gaps}")

    out = ""
    for i, b in enumerate(blocks):
        if i:
            out += f'\n        <Box style={{{{ height: {gaps[i-1]} }}}} />'
        out += "\n        " + b["html"]
    return f'''
    <Box style={{{{ width: {LEFT_W}, height: {BODY}, background: '#FFFFFF', border: '1px solid {C_LINE}', borderRadius: 3, padding: '{pad}px 24px', flexDirection: 'column', justifyContent: 'flex-start' }}}}>{out}
    </Box>'''


def table(cols, rows, head_h=28, row_h=50):
    """cols: [(label, width|None)]; last column flexes."""
    def cells(items, fs, weight, color, h):
        out = []
        for (label, cw), txt in zip(cols, items):
            style = f"height: {h}, fontSize: {fs}, color: '{color}'"
            if weight:
                style += ", fontWeight: 'bold'"
            if cw is None:
                style += ", flex: 1"
            else:
                style += f", width: {cw}"
            out.append(f'\n            <Text style={{{{ {style} }}}}>{esc(txt)}</Text>')
        return "".join(out)

    head = f'''
          <Box style={{{{ flexDirection: 'row', height: {head_h}, alignItems: 'center', borderBottom: '1px solid #B9CFCB' }}}}>{cells([c[0] for c in cols], 12, True, C_INK, head_h)}
          </Box>'''
    body = ""
    for r in rows:
        body += f'''
          <Box style={{{{ flexDirection: 'row', height: {row_h}, alignItems: 'center', borderBottom: '1px solid {C_ROW}' }}}}>{cells(r, 12, False, C_SUB, row_h)}
          </Box>'''
    return head + body


PARAM_COLS = [("关键参数", 160), ("典型取值", None)]


def right_card(children):
    return f'''
    <Box style={{{{ width: {RIGHT_W}, height: {BODY}, background: '#FFFFFF', border: '1px solid {C_LINE}', borderRadius: 3, padding: '20px 24px', flexDirection: 'column', justifyContent: 'center' }}}}>{children}
    </Box>'''


def small_label(text):
    return (f'''<Box style={{{{ flexDirection: 'row', alignItems: 'center', gap: 9, marginBottom: 12 }}}}>
          <Box style={{{{ width: 16, height: 2, background: '{C_DEEP}' }}}} />
          <Text style={{{{ fontSize: 12.5, fontWeight: 'bold', color: '{C_MUTE}' }}}}>{esc(text)}</Text>
        </Box>''')


def notebar(text):
    return f'''
  <Box style={{{{ width: {W}, height: 66, background: '#B2CECB', padding: '0 44px', flexDirection: 'row', alignItems: 'center' }}}}>
    <Text style={{{{ fontSize: 13.5, color: '#1A2E2B', lineHeight: 1.45 }}}}>{esc(text)}</Text>
  </Box>'''


def page(title, tag, rib, left, right, note):
    return f'''<Slide style={{{{ width: {W}, height: {H}, background: '#F6F6F6', padding: 0, fontFamily: 'Microsoft YaHei', flexDirection: 'column' }}}}>
{header(title, tag)}
{ribbon(rib)}

  <Box style={{{{ width: {W}, height: {BODY}, padding: '0 44px', flexDirection: 'row', gap: {GAP} }}}}>
{left}
{right}
  </Box>
{notebar(note)}

</Slide>
'''


# ── 附录 A · 传热传质 ────────────────────────────────────────────────
print("page A")
a1_left = left_card([
    blk_sec("三个状态量：热、湿、碳"),
    blk_eq("1", [
        "室温变化 ＝ （空调冷量 ＋ 除湿显热 ＋ LED 发热 ＋ 围护传热",
        "＋ 太阳得热 ＋ 渗透显热 ＋ 渗透潜热 − 蒸腾潜热）÷ 房间热容",
    ]),
    blk_eq("2", [
        "含湿量变化 ＝ （蒸腾失水 − 除湿水量 − 空调析水",
        "＋ 渗透带入 ＋ 围护渗透）÷ 房间空气质量",
    ]),
    blk_eq("3", "CO₂ 变化 ＝ （注入 ＋ 呼吸 ＋ 渗透带入 − 光合固定）÷ 房间空气体积"),
    blk_sec("分项怎么来"),
    blk_eq("4", [
        "围护 ＝ UA × （室外 − 室内）；太阳 ＝ 太阳得热系数 × 窗面积 × 辐照",
        "渗透 ＝ 换气量 × 空气比热 × （室外 − 室内）；LED 发热 ＝ LED 功率",
    ]),
    blk_eq("5", [
        "饱和水汽压 ＝ 0.6108 × exp(17.27 × 温度 ÷ （温度 ＋ 237.3）)",
        "含湿量 ＝ 0.622 × 水汽压 ÷ （站压 − 水汽压）；潜热 ＝ 2501 − 2.36 × 温度",
    ]),
])
a1_right = right_card(table(PARAM_COLS, [
    ["房间热容", "80 kWh/K；厂房 30–200"],
    ["围护 UA", "50 W/K；夹芯板 0.2–0.45 W/(m²·K)"],
    ["太阳得热系数", "0.15；玻璃 0.1–0.6"],
    ["换气次数", "0.001 /h；密闭厂房 0.01–0.02"],
    ["汽化潜热", "2501 − 2.36T kJ/kg"],
    ["围护湿渗透", "0（气密围护可忽略）"],
    ["空气密度 / 比热", "1.2 kg/m³；1005 J/(kg·K)"],
]))

# ── 附录 B · 作物 ───────────────────────────────────────────────────
print("page B")
a2_left = left_card([
    blk_sec("碳平衡：光合、呼吸、生长"),
    blk_eq("1", [
        "光合 ＝ 冠层截光 × 光项 × 碳项 ÷ （光项 ＋ 碳项）",
        ("冠层截光 ＝ 1 − exp(−消光系数 × 干重)，随干重饱和", "note"),
        ("光项 ＝ 光响应 × 辐照；碳项 ＝ CO₂ 响应 × （空气 CO₂ − 补偿点）", "note"),
    ]),
    blk_eq("2", [
        "CO₂ 响应 ＝ −c₁ × 温度² ＋ c₂ × 温度 − c₃",
        ("c₁ 到 c₃ 由文献拟合，响应在 25 ℃ 附近最强", "note"),
    ]),
    blk_eq("3", "呼吸 ＝ 25 ℃ 呼吸速率 × 干重 × 温度每升 10 ℃ 翻倍"),
    blk_eq("4", "生长 ＝ 碳转化率 × 光合 − 呼吸；鲜重 ＝ 干重 ÷ 干物质率"),
    blk_sec("失水：把气候接回作物"),
    blk_eq("5", "失水 ＝ 蒸腾系数 × 干重 × 饱和差 × 冠层面积 × 昼夜系数"),
])
a2_right = right_card(table(PARAM_COLS, [
    ["碳转化率", "0.544（Van Henten 2003）"],
    ["25 ℃ 暗呼吸", "2.65e-7 /s（同源）"],
    ["冠层消光系数", "53 m²/kg"],
    ["光响应系数", "文献 1e-8；本项目 3.5e-9 kg/J"],
    ["CO₂ 补偿点", "5.2e-5 kg/m³ ≈ 29 ppm"],
    ["蒸腾系数", "1e-4 /(s·kPa)；夜间 ×0.15"],
    ["干物质率", "0.05；生菜 4–6 %"],
]))

# ── 附录 C · 设备与能源 ─────────────────────────────────────────────
print("page C")
a3_left = left_card([
    blk_sec("负荷侧：三台机器的电功率"),
    blk_eq("1", [
        "空调功率 ＝ 冷量 ÷ 能效比",
        ("能效比 ＝ 二阶效率 × 蒸发温度 ÷ （冷凝 − 蒸发），封顶 4.5", "note"),
    ]),
    blk_eq("2", [
        "除湿功率 ＝ 除湿水量 ÷ 有效除湿能效",
        ("室内越干，有效能效越低，最低只余额定的四分之一", "note"),
    ]),
    blk_eq("3", [
        "LED 功率 ＝ PPFD × 覆盖面积 ÷ 灯具光效",
        ("这部分电几乎全变热，同一份电在冷负荷里再算一次", "note"),
    ]),
    blk_sec("供能侧：发电、储电、结算"),
    blk_eq("4", [
        "光伏功率 ＝ 装机 × （辐照 ÷ 1000）× 温度修正 × 逆变效率",
        ("温度修正 ＝ 1 ＋ 功率系数 × （组件温度 − 25），组件温度随辐照升高", "note"),
    ]),
    blk_eq("5", [
        "净负荷 ＝ 光伏 − 负荷",
        ("电池电量 ＝ 上一步 ＋ 充电量 × 充电效率 − 放电量 ÷ 放电效率", "note"),
        ("单位成本 ＝ （年化投资 ＋ 年运维 ＋ 净购电）÷ 年鲜重", "note"),
    ]),
])
a3_right = right_card(table(PARAM_COLS, [
    ["卡诺二阶效率", "0.35；换热器品质 0.2–0.5"],
    ["蒸发 / 冷凝逼近温差", "8 K、15 K；常见 5–10、10–20"],
    ["能效比上限", "4.5；实测 2.5–4.5"],
    ["除湿能效 SMER", "2.0 kg/kWh；实测 1.5–3.0"],
    ["灯具光效", "2.5 µmol/J；商用 1.5–4.0"],
    ["NOCT / 功率系数 / 逆变", "45 ℃、−0.30 %/K、97 %"],
    ["充放电效率", "各 0.91，往返 83 %"],
]))

# ── 附录 D · 数值实现与指标 ─────────────────────────────────────────
print("page D")
a4_left = left_card([
    blk_sec("前向欧拉：三个状态量各推一步"),
    blk_eq("1", "新温度 ＝ 旧温度 ＋ 总热流 × 步长 ÷ （3600 × 房间热容）"),
    blk_eq("2", [
        "新含湿 ＝ 旧含湿 ＋ 总湿流 × 步长 ÷ （空气密度 × 体积）",
        ("再封顶到该温度下的饱和含湿，溢出量记为冷凝水", "note"),
    ]),
    blk_eq("3", [
        "新浓度 ＝ 旧浓度 ＋ 总碳流 × 步长 ÷ （空气密度 × 体积）",
        ("再兜底到补偿点，低于补偿点就锁住不再下降", "note"),
    ]),
    blk_sec("守恒修正与时间分辨率"),
    blk_eq("4", "冷凝回灌 ＝ （封顶溢出 ＋ 触底溢出）× 汽化潜热"),
    blk_eq("5", "一步 600 s → 每小时 6 步 → 全年 52560 步"),
    blk_custom(86, 2.2, '''<Box style={{ flexDirection: 'column', gap: 8, marginTop: 2 }}>
          <Text style={{ fontSize: 13, fontWeight: 'bold', color: '#123B38' }}>三层时间分辨率（别混为一谈）</Text>
          <Box style={{ flexDirection: 'row', gap: 10 }}>
            <Text style={{ width: 132, fontSize: 13, color: '#46554F' }}>气象与电价边界</Text>
            <Text style={{ flex: 1, fontSize: 13, color: '#46554F' }}>1 h · 8760 点，小时内零阶保持</Text>
          </Box>
          <Box style={{ flexDirection: 'row', gap: 10 }}>
            <Text style={{ width: 132, fontSize: 13, color: '#46554F' }}>物理 / 作物 / 设备</Text>
            <Text style={{ flex: 1, fontSize: 13, color: '#46554F' }}>600 s · 每小时 6 内步，全年 52560 步</Text>
          </Box>
          <Box style={{ flexDirection: 'row', gap: 10 }}>
            <Text style={{ width: 132, fontSize: 13, color: '#46554F' }}>输出与光储调度</Text>
            <Text style={{ flex: 1, fontSize: 13, color: '#46554F' }}>1 h · 8760 点，能量按内步累加后聚合</Text>
          </Box>
        </Box>'''),
])
a4_right = right_card(
    small_label("四个核心指标的算法")
    + table(
        [("指标", 62), ("定义", 150), ("代码字段", None)],
        [
            ["总产量", "Σ 收获干重 ÷ 干物质率", "annual_harvest_fw_kg"],
            ["总功率", "逐时负荷的最大值", "max(load_kw)"],
            ["kWh/kg", "年电量 ÷ 年鲜重", "specific_energy_kwh_per_kg"],
            ["单位成本", "年成本 ÷ 年鲜重", "specific_cost_per_kg"],
        ],
        row_h=54,
    )
    + '''
        <Box style={{ height: 18 }} />
        <Box style={{ flexDirection: 'column', gap: 7 }}>
          <Text style={{ fontSize: 12.5, fontWeight: 'bold', color: '#123B38' }}>钳位台账（不静默丢弃）</Text>
          <Text style={{ fontSize: 12.5, color: '#46554F' }}>温度：回传 clipped_deg_c，越界量并入年度统计</Text>
          <Text style={{ fontSize: 12.5, color: '#46554F' }}>湿度：floor_clipped_kg（触底）与 sat_clipped_kg（冷凝）</Text>
          <Text style={{ fontSize: 12.5, color: '#46554F' }}>CO₂：floor_clipped_kg，下限锁在补偿点</Text>
        </Box>'''
)

PAGES = [
    page(
        "附录 A：传热传质——三个状态量的平衡式",
        "附录 A",
        "热、湿、碳各一条：右边每一项都是能指着机器说出来的东西",
        a1_left,
        a1_right,
        "出处：ASHRAE Fundamentals Ch.1（湿空气性质）；Magnus 式（WMO 推荐，水面）；"
        "密闭厂房换气 0.01–0.02 /h（Kozai 2013）；U 值取夹芯板与砌体常见区间。",
    ),
    page(
        "附录 B：作物——单状态碳平衡",
        "附录 B",
        "一个状态量、七个参数：光与碳按联合限制合成，失水反过来绑定气候",
        a2_left,
        a2_right,
        "出处：Van Henten (2003) Biosystems Eng. 85(3):355–364 给出碳转化率、呼吸、消光、补偿点与光响应 1e-8 kg/J；"
        "本项目把光响应标定为 3.5e-9；夜间蒸腾折减见 transpiration.py。",
    ),
    page(
        "附录 C：设备与能源——每台机器的效率模型",
        "附录 C",
        "效率不是常数：能效比随室外温度走，除湿能效随室内含湿量走",
        a3_left,
        a3_right,
        "出处：二阶效率与逼近温差区间取 ASHRAE 换热器经验值；SMER 1.5–3.0 kg/kWh 为 DOE 额定点；"
        "NOCT 45 ℃、−0.30 %/K、逆变 97 % 为铭牌值；电池 4000 循环属 LFP 区间。",
    ),
    page(
        "附录 D：数值实现——怎么推一步、怎么记账、怎么算指标",
        "附录 D",
        "前向欧拉、三处钳位、一份台账；指标定义与代码字段一一对应",
        a4_left,
        a4_right,
        "出处：步长与钳位契约见 vfed/physics/ode.py；含湿封顶用当步新温度、冷凝潜热回灌重算见 design/engine.py；"
        "指标口径见 engine.py 的 summary 汇总段。",
    ),
]

for i, content in enumerate(PAGES, start=5):
    path = os.path.join(BASE, "slides", f"0{i}.slide")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("wrote", path, len(content))
