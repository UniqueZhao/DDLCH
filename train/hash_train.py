from torch.nn.modules import loss
from model.hash_model import DDLCH as DDLCH
import os
from tqdm import tqdm
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import scipy.io as scio
import numpy as np


from .base import TrainBase
from model.optimization import BertAdam
from utils import get_args, calc_neighbor, cosine_similarity, euclidean_similarity
from utils.calc_utils import calc_map_k_matrix as calc_map_k
from dataset.dataloader import dataloader

from train.mas import MASLoss
from model.model import Bottleneck as model




class Trainer(TrainBase):

    def __init__(self,
                rank=0):
        args = get_args()
        super(Trainer, self).__init__(args, rank)
        self.logger.info("dataset len: {}".format(len(self.train_loader.dataset)))
        self.run()

    def _init_model(self):
        self.logger.info("init model.")
        linear = False
        if self.args.hash_layer == "linear":
            linear = True

        self.logger.info("ViT+GPT!")
        HashModel = DDLCH
        self.model = HashModel(outputDim=self.args.output_dim, clipPath=self.args.clip_path,
                            writer=self.writer, logger=self.logger, is_train=self.args.is_train, linear=linear).to(self.rank)
        if self.args.pretrained != "" and os.path.exists(self.args.pretrained):
            self.logger.info("load pretrained model.")
            self.model.load_state_dict(torch.load(self.args.pretrained, map_location=f"cuda:{self.rank}"))
        
        self.model.float()
        self.optimizer = BertAdam([
                    {'params': self.model.clip.parameters(), 'lr': self.args.clip_lr},
                    {'params': self.model.image_hash.parameters(), 'lr': self.args.lr},
                    {'params': self.model.text_hash.parameters(), 'lr': self.args.lr}
                    ], lr=self.args.lr, warmup=self.args.warmup_proportion, schedule='warmup_cosine', 
                    b1=0.9, b2=0.98, e=1e-6, t_total=len(self.train_loader) * self.args.epochs,
                    weight_decay=self.args.weight_decay, max_grad_norm=1.0)
                

    def _init_dataset(self):
        self.logger.info("init dataset.")
        self.logger.info(f"Using {self.args.dataset} dataset.")
        self.args.index_file = os.path.join("./dataset", self.args.dataset, self.args.index_file)
        self.args.caption_file = os.path.join("./dataset", self.args.dataset, self.args.caption_file)
        self.args.label_file = os.path.join("./dataset", self.args.dataset, self.args.label_file)
        train_data, query_data, retrieval_data = dataloader(captionFile=self.args.caption_file, 
                                        indexFile=self.args.index_file, 
                                        labelFile=self.args.label_file, 
                                        maxWords=self.args.max_words,
                                        imageResolution=self.args.resolution,
                                        query_num=self.args.query_num,
                                        train_num=self.args.train_num,
                                        seed=self.args.seed)
        self.train_labels = train_data.get_all_label()
        self.query_labels = query_data.get_all_label()
        self.retrieval_labels = retrieval_data.get_all_label()
        self.args.retrieval_num = len(self.retrieval_labels)
        self.logger.info(f"query shape: {self.query_labels.shape}")
        self.logger.info(f"retrieval shape: {self.retrieval_labels.shape}")
        self.train_loader = DataLoader(
                dataset=train_data,
                batch_size=self.args.batch_size,
                num_workers=self.args.num_workers,
                pin_memory=True,
                shuffle=True
            )
        self.query_loader = DataLoader(
                dataset=query_data,
                batch_size=self.args.batch_size,
                num_workers=self.args.num_workers,
                pin_memory=True,
                shuffle=True
            )
        self.retrieval_loader = DataLoader(
                dataset=retrieval_data,
                batch_size=self.args.batch_size,
                num_workers=self.args.num_workers,
                pin_memory=True,
                shuffle=True
            )

    def train_epoch(self, epoch):
        self.change_state(mode="train")
        self.logger.info(">>>>>> epochs: %d/%d"%(epoch, self.args.epochs))
        all_loss = 0
        times = 0
        for image, text, label, index in self.train_loader:
            self.global_step += 1
            times += 1
            image.float()
            if self.args.dataset not in ["or5k", "colo", "iuxr"]:
                label = torch.ones([image.shape[0]], dtype=torch.int)
                label = label.diag()
            # print(text.dtype)
            # text.float()
            # label.float()
            image = image.to(self.rank, non_blocking=True)
            text = text.to(self.rank, non_blocking=True)
            # print("text shape:", text.shape)
            index = index.numpy()
            # print(text.shape)
            hash_img, hash_text = self.model(image, text)
            if self.args.hash_layer == "select":
                hash_img = torch.cat(hash_img, dim=-1) if isinstance(hash_img, list) else hash_img.view(hash_img.shape[0], -1)
                hash_text = torch.cat(hash_text, dim=-1)if isinstance(hash_text, list) else hash_text.view(hash_text.shape[0], -1)
            loss = self.compute_loss(hash_img, hash_text, label, epoch, times)
            all_loss += loss 


            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

        self.logger.info(f">>>>>> [{epoch}/{self.args.epochs}] loss: {all_loss.data / (len(self.train_loader))}, lr: {'-'.join([str('%.9f'%itm) for itm in sorted(list(set(self.optimizer.get_lr())))])}")

    def train(self):
        self.logger.info("Start train.")

        for epoch in range(self.args.epochs):
            self.train_epoch(epoch)
            self.valid(epoch)
            self.save_model(epoch)
            torch.save(self.model.state_dict(), f'./model_epoch_{epoch + 1}.pt')

        self.logger.info(f">>>>>>> FINISHED >>>>>> Best epoch, I-T: {self.best_epoch_i}, mAP: {self.max_mapi2t}, T-I: {self.best_epoch_t}, mAP: {self.max_mapt2i}")

    def bayesian_loss(self, a: torch.Tensor, b: torch.Tensor, label_sim: torch.Tensor):
        
        s = torch.matmul(a, b.t())
        b_loss = -torch.mean(label_sim * s - torch.log(1 + torch.exp(s)))

        return b_loss
    
    def distribution_loss(self, a: torch.Tensor, b: torch.Tensor, label_sim: torch.Tensor):
        """
        """
        kl_divergence = torch.mean(a * torch.log(a / (b + 0.001)))
        print("mean", torch.mean(a - b))
        print("kl", kl_divergence)
        return kl_divergence


    def similarity_loss(self, a: torch.Tensor, b: torch.Tensor, label_sim: torch.Tensor, threshold=0.05):
        
        # $\vartheta$
        vartheta = self.args.vartheta
        if self.args.sim_threshold != 0:
            threshold = self.args.sim_threshold
        similarity = (1 - cosine_similarity(a, b)) if self.args.similarity_function == "cosine" else euclidean_similarity(a, b)
        
        positive_similarity = similarity * label_sim
        negative_similarity = similarity * (1 - label_sim)
        
        if self.args.similarity_function == "cosine":
            positive_similarity = positive_similarity.clip(threshold) - threshold
            negative_similarity = negative_similarity.clip(max=1.)
            negative_similarity = torch.tensor([1.]).expand_as(negative_similarity).to(self.rank) * (1 - label_sim) - negative_similarity
        elif self.args.similarity_function == "euclidean":

            max_value = float(self.args.output_dim * 2 * vartheta) ** 0.5
            negative_similarity = negative_similarity.clip(max=max_value)
            negative_similarity = torch.tensor([max_value]).expand_as(negative_similarity).to(self.rank) * (1 - label_sim) - negative_similarity

        if self.args.loss_type == "l1":
            positive_loss = positive_similarity.mean()
            negative_loss = negative_similarity.mean()
        elif self.args.loss_type == "l2":
            positive_loss = torch.pow(positive_similarity, 2).mean()
            negative_loss = torch.pow(negative_similarity, 2).mean()
        else:
            raise ValueError("argument of loss_type is not support.")
        
        return similarity, positive_loss, negative_loss

    def make_hash_code(self, code: list) -> torch.Tensor:

        code = torch.stack(code)
        # print(code.shape)
        code = code.permute(1, 0, 2)
        hash_code = torch.argmax(code, dim=-1)
        hash_code[torch.where(hash_code == 0)] = -1
        hash_code = hash_code.float()

        return hash_code

    def get_code(self, data_loader, length: int):

        img_buffer = torch.empty(length, self.args.output_dim, dtype=torch.float).to(self.rank)
        text_buffer = torch.empty(length, self.args.output_dim, dtype=torch.float).to(self.rank)

        for image, text, label, index in tqdm(data_loader):
            image = image.to(self.rank, non_blocking=True)
            text = text.to(self.rank, non_blocking=True)
            index = index.numpy()
            image_hash = self.model.encode_image(image)
            image_hash = self.make_hash_code(image_hash)
            text_hash = self.model.encode_text(text)
            text_hash = self.make_hash_code(text_hash)
            img_buffer[index, :] = image_hash.data
            text_buffer[index, :] = text_hash.data
        
        return img_buffer, text_buffer# img_buffer.to(self.rank), text_buffer.to(self.rank)
        
    def our_loss(self, image, text, label, epoch, times):
        loss = 0

        label_sim = calc_neighbor(label, label)
        if image.is_cuda:
            label_sim = label_sim.to(image.device)
        intra_similarity, intra_positive_loss, intra_negative_loss = self.similarity_loss(image, text, label_sim)
        inter_similarity_i, inter_positive_loss_i, inter_negative_loss_i = self.similarity_loss(image, image, label_sim)
        inter_similarity_t, inter_positive_loss_t, inter_negative_loss_t = self.similarity_loss(text, text, label_sim)
        intra_similarity_loss = (intra_positive_loss + intra_negative_loss) if self.args.similarity_function == "euclidean" else (intra_positive_loss + intra_negative_loss)

        inter_similarity_loss = 0.1 * inter_positive_loss_t + inter_positive_loss_i + (inter_negative_loss_i + 0.1*inter_negative_loss_t) if self.args.similarity_function == "euclidean" else inter_positive_loss_t + inter_positive_loss_i + inter_negative_loss_i + inter_negative_loss_t
        similarity_loss = inter_similarity_loss + intra_similarity_loss
        
        if self.args.hash_layer != "select":
            quantization_loss = (self.hash_loss(image) + self.hash_loss(text)) / 2
            loss = similarity_loss + quantization_loss
            if self.global_step % self.args.display_step == 0:
                self.logger.info(f">>>>>> Display >>>>>> [{epoch}/{self.args.epochs}], [{times}/{len(self.train_loader)}]: all loss: {loss.data}, "\
                    f"SIMILARITY LOSS, Intra, positive: {intra_positive_loss.data}, negitave: {intra_negative_loss.data}, sum: {intra_similarity_loss.data}, " \
                    f"Inter, image positive: {inter_positive_loss_i.data}, image negitave: {inter_negative_loss_i.data}, "\
                    f"text positive: {inter_positive_loss_t.data}, text negitave: {inter_negative_loss_t.data}, sum: {inter_similarity_loss.data}, "\
                    f"QUATIZATION LOSS, {quantization_loss.data}, "\
                    f"lr: {'-'.join([str('%.9f'%itm) for itm in sorted(list(set(self.optimizer.get_lr())))])}")
        else:
            loss = similarity_loss # + self.args.qua_gamma * (image_quantization_loss + text_quantization_loss)
            if self.global_step % self.args.display_step == 0:
                self.logger.info(f">>>>>> Display >>>>>> [{epoch}/{self.args.epochs}], [{times}/{len(self.train_loader)}]: all loss: {loss.data}, "\
                    f"SIMILARITY LOSS, Intra, positive: {intra_positive_loss.data}, negitave: {intra_negative_loss.data}, sum: {intra_similarity_loss.data}, " \
                    f"Inter, image positive: {inter_positive_loss_i.data}, image negitave: {inter_negative_loss_i.data}, "\
                    f"text positive: {inter_positive_loss_t.data}, text negitave: {inter_negative_loss_t.data}, sum: {inter_similarity_loss.data}, "\
                    # f"QUATIZATION LOSS, image: {image_quantization_loss.data}, text: {text_quantization_loss.data}, "\
                    f"lr: {'-'.join([str('%.9f'%itm) for itm in sorted(list(set(self.optimizer.get_lr())))])}")

        return loss
    
    def compute_loss(self, image, text, label, epoch, times):

        query_img, query_txt = self.get_code(self.query_loader, self.args.query_num) if self.args.hash_layer == "select" else super().get_code(self.query_loader, self.args.query_num)
        retrieval_img, retrieval_txt = self.get_code(self.retrieval_loader, self.args.retrieval_num) if self.args.hash_layer == "select" else super().get_code(self.retrieval_loader, self.args.retrieval_num)
        
        retrieval_img = retrieval_img.T 
        retrieval_txt = retrieval_txt.T 
        asignment_loss = self.save_assignment(query_img, query_txt, retrieval_img, retrieval_txt)
        asignment_loss = asignment_loss.to('cuda:0')           
        loss = self.our_loss(image, text, label, epoch, times) + asignment_loss
        loss = self.our_loss(image, text, label, epoch, times)        
        loss = torch.sum(loss)

        return loss

    def test(self, mode_name="i2t"):
        if self.args.pretrained == "":
            raise RuntimeError("test step must load a model! please set the --pretrained argument.")
        self.change_state(mode="valid")
        save_dir = os.path.join(self.args.save_dir, "PR_cruve")
        os.makedirs(save_dir, exist_ok=True)
        query_img, query_txt = self.get_code(self.query_loader, self.args.query_num) if self.args.hash_layer == "select" else super().get_code(self.query_loader, self.args.query_num)
        retrieval_img, retrieval_txt = self.get_code(self.retrieval_loader, self.args.retrieval_num) if self.args.hash_layer == "select" else super().get_code(self.retrieval_loader, self.args.retrieval_num)
        mAPi2t = calc_map_k(query_img, retrieval_txt, self.query_labels, self.retrieval_labels, None, self.rank)
        # print("map map")
        mAPt2i = calc_map_k(query_txt, retrieval_img, self.query_labels, self.retrieval_labels, None, self.rank)
        mAPi2i = calc_map_k(query_img, retrieval_img, self.query_labels, self.retrieval_labels, None, self.rank)
        mAPt2t = calc_map_k(query_txt, retrieval_txt, self.query_labels, self.retrieval_labels, None, self.rank)
        self.max_mapt2i = max(self.max_mapt2i, mAPt2i)
        self.logger.info(f">>>>>> MAP(i->t): {mAPi2t}, MAP(t->i): {mAPt2i}, MAP(t->t): {mAPt2t}, MAP(i->i): {mAPi2i}")

        query_img = query_img.cpu().detach().numpy()
        query_txt = query_txt.cpu().detach().numpy()
        retrieval_img = retrieval_img.cpu().detach().numpy()
        retrieval_txt = retrieval_txt.cpu().detach().numpy()
        query_labels = self.query_labels.numpy()
        retrieval_labels = self.retrieval_labels.numpy()

        result_dict = {
            'q_img': query_img,
            'q_txt': query_txt,
            'r_img': retrieval_img,
            'r_txt': retrieval_txt,
            'q_l': query_labels,
            'r_l': retrieval_labels
        }
        scio.savemat(os.path.join(save_dir, str(self.args.output_dim) + "-ours-" + self.args.dataset + "-" + mode_name + ".mat"), result_dict)
        self.logger.info(">>>>>> save all data!")


    def valid(self, epoch):
        self.logger.info("Valid.")
        self.change_state(mode="valid")
        query_img, query_txt = self.get_code(self.query_loader, self.args.query_num) if self.args.hash_layer == "select" else super().get_code(self.query_loader, self.args.query_num)
        retrieval_img, retrieval_txt = self.get_code(self.retrieval_loader, self.args.retrieval_num) if self.args.hash_layer == "select" else super().get_code(self.retrieval_loader, self.args.retrieval_num)
        mAPi2t = calc_map_k(query_img, retrieval_txt, self.query_labels, self.retrieval_labels, None, self.rank)
        # print("map map")
        mAPt2i = calc_map_k(query_txt, retrieval_img, self.query_labels, self.retrieval_labels, None, self.rank)
        mAPi2i = calc_map_k(query_img, retrieval_img, self.query_labels, self.retrieval_labels, None, self.rank)
        mAPt2t = calc_map_k(query_txt, retrieval_txt, self.query_labels, self.retrieval_labels, None, self.rank)
        if self.max_mapi2t < mAPi2t:
            self.best_epoch_i = epoch
            self.save_mat(query_img, query_txt, retrieval_img, retrieval_txt, mode_name="i2t")
        self.max_mapi2t = max(self.max_mapi2t, mAPi2t)
        if self.max_mapt2i < mAPt2i:
            self.best_epoch_t = epoch
            self.save_mat(query_img, query_txt, retrieval_img, retrieval_txt, mode_name="t2i")
        self.max_mapt2i = max(self.max_mapt2i, mAPt2i)
        self.logger.info(f">>>>>> [{epoch}/{self.args.epochs}], MAP(i->t): {mAPi2t}, MAP(t->i): {mAPt2i}, MAP(t->t): {mAPt2t}, MAP(i->i): {mAPi2i}, \MAX MAP(i->t): {self.max_mapi2t}, MAX MAP(t->i): {self.max_mapt2i}")
        log_message = f">>>>>> [{epoch}/{self.args.epochs}], MAP(i->t): {mAPi2t}, MAP(t->i): {mAPt2i}, MAP(t->t): {mAPt2t}, MAP(i->i): {mAPi2i}, MAX MAP(i->t): {self.max_mapi2t}, MAX MAP(t->i): {self.max_mapt2i}"        
        with open("logs_xiaorong.txt", "a") as log_file:
            log_file.write(log_message + "\n")


    def save_mat(self, query_img, query_txt, retrieval_img, retrieval_txt, mode_name="i2t"):

        save_dir = os.path.join(self.args.save_dir, "PR_cruve")
        os.makedirs(save_dir, exist_ok=True)

        query_img = query_img.cpu().detach().numpy()
        query_txt = query_txt.cpu().detach().numpy()
        retrieval_img = retrieval_img.cpu().detach().numpy()
        retrieval_txt = retrieval_txt.cpu().detach().numpy()
        query_labels = self.query_labels.numpy()
        retrieval_labels = self.retrieval_labels.numpy()      

        result_dict = {
            'q_img': query_img,
            'q_txt': query_txt,
            'r_img': retrieval_img,
            'r_txt': retrieval_txt,
            'q_l': query_labels,
            'r_l': retrieval_labels
        }
        scio.savemat(os.path.join(save_dir, str(self.args.output_dim) + "-ours-" + self.args.dataset + "-" + mode_name + ".mat"), result_dict)
        return


    def save_assignment(self, query_img, query_txt, retrieval_img, retrieval_txt):
        query_img = query_img.cpu().detach().numpy()
        query_txt = query_txt.cpu().detach().numpy()
        retrieval_img = retrieval_img.cpu().detach().numpy()
        retrieval_txt = retrieval_txt.cpu().detach().numpy()
        query_labels = self.query_labels.numpy()
        retrieval_labels = self.retrieval_labels.numpy()       
        

        np.save('query_img_old.npy', query_img)
        np.save('query_txt_old.npy', query_txt)
        np.save('retrieval_img_old.npy', retrieval_img)
        np.save('retrieval_txt_old.npy', retrieval_txt)

        # loaded_q_img_np = np.load('query_img_old.npy')
        # query_img_old = torch.from_numpy(loaded_q_img_np)
        # loaded_q_txt_np = np.load('query_txt_old.npy')
        # query_txt_old = torch.from_numpy(loaded_q_txt_np)
        # loaded_r_img_np = np.load('retrieval_img_old.npy')
        # retrieval_img_old = torch.from_numpy(loaded_r_img_np)
        # loaded_r_txt_np = np.load('retrieval_txt_old.npy')
        # retrieval_txt_old = torch.from_numpy(loaded_r_txt_np)
        
        a = len(self.train_loader.dataset)
        query_img = torch.from_numpy(query_img)
        retrieval_img = torch.from_numpy(retrieval_img)
        dot_product = np.dot(query_img, retrieval_img) 
        norm_a = np.linalg.norm(query_img)  
        norm_b = np.linalg.norm(retrieval_img) 
        cosine_similarity = dot_product / (norm_a * norm_b)  
        cosine_distance = 1 - cosine_similarity
        cosine_distance_hf = cosine_similarity      
        cosine_distance_img = torch.from_numpy(cosine_distance)
        cosine_distance_img = cosine_distance_img[:649, :]

        retrieval_txt = torch.from_numpy(retrieval_txt)
        query_txt = torch.from_numpy(query_txt)
        dot_product = np.dot(query_txt, retrieval_txt)  
        norm_a = np.linalg.norm(query_txt)  
        norm_b = np.linalg.norm(retrieval_txt)  
        cosine_similarity = dot_product / (norm_a * norm_b)  
        cosine_distance = 1 - cosine_similarity
        cosine_distance_txt = torch.from_numpy(cosine_distance)
        cosine_distance_txt = cosine_distance_txt[:649, :]        

        query_txt = query_txt.T 
        dot_product = np.dot(query_img, query_txt)  
        norm_a = np.linalg.norm(query_img)  
        norm_b = np.linalg.norm(query_txt)  
        cosine_similarity = dot_product / (norm_a * norm_b)  
        cosine_distance = 1 - cosine_similarity
        cosine_distance_q = torch.from_numpy(cosine_distance)
        cosine_distance_q = cosine_distance_q[:649, :649]        

        retrieval_img = retrieval_img.T
        dot_product = np.dot(retrieval_img, retrieval_txt)  
        norm_a = np.linalg.norm(retrieval_img)  
        norm_b = np.linalg.norm(retrieval_txt)  
        cosine_similarity = dot_product / (norm_a * norm_b)   
        cosine_distance = 1 - cosine_similarity
        cosine_distance_retrieval = torch.from_numpy(cosine_distance)

        retrieval_labels = retrieval_labels.T
        dot_product = np.dot(query_labels, retrieval_labels)  
        norm_a = np.linalg.norm(query_labels) 
        norm_b = np.linalg.norm(retrieval_labels)  
        cosine_similarity = dot_product / (norm_a * norm_b)  
        cosine_distance = 1 - cosine_similarity
        cosine_distance_labels = torch.from_numpy(cosine_distance)

   
        # N, D = retrieval_img_old.shape
