#!/usr/bin/env python
"""
Created on Apr 10, 2015

@author: Chen Yang

This script generates simulated Oxford Nanopore 2D reads.

"""


from __future__ import print_function
from __future__ import with_statement
import sys
import getopt
import random
import re
from time import strftime
try:
    import numpy as np
except ImportError:
    sys.exit("""You need numpy!
                install it from http://www.numpy.org/""")
import mixed_models as mm

PYTHON_VERSION = sys.version_info
VERSION = "1.0.0"
PRORAM = "NanoSim"
AUTHOR = "Chen Yang (UBC & BCGSC)"
CONTACT = "cheny@bcgsc.ca"

BASES = ['A', 'T', 'C', 'G']


# Check Python version, if it's Python 3, then define a xrange for range
def check_version():
    # There is no xrange built-in function in Python 3.
    try:
        xrange
    except NameError:
        xrange = range
    return


# Usage information
def usage():
    usage_message = "./simulator.py [command] <options>\n" \
                    "[command] circular | linear\n" \
                    "Do not choose 'circular' when there is more than one sequence in the reference\n" \
                    "<options>: \n" \
                    "-h : print usage message\n" \
                    "-r : reference genome in fasta file, specify path and file name\n" \
                    "-c : Flowcell chemistry, R7 or R7.3\n" \
                    "-o : The prefix of output file, default = 'simulated'\n" \
                    "-n : Number of generated reads, default = 24,221 reads\n" \
                    "-p : Error model profile, can be omitted if there is no customized profile\n" \
                    "--perfect: Output perfect reads, no mutations, default = False\n" \
                    "--KmerBias: prohibits homopolymers with length >= 6 bases in output reads\n"

    sys.stderr.write(usage_message)


def read_ecdf(profile):
    # We need to count the number of zeros. If it's over 10 zeros, l_len/l_ratio need to be changed to higher.
    # Because it's almost impossible that the ratio is much lower than the lowest heuristic value.
    header = profile.readline()
    header_info = header.strip().split()
    ecdf_dict = {}
    lanes = len(header_info[1:])

    for i in header_info[1:]:
        boundaries = i.split('-')
        ecdf_dict[(int(boundaries[0])), int(boundaries[1])] = {}

    ecdf_key = sorted(ecdf_dict.keys())
    l_prob = [0.0] * lanes
    l_ratio = [0.0] * lanes

    for line in profile:
        new = line.strip().split('\t')
        ratio = [float(x) for x in new[0].split('-')]
        prob = [float(x) for x in new[1:]]
        for i in xrange(lanes):
            if prob[i] == l_prob[i]:
                continue
            else:
                if l_prob[i] != 0:
                    ecdf_dict[ecdf_key[i]][(l_prob[i], prob[i])] = (l_ratio[i], ratio[1])
                else:
                    ecdf_dict[ecdf_key[i]][(l_prob[i], prob[i])] \
                        = (max(l_ratio[i], ratio[1] - 10 * (ratio[1] - ratio[0])), ratio[1])
                l_ratio[i] = ratio[1]
                l_prob[i] = prob[i]

    for i in xrange(0, len(ecdf_key)):
        last_key = sorted(ecdf_dict[ecdf_key[i]].keys())[-1]
        last_value = ecdf_dict[ecdf_key[i]][last_key]
        ecdf_dict[ecdf_key[i]][last_key] = (last_value[0], ratio[1])

    return ecdf_dict


