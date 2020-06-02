#!/bin/bash

curl -Lo dev.french.jsonlines.bz2 http://boberle.com/files/corpora/dem1921/dem1921_sg_cut2000.dev.jsonlines.bz2
curl -Lo test.french.jsonlines.bz2 http://boberle.com/files/corpora/dem1921/dem1921_sg_cut2000.test.jsonlines.bz2
curl -Lo train.french.jsonlines.bz2 http://boberle.com/files/corpora/dem1921/dem1921_sg_cut2000.train.jsonlines.bz2

bzip2 -d dev.french.jsonlines.bz2
bzip2 -d test.french.jsonlines.bz2
bzip2 -d train.french.jsonlines.bz2

python3 get_char_vocab.py
