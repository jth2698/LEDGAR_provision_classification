"""
Sentence classification with self-attention in keras
"""

import json
import numpy; numpy.random.seed(42)
import re
from collections import Counter
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics import f1_score
from keras.layers import Input, Embedding, Dense
from keras.models import Model, load_model
from keras.preprocessing.sequence import pad_sequences
from keras.callbacks import EarlyStopping
from attn_layer import AttentionLayer
from utils import embed, SplitDataSet, split_corpus, stringify_labels, \
    evaluate_multilabels, tune_clf_thresholds, calc_class_weights


def build_model(max_sent_length, vocab2int, embeddings, num_labels):
    embedding_dim = embeddings[0].shape[0]

    input_layer = Input(shape=(max_sent_length,))

    embedding_layer = Embedding(len(vocab2int),
                                embedding_dim,
                                weights=[embeddings],
                                input_length=max_sent_length,
                                trainable=False,
                                mask_zero=True)

    embedded = embedding_layer(input_layer)

    l_att = AttentionLayer()(embedded)

    dense_1 = Dense(embedding_dim * 2,
                    activation='relu')(l_att)

    classifier = Dense(num_labels,
                       activation='sigmoid')(dense_1)

    model = Model(inputs=input_layer,
                  outputs=classifier)

    model.compile(loss='binary_crossentropy',
                  optimizer='adam',
                  metrics=['accuracy'])

    return model


def tune_threshs(probas, truth):
    # TODO only tune if we have 5+ samples, else leave it at 0.5?
    res = numpy.zeros(probas.shape[1])

    for i in range(probas.shape[1]):
        thresh = max(
            numpy.linspace(
                numpy.min(probas[:, i]),
                numpy.max(probas[:, i]),
                num=100,
            ),
            key=lambda t: f1_score(y_true=truth[:, i], y_pred=(probas[:, i] > t))
        )
        res[i] = thresh

    res[res == 0] = 0.5

    return res


def count_oovs(x):
    oovs = Counter()
    for x_ in x:
        oov = [w for w in re.findall('\w+', x_) if w.lower() not in vocab]
        for w in oov:
            oovs[w] += 1
    return oovs


