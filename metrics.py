from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
from collections import Counter
from sklearn.utils.linear_assignment_ import linear_assignment

INCLUDE_SINGLETONS = False


def f1(p_num, p_den, r_num, r_den, beta=1):
    p = 0 if p_den == 0 else p_num / float(p_den)
    r = 0 if r_den == 0 else r_num / float(r_den)
    return 0 if p + r == 0 else (1 + beta * beta) * p * r / (beta * beta * p + r)

class CorefEvaluator(object):
    def __init__(self):
        self.evaluators = [Evaluator(m) for m in (muc, b_cubed, ceafe)]

    def update(self, predicted, gold, mention_to_predicted, mention_to_gold):
        for e in self.evaluators:
            e.update(predicted, gold, mention_to_predicted, mention_to_gold)

    def get_f1(self):
        return sum(e.get_f1() for e in self.evaluators) / len(self.evaluators)

    def get_recall(self):
        return sum(e.get_recall() for e in self.evaluators) / len(self.evaluators)

    def get_precision(self):
        return sum(e.get_precision() for e in self.evaluators) / len(self.evaluators)

    def get_prf(self):
        return self.get_precision(), self.get_recall(), self.get_f1()

class Evaluator(object):
    def __init__(self, metric, beta=1):
        self.p_num = 0
        self.p_den = 0
        self.r_num = 0
        self.r_den = 0
        self.metric = metric
        self.beta = beta

    def update(self, predicted, gold, mention_to_predicted, mention_to_gold):
        if self.metric == ceafe:
            pn, pd, rn, rd = self.metric(predicted, gold)
        else:
            pn, pd = self.metric(predicted, mention_to_gold)
            rn, rd = self.metric(gold, mention_to_predicted)
        self.p_num += pn
        self.p_den += pd
        self.r_num += rn
        self.r_den += rd

    def get_f1(self):
        return f1(self.p_num, self.p_den, self.r_num, self.r_den, beta=self.beta)

    def get_recall(self):
        return 0 if self.r_num == 0 else self.r_num / float(self.r_den)

    def get_precision(self):
        return 0 if self.p_num == 0 else self.p_num / float(self.p_den)

    def get_prf(self):
        return self.get_precision(), self.get_recall(), self.get_f1()

    def get_counts(self):
        return self.p_num, self.p_den, self.r_num, self.r_den


def evaluate_documents(documents, metric, beta=1):
    evaluator = Evaluator(metric, beta=beta)
    for document in documents:
        evaluator.update(document)
    return evaluator.get_precision(), evaluator.get_recall(), evaluator.get_f1()


def b_cubed(clusters, mention_to_gold):
    num, dem = 0, 0

    for c in clusters:
        if len(c) == 1: # HERE
            #continue
            if not INCLUDE_SINGLETONS:
               assert False
            else:
               pass

        gold_counts = Counter()
        correct = 0
        for m in c:
            if m in mention_to_gold:
                gold_counts[tuple(mention_to_gold[m])] += 1
        for c2, count in gold_counts.items():
            if not INCLUDE_SINGLETONS and len(c2) == 1:
                assert False
            #if len(c2) != 1: # HERE
            #    correct += count * count
            correct += count * count

        num += correct / float(len(c))
        dem += len(c)

    return num, dem


def muc(clusters, mention_to_gold):
    tp, p = 0, 0
    for c in clusters:
        p += len(c) - 1
        tp += len(c)
        linked = set()
        for m in c:
            if m in mention_to_gold:
                linked.add(mention_to_gold[m])
            else:
                tp -= 1
        tp -= len(linked)
    return tp, p


def phi4(c1, c2):
    return 2 * len([m for m in c1 if m in c2]) / float(len(c1) + len(c2))


def ceafe_matching(clusters, gold_clusters):
    for c in clusters:
        if len(c) == 1 and not INCLUDE_SINGLETONS:
            assert False
    #clusters = [c for c in clusters if len(c) != 1]
    clusters = [c for c in clusters] # HERE
    scores = np.zeros((len(gold_clusters), len(clusters)))
    for i in range(len(gold_clusters)):
        for j in range(len(clusters)):
            scores[i, j] = phi4(gold_clusters[i], clusters[j])
    return linear_assignment(-scores), scores


def ceafe(clusters, gold_clusters):
    matching, scores = ceafe_matching(clusters, gold_clusters)
    similarity = sum(scores[matching[:, 0], matching[:, 1]])
    return similarity, len(clusters), similarity, len(gold_clusters)


def lea(clusters, mention_to_gold):
    num, dem = 0, 0

    for c in clusters:
        if len(c) == 1: # HERE
            #continue
            if not INCLUDE_SINGLETONS:
               assert False
            else:
               pass

        common_links = 0
        all_links = len(c) * (len(c) - 1) / 2.0
        for i, m in enumerate(c):
            if m in mention_to_gold:
                for m2 in c[i + 1:]:
                    if m2 in mention_to_gold and mention_to_gold[m] == mention_to_gold[m2]:
                        common_links += 1

        num += len(c) * common_links / float(all_links)
        dem += len(c)

    return num, dem




def get_prf_mentions(gold_clusters, predicted_clusters):
        gold_mentions = {tuple(m) for cluster in gold_clusters for m in cluster}
        predicted_mentions = {tuple(m) for cluster in predicted_clusters for m in cluster}
        tp = len(gold_mentions.intersection(predicted_mentions))
        fn = len(gold_mentions) - tp
        fp = len(predicted_mentions) - tp
        return tp, fn, fp
        
def get_prf_mentions_for_all_documents(gold_docs, predicted_docs):
        tp, fn, fp = 0, 0, 0
        for doc in gold_docs:
                gold = doc['clusters']
                pred = predicted_docs[doc['doc_key']]
                tp_, fn_, fp_ = get_prf_mentions(gold, pred)
                tp += tp_
                fn += fn_
                fp += fp_
        #print("debug:",tp,fn,fp)
        tp = tp / len(gold_docs)
        fn = fn / len(gold_docs)
        fp = fp / len(gold_docs)
        if (fn + tp == 0) or (tp+fp == 0):
               return 0.0, 0.0, 0.0
        r = tp / (fn + tp)
        p = tp / (tp + fp)
        #print("debug:",tp,fn,fp, r, p)
        if p + r == 0:
                return 0.0, 0.0, 0.0
        return p, r, 2 * (p*r) / (p+r)
