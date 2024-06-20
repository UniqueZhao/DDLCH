import torch
import torch.nn as nn
#from models import Encoder as Encoder
from torch.utils.data.dataloader import DataLoader

from dataset.dataloader import dataloader
from torchvision.models import resnet152, resnet101
# from model.model import CLIP as model
import torch.optim as optim


import torch.nn.functional as F
# import lr_scheduler
# from optimizer.radam import RAdam, AdamW


# from pathlib import Path
import os
import random
# model = model()

# model = load_clip('./ViT-B-32.pt')

class MASLoss(nn.Module):
    def __init__(self, model, scale=1e-12):
        super(MASLoss, self).__init__()
        # self.model = model
        self.scale = scale
        self.model = torch.load('./ViT-B-32.pt')
        # self.pre_params = pre_params
        
    def forward(self):
        mas_loss = 1.00
        prev_params = self.model.state_dict()
        # print(prev_params)
        # 可以将 prev_params 保存到文件中，以便稍后使用
        torch.save(prev_params, './prev_params.pt')
        # 加载先前保存的参数
        prev_params = torch.load('./prev_params.pt')
        for name, param in self.model.named_parameters():
            if param.requires_grad==False:
                prev_param = prev_params[name]
                a =random.random()
                b =random.random()                
                mas_loss += torch.sum((param*a - prev_param*b) ** 2)
        mas_loss *= self.scale
        # print("MAS_LOSS:", mas_loss)
        return mas_loss
    
    

    
    
    # def forward(self):
    #     mas_loss1 = 1.0
    #     mas_loss2 = 1.0
    #     mas_loss = 1.0 
    #     print(222222222222222222222222222222222222222222)
    #     #这里参数没有传进去
    #     # for key, value in self.prev_params.items():
    #     #     print(222222222222222222222222222222222222222222)
    #     #     print(f"Key: {key}, Value: {value}")
    #     # for name in self.model.parameters(self):
    #     #         print('NAME:', name)
    #     #         # print('param_type:', param_type)
    #     #         # 执行 MASLoss 中的操作
    #     #     else:
    #     #         print("Name{name} does not exist in self.prev_params")
    #             # 处理键不存在的情况
    #     #key和value的维度不一样 value的维度是不断变化的 key的维度是一直不变的是[144,1024]
    #     for value, key in self.model.parameters(self):  
    #         # key = key.data
    #         # print('KEY:', key)
    #         # # key = key.repeat(1, 2)
    #         # key_shape = key.shape            
    #         # print(key_shape)                     
    #         if name.requires_grad:
    #             # pre_param = self.model.pre
    #             value_shape = value.shape
    #             print(333333)
    #             print(value_shape)
    #             mas_loss1 += torch.sum(value** 2)
    #             mas_loss2 += torch.sum(key**2)
    #             mas_loss += mas_loss1 - mas_loss2 
    #             mas_loss += torch.sum((value - key) ** 2)                    
    #             print(mas_loss)
    #         mas_loss *= self.scale
    #     print('这是loss2')
    #     print(mas_loss)
    #     return mas_loss
