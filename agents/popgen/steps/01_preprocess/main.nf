#!/usr/bin/env nextflow
nextflow.enable.dsl = 2

// ========================================================
// PopGen Agent · 步骤 1：FASTQ → 真 VCF（GRCh38）
// 复用已建好的参考索引；第一轮关闭 snpEff
// ========================================================

params.fastq_dir = "${projectDir}/../../data/fastq"
params.ref       = "${projectDir}/../../data/reference/GRCh38.fa"
params.outdir    = "${projectDir}/../../results"
params.sample_id = "patient"
params.threads   = 8
params.reads     = "${params.fastq_dir}/*_R{1,2}.fastq.gz"


process STAGE_GENOME {
    tag "Reuse prebuilt GRCh38 indexes"

    input:
    path fasta
    path fai
    path dict
    path amb
    path ann
    path bwt
    path pac
    path sa

    output:
    tuple path(fasta), path(fai), path(dict), path(amb), path(ann), path(bwt), path(pac), path(sa), emit: genome

    script:
    """
    echo "Reuse prebuilt indexes (skip bwa/samtools/gatk rebuild)"
    ls -lh ${fasta} ${fai} ${dict} ${bwt} ${sa}
    """
}


process ALIGN_READS {
    tag "BWA-MEM ${params.sample_id}"
    cpus params.threads
    memory '16 GB'

    input:
    tuple path(fasta), path(fai), path(dict), path(amb), path(ann), path(bwt), path(pac), path(sa)
    tuple val(pair_id), path(reads)

    output:
    tuple path(fasta), path(fai), path(dict), path(amb), path(ann), path(bwt), path(pac), path(sa),
          path("${params.sample_id}.sorted.bam"), path("${params.sample_id}.sorted.bam.bai"), emit: aligned

    script:
    """
    bwa mem -t ${task.cpus} \\
        -R "@RG\\tID:${params.sample_id}\\tSM:${params.sample_id}\\tPL:ILLUMINA" \\
        ${fasta} ${reads[0]} ${reads[1]} \\
        | samtools sort -@ ${task.cpus} -o ${params.sample_id}.sorted.bam -
    samtools index ${params.sample_id}.sorted.bam
    """
}


process MARK_DUPLICATES {
    tag "MarkDuplicates ${params.sample_id}"
    cpus 4
    memory '16 GB'

    input:
    tuple path(fasta), path(fai), path(dict), path(amb), path(ann), path(bwt), path(pac), path(sa),
          path(bam), path(bai)

    output:
    tuple path(fasta), path(fai), path(dict), path(amb), path(ann), path(bwt), path(pac), path(sa),
          path("${params.sample_id}.dedup.bam"), path("${params.sample_id}.dedup.bai"), emit: dedup
    path "${params.sample_id}.dup_metrics.txt"

    script:
    """
    gatk MarkDuplicates \\
        -I ${bam} \\
        -O ${params.sample_id}.dedup.bam \\
        -M ${params.sample_id}.dup_metrics.txt \\
        --CREATE_INDEX true \\
        --VALIDATION_STRINGENCY LENIENT
    """
}


process CALL_VARIANTS {
    tag "HaplotypeCaller ${params.sample_id}"
    cpus params.threads
    memory '32 GB'

    input:
    tuple path(fasta), path(fai), path(dict), path(amb), path(ann), path(bwt), path(pac), path(sa),
          path(bam), path(bai)

    output:
    tuple path("${params.sample_id}.vcf.gz"), path("${params.sample_id}.vcf.gz.tbi"), emit: vcf

    script:
    """
    gatk HaplotypeCaller \\
        -R ${fasta} \\
        -I ${bam} \\
        -O ${params.sample_id}.vcf.gz \\
        --native-pair-hmm-use-double-precision true
    """
}


process PUBLISH_VCF {
    tag "Publish patient.vcf"
    publishDir params.outdir, mode: 'copy'

    input:
    tuple path(vcf_gz), path(tbi)

    output:
    path "patient.vcf"
    path "patient.vcf.gz"
    path "patient.vcf.gz.tbi"
    path "patient.bcftools_stats.txt"

    script:
    """
    [ "${vcf_gz}" = "patient.vcf.gz" ] || cp -f ${vcf_gz} patient.vcf.gz
    [ "${tbi}" = "patient.vcf.gz.tbi" ] || cp -f ${tbi} patient.vcf.gz.tbi
    bcftools view -O v -o patient.vcf patient.vcf.gz
    bcftools stats patient.vcf > patient.bcftools_stats.txt
    """
}


workflow {
    log.info """
    ==========================================
    PopGen Agent · Step 1  FASTQ → VCF
    ==========================================
    FASTQ dir : ${params.fastq_dir}
    Reads     : ${params.reads}
    Reference : ${params.ref}
    Output    : ${params.outdir}
    Sample    : ${params.sample_id}
    Threads   : ${params.threads}
    snpEff    : OFF (first real-data round)
    ==========================================
    """

    reads_ch = Channel.fromFilePairs(params.reads, checkIfExists: true)

    ref_fa   = file(params.ref, checkIfExists: true)
    ref_dir  = ref_fa.parent
    ref_fai  = file("${ref_fa}.fai", checkIfExists: true)
    ref_dict = file("${ref_dir}/${ref_fa.simpleName}.dict", checkIfExists: true)
    ref_amb  = file("${ref_fa}.amb", checkIfExists: true)
    ref_ann  = file("${ref_fa}.ann", checkIfExists: true)
    ref_bwt  = file("${ref_fa}.bwt", checkIfExists: true)
    ref_pac  = file("${ref_fa}.pac", checkIfExists: true)
    ref_sa   = file("${ref_fa}.sa",  checkIfExists: true)

    genome_ch = STAGE_GENOME(
        ref_fa, ref_fai, ref_dict, ref_amb, ref_ann, ref_bwt, ref_pac, ref_sa
    ).genome

    aligned_ch = ALIGN_READS(genome_ch, reads_ch).aligned
    dedup_ch   = MARK_DUPLICATES(aligned_ch).dedup
    vcf_ch     = CALL_VARIANTS(dedup_ch).vcf
    PUBLISH_VCF(vcf_ch)
}
