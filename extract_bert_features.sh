export BERT_MODEL_PATH="multi_cased_L-12_H-768_A-12"

if [ ! -e $BERT_MODEL_PATH ]
then
   curl -O https://storage.googleapis.com/bert_models/2018_11_23/multi_cased_L-12_H-768_A-12.zip
   unzip multi_cased_L-12_H-768_A-12.zip
   rm multi_cased_L-12_H-768_A-12.zip
fi

PYTHONPATH=. python3 extract_features.py \
   --input_file=${1} \
   --output_file=./bert_features_${2}.hdf5 \
   --bert_config_file $BERT_MODEL_PATH/bert_config.json \
   --init_checkpoint $BERT_MODEL_PATH/bert_model.ckpt \
   --vocab_file $BERT_MODEL_PATH/vocab.txt \
   --do_lower_case=False \
   --stride 1 \
   --window_size 511 \
   --genres=ge