#         M, _ = query_img_old.shape
#         prod = torch.mm(query_img_old, retrieval_img_old)  # 形状为 [D, M]
#         K = torch.diag(torch.ones(4413))  
#         S = (cosine_distance_hf + 1) / 2  
#         S = torch.from_numpy(S)
#         S2 = torch.mm(S, S.T)
#         S2 = S2.T
                
#         query_img_old = query_img_old.T
#         query_img_old = torch.mm(query_img_old, query_img_old.T)  # 形状为 (4413, 4413)
#         retrieval_img_old_transpose = retrieval_img_old.T
#         retrieval_img_old_transpose = torch.mm(retrieval_img_old_transpose, retrieval_img_old_transpose.T)  # 形状为 (4413, 4413)
#         retrieval_txt_old_transpose = retrieval_txt_old.T
#         retrieval_txt_old_transpose = torch.mm(retrieval_txt_old_transpose, retrieval_txt_old_transpose.T)  # 形状为 (4413, 4413)
#         retrieval_img_old_transpose[retrieval_img_old_transpose == 0] += 1e-6
#         img_weight_matrix_part = torch.matmul(retrieval_img_old, torch.pinverse(retrieval_img_old_transpose))
#         retrieval_img_old = retrieval_img_old.T
#         img_weight_matrix_part = torch.matmul(retrieval_img_old, img_weight_matrix_part)
#         S1 = S[:649, :649]
        
