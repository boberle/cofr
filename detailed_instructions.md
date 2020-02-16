# Detailed instructions


## Training and evaluating

### Extracting features

(This is done by the `setup_training.sh` script.)

First extract features with the `extract_bert_features.sh` script (adapt the BERT path in the script).

Note that the original release by Kantor and Globerson had the option `--window-size 129`, which was not the correct option (`--window_size`, with an underscore) and thus defaults to 511.  This is the value we first used, even if the feature extraction is very slow but produces slightly better results.

```bash
bash extract_bert_features.sh dev.french.jsonlines,train.french.jsonlines train
bash extract_bert_features.sh test.french.jsonlines evaluate
```

Now you have two `bert_feature_train.hdf5` and `bert_feature_evaluate.hdf5` files.

### Training

Download the corpus in jsonlines format (`setup_corpus_{ancor,dem1921}.sh`).

The dev, train and test files must be named according to the options of the `experiments.conf` file (or the reverse: adapt `experiments.conf`), by default: `{dev,train,test}.french.jsonlines}`.

Then run:

```bash
python3 train.py <EXPERIMENT>
```

For the `<EXPERIMENT>`, choose one of `experiments.conf`:

* `train_fr_mentcoref`: train mention detection and coreference resolution,
* `train_fr_ment`: train only mention detection,
* `train_fr_coref`: train only coreference resolution (gold standard mentions are used).

The models are saved in the corresponding `logs` subdirectories (`logs/train_fr_{mentcoref,ment,coref}`).


## Evaluating

Once the training is done, copy the models you want to use for evaluation and prediction into the corresponding `logs` subdirectories: `logs/fr_{mentcoref,ment,coref}` (note the absence of `train`).

You can also download our pretrained models with `setup_models_{ancor,dem1921}.sh`.

### Evaluating with one model

To evaluate one model, just run:

```bash
python3 evaluate.py <EXPERIMENT> test.french.jsonlines
```

where `<EXPERIMENT>` is one of `fr_{mentcoref,ment,coref}`.


### Evaluating with two models

If you have trained one model for mention detection (`train_fr_ment`) and one for coreference resolution (`train_fr_coref`):

```bash
python3 evaluate.py <EXP1>,<EXP2> test.french.jsonlines
```

where `<EXP1>` should be `fr_ment` and `<EXP2>` should be `fr_coref`.


## Predicting


### Creating a jsonlines files

Each line of a `jsonlines` file is a json document, as follows (remove newlines so that each document is on its own line):

```json
{
  "clusters": [],
  "doc_key": "ge:doc1",
  "sentences": [["Ceci", "est", "la", "première", "phrase", "."], ["Ceci", "est", "la", "seconde", "."]],
  "speakers": [["_", "_", "_", "_", "_", "_"], ["_", "_", "_", "_", "_"]]
}
```

Add speaker information if the model has been trained with speaker information (e.g. our pretrained Ancor model).  The first two characters of the `doc_key` is the genre.  Genres must match the genre used to train the models and the parameters in the `experiments.conf` file.

To get a pre-made jsonlinesified document, use one of the test corpus:

```bash
head -n 5 test.french.jsonlines | shuf | head -n 1 > myfile.jsonlines
```


### Predicting

This assumes you have copied your trained models (or our pretrained models) into `logs` subdirectories: `logs/fr_{mentcoref,ment,coref}`, as described above for evaluation.

If you want to predict with one model only, use:

```bash
python3 predict.py <EXPERIMENT> myfile.jsonlines mypredictions.jsonlines
```

If you want to predict with two models (one for mention detection and one for coreference resolution):

```bash
python3 predict.py <EXP1>,<EXP2> myfile.jsonlines mypredictions.jsonlines
```

where `<EXP1>` should be `fr_ment` and `<EXP2>` should be `fr_coref`.

Note that if you use your own corpus, you will need to adapt `char_vocab.french.txt`.  You can do that with the
`python3 get_char_vocab.py` script.



