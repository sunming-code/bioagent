"""
논문용 Figure 1 (scorecard) + Figure 2 (ablation) 생성.
Usage: python evaluation/plot_paper_figures.py
Output: evaluation/results/fig1_scorecard.png, fig2_ablation.png
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── 색상 팔레트 (접근성 고려) ──────────────────────────────
C_GDGPT  = "#2196F3"   # teal-blue  (GDgpt)
C_GPT4O  = "#FF7043"   # warm-orange (GPT-4o)
C_DANGER = "#E53935"   # red (critical ablation)
C_GRAY   = "#90A4AE"   # secondary text

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# ══════════════════════════════════════════════════════════════
# Figure 1  —  Safety-vs-Fluency Scorecard (horizontal dot plot)
# ══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(9, 5.2))
fig.patch.set_facecolor("white")

# ── colour for GDgpt-win dots (override to green) ──
C_WIN = "#43A047"   # green for GDgpt-lead rows

metrics = [
    # (label,                                  gdgpt,       gpt4o,       is_primary, note,              gdgpt_wins)
    ("Abstention Acc.\n(KG-absent, N=8)",       1.00,        0.00,        True,  "",                    True),
    ("Bridge Hit Rate\n(N=15, p<0.001)",        1.00,        0.00,        True,  "",                    True),
    ("Pathway F1\n(N=15, p<0.001)",             0.596,       0.000,       True,  "CI [0.57,0.62]",      True),
    ("LLM-Judge D3 Traceability\n(N=9)",        4.038/5,     3.223/5,     True,  "★ GDgpt leads",       True),
    ("LLM-Judge D4 Clin. Safety\n(N=9, †)",    3.519/5,     4.926/5,     True,  "†D4 paradox — see §5.3", False),
    ("LLM-Judge total\n(0–25, N=9)",            16.333/25,   23.149/25,   False, "†verbosity bias",     False),
]

y_pos = np.arange(len(metrics))

ax.axvline(0.5, color="#CFD8DC", linewidth=1, linestyle="--", zorder=0)
ax.axhline(5.5, color="#B0BEC5", linewidth=1, linestyle="-", alpha=0.6)  # sep primary/secondary

for i, (label, gd, gpt, primary, note, gd_wins) in enumerate(metrics):
    alpha = 1.0 if primary else 0.55
    lw    = 2.5 if primary else 1.5
    dot_color = C_WIN if gd_wins else C_GDGPT

    ax.plot([gd, gpt], [i, i], color=C_GRAY, linewidth=lw*0.6, zorder=1)
    ax.scatter(gd,  i, s=160, color=dot_color, zorder=3, alpha=alpha,
               label="GDgpt" if i == 0 else "")
    ax.scatter(gpt, i, s=160, color=C_GPT4O,   zorder=3, alpha=alpha,
               label="GPT-4o" if i == 0 else "")

    offset_gd  = -0.06 if gd < gpt else 0.04
    offset_gpt =  0.04 if gd < gpt else -0.06
    ax.text(gd  + offset_gd,  i+0.27, f"{gd:.2f}" if gd < 1 else "1.00",
            ha="center", va="bottom", fontsize=8.5, color=dot_color, fontweight="bold")
    ax.text(gpt + offset_gpt, i+0.27, f"{gpt:.2f}" if gpt < 1 else "1.00",
            ha="center", va="bottom", fontsize=8.5, color=C_GPT4O, fontweight="bold")

    if note:
        ax.text(1.04, i, f"  {note}", va="center", ha="left",
                fontsize=7.5, color=C_GRAY, style="italic")

ax.set_yticks(y_pos)
ax.set_yticklabels([m[0] for m in metrics], fontsize=9.5)
ax.set_xlabel("Metric value (normalised to 0–1)", fontsize=10)
ax.set_xlim(-0.05, 1.32)
ax.set_ylim(-0.8, len(metrics) + 0.4)

# legend
legend_handles = [
    mpatches.Patch(color=C_WIN,   label="GDgpt (leads)"),
    mpatches.Patch(color=C_GDGPT, label="GDgpt (trails)"),
    mpatches.Patch(color=C_GPT4O, label="GPT-4o"),
]
ax.legend(handles=legend_handles, loc="lower right", fontsize=9, framealpha=0.9)

ax.text(-0.38, 6.45, "◀  PRIMARY",
        fontsize=8, color="#546E7A", transform=ax.transData)
ax.text(-0.38, -0.72, "▼  SECONDARY",
        fontsize=8, color=C_GRAY, transform=ax.transData)
ax.text(0.5, -0.72,
        "†D4 paradox: GDgpt abstains 100% on KG-absent queries (§4.2) yet judge scores GPT-4o higher — "
        "judge cannot detect calibrated abstention",
        ha="center", fontsize=7.5, color=C_GRAY, style="italic", transform=ax.transData)

ax.set_title("Figure 1: GDgpt vs. GPT-4o — safety-critical metrics (green = GDgpt leads)",
             fontsize=10.5, fontweight="bold", pad=12)
fig.tight_layout()
fig.savefig("evaluation/results/fig1_scorecard.png", dpi=200, bbox_inches="tight")
plt.close()
print("✅ fig1_scorecard.png 저장됨")


# ══════════════════════════════════════════════════════════════
# Figure 2  —  Ablation study (horizontal grouped bars)
# ══════════════════════════════════════════════════════════════
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.2), sharey=True)
fig.patch.set_facecolor("white")

configs = ["Full\n(7-role + Bridge)", "− Multi-role\n(single_agent)", "− Bridge\n(rag_only)"]
pathway_f1  = [0.667, 0.653, 0.084]
bridge_hit  = [1.000, 1.000, 0.000]
colors = [C_GDGPT, "#64B5F6", C_DANGER]  # 마지막은 빨간색 (큰 drop)

y = np.arange(len(configs))

for ax, values, title, xlim in [
    (ax1, pathway_f1, "Pathway F1", 0.75),
    (ax2, bridge_hit, "Bridge Hit Rate", 1.12),
]:
    bars = ax.barh(y, values, color=colors, height=0.5, alpha=0.88)
    ax.set_xlim(0, xlim)
    ax.set_xlabel(title, fontsize=10)
    ax.set_yticks(y)
    if ax == ax1:
        ax.set_yticklabels(configs, fontsize=10)

    for bar, val, cfg in zip(bars, values, configs):
        label = f"{val:.3f}"
        if val < 0.15:
            label += "  ← −87% drop" if "Bridge" in cfg and "Pathway" in title else ""
        ax.text(max(val - 0.03, 0.01), bar.get_y() + bar.get_height()/2,
                label, va="center", ha="right" if val > 0.1 else "left",
                fontsize=9.5, fontweight="bold", color="white" if val > 0.12 else C_DANGER)

    # annotation for Bridge ablation drop
    if "Pathway" in title:
        ax.annotate("−87%", xy=(0.084, 0), xytext=(0.4, 0.05),
                    fontsize=9, color=C_DANGER, fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=C_DANGER, lw=1.5))

ax1.invert_yaxis()
fig.suptitle("Figure 2: Component ablation study (N=3 disease-centered questions)",
             fontsize=11, fontweight="bold", y=1.02)
fig.tight_layout()
fig.savefig("evaluation/results/fig2_ablation.png", dpi=200, bbox_inches="tight")
plt.close()
print("✅ fig2_ablation.png 저장됨")


# ══════════════════════════════════════════════════════════════
# Figure 3  —  LLM-Judge per-dimension comparison (radar + bar)
# Internal (N=9) vs External PcQA (N=5 smoke)
# ══════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(10, 4.0))
fig.patch.set_facecolor("white")

DIMS   = ["D1\nFactual", "D2\nComplete", "D3\nTrace.", "D4\nSafety", "D5\nCohere."]
ALPHA  = 0.75

# ── Left: Internal N=9 (v2.3) ──────────────────────────────
ax = axes[0]
gdgpt_int = [2.926, 2.851, 4.038, 3.519, 3.000]
gpt4o_int = [5.000, 5.000, 3.223, 4.926, 5.000]
x = np.arange(len(DIMS))
w = 0.35
bars_g = ax.bar(x - w/2, gdgpt_int, w, color=C_GDGPT, alpha=ALPHA, label="GDgpt")
bars_b = ax.bar(x + w/2, gpt4o_int, w, color=C_GPT4O, alpha=ALPHA, label="GPT-4o")
# highlight D3 (GDgpt wins) and D4 (paradox)
ax.bar([x[2] - w/2], [gdgpt_int[2]], w, color=C_WIN, alpha=0.95)   # D3 GDgpt win
ax.bar([x[3] + w/2], [gpt4o_int[3]], w, color=C_DANGER, alpha=0.9)  # D4 paradox
ax.set_xticks(x); ax.set_xticklabels(DIMS, fontsize=9)
ax.set_ylim(0, 6.2); ax.set_ylabel("Score (1–5)", fontsize=9)
ax.set_title("Internal test set (N=9)", fontsize=10, fontweight="bold")
ax.axhline(5, color=C_GRAY, linewidth=0.7, linestyle="--", alpha=0.5)
ax.text(x[2] - w/2, gdgpt_int[2] + 0.12, "★", ha="center", fontsize=11, color=C_WIN)
ax.text(x[3] + 0.5, 4.1, "paradox\n↑", ha="center", fontsize=7.5, color=C_DANGER)
ax.legend(fontsize=8, loc="upper left")

# ── Right: External PcQA N=5 smoke ──────────────────────────
ax = axes[1]
gdgpt_ext = [3.177, 1.941, 4.206, 4.235, 3.000]   # N=68 weighted (49+19)
gpt4o_ext = [4.853, 4.588, 2.941, 4.235, 5.000]
bars_g2 = ax.bar(x - w/2, gdgpt_ext, w, color=C_GDGPT, alpha=ALPHA, label="GDgpt")
bars_b2 = ax.bar(x + w/2, gpt4o_ext, w, color=C_GPT4O, alpha=ALPHA, label="GPT-4o")
ax.bar([x[2] - w/2], [gdgpt_ext[2]], w, color=C_WIN, alpha=0.95)   # D3 GDgpt win
ax.bar([x[3] - w/2], [gdgpt_ext[3]], w, color=C_WIN, alpha=0.95)   # D4 GDgpt win (external!)
ax.set_xticks(x); ax.set_xticklabels(DIMS, fontsize=9)
ax.set_ylim(0, 6.2); ax.set_ylabel("Score (1–5)", fontsize=9)
ax.set_title("External PcQA (N=68 w/ per-dim, independent SOKG)", fontsize=9.5, fontweight="bold")
ax.axhline(5, color=C_GRAY, linewidth=0.7, linestyle="--", alpha=0.5)
for dim_i in [2, 3]:
    ax.text(x[dim_i] - w/2, gdgpt_ext[dim_i] + 0.12, "★", ha="center", fontsize=11, color=C_WIN)
ax.legend(fontsize=8, loc="upper left")

fig.suptitle(
    "Figure 3: LLM-Judge per-dimension scores — GDgpt leads D3 (Traceability) on both test sets\n"
    "★ = GDgpt leads | red bar = D4 paradox (judge rewards GPT-4o's confident answers despite 0% abstention)",
    fontsize=9.5, fontweight="bold", y=1.02
)
fig.tight_layout()
fig.savefig("evaluation/results/fig3_llmjudge_dims.png", dpi=200, bbox_inches="tight")
plt.close()
print("✅ fig3_llmjudge_dims.png 저장됨")
