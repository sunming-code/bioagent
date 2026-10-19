#!/usr/bin/env Rscript
packages <- c("scDblFinder", "SingleCellExperiment", "BiocParallel", "zellkonverter", "rhdf5", "HDF5Array",
              "scran", "MatrixGenerics", "sparseMatrixStats", "DelayedMatrixStats",
              "ggplot2", "dplyr", "ggsignif", "patchwork")
for (p in packages) {
    suppressPackageStartupMessages(library(p, character.only = TRUE))
    cat(p, as.character(packageVersion(p)), "\n")
}
cat(R.version.string, "\n")
cat("All required R packages load successfully.\n")