#         img_weight_matrix_part = torch.matmul(img_weight_matrix_part, S1)
#         retrieval_txt_old_transpose[retrieval_txt_old_transpose == 0] += 1e-6
#         retrieval_txt_old = retrieval_txt_old.T
#         txt_weight_matrix_part = torch.matmul(torch.pinverse(retrieval_txt_old_transpose),retrieval_txt_old)
        
#         txt_weight_matrix_part = txt_weight_matrix_part.T
#         img_weight_matrix_part = img_weight_matrix_part[:, :128]
#         W = torch.matmul(img_weight_matrix_part, txt_weight_matrix_part)
#         W = torch.mm(W, W.T)
#         S2 = S2[:649, :649]
#         S = S2*W
#         K = K[:649, :649]
#         KS = torch.mm(K, S.T)  
#         prod = prod[:649, :]
#         result = prod - KS 
#         f_loss_1 = torch.norm(result, p='fro') ** 2
#         e = 1e-9
#         f_loss_1 = f_loss_1 * e
       

#         retrieval_img = retrieval_img.T
#         query_img_old = query_img_old.T
#         prod = torch.mm(query_img_old, retrieval_img)  
#         small_values_tensor = torch.randn(649, 649) * 1e-6               
#         small_values_tensor[:128, :649] = prod
#         prod = small_values_tensor[:649, :649].clone()
#         result = prod - KS         
#         f_loss_2 = torch.norm(result, p='fro') ** 2
#         e = 1e-9
#         f_loss_2 = f_loss_2 * e
        
        
      
        cosine_distance = cosine_distance_img + cosine_distance_txt + cosine_distance_q + cosine_distance_retrieval + cosine_distance_labels
        

        # cosine_distance = cosine_distance_img + cosine_distance_txt + cosine_distance_q + cosine_distance_retrieval + cosine_distance_labels + f_loss_1 + f_loss_2
       
        return cosine_distance
        # return
        


