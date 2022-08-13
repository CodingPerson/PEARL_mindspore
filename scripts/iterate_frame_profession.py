
#测试的主要函数
import argparse
import copy
import gc
import itertools
import math
import os
import pickle
import time
from collections import defaultdict, Counter

import numpy
import numpy as np
from scipy.special import softmax
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from sklearn.metrics import f1_score


from preprocessing_utils import load_clean_text, load_tlabels, load_classnames
from tqdm import tqdm

from static_representations import handle_sentence
from utils import (INTERMEDIATE_DATA_FOLDER_PATH, MODELS,weight_sentence,
                   cosine_similarity_embedding, cosine_similarity_embeddings,
                   evaluate_predictions, tensor_to_numpy, DATA_FOLDER_PATH, ndcg_at_k)

#标准化函数
def MinmaxNormalization(mylist):
    if len(mylist) == 1:
        return np.array([1])
    max=np.max(mylist)
    min=np.min(mylist)
    new_list=[]
    for x in mylist:
        new_list.append((x-min)/(max-min))
    return np.array(new_list)

#对所有的关键词进行汇总
def CountWords_Embeddings(document_statics,document_words,static_word_representations):
    words_id_field = []
    words_embeddings_field=[]
    for doc_ws in document_statics:
        words_id_field.extend(doc_ws)
    words_id_field = list(set(words_id_field))
    for id in words_id_field:
        words_embeddings_field.append(static_word_representations[id])
    return words_id_field,words_embeddings_field