def read_profile(number, chemistry, model_profile, per):
    global unaligned_length, sub_matrix, ref_length
    global match_ht_list, align_ratio, ht_dict, error_par
    global trans_error_pr, match_markov_model

    # Read model profile for match, mismatch, insertion and deletions
    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Read error profile\n")
    error_par = {}
    if model_profile == "":
        model_profile = chemistry + "_model_profile"
    with open(model_profile, 'r') as mod_profile:
        mod_profile.readline()
        for line in mod_profile:
            new_line = line.strip().split("\t")
            if "mismatch" in line:
                error_par["mis"] = [float(x) for x in new_line[1:]]
            elif "insertion" in line:
                error_par["ins"] = [float(x) for x in new_line[1:]]
            else:
                error_par["del"] = [float(x) for x in new_line[1:]]

    trans_error_pr = {}
    with open(chemistry + "_error_markov_model", "r") as error_markov:
        error_markov.readline()
        for line in error_markov:
            info = line.strip().split()
            k = info[0]
            trans_error_pr[k] = {}
            trans_error_pr[k][(0, float(info[1]))] = "mis"
            trans_error_pr[k][(float(info[1]), float(info[1]) + float(info[2]))] = "ins"
            trans_error_pr[k][(1 - float(info[3]), 1)] = "del"

    with open(chemistry + "_first_match.hist", 'r') as fm_profile:
        match_ht_list = read_ecdf(fm_profile)

    with open(chemistry + "_match_markov_model", 'r') as mm_profile:
        match_markov_model = read_ecdf(mm_profile)

    # Read length of unaligned reads
    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Read ECDF of unaligned reads\n")
    unaligned_length = []
    with open(chemistry + "_unaligned_length_ecdf", 'r') as u_profile:
        new = u_profile.readline()
        rate = float(new.split('\t')[1])
        # if parameter perfect is used, all reads should be aligned, number_aligned equals total number of reads.
        if per:
            number_aligned = number
        else:
            number_aligned = int(round(number * rate / (rate + 1)))
        number_unaligned = number - number_aligned
        unaligned_dict = read_ecdf(u_profile)

    for i in xrange(number_unaligned):
        p = random.random()
        key = unaligned_dict.keys()[0]
        for k_p, v_p in unaligned_dict[key].items():
            if k_p[0] <= p < k_p[1]:
                # consider this small range is linearly distributed:
                unaligned = (p - k_p[0])/(k_p[1] - k_p[0]) * (v_p[1] - v_p[0]) + v_p[0]
                unaligned_length.append(int(round(unaligned)))
                break

    unaligned_dict.clear()

    # Read profile of aligned reads
    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Read ECDF of aligned reads\n")

    # Read align ratio profile
    with open(chemistry + "_align_ratio", 'r') as a_profile:
        align_ratio = read_ecdf(a_profile)

    # Read head/unaligned region ratio
    with open(chemistry + "_ht_ratio", 'r') as ht_profile:
        ht_dict = read_ecdf(ht_profile)

    # Read length of aligned reads
    # If "perfect" is chosen, just use the total length ecdf profile, else use the length of aligned region on reference
    if per:
        length_profile = chemistry + "_aligned_reads_ecdf"
    else:
        length_profile = chemistry + "_aligned_length_ecdf"

    with open(length_profile, 'r') as align_profile:
        aligned_dict = read_ecdf(align_profile)
    ref_length = []

    for i in xrange(number_aligned):
        middle_ref = 0
        while middle_ref < 80:
            p = random.random()
            key = aligned_dict.keys()[0]
            for k_p, v_p in aligned_dict[key].items():
                if k_p[0] <= p < k_p[1]:
                    middle_ref = int(round((p - k_p[0])/(k_p[1] - k_p[0]) * (v_p[1] - v_p[0]) + v_p[0]))
                    break
        ref_length.append(middle_ref)

    aligned_dict.clear()


