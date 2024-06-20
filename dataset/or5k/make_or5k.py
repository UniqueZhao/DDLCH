import os
import scipy.io as scio
import numpy as np

import pickle

root_dir = "/root/autodl-tmp/DDLCH/dataset/or5k/ork"

# file_path = os.path.join(root_dir, "/mirflickr25k_annotations_v080")
# file_path = r"D:\CWNU\Papers\CMH+transformer\DCHMT-main\dataset\flickr25k\mirflickr25k_annotations_v080"
file_path = "/root/autodl-tmp/DDLCH/dataset/or5k/ork_annotations"
file_list = os.listdir(file_path)

file_list = [item for item in file_list if "_r1" not in item and "README" not in item]


print("class num:", len(file_list))

class_index = {}
for i, item in enumerate(file_list):          
    class_index.update({item: i})

label_dict = {}
for path_id in file_list:
    path = os.path.join(file_path, path_id)
    with open(path, "r") as f:
        for item in f:
            # print("item:", item)
            item = item.strip()
            if item not in label_dict:
                label = np.zeros(len(file_list))
                label[class_index[path_id]] = 1
                label_dict.update({item: label})
            else:
                # print()
                label_dict[item][class_index[path_id]] = 1

# print(label_dict)
print("create label:", len(label_dict))
keys = list(label_dict.keys())
keys.sort()

labels = []
for key in keys:
    labels.append(label_dict[key])
# print(labels)

# # 假设 label 是你想要保存的变量
# label = {'a': [1, 2, 3], 'b': (4, 5, 6)}  # 这里应该是你的变量，可以是任何 Python 对象

output_filename = "labels.pkl"  # 要写入的文件名，推荐使用 .pkl 扩展名

# 将变量保存到文件中
with open(output_filename, "wb") as output_file:
    pickle.dump(labels, output_file)
print(f"已将变量保存到文件：{output_filename}")


print("labels created:", len(labels))
labels = {"category": labels}


PATH = os.path.join(root_dir, "mir5k")
index = [os.path.join(PATH, "im" + item + ".jpg") for item in keys]
# print(index)
output_filename = "index.pkl"  # 要写入的文件名，推荐使用 .pkl 扩展名

# 将变量保存到文件中
with open(output_filename, "wb") as output_file:
    pickle.dump(index, output_file)
print(f"已将变量保存到文件：{output_filename}")
print("index created:", len(index))
index= {"index": index}


# captions_path = r"D:\CWNU\Papers\CMH+transformer\DCHMT-main\dataset\flickr25k\mirflickr25k\mirflickr\meta\tags"
captions_path = "/root/autodl-tmp/DDLCH/dataset/or5k/ork/mir5k/meta/tags"
captions_list = os.listdir(captions_path)
captions_dict = {}
for item in captions_list:
    id_ = item.split(".")[0].replace("tags", "")
    caption = ""
    with open(os.path.join(captions_path, item), "r", encoding='utf-8') as f:
        for word in f.readlines():
            caption += word.strip() + " "
    caption = caption.strip()
    captions_dict.update({id_: caption})

captions = []

for item in keys:
#     key = '7430'
# try:
#     value = captions_dict[key]
#     print(f"The value for key {key} is: {value}")
# except KeyError:
#     print(f"Key {key} not found in captions_dict.")
#     all_keys = list(captions_dict.keys())
#     print(all_keys)


    captions.append([captions_dict[item]])
# print(captions)
output_filename = "captions.pkl"  # 要写入的文件名，推荐使用 .pkl 扩展名
# 将变量保存到文件中
with open(output_filename, "wb") as output_file:
    pickle.dump(captions, output_file)
print(f"已将变量保存到文件：{output_filename}")
print("captions created:", len(captions))
captions = {"caption": captions}

scio.savemat("/root/autodl-tmp/DDLCH/dataset/or5k/index.mat", index)
scio.savemat("/root/autodl-tmp/DDLCH/dataset/or5k/caption.mat", captions)
scio.savemat("/root/autodl-tmp/DDLCH/dataset/or5k/label.mat", labels)




