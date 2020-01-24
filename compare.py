import json
import metrics
import sys


def evaluate_coref(predicted_clusters, gold_clusters, evaluator):
     gold_clusters = [tuple(tuple(m) for m in gc) for gc in gold_clusters]
     mention_to_gold = {}
     for gc in gold_clusters:
         for mention in gc:
             mention_to_gold[mention] = gc

     predicted_clusters = [tuple(tuple(m) for m in pc) for pc in predicted_clusters]
     mention_to_predicted = {}
     for pc in predicted_clusters:
         for mention in pc:
             mention_to_predicted[mention] = pc

     evaluator.update(predicted_clusters, gold_clusters, mention_to_predicted, mention_to_gold)
     return predicted_clusters


def load_eval_data(gold_file, predicted_file):

  pred = dict()
  for line in open(predicted_file):
    data = json.loads(line)
    pred[data['doc_key']] = data

  gold = []
  for line in open(gold_file):
    data = json.loads(line)
    doc_key = data['doc_key']
    if doc_key in pred:
      pred_clusters = pred[doc_key]['predicted_clusters'] if 'predicted_clusters' in pred[doc_key] else pred[doc_key]['clusters']
      data['predicted_clusters'] = pred_clusters
    else:
      data['predicted_clusters'] = []
    gold.append(data)

  return gold


def evaluate(gold_file, predicted_file):

    metrics.INCLUDE_SINGLETONS = True

    eval_data = load_eval_data(gold_file, predicted_file)

    coref_predictions = {}
    coref_evaluator = metrics.CorefEvaluator()

    for example_num, example in enumerate(eval_data):

        coref_predictions[example["doc_key"]] = evaluate_coref(
          example['predicted_clusters'],
          example['clusters'],
          coref_evaluator,
        )

    mention_p, mention_r, mention_f = metrics.get_prf_mentions_for_all_documents(eval_data, coref_predictions)

    summary_dict = {}

    p, r, f = coref_evaluator.get_prf()
    average_f1 = f * 100
    summary_dict["Average F1 (py)"] = average_f1
    print("Average F1 (py): {:.2f}%".format(average_f1))
    summary_dict["Average precision (py)"] = p
    print("Average precision (py): {:.2f}%".format(p * 100))
    summary_dict["Average recall (py)"] = r
    print("Average recall (py): {:.2f}%".format(r * 100))

    average_mention_f1 = mention_f * 100
    summary_dict["Average mention F1 (py)"] = average_mention_f1
    print("Average mention F1 (py): {:.2f}%".format(average_mention_f1))
    summary_dict["Average mention precision (py)"] = mention_p
    print("Average mention precision (py): {:.2f}%".format(mention_p * 100))
    summary_dict["Average mention recall (py)"] = mention_r
    print("Average mention recall (py): {:.2f}%".format(mention_r * 100))


if __name__ == "__main__":
  
  evaluate(sys.argv[1], sys.argv[2])