#主函数
def main(dataset_name, confidence_threshold ,random_state ,lm_type ,layer ,attention_mechanism):
    inter_data_dir = os.path.join(INTERMEDIATE_DATA_FOLDER_PATH, dataset_name)
    static_repr_path = os.path.join(inter_data_dir, f"static_repr_lm-bbu.pk")
    with open(static_repr_path, "rb") as f:
        vocab = pickle.load(f)
        static_word_representations = vocab["static_word_representations"]
        word_to_index = vocab["word_to_index"]
        vocab_words = vocab["vocab_words"]
    with open(os.path.join(inter_data_dir, f"tokenization_lm-bbu.pk"), "rb") as f:
        tokenization_info = pickle.load(f)["tokenization_info"]
    with open(os.path.join(INTERMEDIATE_DATA_FOLDER_PATH, dataset_name, f"document_repr_lm-bbu.pk"), "rb") as f:
        dictionary = pickle.load(f)
        document_representations = dictionary["document_representations"]
        class_representations = dictionary["class_representations"]
        #类名表征
        static_class_representations = dictionary["static_class_representations"]
        #文档中关键词的id集合
        document_statics = dictionary["document_statics"]
        class_words = dictionary["class_words"]
        #文档中关键词的动态表征集合
        document_context=dictionary["document_context"]
        #文档中的选取的关键词
        document_words = dictionary['document_key_tokens']
        #文档中关键词权重
        document_word_weights = dictionary['document_tokens_weights']
        #文档中关键词表征
        document_word_embeddings=dictionary['document_tokens_embeddings']
        #文档中所有的关键词
        document_all_words = dictionary['document_all_tokens']

    epoch = 60
    #初始化
    cur_class_representations=[[class_representations[i]] for i in range(len(class_representations))]

    finished_class = [i for i in range(len(class_representations))]
    finished_document = [i for i in range(len(tokenization_info))]

    #因为迭代框架选取类关键词是从全局词汇中选取的，所以，我们需要对文档中所有关键词的id和embedding进行汇总
    words_id_field,words_embedding_field=CountWords_Embeddings(document_statics,document_words,static_word_representations)
    exist_words = []
    for i in range(len(class_words)):
        for j in class_words[i]:
            exist_words.append(j)
    start = time.time()
    for itra in range(epoch):
        print("迭代次数："+str(itra))
        if len(finished_class) == 0 and len(finished_document) == 0:
            print('文档迭代结束，框架迭代结束！！！！')
            break
        if len(finished_class) == 0:
            print("类别不再迭代！")


        for i in range(len(class_representations)):
            class_representations[i] = np.array(class_representations[i])
        for i in range(len(static_class_representations)):
            static_class_representations[i] = np.array(static_class_representations[i])

        for i in range(len(class_representations)):
            class_representations[i] = np.array(class_representations[i])
        for i in range(len(static_class_representations)):
            static_class_representations[i] = np.array(static_class_representations[i])





        cluster_similarities=[]
        cluster_nearest_words=[]

        #采用初始化的类名表征进行类别关键词选取与权重计算
        for i in range(len(static_class_representations)):
            cluster_similarities.append(cosine_similarity_embeddings([static_class_representations[i]], np.array(words_embedding_field)))
            cluster_nearest_words.append(np.argsort(-np.array(cosine_similarity_embeddings([static_class_representations[i]], np.array(words_embedding_field))), axis=1))

        exist_words=[]
        for i in range(len(class_words)):
            for j in class_words[i]:
                exist_words.append(j)


        cur_weights=[[] for i in range(len(class_representations))]

        cur_index = [-1 for i in range(len(class_representations))]
        extended_words = ["" for i in range(len(class_representations))]
        for i in range(len(cluster_nearest_words)):
            if i not in finished_class:
                continue
            new_class_words=cluster_nearest_words[i][0]

            new_index = 0
            for j in range(len(new_class_words)):
                #这里是保证 每次选择的单词不会出现重复的情况
                if vocab_words[words_id_field[new_class_words[j]]] not in exist_words:
                    new_index=new_class_words[j]
                    cur_index[i] = new_index

                    extended_words[i]=vocab_words[words_id_field[new_class_words[j]]]
                    class_words[i].append(vocab_words[words_id_field[new_class_words[j]]])
                    exist_words.append(vocab_words[words_id_field[new_class_words[j]]])
                    break
            cur_class_representations[i].append(words_embedding_field[new_index])



        for i in range(len(cur_class_representations)):
            for j in range(len(cur_class_representations[i])):
                cur_weights[i].append(cosine_similarity_embedding(cur_class_representations[i][j],static_class_representations[i]))

        new_class_representations = []
        for i in range(len(cur_class_representations)):
            if i in finished_class:
                new_class_representations.append(
                    np.average(cur_class_representations[i], weights=MinmaxNormalization(cur_weights[i]), axis=0))
            else:
                new_class_representations.append(class_representations[i])

        class_representations = new_class_representations

        if itra <=10 :
            continue
        cluster_similarities = []
        cluster_nearest_words = []
        # 采用初始化的类名表征进行类别关键词选取与权重计算
        for i in range(len(static_class_representations)):
            cluster_similarities.append(cosine_similarity_embeddings([class_representations[i]], np.array(words_embedding_field)))
            cluster_nearest_words.append(np.argsort(-np.array(cosine_similarity_embeddings([class_representations[i]], np.array(words_embedding_field))),axis=1))

        for i in range(len(cluster_nearest_words)):
            if i not in finished_class:
                continue
            length = int(len(class_words[i]))
            new_class_words=cluster_nearest_words[i][0][0:length]
            num = 0
            for j in range(len(new_class_words)):
                #这里是保证 每次选择的单词不会出现重复的情况
                if vocab_words[words_id_field[new_class_words[j]]] not in class_words[i]:
                    num = num+1
                    if num >= length/4:
                        finished_class.remove(i)
                        cur_class_representations[i].pop()
                        class_words[i].pop()
                        print("finish " + str(i))
                        break

        if itra == 40:
            new_document_words=[]
            new_document_representation=[]
            new_token_embeddings=[]
            new_token_weights=[]
            new_cls_ids = []
            for i, _tokenization_info in tqdm(enumerate(tokenization_info), total=len(tokenization_info)):
                if i not in finished_document:

                    new_document_words.append(document_words[i])
                    new_document_representation.append(document_representations[i])
                else:
                    document_representation, tokens,token_embeddings,token_weights,cls_ids= weight_sentence(
                                                              new_class_representations,
                                                              document_context[i],
                                                              document_all_words[i],
                                                              document_statics[i],
                                                              60)
                    new_document_words.append(tokens)
                    new_document_representation.append(document_representation)
                    new_token_embeddings.append(token_embeddings)
                    new_token_weights.append(token_weights)
                    new_cls_ids.append(cls_ids)
                    # if flag == 0:
                    #     finished_document.remove(i)


            document_words = new_document_words
            document_representations = new_document_representation
            document_token_embeddings=new_token_embeddings
            document_token_weights = new_token_weights
            documet_token_cls_ids = new_cls_ids
            print('可进行迭代的文档的个数为'+str(len(finished_document)))
            break
    # 我们需要将document_tokens写入文件
    class_word_similarity_file = open('../data/datasets/profession/class_word_similarity.txt', 'w',encoding='utf-8')
    document_keywords_file = open('../data/datasets/profession/document_keywords.txt', 'w', encoding='utf-8')
    bitem_doc_fre_file = open('../data/datasets/profession/model/bitem_doc_frequency.txt', 'w', encoding='utf-8')
    doc_to_class_similarity_file = open('../data/datasets/profession/model/doc_to_class_similarity.txt', 'w', encoding='utf-8')
    for document in document_words:
        document_keywords_file.write(' '.join(list(document)))
        document_keywords_file.write('\n')
    document_keywords_file.close()
    # #在运行脚本之前，存储中间数据,也就是每个类别与单词静态表征的相似度,我们要注意，这个相似度的计算必须按照indexDocs中所规定的word id来计算
    os.system('python indexDocs.py ../data/datasets/profession/document_keywords.txt ../data/datasets/profession/doc_wids.txt ../data/datasets/profession/voca.txt')
    all_document_words=[]
    # # #顺序读取字典中的单词
    vocab_file = open('../data/datasets/profession/voca.txt','r')
    vocab_lines = vocab_file.readlines()
    for vocab_line in vocab_lines:
        all_document_words.append(str(vocab_line.strip().split('\t')[1]))
    all_document_words_embd=[[] for j in document_words]
    for i in range(len(document_words)):
        for token in document_words[i]:
            all_document_words_embd[i].append(static_word_representations[word_to_index[token]])
    #
    #
    #首先计算出bitem表征
    doc_bitems_embeddings_ids = [[] for i in range(len(tokenization_info))]
    bitem_class_similarity = []
    #doc_bitem_similarity = [[] for i in range(len(document_words))]

    #计算document表征
    document_repr = []
    #documennt表征和类表征的相似度
    doc_to_class_similarity=[[] for i in range(len(tokenization_info))]
    all_doc_bitem_fre = [[] for i in range(len(tokenization_info))]
    # document_representations = []
    t=0
    for document in document_words:
        doc_items = [i for i in range(len(document))]
        all_embeddings = []
        if len(doc_items) == 1:
            all_doc_bitem_fre[t].append(str(1))
            bitem_class_similarity.append(np.ones(72))
            t = t + 1
            continue
        for m in itertools.combinations(doc_items,2):
            doc_bitems_embeddings_ids[t].append(list(m))
            #weights = [0.5 for i in list(m)]
            weights = [document_token_weights[t][i] for i in list(m)]
            embeddings = [document_token_embeddings[t][i] for i in list(m)]
            bitem_embedding = np.average(embeddings,weights=weights,axis=0)
            all_embeddings.append(bitem_embedding)
            all_doc_bitem_fre[t].append(str(1))

            # word_similarity1 = cosine_similarity_embeddings(np.array([all_document_words[t][list(m)[0]]]),class_representations)[0]
            # word_similarity2 = cosine_similarity_embeddings(np.array([all_document_words[t][list(m)[1]]]),class_representations)[0]
            # word_similarity = word_similarity1*word_similarity2
            bitem_similarities = cosine_similarity_embeddings(np.array([bitem_embedding]),class_representations)
            bitem_class_similarity.append((np.array(bitem_similarities[0])))
            doc_to_class_similarity[t].append(np.array(bitem_similarities[0]))
            #doc_bitem_similarity[t].append(np.max(bitem_similarities[0]))
            #bitem_class_similarity.append((np.array(word_similarity)))
        # doc_repr = np.average(all_embeddings,axis=0)
        # document_representations.append(doc_repr)
        # doc_similarities = cosine_similarity_embeddings(np.array([doc_repr]), class_representations)
        # doc_similarities = softmax(doc_similarities)
        # doc_to_class_similarity.append(list((doc_similarities[0])))
    #
        t = t+1
    # # t=0
    # # for document in document_words:
    # #     doc_items = [i for i in range(len(document))]
    # #     for m in itertools.combinations(doc_items,2):
    # #         doc_bitems_embeddings_ids[t].append(list(m))
    # #         embeddings = [static_word_representations[word_to_index[document_words[t][i]]] for i in list(m)]
    # #         doc_weights = np.max(cosine_similarity_embeddings(np.array(embeddings),class_representations),axis=1)
    # #         bitem_embedding = np.average(np.array(embeddings),weights=doc_weights,axis=0)
    # #         bitem_similarities = cosine_similarity_embeddings(np.array([bitem_embedding]),class_representations)
    # #         bitem_class_similarity.append(np.array(bitem_similarities[0]))
    # #     t = t+1
    bitem_class_similarity = np.array(bitem_class_similarity)
    for t in range(bitem_class_similarity.shape[1]):
        for similarity in bitem_class_similarity[:, t]:
            class_word_similarity_file.write(str(similarity) + ' ')
        class_word_similarity_file.write('\n')
    class_word_similarity_file.close()
    #
    # # for i in range(len(doc_to_class_similarity)):
    # #     for similarity in doc_to_class_similarity[i]:
    # #         doc_to_class_similarity_file.write(str(similarity)+' ')
    # #     doc_to_class_similarity_file.write('\n')
    # # doc_to_class_similarity_file.close()
    #
    # # class_to_word_similarity = cosine_similarity_embeddings(class_representations,np.array(all_document_word_embeddings))
    # # word_to_class_similarity = cosine_similarity_embeddings(np.array(all_document_word_embeddings),class_representations)
    # # for t in range(len(word_to_class_similarity)):
    # #     word_to_class_similarity[t] = MinmaxNormalization(word_to_class_similarity[t])
    # # for t in range(word_to_class_similarity.shape[1]):
    # #     for similarity in word_to_class_similarity[:,t]:
    # #         if similarity < 1e-6:
    # #             similarity = 1e-6
    # #         class_word_similarity_file.write(str(similarity) + ' ')
    # #     class_word_similarity_file.write('\n')
    # # class_word_similarity_file.close()
    #
    # #执行python 程序，生成bitem，并计算bitem出现在某个文档中的频率，作为p(b|d)
    all_doc_bitems = [[] for i in range(len(tokenization_info))]
    #对每个doument中的bitem进行生成
    t=0
    for document in document_words:
        for m in itertools.combinations(list(document),2):
            all_doc_bitems[t].append(list(m))
        t = t+1
    # #对所有document中的bitem进行频率的计算
    bitems_doc_dict = dict()
    for i in range(len(all_doc_bitems)):
        for bitem  in all_doc_bitems[i]:
            if "".join(bitem) in bitems_doc_dict.keys():
                bitems_doc_dict["".join(bitem)].append(i)
            if ("".join(bitem[::-1]) in bitems_doc_dict.keys()) and len(set(bitem)) != 1:
                bitems_doc_dict["".join(bitem[::-1])].append(i)
            if "".join(bitem) not in bitems_doc_dict.keys():
                bitems_doc_dict["".join(bitem)] = []
                bitems_doc_dict["".join(bitem)].append(i)
            if ("".join(bitem[::-1]) not in bitems_doc_dict.keys()) and len(set(bitem)) != 1:
                bitems_doc_dict["".join(bitem[::-1])] = []
                bitems_doc_dict["".join(bitem[::-1])].append(i)

    # #对每个document中的bitem进行频率的计算
    all_doc_bitem_fre = [[] for i in range(len(tokenization_info))]
    for i in range(len(all_doc_bitems)):
        document_bitems = all_doc_bitems[i]
        for bitem in document_bitems:
            #这个地方如果，这么算，则对于doucment中相同的bitem，则会求和多次
            bitem_doc_fre = len([bitem for x in document_bitems if set(x) == set(bitem)])
            bitem_all_fre = len(bitems_doc_dict[''.join(bitem)])
            bitem_fre = float(bitem_doc_fre / bitem_all_fre)
            all_doc_bitem_fre[i].append(bitem_fre)
            #all_doc_bitem_fre[i].append(1)

    for t in range(len(all_doc_bitem_fre)):
        for bitem_fre in all_doc_bitem_fre[t]:
            bitem_doc_fre_file.write(str(bitem_fre)+' ')
        bitem_doc_fre_file.write('\n')
    bitem_doc_fre_file.close()
    # for t in range(len(doc_bitem_similarity)):
    #     for bitem_fre in doc_bitem_similarity[t]:
    #         bitem_doc_fre_file.write(str(bitem_fre) + ' ')
    #     bitem_doc_fre_file.write('\n')
    # bitem_doc_fre_file.close()
    # 每个文档中单词与类的对应比例
    # class_partition = [0 for t in range(72)]
    # for m in range(len(documet_token_cls_ids)):
    #     #     word_id = [0 for t in range(72)]
    #     for id in documet_token_cls_ids[m]:
    #         class_partition[id] = class_partition[id] + 1
    # #     doc_word_to_class.append(np.array(word_id))
    # class_sum = sum(class_partition)
    # class_partition = [str(float(i / class_sum)) for i in class_partition]
    #print(sum(class_partition))
    # class_partition_file = open('../data/datasets/profession/class_partition.txt', 'w', encoding='utf-8')
    # class_partition_file.write(' '.join(class_partition))
    # class_partition_file.close()
    doc_word_to_class = []
    for m in range(len(documet_token_cls_ids)):
        word_id = [0 for t in range(72)]
        for id in documet_token_cls_ids[m]:
            word_id[id] = word_id[id] + 1
        doc_word_to_class.append(np.array(word_id))
    #运行脚本
    for e in range(20):
        print(os.system('../src/btm est 72 '+str(len(vocab_lines))+' '+'0.69 0.01 50 100 ../data/datasets/profession/doc_wids.txt ../data/datasets/profession/model/ ../data/datasets/profession/class_word_similarity.txt '+str(bitem_class_similarity.shape[0])))
        print(os.system('../src/btm inf sum_b 72 ../data/datasets/profession/doc_wids.txt ../data/datasets/profession/model/ ../data/datasets/profession/model/bitem_doc_frequency.txt' ))
        cosine_similarities = np.loadtxt('../data/datasets/profession/model/k72.pz_d')

        # cosine_similarities = []
        # for doc_bitem in doc_to_class_similarity:
        #     cosine_similarities.append(sum(doc_bitem))
        repr_probility = cosine_similarities
        repr_prediction = np.argmax(repr_probility,axis=1)
        class_proportion = np.argmax(np.array(doc_word_to_class), axis=1)
        data_dir = os.path.join(DATA_FOLDER_PATH, dataset_name)
        gold_labels = load_tlabels(data_dir)
        classes = load_classnames(data_dir)
        print("class_num " + str(len(classes)))
        # for i in range(len(gold_labels)):
        #     all_classes = [m for m in documet_token_cls_ids[i]]
        #     counter = Counter(all_classes)
        #     values = dict(counter).keys()
        #     if repr_prediction[i] not in values:
        #         repr_probility[i] = doc_word_to_class[i]

        score = 0
        big_count = 0
        big_MRR = 0
        gold_set = set([])
        prof_dict = defaultdict(lambda: [0.0, 0])
        for i in range(len(gold_labels)):
            index_list = list(np.argsort(-repr_probility[i]))
            curr_golds = [int(i) for i in gold_labels[i].split(" ")]
            ranks = np.zeros(len(class_representations))
            for gold in curr_golds:
                gold_set.add(gold)
                gold_index = index_list.index(gold)
                ranks[gold_index] = 1
            score = score + ndcg_at_k(ranks, 1000)
        print("ndcg")
        print(score / len(gold_labels))
        for i in range(len(gold_labels)):
            index_list = list(np.argsort(-repr_probility[i]))
            curr_golds = [int(i) for i in gold_labels[i].split(" ")]
            for gold in curr_golds:
                gold_index = index_list.index(gold)
                imrr = 1.0 / (gold_index + 1)
                prof_dict[gold][0] += imrr
                prof_dict[gold][1] += 1
        for prof, stats in prof_dict.items():
            big_count += 1
            big_MRR += float(stats[0] / stats[1])
        print("mrr")
        print(big_MRR / big_count)
        true_num = 0

        for i in range(len(gold_labels)):
            curr_golds = [int(i) for i in gold_labels[i].split(" ")]
            #all_classes = [m for m in documet_token_cls_ids[i]]
            # counter = Counter(all_classes)
            # values = dict(counter).keys()
            # if repr_prediction[i] not in values:
            #     repr_prediction[i] = class_proportion[i]
            if repr_prediction[i] in curr_golds:
                true_num = true_num + 1
        print("acc")
        print(float(true_num / len(gold_labels)))
        pwz_list = np.loadtxt('../data/datasets/profession/model/k72.pw_z', dtype=np.float)
        pwz = []
        for t in range(pwz_list.shape[1]):
            pwz.append(pwz_list[:,t])
        bitem_class_similarity = []
        bitem_similarity_dict={}
        for document in document_words:
            doc_items = [i for i in range(len(document))]
            for m in itertools.combinations(doc_items, 2):
                bitem_surface = document[list(m)[0]]+document[list(m)[1]]
                bitem_surface_reverse = document[list(m)[1]]+document[list(m)[0]]
                if (bitem_surface not in bitem_similarity_dict) and (bitem_surface_reverse not in bitem_similarity_dict):
                    word_s1 = pwz[all_document_words.index(document[list(m)[0]])]
                    word_s2 = pwz[all_document_words.index(document[list(m)[1]])]
                    word_similarity = word_s1*word_s2
                    bitem_similarity_dict[bitem_surface] = word_similarity
                    bitem_similarity_dict[bitem_surface_reverse] = word_similarity
                else:
                    if bitem_surface in bitem_similarity_dict:
                        word_similarity = bitem_similarity_dict[bitem_surface]
                    else:
                        word_similarity = bitem_similarity_dict[bitem_surface_reverse]
                bitem_class_similarity.append(word_similarity)
        class_word_similarity_file = open('../data/datasets/profession/class_word_similarity.txt', 'w', encoding='utf-8')
        bitem_class_similarity = np.array(bitem_class_similarity)
        for t in range(bitem_class_similarity.shape[1]):
            for similarity in bitem_class_similarity[:, t]:
                class_word_similarity_file.write(str(similarity) + ' ')
            class_word_similarity_file.write('\n')
        class_word_similarity_file.close()



    print('时间总和：')
    print(time.time() - start)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_name", default="profession")
    parser.add_argument("--confidence_threshold", default=1)
    parser.add_argument("--random_state", type=int, default=42)
    parser.add_argument("--lm_type", type=str, default='bbu')
    parser.add_argument("--layer", type=int, default=12)
    ##chenhu
    parser.add_argument("--attention_mechanism", type=str, default="norm_1_2")
    args = parser.parse_args()
    print(vars(args))
    main(args.dataset_name, args.confidence_threshold, args.random_state, args.lm_type, args.layer,
         args.attention_mechanism)