def simulation(ref, out, dna_type, per, mis_w, ins_w, del_w, kmer_bias):
    global unaligned_length, ref_length, sub_matrix
    global genome_len, seq_dict, seq_len
    global match_ht_list, align_ratio, ht_dict, match_markov_model
    global trans_error_pr, error_par

    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Read in reference genome\n")
    seq_dict = {}
    seq_len = {}

    # Read in the reference genome
    with open(ref, 'r') as infile:
        for line in infile:
            if line[0] == ">":
                new_line = line.strip()[1:].split()
                chr_name = "-".join(new_line)
            else:
                if chr_name in seq_dict:
                    seq_dict[chr_name] += line.strip()
                else:
                    seq_dict[chr_name] = line.strip()

    if len(seq_dict) > 1 and dna_type == "circular":
        sys.stderr.write("Do not choose circular if there is more than one chromosome in the genome!")
        sys.exit(1)

    for key in seq_dict.keys():
        seq_len[key] = len(seq_dict[key])
    genome_len = sum(seq_len.values())

    # Start simulation
    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Start simulation of random reads\n")
    out_reads = open(out + "_reads.fasta", 'w')
    out_error = open(out + "_error_profile", 'w')
    out_error.write("Seq_name\tSeq_pos\terror_type\terror_length\tref_base\tseq_base\n")

    # Simulate random reads
    for i in xrange(len(unaligned_length)):
        unaligned = unaligned_length[i]
        unaligned, error_dict = unaligned_error_list(unaligned, error_par)
        new_read, new_read_name = extract_read(dna_type, unaligned)
        out_reads.write(">" + new_read_name + "_" + str(unaligned) + "-" + str(i) + "\n")
        read_mutated = mutate_read(new_read, new_read_name, out_error, error_dict, kmer_bias, False)
        out_reads.write(read_mutated + "\n")
    del unaligned_length

    middle_length = []
    aligned_length = []
    middle_all_ratio = []
    remainder_length = []
    head_length = []
    tail_length = []

    # Simulate aligned reads
    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Start simulation of aligned reads\n")
    if per:
        for i in xrange(len(ref_length)):
            new_read, new_read_name = extract_read(dna_type, ref_length[i])
            out_reads.write(">" + new_read_name + "_" + str(ref_length[i]) + "_" + str(i) + "\n")
            out_reads.write(new_read + "\n")
        out_reads.close()
        out_error.close()
        return

    for i in xrange(len(ref_length)):
        middle, middle_ref, error_dict = error_list(ref_length[i], match_markov_model, match_ht_list, error_par,
                                                    trans_error_pr, mis_w, ins_w, del_w)

        ref_length[i] = middle_ref
        middle_length.append(middle)

        for k_align in sorted(align_ratio.keys()):
            if k_align[0] <= middle < k_align[1]:
                break

        total = 0
        while total < 400:
            p = random.random()
            for k_r, v_r in align_ratio[k_align].items():
                if k_r[0] <= p < k_r[1]:
                    ratio = (p - k_r[0])/(k_r[1] - k_r[0]) * (v_r[1] - v_r[0]) + v_r[0]
                    total = int(round(middle / ratio))
                    remainder = total - int(round(middle))
                    break
        aligned_length.append(total)
        middle_all_ratio.append(ratio)
        remainder_length.append(remainder)

        if remainder == 0:
            head = 0
            tail = 0
        else:
            for k_ht in sorted(ht_dict.keys()):
                if k_ht[0] <= remainder < k_ht[1]:
                    p = random.random()
                    for k_h, v_h in ht_dict[k_ht].items():
                        if k_h[0] <= p < k_h[1]:
                            ratio = (p - k_h[0])/(k_h[1] - k_h[0]) * (v_h[1] - v_h[0]) + v_h[0]
                            head = int(round(remainder * ratio))
                            tail = remainder - head
                            break
                    break
        head_length.append(head)
        tail_length.append(tail)

        # Extract middle region from reference genome
        new_read, new_read_name = extract_read(dna_type, middle_ref)

        # Mutate read
        read_mutated = mutate_read(new_read, new_read_name, out_error, error_dict, kmer_bias)

        # Add head and tail region
        for x in xrange(head):
            new_base = random.choice(BASES)
            read_mutated = new_base + read_mutated

        for x in xrange(tail):
            new_base = random.choice(BASES)
            read_mutated = read_mutated + new_base

        p = random.random()
        if p < 0.5:
            read_mutated = reverse_complement(read_mutated)

        out_reads.write(">" + new_read_name + "_" + str(head) + "_" + str(middle) + "_" +
                        str(tail) + "-" + str(i) + "\n")
        out_reads.write(read_mutated + "\n")

    out_reads.close()
    out_error.close()

    align_ratio.clear()
    ht_dict.clear()

    o1 = open("head", 'w')
    o2 = open("middle", 'w')
    o3 = open("tail", 'w')
    o4 = open("aligned", 'w')
    o5 = open("ht", 'w')
    o6 = open("ratio", 'w')
    o7 = open("middle_ref", 'w')

    o1.write("\n".join(str(x) for x in head_length))
    o2.write("\n".join(str(x) for x in middle_length))
    o3.write("\n".join(str(x) for x in tail_length))
    o4.write("\n".join(str(x) for x in aligned_length))
    o5.write("\n".join(str(x) for x in remainder_length))
    o6.write("\n".join(str(x) for x in middle_all_ratio))
    o7.write("\n".join(str(x) for x in ref_length))

    o1.close()
    o2.close()
    o3.close()
    o4.close()
    o5.close()
    o6.close()
    o7.close()


def reverse_complement(seq):
    comp = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}
    seq_list = list(seq)
    reverse_seq_list = reversed([comp.get(base, base) for base in seq_list])
    reverse_seq = ''.join(reverse_seq_list)
    return reverse_seq


