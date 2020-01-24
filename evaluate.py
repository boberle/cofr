#!/usr/bin/env python
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import subprocess

import tensorflow as tf

import util
import coref_model as cm


def run_2models(exp1, exp2, eval_path):

  if len(sys.argv) == 4:
     outfpath = sys.argv[3]
  else:
     raise RuntimeError("You need to specify an output file when using 2 models")

  #proc_args = f"python3 predict.py {exp1} {eval_path} intermediate.jsonlines --no-bertify --no-predicted".split()
  proc_args = f"python3 evaluate.py {exp1} {eval_path} intermediate.jsonlines".split()
  subprocess.run(proc_args, check=True)

  proc_args = f"python3 evaluate.py {exp2} intermediate.jsonlines {outfpath}".split()
  subprocess.run(proc_args, check=True)

  print("=" * 72)

  proc_args = f"python3 compare.py {eval_path} {outfpath}".split()
  subprocess.run(proc_args, check=True)



def run_1model(eval_path):

  outfpath = sys.argv[3] if len(sys.argv) == 4 else None

  sys.argv = sys.argv[:2]
  args = util.get_args()
  config = util.initialize_from_env(args.experiment, args.logdir)
  config['eval_path'] = eval_path

  model = cm.CorefModel(config, eval_mode=True)
  with tf.Session() as session:
    model.restore(session, args.latest_checkpoint)
    model.evaluate(session, official_stdout=True, pprint=False, test=True, outfpath=outfpath)


if __name__ == "__main__":

  eval_path = sys.argv[2]

  if ',' in sys.argv[1]:
    run_2models(*sys.argv[1].split(","), eval_path)
  else:
    run_1model(eval_path)
