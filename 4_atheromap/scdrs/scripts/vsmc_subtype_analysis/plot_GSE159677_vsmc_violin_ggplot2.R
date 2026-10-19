#!/usr/bin/env Rscript
# ggplot2 版 VSMC 亚型 scDRS violin 图
# 输出：
#   plots/vsmc_subtype_analysis/GSE159677_vsmc_final_violin_ggplot2.png
#   plots/vsmc_subtype_analysis/GSE159677_vsmc_subtype_condition_violin_ggplot2.png

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
  library(ggsignif)
})

# ── 路径 ──────────────────────────────────────────────────────────────────────
WORK_DIR <- Sys.getenv("ATHEROMAP_SCDRS_WORK_DIR")
if (!nzchar(WORK_DIR)) stop("Set ATHEROMAP_SCDRS_WORK_DIR before running")
MERGED   <- file.path(WORK_DIR, "merged/vsmc_subtype_analysis")
PLOT_DIR <- file.path(WORK_DIR, "plots/vsmc_subtype_analysis")

# ── 读取数据 ──────────────────────────────────────────────────────────────────
df <- read.csv(file.path(MERGED, "GSE159677_vsmc_celllevel_scores.csv"),
               stringsAsFactors = FALSE)

stats_subtype <- read.csv(
  file.path(MERGED, "GSE159677_vsmc_final_stats_z_score.csv"),
  stringsAsFactors = FALSE
)
stats_cond <- read.csv(
  file.path(MERGED, "GSE159677_vsmc_subtype_condition_stats_z_score.csv"),
  stringsAsFactors = FALSE
)

# ── 亚型顺序 & 颜色 ───────────────────────────────────────────────────────────
SUBTYPE_ORDER  <- c("Contractile", "Fibromyocyte", "Modulated")
SUBTYPE_COLORS <- c(
  "Contractile"  = "#4878D0",
  "Fibromyocyte" = "#6AAF5E",
  "Modulated"    = "#E07B3A"
)
COND_COLORS <- c("D" = "#B5651D", "H" = "#5B7FA6")

df$subtype   <- factor(df$subtype,   levels = SUBTYPE_ORDER)
df$condition <- factor(df$condition, levels = c("D", "H"))

# ── p 值 → 星号 ──────────────────────────────────────────────────────────────
p_to_stars <- function(p) {
  ifelse(p < 0.0001, "****",
  ifelse(p < 0.001,  "***",
  ifelse(p < 0.01,   "**",
  ifelse(p < 0.05,   "*", "ns"))))
}

# ══════════════════════════════════════════════════════════════════════════════
# 图 1：3 亚型 scDRS violin（只标涉及 Fibromyocyte 的两对）
# ══════════════════════════════════════════════════════════════════════════════

sig_pairs <- stats_subtype %>%
  filter(
    test == "mannwhitneyu", p_adj_bh < 0.05,
    group1 == "Contractile" & group2 == "Fibromyocyte" |
    group2 == "Fibromyocyte" & group1 == "Modulated" |
    group1 == "Fibromyocyte" & group2 == "Modulated"
  ) %>%
  mutate(stars = p_to_stars(p_adj_bh)) %>%
  select(group1, group2, stars)

annotations <- sig_pairs$stars
comparisons <- mapply(c, sig_pairs$group1, sig_pairs$group2, SIMPLIFY = FALSE)

y_max <- max(df$score, na.rm = TRUE)
y_pos <- seq(from = y_max + 0.3, by = 0.5, length.out = nrow(sig_pairs))

p1 <- ggplot(df, aes(x = subtype, y = score, fill = subtype)) +
  geom_violin(trim = FALSE, alpha = 0.85, color = NA, scale = "width") +
  geom_boxplot(
    width = 0.12, outlier.shape = NA,
    fill  = "white", color = "grey30", alpha = 0.7
  ) +
  geom_jitter(width = 0.15, size = 0.25, alpha = 0.25, color = "grey20") +
  ggsignif::geom_signif(
    comparisons = comparisons,
    annotations = annotations,
    y_position  = y_pos,
    tip_length  = 0.01,
    textsize    = 3.8,
    color       = "black"
  ) +
  scale_fill_manual(values = SUBTYPE_COLORS) +
  labs(
    title = paste0("VSMC subtype scDRS score (", length(SUBTYPE_ORDER), " subtypes)"),
    x     = NULL,
    y     = "z_score_norm_score"
  ) +
  theme_classic(base_size = 13) +
  theme(
    legend.position    = "none",
    plot.title         = element_text(hjust = 0.5, size = 13),
    axis.text.x        = element_text(size = 11),
    panel.grid.major.y = element_line(color = "grey90", linewidth = 0.4)
  )

ggsave(
  file.path(PLOT_DIR, "GSE159677_vsmc_final_violin_ggplot2.png"),
  p1, width = 8, height = 5.5, dpi = 200
)
cat("saved: GSE159677_vsmc_final_violin_ggplot2.png\n")

# ══════════════════════════════════════════════════════════════════════════════
# 图 2：亚型 × 条件 violin
# ══════════════════════════════════════════════════════════════════════════════

sig_cond <- stats_cond %>%
  filter(!is.na(p_adj_bh), p_adj_bh < 0.05) %>%
  mutate(stars = p_to_stars(p_adj_bh))

y_sig_top <- max(df$score, na.rm = TRUE) + 0.3

p2 <- ggplot(df, aes(x = condition, y = score, fill = condition)) +
  geom_violin(trim = FALSE, alpha = 0.85, color = NA, scale = "width") +
  geom_boxplot(
    width = 0.15, outlier.shape = NA,
    fill  = "white", color = "grey30", alpha = 0.7
  ) +
  facet_wrap(~ subtype, nrow = 1) +
  scale_fill_manual(
    values = COND_COLORS,
    labels = c("D" = "Disease (D)", "H" = "Healthy (H)")
  ) +
  labs(
    title = paste0("VSMC subtype × condition scDRS score (", length(SUBTYPE_ORDER), " subtypes)"),
    x     = NULL,
    y     = "z_score_norm_score",
    fill  = "Condition"
  ) +
  theme_bw(base_size = 13) +
  theme(
    plot.title         = element_text(hjust = 0.5, size = 13),
    strip.text         = element_text(size = 11, face = "bold"),
    strip.background   = element_blank(),
    legend.position    = "right",
    panel.grid.major.y = element_line(color = "grey90", linewidth = 0.4),
    panel.grid.minor   = element_blank(),
    panel.grid.major.x = element_blank(),
    axis.text.x        = element_text(size = 11),
    panel.border       = element_rect(color = "grey60", fill = NA, linewidth = 0.5)
  )

for (i in seq_len(nrow(sig_cond))) {
  st    <- sig_cond$subtype[i]
  stars <- sig_cond$stars[i]
  p2 <- p2 +
    ggsignif::geom_signif(
      data         = df %>% filter(subtype == st),
      comparisons  = list(c("D", "H")),
      annotations  = stars,
      y_position   = y_sig_top,
      tip_length   = 0.01,
      textsize     = 3.8,
      color        = "black",
      map_signif_level = FALSE
    )
}

ggsave(
  file.path(PLOT_DIR, "GSE159677_vsmc_subtype_condition_violin_ggplot2.png"),
  p2, width = 9, height = 5.5, dpi = 200
)
cat("saved: GSE159677_vsmc_subtype_condition_violin_ggplot2.png\n")