def extract_read(dna_type, length):
    global seq_dict, seq_len, genome_len

    if length > max(seq_dict.values()):
        length = max(seq_dict.values())

    # Extract the aligned region from reference
    if dna_type == "circular":
        ref_pos = random.randint(0, genome_len)
        chromosome = seq_dict.keys()[0]
        new_read_name = chromosome + "_" + str(ref_pos)
        if length + ref_pos <= genome_len:
            new_read = seq_dict[chromosome][ref_pos: ref_pos + length]
        else:
            new_read = seq_dict[chromosome][ref_pos:]
            new_read = new_read + seq_dict[chromosome][0: length - genome_len + ref_pos]
    else:
        # Generate a random number within the size of the genome. Suppose chromosomes are connected
        # tail to head one by one in the order of the dictionary. If the start position fits in one
        # chromosome, but the end position does not, then restart generating random number.
        while True:
            new_read = ""
            ref_pos = random.randint(0, genome_len)
            for key in seq_len.keys():
                if ref_pos + length <= seq_len[key]:
                    new_read = seq_dict[key][ref_pos: ref_pos + length]
                    new_read_name = key + "_" + str(ref_pos)
                    break
                elif ref_pos < seq_len[key]:
                    break
                else:
                    ref_pos -= seq_len[key]
            if new_read != "":
                break
    return new_read, new_read_name


def unaligned_error_list(length, error_p):
    e_dict = {}
    error_rate = {(0, 0.4): "match", (0.4, 0.7): "mis", (0.7, 0.85): "ins", (0.85, 1): "del"}
    pos = 0
    last_is_ins = False
    while pos < length:
        p = random.random()
        for k_error in error_rate.keys():
            if k_error[0] <= p < k_error[1]:
                error_type = error_rate[k_error]
                break

        if error_type == "match":
            step = 1

        elif error_type == "mis":
            step = mm.pois_geom(error_p["mis"][0], error_p["mis"][2], error_p["mis"][3])
            e_dict[pos] = ["mis", step]

        elif error_type == "ins":
            step = mm.wei_geom(error_p["ins"][0], error_p["ins"][1], error_p["ins"][2], error_p["ins"][3])
            if last_is_ins:
                e_dict[pos + 0.1][1] += step
            else:
                e_dict[pos + 0.1] = ["ins", step]
                last_is_ins = True

        else:
            step = mm.wei_geom(error_p["del"][0], error_p["del"][1], error_p["del"][2], error_p["del"][3])
            e_dict[pos] = ["del", step]

        if error_type != "ins":
            pos += step
            last_is_ins = False

        if pos > length:
            length = pos

    return length, e_dict


def error_list(m_ref, m_model, m_ht_list, error_p, trans_p, m_w, i_w, d_w):
    # l_old is the original length, and l_new is used to control the new length after introducing errors
    l_new = m_ref
    pos = 0
    e_dict = {}
    middle_ref = m_ref
    last_error = "start"

    # The first match come from m_ht_list
    p = random.random()
    k1 = m_ht_list.keys()[0]
    for k2, v2 in m_ht_list[k1].items():
        if k2[0] < p <= k2[1]:
            last_match = int(np.floor((p - k2[0])/(k2[1] - k2[0]) * (v2[1] - v2[0]) + v2[0]))
            if last_match < 2:
                last_match = 2
    pos += last_match

    # Select an error, then the step size, and then a match and so on so forth.
    while pos < middle_ref:
        # pick the error based on Markov chain
        p = random.random()
        for k in trans_p[last_error].keys():
            if k[0] <= p < k[1]:
                error = trans_p[last_error][k]
                break

        if error == "mis":
            step = mm.pois_geom(error_p["mis"][0], error_p["mis"][2], error_p["mis"][3] * m_w)
        elif error == "ins":
            step = mm.wei_geom(error_p[error][0], error_p[error][1], error_p[error][2], error_p[error][3] * i_w)
            l_new += step
        else:
            step = mm.wei_geom(error_p[error][0], error_p[error][1], error_p[error][2], error_p[error][3] * d_w)
            l_new -= step

        if error != "ins":
            e_dict[pos] = [error, step]
            pos += step
            if pos >= middle_ref:
                l_new += pos - middle_ref
                middle_ref = pos
        else:
            e_dict[pos - 0.5] = [error, step]

        last_error = error

        # Randomly select a match length
        for k1 in m_model.keys():
            if k1[0] <= last_match < k1[1]:
                break
        p = random.random()
        for k2, v2 in m_model[k1].items():
            if k2[0] < p <= k2[1]:
                step = int(np.floor((p - k2[0])/(k2[1] - k2[0]) * (v2[1] - v2[0]) + v2[0]))
                break
        # there are no two 0 base matches together
        if last_match == 0 and step == 0:
            step = 1

        last_match = step
        if pos + last_match > middle_ref:
            l_new += pos + last_match - middle_ref
            middle_ref = pos + last_match

        pos += last_match
        if last_match == 0:
            last_error += "0"

    return l_new, middle_ref, e_dict


