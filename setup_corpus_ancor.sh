#!/bin/bash

curl -o dev.french.jsonlines.bz2 http://boberle.com/files/corpora/ancor/ancor_orig_sg_splitsent100.dev.jsonlines.bz2
curl -o test.french.jsonlines.bz2 http://boberle.com/files/corpora/ancor/ancor_orig_sg_splitsent100.test.jsonlines.bz2
curl -o train.french.jsonlines.bz2 http://boberle.com/files/corpora/ancor/ancor_orig_sg_splitsent100.train.jsonlines.bz2

bzip2 -d dev.french.jsonlines.bz2
bzip2 -d test.french.jsonlines.bz2
bzip2 -d train.french.jsonlines.bz2

python3 get_char_vocab.py
