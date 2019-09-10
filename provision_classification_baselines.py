import numpy; numpy.random.seed(42)
import pickle
from typing import List, Dict, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.linear_model import LogisticRegression
from utils import split_corpus, SplitDataSet, evaluate_multilabels


def train_classifiers(x_train: numpy.array, y_train: numpy.array) -> OneVsRestClassifier:
    clf = LogisticRegression(class_weight='balanced', max_iter=10000, solver='lbfgs')
    ovr = OneVsRestClassifier(clf, n_jobs=-1)
    ovr.fit(x_train, y_train)
    return ovr


def stringify_labels(y_vecs: numpy.array, mlb: MultiLabelBinarizer,
                     thresh: float = 0.5, label_threshs: Dict[str, float] = None) -> List[List[str]]:
    """
    Turn prediction probabilities into label strings
    :param y_vecs:
    :param mlb:
    :param thresh:
    :param label_threshs: Classification threshold per label
    :return:
    """
    y_pred: List[List[str]] = []
    if not label_threshs:
        label_threshs = {l: thresh for l in mlb.classes_}
    label_threshs = [label_threshs[l] for l in mlb.classes_]
    for prediction in y_vecs:
        label_indexes = numpy.where(prediction >= label_threshs)[0]
        if label_indexes.size > 0:  # One of the classes has triggered
            labels = set(numpy.take(mlb.classes_, label_indexes))
        else:
            labels = []
        y_pred.append(labels)
    return y_pred


def classify_by_labelname(x_test: List[str], y_train: List[List[str]]) -> List[List[str]]:
    label_set = set(l for labels in y_train for l in labels)
    y_preds = []
    for x in x_test:
        y_pred = []
        for label in label_set:
            if label in x.lower() or (label.endswith('s') and label[:-1] in x.lower()):
                y_pred.append(label)
        y_preds.append(y_pred)
    return y_preds


def tune_clf_thresholds(test_x, test_y, classifier: OneVsRestClassifier, mlb: MultiLabelBinarizer) \
        -> Tuple[numpy.array, Dict[str, float]]:
    y_pred_vecs = classifier.predict_proba(test_x)
    thresh_range = [t / 10.0 for t in range(1, 10)]
    all_results = dict()
    for thresh in thresh_range:
        y_pred = stringify_labels(y_pred_vecs, mlb, thresh=thresh)
        eval_results = evaluate_multilabels(test_y, y_pred, do_print=False)
        all_results[thresh] = eval_results

    label_threshs: Dict[str, float] = dict()
    for label in mlb.classes_:
        best_thresh, best_f1 = 0.1, 0.0
        for curr_thresh in thresh_range:
            curr_f1 = all_results[curr_thresh][label]['f1']
            if curr_f1 > best_f1:
                best_thresh = curr_thresh
                best_f1 = curr_f1
        label_threshs[label] = best_thresh

    y_pred = stringify_labels(y_pred_vecs, mlb, label_threshs=label_threshs)
    return y_pred, label_threshs


if __name__ == '__main__':
    corpus_file = 'sec_corpus_2016-2019_clean_freq100.jsonl'

    print('Loading corpus', corpus_file)
    dataset: SplitDataSet = split_corpus(corpus_file)

    print('Predicting with label names')
    # y_preds_labelnames = classify_by_labelname(dataset.x_test, dataset.y_train)
    # evaluate_multilabels(dataset.y_test, y_preds_labelnames, do_print=True)

    print('Vectorizing')
    tfidfizer = TfidfVectorizer(sublinear_tf=True)
    x_train_vecs = tfidfizer.fit_transform(dataset.x_train)
    x_test_vecs = tfidfizer.transform(dataset.x_test)
    mlb = MultiLabelBinarizer().fit(dataset.y_train + dataset.y_test + dataset.y_dev)
    y_train_vecs = mlb.transform(dataset.y_train)
    y_test_vecs = mlb.transform(dataset.y_test)

    print('Training LogReg')
    classifier = train_classifiers(x_train_vecs, y_train_vecs)
    y_preds_lr, _ = tune_clf_thresholds(x_test_vecs, dataset.y_test, classifier, mlb)
    evaluate_multilabels(dataset.y_test, y_preds_lr, do_print=True)

    with open('/tmp/' + corpus_file.replace('.json', '_clf.pkl'), 'wb') as f:
        pickle.dump(classifier, f)