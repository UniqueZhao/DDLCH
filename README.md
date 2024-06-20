<<<<<<< HEAD

# DDLCH

=======

# Deep Differential Lifelong Cross-modal Hashing for Stream Medical Data Retrieval (DDLCH)

## Abstract

With the explosive growth of stream medical multi-modal data, it is significant to develop an
efficient cross-modal retrieval algorithm to achieve effective retrieval. Within it, deep cross-modal
hashing which maps cross-modal data into low-dimensional Hamming space where similarity in
high-dimension space is preserved has made much progress. However, most of deep cross-modal
hashing algorithms are usually facing disability of adapting to dynamic steam medical data, non-
differentiable optimization and unaligned semantic across modalities. To address these, we, in this
paper, propose a novel deep differential lifelong cross-modal hashing method for large-scale stream
medical data retrieval. Specifically, we firstly design lifelong learning module to keep hash code
of original data unchanged and directly learn hash code of incremental data with new categories
to achieve continuous retrieval of stream medical data, which significantly reduces training time
and computation resource. Then, we propose differential cross-modal hashing module to generate
discriminative binary hash codes, which yields continuous and differentiable optimization and
improves accuracy. Besides, we introduce semantic alignment module which embeds intra-modal and
inter-modal losses to maintain the semantic similarity and dis-similarity among stream medical data
across modalities. Extensive experiments on benchmark medical data sets show that our proposed
method can retrieve dynamic stream medical cross-modal data effectively and obtain higher retrieval
performance comparing with recent state-of-the-art approaches.

------

### Dependencies 

you need to install these package to run

- visdom 0.1.8+
- pytorch 1.0.0+
- tqdm 4.0+  
- python 3.5+

----

### Dataset

we implement our method on dataset ODIR-5K, Colorectal and IU X-Ray:

(1) please download the ODIR-5K dataset from (https://odir2019.grand-challenge.org/dataset/)  and put it under the folder /dataset/data/.

(2) please download the Colorectal dataset from https://cdas.cancer.gov/datasets/plco/22/ and put them under the folder /dataset/data/.

(3) please download the IU X-Ray dataset from [https://openi.nlm.nih.gov/gridquery.php?q=Indiana%20chest%20X-ray%20collection&it=xg] and put them under the folder /dataset/data/.

### How to run

 Step1: Run make_or5k.py

Step2:  Run main.py --is-train

>>>>>>> 551f8a6 (first commit)
