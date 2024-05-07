# set logging level 
import logging 
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor
import subprocess

from bam_to_bed import bam_to_bed 
from parallel_bed_operations import split_bed_file, write_sorted_chunk
from gtf_to_bed import gtf_to_bed, extend_gene_bed
from process_genome import read_chromosomes_from_genome_file, filter_bed_by_chromosome_inplace
from process_genome import read_chromosomes_from_genome_file

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# intersect the bam file against, exons, genes, and dog regions
def run_bedtools(bam_file, gtf_file, dog_bed_file, genome_file, output_dir, num_files=104):
    # Convert bam to bed and calculate the 3' end coordinates 
    bed_file, end_coordinates = bam_to_bed(bam_file, output_dir, num_files)

    # print("Preview of end_coordinates:")
    # for i, (key, value) in enumerate(end_coordinates.items()):
    #     if i < 5:
    #         print(f"{key}: {value}")

    # Split bed file into chunks
    temp_bed_files = split_bed_file(bed_file, output_dir, num_files)

    # convert exons and genes to bed 
    exon_bed_file = gtf_to_bed(gtf_file, "exon", output_dir)
    gene_bed_file = gtf_to_bed(gtf_file, "gene", output_dir)

    chromosomes = read_chromosomes_from_genome_file(genome_file)

    filter_bed_by_chromosome_inplace(exon_bed_file, chromosomes)
    filter_bed_by_chromosome_inplace(gene_bed_file, chromosomes)

    # extend genes to get DOG regions 
    dog_bed_file = extend_gene_bed(gene_bed_file, output_dir, genome_file)

    logging.info("Calculating alignment overlap with exons, genes and DOG regions")

    # Initialize ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=num_files) as executor:
        # Create tasks for intersecting with exons, genes, and DOGs
        tasks = []
        for bed_chunk in temp_bed_files:
            intersect_exon_cmd = f"bedtools intersect -a {bed_chunk} -b {exon_bed_file} -wo -s -sorted -g {genome_file} | sort -k4,4 -k6,6 -k8,8nr --parallel=104 --buffer-size=80G > {bed_chunk}_exon_overlap.bed"
            intersect_gene_cmd = f"bedtools intersect -a {bed_chunk} -b {gene_bed_file} -wo -s -sorted -g {genome_file} | sort -k4,4 -k6,6 -k8,8nr --parallel=104 --buffer-size=80G > {bed_chunk}_gene_overlap.bed"
            dog_intersect_cmd = f"bedtools intersect -a {bed_chunk} -b {dog_bed_file} -wo -s -sorted -g {genome_file} | sort -k4,4 -k6,6 -k8,8nr --parallel=104 --buffer-size=80G > {bed_chunk}_dog_overlap.bed"

            # intersect_exon_cmd = f"bedtools intersect -a {bed_chunk} -b {exon_bed_file} -wo -s -sorted | sort -k4,4 -k6,6 -k8,8nr --parallel=104 --buffer-size=80G > {bed_chunk}_exon_overlap.bed"
            # intersect_gene_cmd = f"bedtools intersect -a {bed_chunk} -b {gene_bed_file} -wo -s -sorted | sort -k4,4 -k6,6 -k8,8nr --parallel=104 --buffer-size=80G > {bed_chunk}_gene_overlap.bed"
            # dog_intersect_cmd = f"bedtools intersect -a {bed_chunk} -b {dog_bed_file} -wo -s -sorted | sort -k4,4 -k6,6 -k8,8nr --parallel=104 --buffer-size=80G > {bed_chunk}_dog_overlap.bed"
 
            tasks.extend([executor.submit(subprocess.run, cmd, shell=True, check=True) for cmd in [intersect_exon_cmd, intersect_gene_cmd, dog_intersect_cmd]])

        # Wait for all tasks to complete
        for task in as_completed(tasks):
            task.result()

    # Concatenate and sort the results
    for suffix in ["exon_overlap", "gene_overlap", "dog_overlap"]:
        output_files = [f"{bed_chunk}_{suffix}.bed" for bed_chunk in temp_bed_files]
        final_output_file = f"{bed_file}_{suffix}_final.bed"
        cmd = "cat " + " ".join(output_files) + f" | sort -k1,1 -k2,2n -k3,3n --parallel=104 --buffer-size=80G > {final_output_file}"
        process = subprocess.Popen(cmd, shell=True)
        process.wait()

        # Remove temporary files
        # for temp_file in output_files:
            # os.remove(temp_file)

    # Remove temporary bed chunks
    # for temp_bed in temp_bed_files:
        # os.remove(temp_bed)

    return f"{bed_file}_exon_overlap_final.bed", f"{bed_file}_gene_overlap_final.bed", f"{bed_file}_dog_overlap_final.bed", bed_file, end_coordinates
