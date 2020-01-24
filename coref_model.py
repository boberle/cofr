from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import operator
import random
import math
import json
import threading
import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
import h5py

import util
#import coref_ops # depends on config['use_gold_mentions']
import conll
import metrics
from util import attention_layer

class CorefModel(object):
    def __init__(self, config, eval_mode=False):
        self.config = config


        #### bad practice: singletons in the `metrics` module ####
        metrics.INCLUDE_SINGLETONS = self.config['include_singletons']

        ###

        #### import coref_ops depending on 'gold_mentions' config
        global coref_ops
        if config['use_gold_mentions']:
           print('   /!\\ using gold mentions /!\\   ')
           import coref_ops_gold_mentions as coref_ops
        else:
           print('   /!\\ **not** using gold mentions /!\\   ')
           import coref_ops
        ####

        self.context_embeddings = util.EmbeddingDictionary(config["context_embeddings"])
        self.head_embeddings = util.EmbeddingDictionary(config["head_embeddings"], maybe_cache=self.context_embeddings)
        self.char_embedding_size = config["char_embedding_size"]
        self.char_dict = util.load_char_dict(config["char_vocab_path"])
        self.max_span_width = config["max_span_width"]
        self.genres = {g: i for i, g in enumerate(config["genres"])}
        if config["lm_path"]:
            self.lm_file = h5py.File(self.config["lm_path"], "r")
        else:
            self.lm_file = None
        self.lm_layers = self.config["lm_layers"]
        self.lm_size = self.config["lm_size"]
        self.eval_data = None  # Load eval data lazily.

        input_props = []
        input_props.append((tf.string, [None, None]))  # Tokens.
        input_props.append((tf.float32, [None, None, self.context_embeddings.size]))  # Context embeddings.
        input_props.append((tf.float32, [None, None, self.head_embeddings.size]))  # Head embeddings.
        input_props.append((tf.float32, [None, None, self.lm_size, self.lm_layers]))  # LM embeddings.
        input_props.append((tf.int32, [None, None, None]))  # Character indices.
        input_props.append((tf.int32, [None]))  # Text lengths.
        input_props.append((tf.int32, [None]))  # Speaker IDs.
        input_props.append((tf.int32, []))  # Genre.
        input_props.append((tf.bool, []))  # Is training.
        input_props.append((tf.int32, [None]))  # Gold starts.
        input_props.append((tf.int32, [None]))  # Gold ends.
        input_props.append((tf.int32, [None]))  # Cluster ids.

        self.queue_input_tensors = [tf.placeholder(dtype, shape) for dtype, shape in input_props]
        dtypes, shapes = zip(*input_props)
        queue = tf.PaddingFIFOQueue(capacity=10, dtypes=dtypes, shapes=shapes)
        self.enqueue_op = queue.enqueue(self.queue_input_tensors)
        self.input_tensors = queue.dequeue()

        self.predictions, self.loss = self.get_predictions_and_loss(*self.input_tensors)
        self.global_step = tf.Variable(0, name="global_step", trainable=False)
        self.reset_global_step = tf.assign(self.global_step, 0)
        self.learning_rate = tf.train.exponential_decay(self.config["learning_rate"], self.global_step,
                                                        self.config["decay_frequency"], self.config["decay_rate"],
                                                        staircase=True)
        self.trainable_variables = tf.trainable_variables()
        gradients = tf.gradients(self.loss, self.trainable_variables)
        gradients, _ = tf.clip_by_global_norm(gradients, self.config["max_gradient_norm"])
        optimizers = {
            "adam": tf.train.AdamOptimizer,
            "sgd": tf.train.GradientDescentOptimizer
        }
        optimizer = optimizers[self.config["optimizer"]](self.learning_rate)
        opt_op = optimizer.apply_gradients(zip(gradients, self.trainable_variables), global_step=self.global_step)
        # Create an ExponentialMovingAverage object
        self.ema = tf.train.ExponentialMovingAverage(decay=self.config["ema_decay"])
        with tf.control_dependencies([opt_op]):
            self.train_op = self.ema.apply(self.trainable_variables)
        self.gold_loss = tf.constant(0.)

        # Don't try to restore unused variables from the TF-Hub ELMo module.
        vars_to_restore = [v for v in tf.global_variables() if "module/" not in v.name]
        if eval_mode:
            vars_to_restore = {self.ema.average_name(v): v for v in tf.trainable_variables()}
        self.saver = tf.train.Saver(vars_to_restore)

        if not eval_mode:
            # Make backup variables
            with tf.variable_scope('BackupVariables'):
                self.backup_vars = [tf.get_variable(var.op.name, dtype=var.value().dtype, trainable=False,
                                                    initializer=var.initialized_value())
                                    for var in self.trainable_variables]

            self.is_training = self.input_tensors[8]
            self.switch_to_train_mode_op = tf.cond(self.is_training, lambda: tf.group(), self.to_training)
            self.switch_to_test_mode_op = tf.cond(self.is_training, self.to_testing, lambda: tf.group())

    def ema_to_weights(self):
        return tf.group(*(tf.assign(var, self.ema.average(var).read_value())
                          for var in self.trainable_variables))

    def save_weight_backups(self):
        return tf.group(*(tf.assign(bck, var.read_value())
                          for var, bck in zip(self.trainable_variables, self.backup_vars)))

    def restore_weight_backups(self):
        return tf.group(*(tf.assign(var, bck.read_value())
                          for var, bck in zip(self.trainable_variables, self.backup_vars)))

    def to_training(self):
        return self.restore_weight_backups()

    def to_testing(self):
        with tf.control_dependencies([self.save_weight_backups()]):
            return self.ema_to_weights()

    def start_enqueue_thread(self, session):
        with open(self.config["train_path"]) as f:
            train_examples = [json.loads(jsonline) for jsonline in f.readlines()]

        def _enqueue_loop():
            while True:
                #with open(self.config["train_path"]) as f:
                #    train_examples = [json.loads(jsonline) for jsonline in f.readlines()]
                random.shuffle(train_examples)
                for example in train_examples:
                    tensorized_example = self.tensorize_example(example, is_training=True)
                    #### if no mentions in document, skip (see explanations in tensorize_example())
                    if tensorized_example is None:
                        continue
                    feed_dict = dict(zip(self.queue_input_tensors, tensorized_example))
                    session.run(self.enqueue_op, feed_dict=feed_dict)

        enqueue_thread = threading.Thread(target=_enqueue_loop)
        enqueue_thread.daemon = True
        enqueue_thread.start()

    def restore(self, session, latest_checkpoint=False, fpath=None):

        #####
        if fpath:
            checkpoint_path = fpath
        else:
           if latest_checkpoint:
               checkpoint_path = tf.train.latest_checkpoint(self.config["log_dir"])
           else:
               checkpoint_path = os.path.join(self.config["log_dir"], "model.max.ckpt")
        #####

        print("Restoring from {}".format(checkpoint_path))
        session.run(tf.global_variables_initializer())
        self.saver.restore(session, checkpoint_path)

    def load_lm_embeddings(self, doc_key):
        if self.lm_file is None:
            return np.zeros([0, 0, self.lm_size, self.lm_layers])
        file_key = doc_key.replace("/", ":")
        group = self.lm_file[file_key]
        num_sentences = len(list(group.keys()))
        sentences = [group[str(i)][...] for i in range(num_sentences)]
        lm_emb = np.zeros([num_sentences, max(s.shape[0] for s in sentences), self.lm_size, self.lm_layers])
        for i, s in enumerate(sentences):
            lm_emb[i, :s.shape[0], :, :] = s
        return lm_emb


    def tensorize_mentions(self, mentions):
        if len(mentions) > 0:
            starts, ends = zip(*mentions)
        else:
            starts, ends = [], []
        return np.array(starts), np.array(ends)

    def tensorize_span_labels(self, tuples, label_dict):
        if len(tuples) > 0:
            starts, ends, labels = zip(*tuples)
        else:
            starts, ends, labels = [], [], []
        return np.array(starts), np.array(ends), np.array([label_dict[c] for c in labels])




    def tensorize_example(self, example, is_training):

        clusters = example["clusters"]

        ###
        if self.config['use_gold_mentions']:

           if self.config['include_singletons']:
               min_length = 1
           else:
               min_length = 2

           new_clusters = []
           for cluster in clusters:
             new_cluster = []
             for start, end in cluster:
                if end - start < self.config["max_span_width"]:
                   new_cluster.append((start, end))
             if len(new_cluster) >= min_length: ################### NOTE: Removing cluster if singleton because of removal of a long mention ###################################
                new_clusters.append(new_cluster)
           clusters = new_clusters
           # return None if no mentions
           if not len(clusters):
               return None
           example["clusters"] = clusters
        ###


        gold_mentions = sorted(tuple(m) for m in util.flatten(clusters))
        gold_mention_map = {m: i for i, m in enumerate(gold_mentions)}
        cluster_ids = np.zeros(len(gold_mentions))
        for cluster_id, cluster in enumerate(clusters):
            for mention in cluster:
                cluster_ids[gold_mention_map[tuple(mention)]] = cluster_id + 1

        sentences = example["sentences"]
        num_words = sum(len(s) for s in sentences)

        # if not enough words, k may be 0...
        if num_words * self.config['top_span_ratio'] < 1:
            return None


        speakers = util.flatten(example["speakers"])

        assert num_words == len(speakers)

        max_sentence_length = max(len(s) for s in sentences)
        max_word_length = max(max(max(len(w) for w in s) for s in sentences), max(self.config["filter_widths"]))
        text_len = np.array([len(s) for s in sentences])
        tokens = [[""] * max_sentence_length for _ in sentences]
        context_word_emb = np.zeros([len(sentences), max_sentence_length, self.context_embeddings.size])
        head_word_emb = np.zeros([len(sentences), max_sentence_length, self.head_embeddings.size])
        char_index = np.zeros([len(sentences), max_sentence_length, max_word_length])
        for i, sentence in enumerate(sentences):
            for j, word in enumerate(sentence):
                tokens[i][j] = word
                context_word_emb[i, j] = self.context_embeddings[word]
                head_word_emb[i, j] = self.head_embeddings[word]
                char_index[i, j, :len(word)] = [self.char_dict[c] for c in word]
        tokens = np.array(tokens)

        speaker_dict = {s: i for i, s in enumerate(set(speakers))}
        speaker_ids = np.array([speaker_dict[s] for s in speakers])

        doc_key = example["doc_key"]
        genre = self.genres[doc_key[:2]]

        gold_starts, gold_ends = self.tensorize_mentions(gold_mentions)

        lm_emb = self.load_lm_embeddings(doc_key)

        example_tensors = (
            tokens, context_word_emb, head_word_emb, lm_emb, char_index, text_len, speaker_ids, genre, is_training,
            gold_starts, gold_ends, cluster_ids)

        if is_training and len(sentences) > self.config["max_training_sentences"]:
            res = self.truncate_example(*example_tensors)
            if res is None and self.config['use_gold_mentions']:
                return None
            return res
        else:
            return example_tensors


    def truncate_example(self, tokens, context_word_emb, head_word_emb, lm_emb, char_index, text_len, speaker_ids,
                         genre, is_training, gold_starts, gold_ends, cluster_ids):
        max_training_sentences = self.config["max_training_sentences"]
        num_sentences = context_word_emb.shape[0]
        assert num_sentences > max_training_sentences

        sentence_offset = random.randint(0, num_sentences - max_training_sentences)
        word_offset = text_len[:sentence_offset].sum()
        num_words = text_len[sentence_offset:sentence_offset + max_training_sentences].sum()
        tokens = tokens[sentence_offset:sentence_offset + max_training_sentences, :]
        context_word_emb = context_word_emb[sentence_offset:sentence_offset + max_training_sentences, :, :]
        head_word_emb = head_word_emb[sentence_offset:sentence_offset + max_training_sentences, :, :]
        lm_emb = lm_emb[sentence_offset:sentence_offset + max_training_sentences, :, :, :]
        char_index = char_index[sentence_offset:sentence_offset + max_training_sentences, :, :]
        text_len = text_len[sentence_offset:sentence_offset + max_training_sentences]

        speaker_ids = speaker_ids[word_offset: word_offset + num_words]
        gold_spans = np.logical_and(gold_ends >= word_offset, gold_starts < word_offset + num_words)
        gold_starts = gold_starts[gold_spans] - word_offset
        gold_ends = gold_ends[gold_spans] - word_offset
        cluster_ids = cluster_ids[gold_spans]

        if not len(gold_starts):
            return None

        return tokens, context_word_emb, head_word_emb, lm_emb, char_index, text_len, speaker_ids, genre, is_training, gold_starts, gold_ends, cluster_ids

    def get_candidate_labels(self, candidate_starts, candidate_ends, labeled_starts, labeled_ends, labels):
        same_start = tf.equal(tf.expand_dims(labeled_starts, 1),
                              tf.expand_dims(candidate_starts, 0))  # [num_labeled, num_candidates]
        same_end = tf.equal(tf.expand_dims(labeled_ends, 1),
                            tf.expand_dims(candidate_ends, 0))  # [num_labeled, num_candidates]
        same_span = tf.to_int32(tf.logical_and(same_start, same_end))  # [num_labeled, num_candidates]
        is_gold_span = tf.reduce_sum(same_span, axis=0)
        candidate_labels = tf.matmul(tf.expand_dims(labels, 0), same_span)  # [1, num_candidates]
        candidate_labels = tf.squeeze(candidate_labels, 0)  # [num_candidates]
        return candidate_labels, is_gold_span

    def get_dropout(self, dropout_rate, is_training):
        return 1 - (tf.to_float(is_training) * dropout_rate)

    def coarse_to_fine_pruning(self, top_span_emb, top_span_mention_scores, c):
        k = util.shape(top_span_emb, 0)
        top_span_range = tf.range(k)  # [k]
        antecedent_offsets = tf.expand_dims(top_span_range, 1) - tf.expand_dims(top_span_range, 0)  # [k, k]
        antecedents_mask = antecedent_offsets >= 1  # [k, k]
        fast_antecedent_scores = tf.expand_dims(top_span_mention_scores, 1) + tf.expand_dims(top_span_mention_scores,
                                                                                             0)  # [k, k]
        fast_antecedent_scores += tf.log(tf.to_float(antecedents_mask))  # [k, k]
        fast_antecedent_scores += self.get_fast_antecedent_scores(top_span_emb)  # [k, k]

        _, top_antecedents = tf.nn.top_k(fast_antecedent_scores, c, sorted=False)  # [k, c]
        top_antecedents_mask = util.batch_gather(antecedents_mask, top_antecedents)  # [k, c]
        top_fast_antecedent_scores = util.batch_gather(fast_antecedent_scores, top_antecedents)  # [k, c]
        top_antecedent_offsets = util.batch_gather(antecedent_offsets, top_antecedents)  # [k, c]
        return top_antecedents, top_antecedents_mask, top_fast_antecedent_scores, top_antecedent_offsets

    def distance_pruning(self, top_span_emb, top_span_mention_scores, c):
        k = util.shape(top_span_emb, 0)
        top_antecedent_offsets = tf.tile(tf.expand_dims(tf.range(c) + 1, 0), [k, 1])  # [k, c]
        raw_top_antecedents = tf.expand_dims(tf.range(k), 1) - top_antecedent_offsets  # [k, c]
        top_antecedents_mask = raw_top_antecedents >= 0  # [k, c]
        top_antecedents = tf.maximum(raw_top_antecedents, 0)  # [k, c]

        top_fast_antecedent_scores = tf.expand_dims(top_span_mention_scores, 1) + tf.gather(top_span_mention_scores,
                                                                                            top_antecedents)  # [k, c]
        top_fast_antecedent_scores += tf.log(tf.to_float(top_antecedents_mask))  # [k, c]
        return top_antecedents, top_antecedents_mask, top_fast_antecedent_scores, top_antecedent_offsets

    def compute_b3_loss(self, p_m_entity, gold_m_entity, beta=2.0):
        # remove singleton entities
        gold_entities = tf.reduce_sum(gold_m_entity, 0) > 1.2
        gold_entities = tf.cond(tf.reduce_any(gold_entities),
                                true_fn=lambda: gold_entities,
                                false_fn=lambda: tf.reduce_sum(gold_m_entity, 0) > 0)
        k = tf.shape(p_m_entity)[0]
        sys_m_e = tf.one_hot(tf.argmax(p_m_entity, 1), k)
        sys_entities = tf.reduce_sum(sys_m_e, 0) > 1.2
        sys_entities = tf.cond(tf.reduce_any(sys_entities),
                               true_fn=lambda: sys_entities,
                               false_fn=lambda: tf.reduce_sum(sys_m_e, 0) > 0)

        gold_entity_filter = tf.reshape(tf.where(gold_entities), [-1])
        gold_cluster = tf.gather(tf.transpose(gold_m_entity), gold_entity_filter)  # [gold_entities, mentions]  x[i, j] = I[m_j \in e_i]

        sys_entity_filter, merge = tf.cond(pred=tf.reduce_any(sys_entities & gold_entities),
                                           true_fn=lambda: (tf.reshape(tf.where(sys_entities), [-1]), tf.constant(0)),
                                           false_fn=lambda: (
                                           tf.reshape(tf.where(sys_entities | gold_entities), [-1]), tf.constant(1)))
        system_cluster = tf.gather(tf.transpose(p_m_entity), sys_entity_filter)  # [sys_entities, mentions]  x[i, j] = p[m_j \in e_i]

        # compute intersections
        gold_sys_intersect = tf.pow(tf.matmul(gold_cluster, system_cluster, transpose_b=True), 2)  # [gold_entities, sys_entities]  x[i, j] = \sum_k I[m_k \in e_i] * p[m_k \in e_j]
        r_num = tf.reduce_sum(tf.reduce_sum(gold_sys_intersect, 1) / tf.reduce_sum(gold_cluster, 1))
        r_den = tf.reduce_sum(gold_cluster)
        recall = tf.reshape(r_num / r_den, [])

        sys_gold_intersection = tf.transpose(gold_sys_intersect)
        p_num = tf.reduce_sum(tf.reduce_sum(sys_gold_intersection, 1) / tf.reduce_sum(system_cluster, 1))
        p_den = tf.reduce_sum(system_cluster)
        prec = tf.reshape(p_num / p_den, [])

        beta_2 = beta ** 2
        f_beta = (1 + beta_2) * prec * recall / (beta_2 * prec + recall)

        lost = 1.-f_beta
        # lost = tf.Print(lost, [lost, r_num, r_den, p_num, p_den, p_m_entity, gold_m_entity], summarize=1000)
        # lost = tf.Print(lost, [lost, merge,
        #                        r_num, r_den, p_num, p_den,
        #                        gold_entity_filter, sys_entity_filter,  # tf.reduce_sum(p_m_entity, 0),
        #                        beta, recall, prec, f_beta], summarize=1000)
        # lost = tf.Print(lost, [lost,
        #                        tf.reduce_all([r_num > .1, p_num > .1, r_den > .1, p_den > .1]),
        #                        r_num, r_den, p_num, p_den,
        #                        tf.reduce_sum(gold_sys_intersect, 1), tf.reduce_sum(gold_cluster, 1)], summarize=1000)
        #
        # return tf.cond(pred=tf.reduce_all([r_num > .1, p_num > .1, r_den > .1, p_den > .1]),
        #                true_fn=lambda: lost,
        #                false_fn=lambda: lost * 0.)

        return lost

    def get_predictions_and_loss(self, tokens, context_word_emb, head_word_emb, lm_emb, char_index, text_len,
                                 speaker_ids, genre, is_training, gold_starts, gold_ends, cluster_ids):
        self.dropout = self.get_dropout(self.config["dropout_rate"], is_training)
        self.lexical_dropout = self.get_dropout(self.config["lexical_dropout_rate"], is_training)
        self.lstm_dropout = self.get_dropout(self.config["lstm_dropout_rate"], is_training)

        num_sentences = tf.shape(context_word_emb)[0]
        max_sentence_length = tf.shape(context_word_emb)[1]

        context_emb_list = [context_word_emb]
        head_emb_list = [head_word_emb]

        if self.config["char_embedding_size"] > 0:
            char_emb = tf.gather(
                tf.get_variable("char_embeddings", [len(self.char_dict), self.config["char_embedding_size"]]),
                char_index)  # [num_sentences, max_sentence_length, max_word_length, emb]
            flattened_char_emb = tf.reshape(char_emb, [num_sentences * max_sentence_length, util.shape(char_emb, 2),
                                                       util.shape(char_emb,
                                                                  3)])  # [num_sentences * max_sentence_length, max_word_length, emb]
            flattened_aggregated_char_emb = util.cnn(flattened_char_emb, self.config["filter_widths"], self.config[
                "filter_size"])  # [num_sentences * max_sentence_length, emb]
            aggregated_char_emb = tf.reshape(flattened_aggregated_char_emb, [num_sentences, max_sentence_length,
                                                                             util.shape(flattened_aggregated_char_emb,
                                                                                        1)])  # [num_sentences, max_sentence_length, emb]
            context_emb_list.append(aggregated_char_emb)
            head_emb_list.append(aggregated_char_emb)

        if not self.lm_file:
            elmo_module = hub.Module("https://tfhub.dev/google/elmo/2")
            lm_embeddings = elmo_module(
                inputs={"tokens": tokens, "sequence_len": text_len},
                signature="tokens", as_dict=True)
            word_emb = lm_embeddings["word_emb"]  # [num_sentences, max_sentence_length, 512]
            lm_emb = tf.stack([tf.concat([word_emb, word_emb], -1),
                               lm_embeddings["lstm_outputs1"],
                               lm_embeddings["lstm_outputs2"]], -1)  # [num_sentences, max_sentence_length, 1024, 3]
        lm_emb_size = util.shape(lm_emb, 2)
        lm_num_layers = util.shape(lm_emb, 3)
        with tf.variable_scope("lm_aggregation"):
            self.lm_weights = tf.nn.softmax(
                tf.get_variable("lm_scores", [lm_num_layers], initializer=tf.constant_initializer(0.0)))
            self.lm_scaling = tf.get_variable("lm_scaling", [], initializer=tf.constant_initializer(1.0))
        flattened_lm_emb = tf.reshape(lm_emb, [num_sentences * max_sentence_length * lm_emb_size, lm_num_layers])
        flattened_aggregated_lm_emb = tf.matmul(flattened_lm_emb, tf.expand_dims(self.lm_weights,
                                                                                 1))  # [num_sentences * max_sentence_length * emb, 1]
        aggregated_lm_emb = tf.reshape(flattened_aggregated_lm_emb, [num_sentences, max_sentence_length, lm_emb_size])
        aggregated_lm_emb *= self.lm_scaling
        context_emb_list.append(aggregated_lm_emb)

        context_emb = tf.concat(context_emb_list, 2)  # [num_sentences, max_sentence_length, emb]
        head_emb = tf.concat(head_emb_list, 2)  # [num_sentences, max_sentence_length, emb]
        context_emb = tf.nn.dropout(context_emb, self.lexical_dropout)  # [num_sentences, max_sentence_length, emb]
        head_emb = tf.nn.dropout(head_emb, self.lexical_dropout)  # [num_sentences, max_sentence_length, emb]

        text_len_mask = tf.sequence_mask(text_len, maxlen=max_sentence_length)  # [num_sentence, max_sentence_length]

        context_outputs = self.lstm_contextualize(context_emb, text_len, text_len_mask)  # [num_words, emb]
        num_words = util.shape(context_outputs, 0)

        genre_emb = tf.gather(tf.get_variable("genre_embeddings", [len(self.genres), self.config["feature_size"]]),
                              genre)  # [emb]

        sentence_indices = tf.tile(tf.expand_dims(tf.range(num_sentences), 1),
                                   [1, max_sentence_length])  # [num_sentences, max_sentence_length]
        flattened_sentence_indices = self.flatten_emb_by_sentence(sentence_indices, text_len_mask)  # [num_words]
        flattened_head_emb = self.flatten_emb_by_sentence(head_emb, text_len_mask)  # [num_words]

        candidate_starts = tf.tile(tf.expand_dims(tf.range(num_words), 1),
                                   [1, self.max_span_width])  # [num_words, max_span_width]
        candidate_ends = candidate_starts + tf.expand_dims(tf.range(self.max_span_width),
                                                           0)  # [num_words, max_span_width]
        candidate_start_sentence_indices = tf.gather(flattened_sentence_indices,
                                                     candidate_starts)  # [num_words, max_span_width]
        candidate_end_sentence_indices = tf.gather(flattened_sentence_indices, tf.minimum(candidate_ends,
                                                                                          num_words - 1))  # [num_words, max_span_width]
        candidate_mask = tf.logical_and(candidate_ends < num_words, tf.equal(candidate_start_sentence_indices,
                                                                             candidate_end_sentence_indices))  # [num_words, max_span_width]
        flattened_candidate_mask = tf.reshape(candidate_mask, [-1])  # [num_words * max_span_width]
        candidate_starts = tf.boolean_mask(tf.reshape(candidate_starts, [-1]),
                                           flattened_candidate_mask)  # [num_candidates]
        candidate_ends = tf.boolean_mask(tf.reshape(candidate_ends, [-1]), flattened_candidate_mask)  # [num_candidates]
        candidate_sentence_indices = tf.boolean_mask(tf.reshape(candidate_start_sentence_indices, [-1]),
                                                     flattened_candidate_mask)  # [num_candidates]

        candidate_cluster_ids, candidate_is_gold = self.get_candidate_labels(candidate_starts, candidate_ends, gold_starts, gold_ends,
                                                                             cluster_ids)  # [num_candidates]

        candidate_span_emb = self.get_span_emb(flattened_head_emb, context_outputs, candidate_starts,
                                               candidate_ends)  # [num_candidates, emb]
        candidate_mention_scores = self.get_mention_scores(candidate_span_emb)  # [k, 1]
        candidate_mention_scores = tf.squeeze(candidate_mention_scores, 1)  # [k]

        if self.config['mention_loss']:
            candidate_mention_scores_for_pruning = self.get_mention_scores(candidate_span_emb,
                                                                           "mention_scores_for_loss")  # [k, 1]
            candidate_mention_scores_for_pruning = tf.squeeze(candidate_mention_scores_for_pruning, 1)  # [k]
        else:
            candidate_mention_scores_for_pruning = candidate_mention_scores


        #####
        if self.config['use_gold_mentions']:

           k = tf.to_int32(tf.shape(gold_starts)[0])
           top_span_indices = coref_ops.extract_spans(candidate_starts, # need for sorting
                                                      candidate_ends, # need for sorting
                                                      gold_starts,
                                                      gold_ends,
                                                      True) # [1, k]


        else:

           k = tf.to_int32(tf.floor(tf.to_float(tf.shape(context_outputs)[0]) * self.config["top_span_ratio"]))
           top_span_indices = coref_ops.extract_spans(tf.expand_dims(candidate_mention_scores_for_pruning, 0),
                                                      tf.expand_dims(candidate_starts, 0),
                                                      tf.expand_dims(candidate_ends, 0),
                                                      tf.expand_dims(k, 0),
                                                      util.shape(context_outputs, 0),
                                                      True)  # [1, k]

        #####


        top_span_indices.set_shape([1, None])
        top_span_indices = tf.squeeze(top_span_indices, 0)  # [k]

        top_span_starts = tf.gather(candidate_starts, top_span_indices)  # [k]
        top_span_ends = tf.gather(candidate_ends, top_span_indices)  # [k]
        top_span_emb = tf.gather(candidate_span_emb, top_span_indices)  # [k, emb]
        top_span_cluster_ids = tf.gather(candidate_cluster_ids, top_span_indices)  # [k]
        top_span_mention_scores = tf.gather(candidate_mention_scores, top_span_indices)  # [k]
        self.top_span_mention_scores = top_span_mention_scores
        top_span_sentence_indices = tf.gather(candidate_sentence_indices, top_span_indices)  # [k]
        top_span_speaker_ids = tf.gather(speaker_ids, top_span_starts)  # [k]

        cluster_id_to_first_mention_id = tf.unsorted_segment_min(tf.range(k), top_span_cluster_ids, k)
        mention_id_to_first_mention_id = tf.gather(cluster_id_to_first_mention_id, top_span_cluster_ids)
        valid_cluster_ids = tf.to_int32(top_span_cluster_ids > 0)
        mention_id_to_first_mention_id = (mention_id_to_first_mention_id * valid_cluster_ids +
                                          tf.range(k) * (1 - valid_cluster_ids))
        gold_entity_matrix = tf.one_hot(mention_id_to_first_mention_id, k)

        c = tf.minimum(self.config["max_top_antecedents"], k)

        if self.config["coarse_to_fine"]:
            top_antecedents, top_antecedents_mask, top_fast_antecedent_scores, top_antecedent_offsets = self.coarse_to_fine_pruning(
                top_span_emb, top_span_mention_scores, c)
        else:
            top_antecedents, top_antecedents_mask, top_fast_antecedent_scores, top_antecedent_offsets = self.distance_pruning(
                top_span_emb, top_span_mention_scores, c)

        dummy_scores = tf.zeros([k, 1])  # [k, 1]
        top_refined_emb = None
        top_antecedent_scores = tf.concat([dummy_scores, top_fast_antecedent_scores], 1)  # [k, c + 1]
        for i in range(self.config["coref_depth"]):
            with tf.variable_scope("coref_layer_{}".format(1 if self.config["refinement_sharing"] else i),
                                   reuse=i > 0 if self.config["refinement_sharing"] else False):
                top_antecedent_emb = tf.gather(top_span_emb, top_antecedents)  # [k, c, emb]
                top_antecedent_scores = top_fast_antecedent_scores + \
                                        self.get_slow_antecedent_scores(top_span_emb,
                                                                        top_antecedents,
                                                                        top_antecedent_emb,
                                                                        top_antecedent_offsets,
                                                                        top_span_speaker_ids,
                                                                        genre_emb,
                                                                        top_antecedent_scores)  # [k, c]
                top_antecedent_scores = tf.concat([dummy_scores, top_antecedent_scores], 1)  # [k, c + 1]
                top_antecedent_weights = tf.nn.softmax(top_antecedent_scores)  # [k, c + 1]

                mention_indices = tf.tile(tf.expand_dims(tf.range(k, dtype=top_antecedents.dtype), 1), [1, c + 1])
                antecedent_indices = tf.concat(
                    [tf.expand_dims(tf.range(k, dtype=top_antecedents.dtype), 1), top_antecedents], axis=-1)
                antecedent_matrix_scatter_indices = tf.stack([mention_indices, antecedent_indices], axis=-1)
                antecedent_matrix = tf.scatter_nd(antecedent_matrix_scatter_indices, top_antecedent_weights, [k, k])
                entity_matrix = util.compute_p_m_entity(antecedent_matrix, k)  # [k, k]

                if self.config['entity_average']:
                    entity_matrix = entity_matrix / (
                                tf.reduce_sum(entity_matrix, axis=0, keepdims=True) + 1e-6)

                # entity_matrix = tf.Print(entity_matrix, [antecedent_matrix, entity_matrix], message="p_m_entity", summarize=1000)

                if self.config["antecedent_averaging"]:
                    top_antecedent_emb = tf.concat([tf.expand_dims(top_span_emb, 1), top_antecedent_emb],
                                                   1)  # [k, c + 1, emb]
                    top_aa_emb = tf.reduce_sum(tf.expand_dims(top_antecedent_weights, 2) * top_antecedent_emb,
                                                    1)  # [k, emb]
                else:
                    top_aa_emb = top_span_emb

                if self.config["entity_equalization"]:
                    antecedent_mask = tf.to_float(tf.sequence_mask(tf.range(k) + 1, k))  # [k, k]
                    antecedent_mask = tf.expand_dims(antecedent_mask, 2)  # [k, k, 1]
                    entity_matrix_per_timestep = tf.expand_dims(entity_matrix, 0) * antecedent_mask  # [k, k, k]
                    entity_emb_per_timestep = tf.tensordot(entity_matrix_per_timestep, top_aa_emb,
                                                            [[1], [0]])  # [k, k, emb]
                    mention_entity_emb_per_timestep = tf.tensordot(entity_matrix, entity_emb_per_timestep,
                                                                    [[1], [1]])  # [k, k, emb]
                    indices = tf.tile(tf.expand_dims(tf.range(k), 1), [1, 2])
                    top_ee_emb = tf.gather_nd(mention_entity_emb_per_timestep, indices)
                else:
                    top_ee_emb = top_aa_emb

                top_refined_emb = top_ee_emb

                with tf.variable_scope("f"):
                    f = tf.sigmoid(util.projection(tf.concat([top_span_emb, top_refined_emb], 1),
                                                   util.shape(top_span_emb, -1)))  # [k, emb]
                    top_span_emb = f * top_refined_emb + (1 - f) * top_span_emb  # [k, emb]

        self.b3_loss = self.compute_b3_loss(entity_matrix, gold_entity_matrix) * 10.
        top_antecedent_cluster_ids = tf.gather(top_span_cluster_ids, top_antecedents)  # [k, c]
        top_antecedent_cluster_ids += tf.to_int32(tf.log(tf.to_float(top_antecedents_mask)))  # [k, c]
        same_cluster_indicator = tf.equal(top_antecedent_cluster_ids, tf.expand_dims(top_span_cluster_ids, 1))  # [k, c]
        non_dummy_indicator = tf.expand_dims(top_span_cluster_ids > 0, 1)  # [k, 1]
        pairwise_labels = tf.logical_and(same_cluster_indicator, non_dummy_indicator)  # [k, c]
        dummy_labels = tf.logical_not(tf.reduce_any(pairwise_labels, 1, keepdims=True))  # [k, 1]
        top_antecedent_labels = tf.concat([dummy_labels, pairwise_labels], 1)  # [k, c + 1]
        self.antecedent_loss = self.softmax_loss(top_antecedent_scores, top_antecedent_labels)  # [k]
        self.antecedent_loss = tf.reduce_sum(self.antecedent_loss)  # []

        gold_loss = tf.losses.sigmoid_cross_entropy(tf.expand_dims(candidate_is_gold, 0),
                                                    tf.expand_dims(candidate_mention_scores_for_pruning, 0),
                                                    reduction='none')[0]  # [num_candidates]
        positive_gold_losses = tf.cond(tf.reduce_any(tf.equal(candidate_is_gold, 1)),
                                       lambda: tf.boolean_mask(gold_loss, tf.equal(candidate_is_gold, 1)),
                                       lambda: gold_loss)
        negative_gold_losses = tf.cond(tf.reduce_any(tf.equal(candidate_is_gold, 0)),
                                       lambda: tf.boolean_mask(gold_loss, tf.equal(candidate_is_gold, 0)),
                                       lambda: gold_loss)
        n_pos = tf.shape(positive_gold_losses)[0]
        n_neg = tf.minimum(n_pos * 10, tf.shape(negative_gold_losses)[0])
        negative_gold_losses, _ = tf.nn.top_k(negative_gold_losses, n_neg, sorted=False)
        ohem_gold_loss = tf.reduce_mean(tf.concat([positive_gold_losses, negative_gold_losses], axis=0))
        ohem_gold_loss = ohem_gold_loss * 100.
        self.mention_loss = ohem_gold_loss

        losses = []
        if self.config['b3_loss']:
            losses.append(self.b3_loss)
        if self.config['antecedent_loss']:
            losses.append(self.antecedent_loss)
        if self.config['mention_loss']:
            losses.append(self.mention_loss)
        loss = tf.add_n(losses)

        return [candidate_starts, candidate_ends, candidate_mention_scores, top_span_starts, top_span_ends,
                top_antecedents, top_antecedent_scores], loss

    def get_span_emb(self, head_emb, context_outputs, span_starts, span_ends):
        span_emb_list = []

        span_start_emb = tf.gather(context_outputs, span_starts)  # [k, emb]
        span_emb_list.append(span_start_emb)

        span_end_emb = tf.gather(context_outputs, span_ends)  # [k, emb]
        span_emb_list.append(span_end_emb)

        span_width = 1 + span_ends - span_starts  # [k]

        if self.config["use_features"]:
            span_width_index = span_width - 1  # [k]
            span_width_emb = tf.gather(
                tf.get_variable("span_width_embeddings", [self.config["max_span_width"], self.config["feature_size"]]),
                span_width_index)  # [k, emb]
            span_width_emb = tf.nn.dropout(span_width_emb, self.dropout)
            span_emb_list.append(span_width_emb)

        if self.config["model_heads"]:
            span_indices = tf.expand_dims(tf.range(self.config["max_span_width"]), 0) + tf.expand_dims(span_starts,
                                                                                                       1)  # [k, max_span_width]
            span_indices = tf.minimum(util.shape(context_outputs, 0) - 1, span_indices)  # [k, max_span_width]
            span_text_emb = tf.gather(head_emb, span_indices)  # [k, max_span_width, emb]
            with tf.variable_scope("head_scores"):
                self.head_scores = util.projection(context_outputs, 1)  # [num_words, 1]
            span_head_scores = tf.gather(self.head_scores, span_indices)  # [k, max_span_width, 1]
            span_mask = tf.expand_dims(tf.sequence_mask(span_width, self.config["max_span_width"], dtype=tf.float32),
                                       2)  # [k, max_span_width, 1]
            span_head_scores += tf.log(span_mask)  # [k, max_span_width, 1]
            self.span_attention = tf.nn.softmax(span_head_scores, 1)  # [k, max_span_width, 1]
            span_head_emb = tf.reduce_sum(self.span_attention * span_text_emb, 1)  # [k, emb]
            span_emb_list.append(span_head_emb)

        span_emb = tf.concat(span_emb_list, 1)  # [k, emb]

        return span_emb  # [k, emb]

    def get_mention_scores(self, span_emb, name=None):
        with tf.variable_scope(name, "mention_scores"):
            return util.ffnn(span_emb, self.config["ffnn_depth"], self.config["ffnn_size"], 1, self.dropout)  # [k, 1]

    def softmax_loss(self, antecedent_scores, antecedent_labels):
        gold_scores = antecedent_scores + tf.log(tf.to_float(antecedent_labels))  # [k, max_ant + 1]
        marginalized_gold_scores = tf.reduce_logsumexp(gold_scores, [1])  # [k]
        log_norm = tf.reduce_logsumexp(antecedent_scores, [1])  # [k]
        return log_norm - marginalized_gold_scores  # [k]

    def bucket_distance(self, distances):
        """
        Places the given values (designed for distances) into 10 semi-logscale buckets:
        [0, 1, 2, 3, 4, 5-7, 8-15, 16-31, 32-63, 64+].
        """
        logspace_idx = tf.to_int32(tf.floor(tf.log(tf.to_float(distances)) / math.log(2))) + 3
        use_identity = tf.to_int32(distances <= 4)
        combined_idx = use_identity * distances + (1 - use_identity) * logspace_idx
        return tf.clip_by_value(combined_idx, 0, 9)

    def get_slow_antecedent_scores_with_refined(self,
                                                top_span_emb,
                                                top_refined_emb,
                                                top_antecedents,
                                                top_antecedent_emb,
                                                top_antecedent_offsets,
                                                top_span_speaker_ids,
                                                genre_emb):
        k = util.shape(top_span_emb, 0)
        c = util.shape(top_antecedents, 1)

        feature_emb_list = []

        if self.config["use_metadata"]:
            top_antecedent_speaker_ids = tf.gather(top_span_speaker_ids, top_antecedents)  # [k, c]
            same_speaker = tf.equal(tf.expand_dims(top_span_speaker_ids, 1), top_antecedent_speaker_ids)  # [k, c]
            speaker_pair_emb = tf.gather(tf.get_variable("same_speaker_emb", [2, self.config["feature_size"]]),
                                         tf.to_int32(same_speaker))  # [k, c, emb]
            feature_emb_list.append(speaker_pair_emb)

            tiled_genre_emb = tf.tile(tf.expand_dims(tf.expand_dims(genre_emb, 0), 0), [k, c, 1])  # [k, c, emb]
            feature_emb_list.append(tiled_genre_emb)

        if self.config["use_features"]:
            antecedent_distance_buckets = self.bucket_distance(top_antecedent_offsets)  # [k, c]
            antecedent_distance_emb = tf.gather(
                tf.get_variable("antecedent_distance_emb", [10, self.config["feature_size"]]),
                antecedent_distance_buckets)  # [k, c, emb]
            feature_emb_list.append(antecedent_distance_emb)

        feature_emb = tf.concat(feature_emb_list, 2)  # [k, c, emb]
        feature_emb = tf.nn.dropout(feature_emb, self.dropout)  # [k, c, emb]

        # from_tensor = top_span_emb  # [k, emb]
        # to_tensor = tf.concat([top_antecedent_emb, feature_emb], 2)  # [k, c, emb]
        #
        # if top_refined_emb is not None:
        #     from_tensor = tf.concat([top_span_emb, top_refined_emb], axis=1)  # [k, emb]
        #     top_antecedent_refined_emb = tf.gather(top_refined_emb, top_antecedents)  # [k, c, emb]
        #     to_tensor = tf.concat([to_tensor, top_antecedent_refined_emb], 2)  # [k, c, emb]
        #
        # from_tensor = tf.expand_dims(from_tensor, 1)  # [k, 1, emb]
        #
        # slow_antecedent_scores = util.attention_scores_layer(from_tensor,
        #                                                      to_tensor,
        #                                                      size_per_head=self.config["ffnn_depth"])  # [k, 1, 1, c]
        # slow_antecedent_scores = tf.squeeze(slow_antecedent_scores, [1, 2])  # [k, c]

        from_tensor = top_span_emb  # [k, emb]
        to_tensor = top_antecedent_emb  # [k, c, emb]

        if top_refined_emb is not None:
            from_tensor = tf.concat([from_tensor, top_refined_emb], axis=1)  # [k, emb]
            top_antecedent_refined_emb = tf.gather(top_refined_emb, top_antecedents)  # [k, c, emb]
            to_tensor = tf.concat([to_tensor, top_antecedent_refined_emb], 2)  # [k, c, emb]

        from_tensor = tf.expand_dims(from_tensor, 1)  # [k, 1, emb]
        similarity_emb = from_tensor * to_tensor  # [k, c, emb]
        from_tensor = tf.tile(from_tensor, [1, c, 1])  # [k, c, emb]

        pair_emb = tf.concat([from_tensor, to_tensor, similarity_emb, feature_emb], 2)  # [k, c, emb]

        with tf.variable_scope("slow_antecedent_scores"):
            slow_antecedent_scores = util.ffnn(pair_emb, self.config["ffnn_depth"], self.config["ffnn_size"], 1,
                                               self.dropout)  # [k, c, 1]
        slow_antecedent_scores = tf.squeeze(slow_antecedent_scores, 2)  # [k, c]

        return slow_antecedent_scores  # [k, c]

    def get_slow_antecedent_scores(self, top_span_emb, top_antecedents, top_antecedent_emb, top_antecedent_offsets,
                                   top_span_speaker_ids, genre_emb, prev_antecedent_scores=None):
        k = util.shape(top_span_emb, 0)
        c = util.shape(top_antecedents, 1)

        feature_emb_list = []

        if self.config["use_metadata"]:
            top_antecedent_speaker_ids = tf.gather(top_span_speaker_ids, top_antecedents)  # [k, c]
            same_speaker = tf.equal(tf.expand_dims(top_span_speaker_ids, 1), top_antecedent_speaker_ids)  # [k, c]
            speaker_pair_emb = tf.gather(tf.get_variable("same_speaker_emb", [2, self.config["feature_size"]]),
                                         tf.to_int32(same_speaker))  # [k, c, emb]
            feature_emb_list.append(speaker_pair_emb)

            tiled_genre_emb = tf.tile(tf.expand_dims(tf.expand_dims(genre_emb, 0), 0), [k, c, 1])  # [k, c, emb]
            feature_emb_list.append(tiled_genre_emb)

        if self.config["use_features"]:
            antecedent_distance_buckets = self.bucket_distance(top_antecedent_offsets)  # [k, c]
            antecedent_distance_emb = tf.gather(
                tf.get_variable("antecedent_distance_emb", [10, self.config["feature_size"]]),
                antecedent_distance_buckets)  # [k, c, emb]
            feature_emb_list.append(antecedent_distance_emb)

        feature_emb = tf.concat(feature_emb_list, 2)  # [k, c, emb]
        feature_emb = tf.nn.dropout(feature_emb, self.dropout)  # [k, c, emb]

        if self.config["use_cluster_size"]:
            top_antecedent_weights = tf.nn.softmax(prev_antecedent_scores)  # [k, c + 1]
            mention_indices = tf.tile(tf.expand_dims(tf.range(k, dtype=top_antecedents.dtype), 1), [1, c + 1])
            antecedent_indices = tf.concat(
                [tf.expand_dims(tf.range(k, dtype=top_antecedents.dtype), 1), top_antecedents], axis=-1)
            indices = tf.stack([mention_indices, antecedent_indices], axis=-1)
            antecedent_matrix = tf.scatter_nd(indices, top_antecedent_weights, [k, k])
            cluster_matrix = util.compute_p_m_entity(antecedent_matrix, k)  # [k, k]
            antecedent_mask = tf.to_float(tf.sequence_mask(tf.range(k) + 1, k))  # [k, k]
            antecedent_mask = tf.expand_dims(antecedent_mask, 2)  # [k, k, 1]
            cluster_matrix_per_timestep = tf.expand_dims(cluster_matrix, 0) * antecedent_mask  # [k, k, k]
            timestep_cluster_size = tf.reduce_sum(cluster_matrix_per_timestep, 1)
            mention_cluster_size = tf.tensordot(cluster_matrix, timestep_cluster_size, [[1], [1]])
            mention_indices = tf.tile(tf.expand_dims(tf.range(k), 1), [1, c])
            cluster_size_indices = tf.stack([mention_indices, top_antecedents], axis=-1)
            antecedent_cluster_size = tf.gather_nd(mention_cluster_size, cluster_size_indices)
            feature_emb = tf.concat([feature_emb, tf.expand_dims(antecedent_cluster_size, 2)], axis=2)

        target_emb = tf.expand_dims(top_span_emb, 1)  # [k, 1, emb]
        similarity_emb = top_antecedent_emb * target_emb  # [k, c, emb]
        target_emb = tf.tile(target_emb, [1, c, 1])  # [k, c, emb]

        pair_emb = tf.concat([target_emb, top_antecedent_emb, similarity_emb, feature_emb], 2)  # [k, c, emb]

        with tf.variable_scope("slow_antecedent_scores"):
            slow_antecedent_scores = util.ffnn(pair_emb, self.config["ffnn_depth"], self.config["ffnn_size"], 1,
                                               self.dropout)  # [k, c, 1]
        slow_antecedent_scores = tf.squeeze(slow_antecedent_scores, 2)  # [k, c]
        return slow_antecedent_scores  # [k, c]

    def get_fast_antecedent_scores(self, top_span_emb):
        with tf.variable_scope("src_projection"):
            source_top_span_emb = tf.nn.dropout(util.projection(top_span_emb, util.shape(top_span_emb, -1)),
                                                self.dropout)  # [k, emb]
        target_top_span_emb = tf.nn.dropout(top_span_emb, self.dropout)  # [k, emb]
        return tf.matmul(source_top_span_emb, target_top_span_emb, transpose_b=True)  # [k, k]

    def flatten_emb_by_sentence(self, emb, text_len_mask):
        num_sentences = tf.shape(emb)[0]
        max_sentence_length = tf.shape(emb)[1]

        emb_rank = len(emb.get_shape())
        if emb_rank == 2:
            flattened_emb = tf.reshape(emb, [num_sentences * max_sentence_length])
        elif emb_rank == 3:
            flattened_emb = tf.reshape(emb, [num_sentences * max_sentence_length, util.shape(emb, 2)])
        else:
            raise ValueError("Unsupported rank: {}".format(emb_rank))
        return tf.boolean_mask(flattened_emb, tf.reshape(text_len_mask, [num_sentences * max_sentence_length]))

    def lstm_contextualize(self, text_emb, text_len, text_len_mask):
        num_sentences = tf.shape(text_emb)[0]

        current_inputs = text_emb  # [num_sentences, max_sentence_length, emb]

        for layer in range(self.config["contextualization_layers"]):
            with tf.variable_scope("layer_{}".format(layer)):
                with tf.variable_scope("fw_cell"):
                    cell_fw = util.CustomLSTMCell(self.config["contextualization_size"], num_sentences,
                                                  self.lstm_dropout)
                with tf.variable_scope("bw_cell"):
                    cell_bw = util.CustomLSTMCell(self.config["contextualization_size"], num_sentences,
                                                  self.lstm_dropout)
                state_fw = tf.contrib.rnn.LSTMStateTuple(tf.tile(cell_fw.initial_state.c, [num_sentences, 1]),
                                                         tf.tile(cell_fw.initial_state.h, [num_sentences, 1]))
                state_bw = tf.contrib.rnn.LSTMStateTuple(tf.tile(cell_bw.initial_state.c, [num_sentences, 1]),
                                                         tf.tile(cell_bw.initial_state.h, [num_sentences, 1]))

                (fw_outputs, bw_outputs), _ = tf.nn.bidirectional_dynamic_rnn(
                    cell_fw=cell_fw,
                    cell_bw=cell_bw,
                    inputs=current_inputs,
                    sequence_length=text_len,
                    initial_state_fw=state_fw,
                    initial_state_bw=state_bw)

                text_outputs = tf.concat([fw_outputs, bw_outputs], 2)  # [num_sentences, max_sentence_length, emb]
                text_outputs = tf.nn.dropout(text_outputs, self.lstm_dropout)
                if layer > 0:
                    highway_gates = tf.sigmoid(util.projection(text_outputs, util.shape(text_outputs,
                                                                                        2)))  # [num_sentences, max_sentence_length, emb]
                    text_outputs = highway_gates * text_outputs + (1 - highway_gates) * current_inputs
                current_inputs = text_outputs

        return self.flatten_emb_by_sentence(text_outputs, text_len_mask)

    def get_predicted_antecedents(self, antecedents, antecedent_scores):
        predicted_antecedents = []
        for i, index in enumerate(np.argmax(antecedent_scores, axis=1) - 1):
            if index < 0:
                predicted_antecedents.append(-1)
            else:
                predicted_antecedents.append(antecedents[i, index])
        return predicted_antecedents

    def get_predicted_clusters(self, top_span_starts, top_span_ends, predicted_antecedents, include_singletons=False):
        mention_to_predicted = {}
        predicted_clusters = []
        for i, predicted_index in enumerate(predicted_antecedents):
            if predicted_index < 0:
                continue
            assert i > predicted_index
            predicted_antecedent = (int(top_span_starts[predicted_index]), int(top_span_ends[predicted_index]))
            if predicted_antecedent in mention_to_predicted:
                predicted_cluster = mention_to_predicted[predicted_antecedent]
            else:
                predicted_cluster = len(predicted_clusters)
                predicted_clusters.append([predicted_antecedent])
                mention_to_predicted[predicted_antecedent] = predicted_cluster

            mention = (int(top_span_starts[i]), int(top_span_ends[i]))
            predicted_clusters[predicted_cluster].append(mention)
            mention_to_predicted[mention] = predicted_cluster

        #####
        if include_singletons or self.config['include_singletons']:
            for i, predicted_index in enumerate(predicted_antecedents):
              mention = (int(top_span_starts[i]), int(top_span_ends[i]))
              if mention not in mention_to_predicted:
                 predicted_cluster = len(predicted_clusters)
                 mention_to_predicted[mention] = predicted_cluster
                 predicted_clusters.append([mention])
        #####

        predicted_clusters = [tuple(pc) for pc in predicted_clusters]
        mention_to_predicted = {m: predicted_clusters[i] for m, i in mention_to_predicted.items()}

        return predicted_clusters, mention_to_predicted

    def evaluate_coref(self, top_span_starts, top_span_ends, predicted_antecedents, gold_clusters, evaluator):
        gold_clusters = [tuple(tuple(m) for m in gc) for gc in gold_clusters]
        mention_to_gold = {}
        for gc in gold_clusters:
            for mention in gc:
                mention_to_gold[mention] = gc

        predicted_clusters, mention_to_predicted = self.get_predicted_clusters(top_span_starts, top_span_ends,
                                                                               predicted_antecedents)
        evaluator.update(predicted_clusters, gold_clusters, mention_to_predicted, mention_to_gold)
        return predicted_clusters

    def load_eval_data(self):
        if self.eval_data is None:
            def load_line(line):
                example = json.loads(line)
                return self.tensorize_example(example, is_training=False), example

            with open(self.config["eval_path"]) as f:
                #self.eval_data = [load_line(l) for l in f.readlines()]
                self.eval_data = [x for x in (load_line(l) for l in f.readlines()) if x[0] is not None]
            num_words = sum(tensorized_example[2].sum() for tensorized_example, _ in self.eval_data)
            print("Loaded {} eval examples.".format(len(self.eval_data)))

    def evaluate(self, session, official_stdout=False, pprint=False, test=False, outfpath=None):
        self.load_eval_data()

        coref_predictions = {}
        coref_evaluator = metrics.CorefEvaluator()

        if not test:
            session.run(self.switch_to_test_mode_op)

        if outfpath:
          fh = open(outfpath, 'w')

        for example_num, (tensorized_example, example) in enumerate(self.eval_data):
            _, _, _, _, _, _, _, _, _, gold_starts, gold_ends, _ = tensorized_example
            feed_dict = {i: t for i, t in zip(self.input_tensors, tensorized_example)}

            candidate_starts, candidate_ends, candidate_mention_scores, top_span_starts, top_span_ends, top_antecedents, top_antecedent_scores = session.run(
                self.predictions, feed_dict=feed_dict)

            predicted_antecedents = self.get_predicted_antecedents(top_antecedents, top_antecedent_scores)
            coref_predictions[example["doc_key"]] = self.evaluate_coref(top_span_starts, top_span_ends,
                                                                        predicted_antecedents, example["clusters"],
                                                                        coref_evaluator)

            if pprint:
                tokens = util.flatten(example["sentences"])
                print("GOLD CLUSTERS:")
                util.coref_pprint(tokens, example["clusters"])
                print("PREDICTED CLUSTERS:")
                util.coref_pprint(tokens, coref_predictions[example["doc_key"]])
                print('==================================================================')

            if example_num % 10 == 0:
                print("Evaluated {}/{} examples.".format(example_num + 1, len(self.eval_data)))

            ### save the jsonlines
            if outfpath:
               predicted_clusters_sg, _ = self.get_predicted_clusters(top_span_starts, top_span_ends, predicted_antecedents, include_singletons=True)
               #predicted_clusters_nosg, _ = self.get_predicted_clusters(top_span_starts, top_span_ends, predicted_antecedents, include_singletons=False)

               copy = { k: v for k, v in example.items() }
               copy['clusters'] = predicted_clusters_sg
               fh.write(json.dumps(copy)+"\n")
            ###

        if outfpath:
          fh.close()

        if not test:
            session.run(self.switch_to_train_mode_op)

        mention_p, mention_r, mention_f = metrics.get_prf_mentions_for_all_documents([e[1] for e in self.eval_data], coref_predictions)

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


        # if test:
        #     conll_results = conll.evaluate_conll(self.config["conll_eval_path"], coref_predictions, official_stdout)
        #     average_f1 = sum(results["f"] for results in conll_results.values()) / len(conll_results)
        #     summary_dict["Average F1 (conll)"] = average_f1
        #     print("Average F1 (conll): {:.2f}%".format(average_f1))

        return util.make_summary(summary_dict), average_f1, average_mention_f1
