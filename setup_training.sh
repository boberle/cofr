#!/bin/bash

python3 get_char_vocab.py

python3 filter_embeddings.py cc.fr.300.vec train.french.jsonlines dev.french.jsonlines # test.french.jsonlines

bash extract_bert_features.sh dev.french.jsonlines,train.french.jsonlines train
#bash extract_bert_features.sh test.french.jsonlines evaluate
