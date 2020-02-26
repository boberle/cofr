from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys
import json
import subprocess

import tensorflow as tf
import coref_model as cm
import util


def bertify(fn, outfn, config):
  args = [
    "python3", "extract_features.py",
    f"--input_file={fn}",
    f"--output_file={outfn}",
    f"--bert_config_file={config['bert_model_path']}/bert_config.json",
    f"--init_checkpoint={config['bert_model_path']}/bert_model.ckpt",
    f"--vocab_file={config['bert_model_path']}/vocab.txt",
    "--do_lower_case=False",
    "--stride=1",
    "--window_size=129",
    "--genres=" + ",".join(config['genres']),
  ]
  env = os.environ.copy()
  env['PYTHONPATH'] = "."
  subprocess.run(args, env=env, check=True)




def run(config, input_filename, output_filename, cluster_key):

  model = cm.CorefModel(config)

  with tf.Session() as session:
    model.restore(session)

    with open(output_filename, "w") as output_file:
      with open(input_filename) as input_file:
        for example_num, line in enumerate(input_file.readlines()):
          example = json.loads(line)
          tensorized_example = model.tensorize_example(example, is_training=False)
          if tensorized_example is None:
            example[cluster_key] = []
          else:
            feed_dict = {i:t for i,t in zip(model.input_tensors, tensorized_example)}
            _, _, _, top_span_starts, top_span_ends, top_antecedents, top_antecedent_scores = session.run(model.predictions, feed_dict=feed_dict)
            predicted_antecedents = model.get_predicted_antecedents(top_antecedents, top_antecedent_scores)
            example[cluster_key], _ = model.get_predicted_clusters(top_span_starts, top_span_ends, predicted_antecedents)

          if cluster_key == "predicted_clusters" and "clusters" in example:
             del example["clusters"]

          output_file.write(json.dumps(example))
          output_file.write("\n")
          if example_num % 100 == 0:
            print("Decoded {} examples.".format(example_num + 1))

  print(f"Predicted {example_num+1} examples.")


def run_1model(config, input_filename, output_filename, cluster_key):
  run(
    config=config,
    input_filename=input_filename,
    output_filename=output_filename,
    cluster_key=cluster_key,
  )


def run_2models(exp1, exp2, input_filename, output_filename):

  args = f"python3 predict.py {exp1} {input_filename} intermediate.jsonlines --no-predicted".split()
  subprocess.run(args, check=True)

  args = f"python3 predict.py {exp2} intermediate.jsonlines {output_filename} --no-bertify".split()
  subprocess.run(args, check=True)



if __name__ == "__main__":

  two_models = "," in sys.argv[1]
  input_filename = sys.argv[2]
  output_filename = sys.argv[3]

  if two_models:
    exp1, exp2 = sys.argv[1].split(",")
    run_2models(
      exp1, exp2,
      input_filename=input_filename,
      output_filename=output_filename,
    )
  else:
    config = util.initialize_from_env(sys.argv[1])
    must_bertify = "--no-bertify" not in sys.argv
    cluster_key = "clusters" if "--no-predicted" in sys.argv else "predicted_clusters"
    config['lm_path'] = "bert_features_predict.hdf5"
    if must_bertify:
      bertify(input_filename, config['lm_path'], config)
    run_1model(
      config=config,
      input_filename=input_filename,
      output_filename=output_filename,
      cluster_key=cluster_key,
    )