if __name__ == '__main__':

    do_train = False
    do_test = True
    do_test_nda = True
    classification_thresh = 0.5

    # corpus_file = 'data/sec_corpus_2016-2019_clean_freq100_subsampled.jsonl'
    # model_name = 'MLP_attn_freq100_subsampled.h5'

    # corpus_file = 'data/sec_corpus_2016-2019_clean_proto.jsonl'
    # model_name = 'MLP_attn_proto.h5'

    # corpus_file = 'data/sec_corpus_2016-2019_clean_projected_real_roots_subsampled.jsonl'
    # model_name = 'MLP_attn_leaves_subsampled.h5'

    corpus_file = 'data/sec_corpus_2016-2019_clean_NDA_PTs2.jsonl'
    model_name = 'MLP_attn_nda.h5'

    embedding_file = 'data/wiki.multi.en.vec_data.npy'
    vocab_file = 'data/wiki.multi.en.vec_vocab.json'
    # embedding_file = 'data/Law2Vec.200d_data.npy'
    # vocab_file = 'data/Law2Vec.200d_vocab.json'
    # embedding_file = 'data/sec_fasttext_vecs_data.npy'
    # vocab_file = 'data/sec_fasttext_vecs_vocab.json'

    embeddings = numpy.load(embedding_file)
    vocab = json.load(open(vocab_file))
    int2vocab = {i: w for w, i in vocab.items()}
    embedding_dim = embeddings[0].shape[0]

    print('Loading corpus', corpus_file)
    dataset: SplitDataSet = split_corpus(corpus_file)
    print(len(dataset.y_train), 'training samples')
    print(len(dataset.y_test), 'test samples')
    print(len(dataset.y_dev), 'dev samples')

    # oov_counts = count_oovs(dataset.x_train)
    # breakpoint()

    mlb = MultiLabelBinarizer().fit(dataset.y_train)
    num_classes = mlb.classes_.shape[0]
    train_y = mlb.transform(dataset.y_train)
    test_y = mlb.transform(dataset.y_test)
    dev_y = mlb.transform(dataset.y_dev)

    train_x_int = [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                   for x_ in dataset.x_train]
    test_x_int = [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                  for x_ in dataset.x_test]
    dev_x_int = [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                 for x_ in dataset.x_dev]

    max_sent_length = max([len(x_) for x_ in train_x_int])
    train_x = pad_sequences(train_x_int, max_sent_length)
    test_x = pad_sequences(test_x_int, max_sent_length)
    dev_x = pad_sequences(dev_x_int, max_sent_length)

    if do_train:
        model = build_model(max_sent_length, vocab, embeddings, num_classes)
        print(model.summary())

        class_weights = calc_class_weights(train_y, mlb.classes_)
        class_weights = {i: w for i, w in enumerate(class_weights)}

        early_stopping = EarlyStopping(monitor='val_loss',
                                       patience=3,
                                       restore_best_weights=True)

        try:
            model.fit(train_x, train_y,
                      batch_size=32,
                      epochs=50,
                      verbose=1,
                      validation_data=(dev_x, dev_y),
                      class_weight=class_weights,
                      callbacks=[early_stopping])
        except KeyboardInterrupt:
            pass

        model.save('saved_models/%s' % model_name, overwrite=True)

    else:
        model = load_model('saved_models/%s' % model_name,
                           custom_objects={'AttentionLayer': AttentionLayer})

    # plot_model(model, to_file='/tmp/%s.png' % model_name)

    if do_test:
        print('predicting')
        y_pred_bin_dev = model.predict(dev_x, verbose=1)
        label_threshs = tune_clf_thresholds(y_pred_bin_dev, dataset.y_dev, mlb)
        y_pred_bin = model.predict(test_x, verbose=1)
        y_pred = stringify_labels(y_pred_bin, mlb, label_threshs=label_threshs)
        evaluate_multilabels(dataset.y_test, y_pred, do_print=True)

    if do_test_nda:
        nda_file = 'data/nda_proprietary_data2_sampled.jsonl'
        print('Loading corpus from', nda_file)

        nda_x, nda_y = [], []
        for line in open(nda_file):
            data = json.loads(line)
            nda_x.append(data['provision'])
            nda_y.append(list(data['label']))

        nda_x_int =  [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                       for x_ in nda_x]
        nda_x_vecs = pad_sequences(nda_x_int, max_sent_length)

        y_pred_bin= model.predict(nda_x_vecs, verbose=1)
        y_pred = stringify_labels(y_pred_bin, mlb, label_threshs=label_threshs)
        evaluate_multilabels(nda_y, y_pred, do_print=True)

        """
        dataset: SplitDataSet = split_corpus(nda_file)

        train_y = mlb.transform(dataset.y_train)
        test_y = mlb.transform(dataset.y_test)
        dev_y = mlb.transform(dataset.y_dev)

        train_x_int = [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                       for x_ in dataset.x_train]
        test_x_int = [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                      for x_ in dataset.x_test]
        dev_x_int = [[vocab[w] for w in re.findall('\w+', x_.lower()) if w in vocab]
                     for x_ in dataset.x_dev]

        train_x = pad_sequences(train_x_int, max_sent_length)
        test_x = pad_sequences(test_x_int, max_sent_length)
        dev_x = pad_sequences(dev_x_int, max_sent_length)

        # Use full data, except dev
        all_test = False
        if all_test:
            test_x = numpy.append(test_x, train_x, axis=0)
            dataset.y_test = numpy.append(dataset.y_test, dataset.y_train, axis=0)

        print('predicting NDA')
        y_pred_bin_dev = model.predict(dev_x, verbose=1)
        label_threshs = tune_clf_thresholds(y_pred_bin_dev, dataset.y_dev, mlb)
        y_pred_bin = model.predict(test_x, verbose=1)
        y_pred = stringify_labels(y_pred_bin, mlb, label_threshs=label_threshs)
        evaluate_multilabels(dataset.y_test, y_pred, do_print=True)
        """