def mutate_read(read, read_name, error_log, e_dict, bias, aligned=True):
    for key in sorted(e_dict.keys(), reverse=True):
        val = e_dict[key]
        key = int(round(key))

        if val[0] == "mis":
            ref_base = read[key: key + val[1]]
            while True:
                new_bases = ""
                for i in xrange(val[1]):
                    tmp_bases = list(BASES)
                    tmp_bases.remove(read[key + i])
                    new_base = random.choice(tmp_bases)
                    new_bases += new_base
                check_kmer = read[key - 5: key] + new_bases + read[key + val[1]: key + val[1] + 5]
                if not bias or not re.search("AAAAAA+|TTTTTT+|CCCCCC+|GGGGGG+", check_kmer):
                    break
            new_read = read[:key] + new_bases + read[key + val[1]:]

        elif val[0] == "del":
            new_bases = val[1] * "-"
            ref_base = read[key: key + val[1]]
            new_read = read[: key] + read[key + val[1]:]

        elif val[0] == "ins":
            ref_base = val[1] * "-"
            while True:
                new_bases = ""
                for i in xrange(val[1]):
                    new_base = random.choice(BASES)
                    new_bases += new_base
                check_kmer = read[key - 5: key] + new_bases + read[key: key + 5]
                if not bias or not re.search("AAAAAA+|TTTTTT+|CCCCCC+|GGGGGG+", check_kmer):
                    break
            new_read = read[:key] + new_bases + read[key:]

        read = new_read

        if aligned and val[0] != "match":
            error_log.write(read_name + "\t" + str(key) + "\t" + val[0] + "\t" + str(val[1]) +
                            "\t" + ref_base + "\t" + new_bases + "\n")

    # If choose to have kmer bias, then need to compress homopolymers to 5-mer
    if bias:
        new_read = re.sub("AAAAAA+", "AAAAA", new_read)
        new_read = re.sub("CCCCCC+", "CCCCC", new_read)
        new_read = re.sub("TTTTTT+", "TTTTT", new_read)
        new_read = re.sub("GGGGGG+", "GGGGG", new_read)

    return new_read


def main():
    check_version()

    ref = ""
    chemistry = ""
    out = "simulated"
    number = 24221
    model_profile = ""
    perfect = False
    # ins, del, mis rate represent the weight tuning in mix model
    ins_rate = 1
    del_rate = 1
    mis_rate = 1
    kmer_bias = False

    # Parse options and parameters
    if len(sys.argv) < 6:
        usage()
        sys.exit(2)
    else:
        dna_type = sys.argv[1]
        if dna_type not in ["circular", "linear"]:
            usage()
        try:
            opts, args = getopt.getopt(sys.argv[2:], "hr:c:o:n:i:d:m:p:", ["perfect", "KmerBias"])
        except getopt.GetoptError:
            usage()
            sys.exit(2)
        for opt, arg in opts:
            if opt == "-r":
                ref = arg
            elif opt == "-c":
                chemistry = arg
                if chemistry not in ("R7", "R7.3"):
                    usage()
                    sys.exit(2)
            elif opt == "-o":
                out = arg
            elif opt == "-n":
                number = int(arg)
            elif opt == "-p":
                model_profile = arg
            elif opt == "-i":
                ins_rate = float(arg)
            elif opt == "-d":
                del_rate = float(arg)
            elif opt == "-m":
                mis_rate = float(arg)
            elif opt == "--perfect":
                perfect = True
            elif opt == "--KmerBias":
                kmer_bias = True
            elif opt == "-h":
                print("./simulator.py circular|linear -r <reference genome> -c <flowcell chemistry> "
                      "-o <output prefix> -n <number of simulated reads>")

    # Generate log file
    sys.stdout = open(out + ".log", 'w')
    # Record the command typed to log file
    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ': ' + ' '.join(sys.argv) + '\n')

    if ref == "" or chemistry == "":
        usage()
        sys.exit(2)

    # Read in reference genome and generate simulated reads
    read_profile(number, chemistry, model_profile, perfect)

    simulation(ref, out, dna_type, perfect, mis_rate, ins_rate, del_rate, kmer_bias)

    sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ": Finished!")
    sys.stdout.close()

if __name__ == "__main__":
    main()