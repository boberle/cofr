# coFR: COreference resolution tool For FRench


## Introduction

This repository contains an adaptation of the [Kantor and Globerson's coreference resolution tool](https://github.com/kentonl/e2e-coref) (described in Kantor and Globerson, 2019) to French.  The work is described in the following paper:

[Wilkens Rodrigo, Oberle Bruno, Landragin Frédéric, Todirascu Amalia (2020). **French coreference for spoken and written language**, _Proceedings of the 12th Edition of the Language Resources and Evaluation Conference (LREC 2020)_, Marseille, France](https://lrec2020.lrec-conf.org/en/).

For training and evaluation, we used two French corpora:

- Democrat (Landragin, 2016),
- Ancor (Muzerelle et al., 2014).

We converted the corpora into the `jsonlines` format used by the original system.  The Democrat corpus, originally composed of 10000-word-long chunks of longer texts has been split down to 2000-word-long documents.  We kept only the texts from the 19th century to the 20th century.  The Ancor corpus has been cut into thematic sections.  The corpus used are available for download below.

We have trained three models:

- `fr_mentcoref`: the model has been trained to detect mentions (all mentions, including singletons) and to resolve coreference,
- `fr_ment`: the model has been trained to detect mentions (all mentions) only,
- `fr_coref`: the model has been trained to resolve coreference only (oracle mentions are to be fed to the system in order to use this model).

We report the results of three experiments:

- using the model `fr_mentcoref`: this is the original end-to-end setup, in which one model both detects mentions and resolves coreference,
- using the model `fr_coref`: this is used to evaluate the coreference resolution task proper (as opposed to the combined two subtasks of mention detection and coreference resolution).  Oracle mentions are given to the system,
- using a sequence of two models: `fr_ment`, specialized for mention detection, and `fr_coref`, specialized for coreference resolution.

Features must be extracted before training or evaluating the model (this step is called `bertification` since it uses [BERT](https://github.com/google-research/bert) (Bidirectional Encoder Representations from Transformers)).  We tested two window sizes, the default one (511) and the one proposed by Kantor and Globerson (129).  The bigger window yields slightly better results, but the bertification process is longer (about 8x).  All our pretrained models use the bigger window size.


<table class="tg">
  <tr>
    <th class="tg-0lax"></th>
    <th class="tg-baqh" colspan="3">default window size (511)</th>
    <th class="tg-baqh" colspan="3">small window size (129)</th>
  </tr>
  <tr>
    <td class="tg-0pky"></td>
    <td class="tg-0pky">fr_mentcoref<br></td>
    <td class="tg-0pky">fr_coref</td>
    <td class="tg-fymr">fr_ment + fr_coref</td>
    <td class="tg-0pky">fr_mentcoref</td>
    <td class="tg-0lax">fr_coref</td>
    <td class="tg-0lax">fr_ment + fr_coref</td>
  </tr>
  <tr>
    <td class="tg-0pky">dem1921 (mention identification)</td>
    <td class="tg-0pky">76.36</td>
    <td class="tg-0pky">99.96</td>
    <td class="tg-fymr">88.95</td>
    <td class="tg-0pky">75.88</td>
    <td class="tg-0lax">99.96</td>
    <td class="tg-0lax">88.58</td>
  </tr>
  <tr>
    <td class="tg-0pky">dem1921 (conll f1)</td>
    <td class="tg-0pky">66.00</td>
    <td class="tg-0pky">85.04</td>
    <td class="tg-fymr">75.00</td>
    <td class="tg-0pky">65.38</td>
    <td class="tg-0lax">84.84</td>
    <td class="tg-0lax">74.97</td>
  </tr>
  <tr>
    <td class="tg-0pky">ancor (mention identification)</td>
    <td class="tg-0pky">52.75</td>
    <td class="tg-0pky">99.99</td>
    <td class="tg-fymr">88.06</td>
    <td class="tg-0pky">52.37</td>
    <td class="tg-0lax">99.99</td>
    <td class="tg-0lax">88.03</td>
  </tr>
  <tr>
    <td class="tg-0lax">ancor (conll f1)</td>
    <td class="tg-0lax">50.50</td>
    <td class="tg-0lax">88.75</td>
    <td class="tg-1wig">75.65</td>
    <td class="tg-0lax">50.48</td>
    <td class="tg-0lax">88.45</td>
    <td class="tg-0lax">75.47</td>
  </tr>
</table>


Note that these results include singleton mentions, which are available in both French corpora, but not in the standard corpus used for evaluation of English systems (OntoNotes/CoNLL 2012).

These scores were obtained with the official [scorer script](https://github.com/conll/reference-coreference-scorers) used for the CoNLL 2012 evaluation compaign.


References:
- Kantor and Globerson, 2019. "Coreference Resolution with Entity Equalization",
- Landragin, 2016. "Description, modélisation et détection automatique des chaı̂nes de référence (DEMOCRAT). Bulletin de l'Association Française pour l'Intelligence Artificielle.
- Muzerelle, Lefeuvre, Schang, Antoine Pelletier, Maurel, Eshkol and Villaneau 2014. ANCOR centre, a large free spoken french coreference corpus: description of the resource and reliability measures. In Proceedings of the 9th Language Resources and Evaluation Conference (LREC'2014).



## Getting started

First install the library requirements.  By default, we use `tensorflow-gpu`.  Install `tensorflow` if you want to use your CPU.

```bash
pip3 install -r requirements.txt
```

Examples below use Democrat.  If you prefer to train and evaluate with Ancor, use the `setup_{corpus,models}_ancor.sh` scripts and adapt the `experiments.conf` configuration file (search for `ancor` and `democrat` and comment/uncomment parameters according to your corpus).


### Evaluating

To reproduce our results, please run the following commands:

```
bash -x -e setup_all.sh
bash -x -e setup_corpus_dem1921.sh
bash -x -e setup_models_dem1921.sh
bash -x -e extract_bert_features.sh test.french.jsonlines evaluate
python3 evaluate.py fr_ment,fr_coref test.french.jsonlines output.jsonlines
```

This will download the corpus and our pretrained models.

Note that the longest part is the bertification and should be done with a GPU.  As said before, you can reduce the window size to 129.  This would yield slightly lower results but will dramatically decrease the bertification time.

Also note that this is not the official evaluation from the `scorer.pl` script used for the CoNLL-2012 evaluation campaign.  For that, you need to convert the `output.jsonlines` file to the CoNLL format and to use the [scorer script](https://github.com/conll/reference-coreference-scorers).

To convert to CoNLL, please see [these scripts](https://github.com/boberle/corefconversion).


### Training

To train new models, please run the following commands:

```
bash -x -e setup_all.sh
bash -x -e setup_corpus_dem1921.sh
bash -x -e setup_training.sh
python3 train.py train_fr_ment
python3 train.py train_fr_coref
```

### Predicting

First, you will need to download [BERT Multilingual](https://github.com/google-research/bert):

```
wget https://storage.googleapis.com/bert_models/2018_11_23/multi_cased_L-12_H-768_A-12.zip
unzip multi_cased_L-12_H-768_A-12.zip
rm multi_cased_L-12_H-768_A-12.zip
```

To make predictions with our pretrained models, you will need to convert your corpus in the `jsonlines` format (see use [these scripts](https://github.com/boberle/corefconversion) or the `detail_instructions.md` file).  For a demo, you can use one the document of the Democrat corpus:


```
bash -x -e setup_all.sh
bash -x -e setup_models_dem1921.sh
bash -x -e setup_corpus_dem1921.sh
head -n 5 test.french.jsonlines | shuf | head -n 1 > myfile.jsonlines
python3 predict.py fr_ment,fr_coref myfile.jsonlines mypredictions.jsonlines
```

To convert to the text or CoNLL formats, please see [these scripts](https://github.com/boberle/corefconversion).


## Example

Here is an example.  This is an except from the _Chartreuse de Parme_ (Stendhal), from [Wikisource](https%3A%2F%2Ffr.wikisource.org%2Fwiki%2FLa_Chartreuse_de_Parme_%28%25C3%25A9dition_Martineau%2C_1927%29).  This text is **NOT** part of the Democrat corpus, so it was totally unseen during the development and the training phases:

<b><span style="color: hsl(0, 100%, 40%);">[</span>Le marquis<span style="color: hsl(0, 100%, 40%);">]<sub>1</sub></span></b> professait <span style="color: gray;">[</span>une haine vigoureuse<span style="color: gray;">]</span> pour <span style="color: gray;">[</span>les lumières<span style="color: gray;">]</span> ; ce sont <b><span style="color: hsl(25, 100%, 40%);">[</span>les idées<span style="color: hsl(25, 100%, 40%);">]<sub>2</sub></span></b> , disait <b><span style="color: hsl(0, 100%, 40%);">[</span>-il<span style="color: hsl(0, 100%, 40%);">]<sub>1</sub></span></b> , <b><span style="color: hsl(25, 100%, 40%);">[</span>qui<span style="color: hsl(25, 100%, 40%);">]<sub>2</sub></span></b> ont perdu <span style="color: gray;">[</span>l' Italie<span style="color: gray;">]</span> ; <b><span style="color: hsl(0, 100%, 40%);">[</span>il<span style="color: hsl(0, 100%, 40%);">]<sub>1</sub></span></b> ne savait trop comment concilier <span style="color: gray;">[</span>cette sainte horreur de <span style="color: gray;">[</span>l' instruction<span style="color: gray;">]</span><span style="color: gray;">]</span> , avec le désir de voir <b><span style="color: hsl(50, 100%, 40%);">[</span><b><span style="color: hsl(0, 100%, 40%);">[</span>son<span style="color: hsl(0, 100%, 40%);">]<sub>1</sub></span></b> fils Fabrice<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> perfectionner <span style="color: gray;">[</span>l' éducation si brillamment commencée chez <span style="color: gray;">[</span>les jésuites<span style="color: gray;">]</span><span style="color: gray;">]</span> . Pour courir <span style="color: gray;">[</span>le moins de risques possible<span style="color: gray;">]</span> , <b><span style="color: hsl(0, 100%, 40%);">[</span>il<span style="color: hsl(0, 100%, 40%);">]<sub>1</sub></span></b> chargea <b><span style="color: hsl(75, 100%, 40%);">[</span>le bon abbé Blanès<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> , curé de <span style="color: gray;">[</span>Grianta<span style="color: gray;">]</span> , de faire continuer <b><span style="color: hsl(50, 100%, 40%);">[</span>Fabrice<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> <b><span style="color: hsl(50, 100%, 40%);">[</span>ses<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> études en <b><span style="color: hsl(100, 100%, 40%);">[</span>latin<span style="color: hsl(100, 100%, 40%);">]<sub>5</sub></span></b> . Il eût fallu que <b><span style="color: hsl(75, 100%, 40%);">[</span>le curé lui-même<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> sût <b><span style="color: hsl(125, 100%, 40%);">[</span>cette langue<span style="color: hsl(125, 100%, 40%);">]<sub>6</sub></span></b> ; or <b><span style="color: hsl(125, 100%, 40%);">[</span>elle<span style="color: hsl(125, 100%, 40%);">]<sub>6</sub></span></b> était <span style="color: gray;">[</span>l' objet de <span style="color: gray;">[</span><b><span style="color: hsl(50, 100%, 40%);">[</span>ses<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> mépris<span style="color: gray;">]</span><span style="color: gray;">]</span> ; <span style="color: gray;">[</span><b><span style="color: hsl(50, 100%, 40%);">[</span>ses<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> connaissances en <span style="color: gray;">[</span>ce genre<span style="color: gray;">]</span><span style="color: gray;">]</span> se bornaient à réciter , par cœur , <span style="color: gray;">[</span>les prières de <b><span style="color: hsl(150, 100%, 40%);">[</span><b><span style="color: hsl(50, 100%, 40%);">[</span>son<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> missel<span style="color: hsl(150, 100%, 40%);">]<sub>7</sub></span></b><span style="color: gray;">]</span> , <b><span style="color: hsl(150, 100%, 40%);">[</span>dont<span style="color: hsl(150, 100%, 40%);">]<sub>7</sub></span></b> <b><span style="color: hsl(50, 100%, 40%);">[</span>il<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> pouvait rendre à peu près <span style="color: gray;">[</span>le sens<span style="color: gray;">]</span> à <span style="color: gray;">[</span><b><span style="color: hsl(50, 100%, 40%);">[</span>ses<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> ouailles<span style="color: gray;">]</span> . Mais <b><span style="color: hsl(75, 100%, 40%);">[</span>ce curé<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> n' en était pas moins fort respecté et même redouté dans <span style="color: gray;">[</span>le canton<span style="color: gray;">]</span> ; <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> avait toujours dit que ce n' était point en <span style="color: gray;">[</span>treize semaines<span style="color: gray;">]</span> ni même en <span style="color: gray;">[</span>treize mois<span style="color: gray;">]</span> , que l' on verrait s' accomplir <span style="color: gray;">[</span>la célèbre prophétie de <span style="color: gray;">[</span>saint Giovita<span style="color: gray;">]</span><span style="color: gray;">]</span> , le patron de <span style="color: gray;">[</span>Brescia<span style="color: gray;">]</span> . <b><span style="color: hsl(75, 100%, 40%);">[</span>Il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> ajoutait , quand <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> parlait à <span style="color: gray;">[</span>des amis sûrs<span style="color: gray;">]</span> , que <span style="color: gray;">[</span>ce nombre treize<span style="color: gray;">]</span> devait être interprété d' <b><span style="color: hsl(175, 100%, 40%);">[</span>une façon<span style="color: hsl(175, 100%, 40%);">]<sub>8</sub></span></b> <b><span style="color: hsl(175, 100%, 40%);">[</span>qui<span style="color: hsl(175, 100%, 40%);">]<sub>8</sub></span></b> étonnerait bien de <b><span style="color: hsl(200, 100%, 40%);">[</span>le monde<span style="color: hsl(200, 100%, 40%);">]<sub>9</sub></span></b> , s' il était permis de tout dire ( <span style="color: gray;">[</span>1813<span style="color: gray;">]</span> ) . <span style="color: gray;">[</span>Le fait<span style="color: gray;">]</span> est que <b><span style="color: hsl(75, 100%, 40%);">[</span>l' abbé Blanès<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> , personnage d' <span style="color: gray;">[</span><span style="color: gray;">[</span>une honnêteté<span style="color: gray;">]</span> et d' <span style="color: gray;">[</span>une vertu primitives<span style="color: gray;">]</span><span style="color: gray;">]</span> , et de plus homme d' esprit , passait <span style="color: gray;">[</span>toutes les nuits<span style="color: gray;">]</span> à <span style="color: gray;">[</span>le haut de <b><span style="color: hsl(225, 100%, 40%);">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>son<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> clocher<span style="color: hsl(225, 100%, 40%);">]<sub>10</sub></span></b><span style="color: gray;">]</span> ; <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> était fou d' <span style="color: gray;">[</span>astrologie<span style="color: gray;">]</span> . Après avoir usé <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>ses<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> journées<span style="color: gray;">]</span> à calculer <b><span style="color: hsl(250, 100%, 40%);">[</span><span style="color: gray;">[</span>des conjonctions<span style="color: gray;">]</span> et <span style="color: gray;">[</span>des positions d' étoiles<span style="color: gray;">]</span><span style="color: hsl(250, 100%, 40%);">]<sub>11</sub></span></b> , <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> employait <span style="color: gray;">[</span>la meilleure part de <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>ses<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> nuits<span style="color: gray;">]</span><span style="color: gray;">]</span> à <b><span style="color: hsl(250, 100%, 40%);">[</span>les<span style="color: hsl(250, 100%, 40%);">]<sub>11</sub></span></b> suivre dans <span style="color: gray;">[</span>le ciel<span style="color: gray;">]</span> . Par suite de <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>sa<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> pauvreté<span style="color: gray;">]</span> , <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> n' avait d' <span style="color: gray;">[</span>autre instrument<span style="color: gray;">]</span> qu' <span style="color: gray;">[</span>une longue lunette à <span style="color: gray;">[</span>tuyau de carton<span style="color: gray;">]</span><span style="color: gray;">]</span> . <b><span style="color: hsl(275, 100%, 40%);">[</span>On<span style="color: hsl(275, 100%, 40%);">]<sub>12</sub></span></b> peut juger de <b><span style="color: hsl(300, 100%, 40%);">[</span>le mépris<span style="color: hsl(300, 100%, 40%);">]<sub>13</sub></span></b> <b><span style="color: hsl(300, 100%, 40%);">[</span>qu'<span style="color: hsl(300, 100%, 40%);">]<sub>13</sub></span></b> avait pour <span style="color: gray;">[</span>l' étude de <span style="color: gray;">[</span>les langues<span style="color: gray;">]</span><span style="color: gray;">]</span> <b><span style="color: hsl(325, 100%, 40%);">[</span>un homme<span style="color: hsl(325, 100%, 40%);">]<sub>14</sub></span></b> <b><span style="color: hsl(325, 100%, 40%);">[</span>qui<span style="color: hsl(325, 100%, 40%);">]<sub>14</sub></span></b> passait <span style="color: gray;">[</span><b><span style="color: hsl(325, 100%, 40%);">[</span>sa<span style="color: hsl(325, 100%, 40%);">]<sub>14</sub></span></b> vie<span style="color: gray;">]</span> à découvrir <span style="color: gray;">[</span>l' époque précise de <b><span style="color: hsl(350, 100%, 40%);">[</span>la chute de <span style="color: gray;">[</span>les empires<span style="color: gray;">]</span> et de <span style="color: gray;">[</span>les révolutions<span style="color: gray;">]</span><span style="color: hsl(350, 100%, 40%);">]<sub>15</sub></span></b><span style="color: gray;">]</span> <b><span style="color: hsl(350, 100%, 40%);">[</span>qui<span style="color: hsl(350, 100%, 40%);">]<sub>15</sub></span></b> changent <span style="color: gray;">[</span>la face de <b><span style="color: hsl(200, 100%, 40%);">[</span>le monde<span style="color: hsl(200, 100%, 40%);">]<sub>9</sub></span></b><span style="color: gray;">]</span> . Que sais <b><span style="color: hsl(0, 100%, 70%);">[</span>-je<span style="color: hsl(0, 100%, 70%);">]<sub>16</sub></span></b> de plus sur <b><span style="color: hsl(25, 100%, 70%);">[</span>un cheval<span style="color: hsl(25, 100%, 70%);">]<sub>17</sub></span></b> , disait <b><span style="color: hsl(0, 100%, 70%);">[</span>-il<span style="color: hsl(0, 100%, 70%);">]<sub>16</sub></span></b> à <b><span style="color: hsl(50, 100%, 40%);">[</span>Fabrice<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> , depuis qu' <b><span style="color: hsl(275, 100%, 40%);">[</span>on<span style="color: hsl(275, 100%, 40%);">]<sub>12</sub></span></b> <b><span style="color: hsl(0, 100%, 70%);">[</span>m'<span style="color: hsl(0, 100%, 70%);">]<sub>16</sub></span></b> a appris qu' en <b><span style="color: hsl(100, 100%, 40%);">[</span>latin<span style="color: hsl(100, 100%, 40%);">]<sub>5</sub></span></b> <b><span style="color: hsl(25, 100%, 70%);">[</span>il<span style="color: hsl(25, 100%, 70%);">]<sub>17</sub></span></b> s' appelle <span style="color: gray;">[</span>equus<span style="color: gray;">]</span> ? <b><span style="color: hsl(50, 100%, 70%);">[</span>Les paysans<span style="color: hsl(50, 100%, 70%);">]<sub>18</sub></span></b> redoutaient <b><span style="color: hsl(75, 100%, 40%);">[</span>l' abbé Blanès<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> comme <span style="color: gray;">[</span>un grand magicien<span style="color: gray;">]</span> : pour <b><span style="color: hsl(75, 100%, 40%);">[</span>lui<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> , à l' aide de <b><span style="color: hsl(75, 100%, 70%);">[</span>la peur<span style="color: hsl(75, 100%, 70%);">]<sub>19</sub></span></b> <b><span style="color: hsl(75, 100%, 70%);">[</span>qu'<span style="color: hsl(75, 100%, 70%);">]<sub>19</sub></span></b> inspiraient <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>ses<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> stations<span style="color: gray;">]</span> dans <b><span style="color: hsl(225, 100%, 40%);">[</span>le clocher<span style="color: hsl(225, 100%, 40%);">]<sub>10</sub></span></b> , <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> <b><span style="color: hsl(50, 100%, 70%);">[</span>les<span style="color: hsl(50, 100%, 70%);">]<sub>18</sub></span></b> empêchait de voler . <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>Ses<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> confrères les curés de <span style="color: gray;">[</span>les environs<span style="color: gray;">]</span><span style="color: gray;">]</span> , fort jaloux de <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>son<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> influence<span style="color: gray;">]</span> , <b><span style="color: hsl(75, 100%, 40%);">[</span>le<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> détestaient ; <b><span style="color: hsl(100, 100%, 70%);">[</span>le marquis del Dongo<span style="color: hsl(100, 100%, 70%);">]<sub>20</sub></span></b> <b><span style="color: hsl(75, 100%, 40%);">[</span>le<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> méprisait tout simplement , parce qu' <b><span style="color: hsl(100, 100%, 70%);">[</span>il<span style="color: hsl(100, 100%, 70%);">]<sub>20</sub></span></b> raisonnait trop pour <span style="color: gray;">[</span>un homme de si bas étage<span style="color: gray;">]</span> . <b><span style="color: hsl(50, 100%, 40%);">[</span>Fabrice<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> <b><span style="color: hsl(75, 100%, 40%);">[</span>l'<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> adorait ; pour <b><span style="color: hsl(75, 100%, 40%);">[</span>lui<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> plaire <b><span style="color: hsl(50, 100%, 40%);">[</span>il<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> passait quelquefois <span style="color: gray;">[</span>des soirées entières<span style="color: gray;">]</span> à faire <span style="color: gray;">[</span>des additions<span style="color: gray;">]</span> ou <span style="color: gray;">[</span>des multiplications énormes<span style="color: gray;">]</span> . Puis <b><span style="color: hsl(50, 100%, 40%);">[</span>il<span style="color: hsl(50, 100%, 40%);">]<sub>3</sub></span></b> montait à <b><span style="color: hsl(225, 100%, 40%);">[</span>le clocher<span style="color: hsl(225, 100%, 40%);">]<sub>10</sub></span></b> : c' était <span style="color: gray;">[</span>une grande faveur<span style="color: gray;">]</span> et que <b><span style="color: hsl(75, 100%, 40%);">[</span>l' abbé Blanès<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> n' avait jamais accordée à personne ; mais <b><span style="color: hsl(75, 100%, 40%);">[</span>il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> aimait <b><span style="color: hsl(75, 100%, 40%);">[</span>cet enfant<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> pour <span style="color: gray;">[</span><b><span style="color: hsl(75, 100%, 40%);">[</span>sa<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> naïveté<span style="color: gray;">]</span> . Si <b><span style="color: hsl(75, 100%, 40%);">[</span>tu<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> ne deviens pas hypocrite , <b><span style="color: hsl(75, 100%, 40%);">[</span>lui<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> disait <b><span style="color: hsl(75, 100%, 40%);">[</span>-il<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> , peut-être <b><span style="color: hsl(75, 100%, 40%);">[</span>tu<span style="color: hsl(75, 100%, 40%);">]<sub>4</sub></span></b> seras <span style="color: gray;">[</span>un homme<span style="color: gray;">]</span> .


## Going further

See the `detail_instructions.md` file for more information.


## Other Quirks

* It does not use GPUs by default. Instead, it looks for the `GPU` environment variable, which the code treats as shorthand for `CUDA_VISIBLE_DEVICES`.

## License

This work is published under the terms of the Apache 2.0 licence.  See the `LICENSE` file for more information.


## Acknowledgments

This work was supported by the Democrat projects (DEscription et MOdélisation des Chaı̂nes de Référence: outils pour l'Annotation de corpus (en diachronie et en langues comparées) et le Traitement automatique) and Alector (Aide à la lecture pour enfants dyslexiques et faibles lecteurs), from the French National Research Agency (ANR) (ANR-16-CE28-0005 and ANR-15-CE38-0008, respectively).
