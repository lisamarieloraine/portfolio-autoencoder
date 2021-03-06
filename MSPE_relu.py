# -*- coding: utf-8 -*-
"""
Created on Mon Mar 18 09:46:47 2019

@author: tobiashoogteijling
"""

import numpy as np
import read_data as data
import tensorflow as tf
import random as rn
from keras import backend as K
import pandas as pd
from keras.layers.advanced_activations import LeakyReLU, ReLU, ELU
from keras.layers import Input, Dense, GaussianNoise
from keras.models import Model, Sequential
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.utils import HDF5Matrix
import scipy

session_conf = tf.ConfigProto(intra_op_parallelism_threads=1,
                              inter_op_parallelism_threads=1)

def chi2test(u):
  num_pos=0
  T=np.size(u,0)
  N=np.size(u,1)
  u=np.matrix(u)
  num_pos=sum(n>0 for n in u).sum()
  chi2=4*np.square(num_pos-0.5*N*T)/N/T
  return chi2

def pesarantest(u):
  T=np.size(u,0)
  N=np.size(u,1)
  CD=0
  for i in range(0,N-1):
    for j in range(i+1,N):
      CD=CD+np.corrcoef(u.iloc[:,i],u.iloc[:,j])[0,1]
  CD=np.sqrt(2*T/N/(N-1))*CD  
  return CD  

def portmanteau(u,h):
  T=np.size(u,0)
  N=np.size(u,1)
  C=np.zeros((h+1,N,N))
  Q=0
  for k in range(0,h+1):
    for i in range(1+k,T):
      C[k,:,:]=np.add(C[k,:,:],np.outer(u.iloc[i,:],u.iloc[i-k,:]))
    C[k,:,:]=C[k,:,:]/T
  C0_inv=np.linalg.inv(C[0,:,:])
  for k in range(1,h+1):
    Q=Q+1/(T-k)*np.trace(np.transpose(C[h,:,:])*C0_inv*C[h,:,:]*C0_inv)
  Q=Q*T*T
  return Q


def advanced_autoencoder(x_in,x, epochs, batch_size, activations, depth, neurons):
    sess = tf.Session(graph=tf.get_default_graph(), config=session_conf)
    K.set_session(sess)
    num_stock=len(x_in.columns)
    
    # activation functions    
    if activations == 'elu':
        function = ELU(alpha=1.0)
    elif activations == 'lrelu':
        function = LeakyReLU(alpha=0.1)
    else:
        function = ReLU(max_value=None, negative_slope=0.0, threshold=0.0)
        
    autoencoder = Sequential()
    # encoding layers of desired depth
    for n in range(1, depth+1):
        # input layer
        if n==1:
            #autoencoder.add(GaussianNoise(stddev=0.01, input_shape=(num_stock,)))
            autoencoder.add(Dense(int(neurons/n), input_shape=(num_stock,)))
            autoencoder.add(function)
        else:            
            autoencoder.add(Dense(int(neurons/n)))
            autoencoder.add(function)
    # decoding layers of desired depth
    for n in range(depth, 1, -1):
        autoencoder.add(Dense(int(neurons/(n-1))))
        autoencoder.add(function)
    # output layer
    autoencoder.add(Dense(num_stock, activation='linear'))
    
    # compiling the model
    autoencoder.compile(optimizer='adam', loss='mean_squared_error', metrics=['accuracy'])
    
    earlystopper=EarlyStopping(monitor='val_loss',min_delta=0,patience=10,verbose=0,mode='auto',baseline=None,restore_best_weights=True)
    history=autoencoder.fit(x_in, x_in, epochs=epochs, batch_size=batch_size, \
                              shuffle=False, validation_split=0.15, verbose=0,callbacks=[earlystopper])
    y=autoencoder.predict(x)
    
    #CLOSE TF SESSION
    K.clear_session()
    return y
    

dataset = data.import_data('CDAX_without_penny_stocks')
np.random.seed(1)
rn.seed(12345)        
tf.set_random_seed(1234)

num_obs=dataset.shape[0]
num_stock=dataset.shape[1]
in_fraction=int(0.5*num_obs)
first_period=num_obs
x_in=dataset.iloc[:in_fraction,:]

chi2_bound=6.635
z_bound=2.58
runs=1
labda=0.94
s=500

x=np.matrix(dataset.iloc[:first_period,:])
num_obs=first_period

# predictions standard
r_pred=np.zeros((num_obs,num_stock))
s_pred=np.zeros((num_obs,num_stock,num_stock))
s_pred[0,:num_stock,:num_stock]=np.outer((r_pred[0:1,:num_stock]),(r_pred[0:1,:num_stock]))
weights=np.zeros((num_obs-in_fraction,num_stock))
portfolio_ret=np.zeros((num_obs-in_fraction,1))
portfolio_vol=np.zeros((num_obs-in_fraction,1))
MSPE_sigma=0
           
for i in range(1,num_obs):
  if i<s+1:
    r_pred[i:i+1,:num_stock]=x[0:i,:num_stock].mean(axis=0)
  else:
    r_pred[i:i+1,:num_stock]=x[i-s:i,:num_stock].mean(axis=0)
  s_pred[i,:num_stock,:num_stock]=(1-labda)*np.outer((x[i-1:i,:num_stock]-r_pred[i-1:i,:num_stock]),(x[i-1:i,:num_stock]-r_pred[i-1:i,:num_stock]))+labda*s_pred[i-1,:num_stock,:num_stock]

f_errors=r_pred-x
MSPE_r=np.square(f_errors[num_obs-in_fraction:,:num_stock]).mean()
for i in range(in_fraction,num_obs):
  MSPE_sigma=MSPE_sigma+np.square(np.outer(f_errors[i:i+1,:],f_errors[i:i+1,:])-s_pred[i,:num_stock,:num_stock]).mean()
MSPE_sigma=MSPE_sigma/(num_obs-in_fraction)

outcomes_rej_chi2=np.zeros((1,7))
outcomes_rej_pes=np.zeros((1,7))
outcomes_rej_both=np.zeros((1,7))
relu_vo=np.zeros((1,7))
np.random.seed(5121)
rn.seed(51212345)        
tf.set_random_seed(5121234)
#prediction autoencoded data
for q in range(0,100):
    print(q)
    auto_data=advanced_autoencoder(x_in,x,1000,10,'relu',3,100)
    auto_data=np.matrix(auto_data)
    errors = np.add(auto_data[:in_fraction,:],-x_in)
    A=np.zeros((5))
    A[0]=chi2test(errors)
    A[1]=pesarantest(errors)
    A[2]=portmanteau(errors,1)
    A[3]=portmanteau(errors,3)
    A[4]=portmanteau(errors,5)
    r_pred_auto=np.zeros((num_obs,num_stock))
    s_pred_auto=np.zeros((num_obs,num_stock,num_stock))
    s_pred_auto[0,:num_stock,:num_stock]=np.outer((r_pred_auto[0:1,:num_stock]),(r_pred_auto[0:1,:num_stock]))
  
    weights_auto=np.zeros((num_obs-in_fraction,num_stock))
    portfolio_ret_auto=np.zeros((num_obs-in_fraction,1))
    portfolio_vol_auto=np.zeros((num_obs-in_fraction,1))
    MSPE_sigma_auto=0
           
    for i in range(1,num_obs):
        if i<s+1:
            r_pred_auto[i,:num_stock]=auto_data[0:i,:num_stock].mean(axis=0)
        else:
            r_pred_auto[i,:num_stock]=auto_data[i-s:i,:num_stock].mean(axis=0)
        s_pred_auto[i,:num_stock,:num_stock]=(1-labda)*np.outer((auto_data[i-1,:num_stock]-r_pred_auto[i-1,:num_stock]),(auto_data[i-1,:num_stock]-r_pred_auto[i-1,:num_stock]))+labda*s_pred_auto[i-1,:num_stock,:num_stock]
        for j in range(0,num_stock):
            s_pred_auto[i,j,j]=s_pred[i,j,j]
           
    f_errors_auto=r_pred_auto-x
    MSPE_r_auto=np.square(f_errors_auto[num_obs-in_fraction:,:num_stock]).mean()
    for i in range(in_fraction,num_obs):
        MSPE_sigma_auto=MSPE_sigma_auto+np.square(np.outer(f_errors_auto[i:i+1,:],f_errors_auto[i:i+1,:])-s_pred_auto[i,:num_stock,:num_stock]).mean()
    MSPE_sigma_auto=MSPE_sigma_auto/(num_obs-in_fraction)
    res=np.zeros((1,7))
    res[0,:5]=A
    res[0,5]=MSPE_r_auto
    res[0,6]=MSPE_sigma_auto
    if (A[0]<chi2_bound and abs(A[1])<z_bound) or 1>0:
        relu_vo=np.concatenate((relu_vo,res),axis=0)
    elif (A[0]<chi2_bound and abs(A[1])>=z_bound):
        outcomes_rej_pes=np.concatenate((outcomes_rej_pes,res),axis=0)
    elif (A[0]>=chi2_bound and abs(A[1])<z_bound):
        outcomes_rej_chi2=np.concatenate((outcomes_rej_chi2,res),axis=0)            
    else:
        outcomes_rej_both=np.concatenate((outcomes_rej_both,res),axis=0)


tabelr=np.zeros((5,5))
tabelr[0,0]=MSPE_r
tabelr[2,0]=MSPE_r
tabelr[3,0]=MSPE_r
tabelr[4,0]=0
tabelr[0,1]=relu_vo[1:,5].mean()
tabelr[1,1]=scipy.stats.ttest_1samp(relu_vo[0:,5],MSPE_r)[0]
tabelr[2,1]=np.amin(relu_vo[0:,5])
tabelr[3,1]=np.amax(relu_vo[0:,5])
tabelr[4,1]=np.std(relu_vo[0:,5])

tabelr[0,2]=MSPE_sigma
tabelr[2,2]=MSPE_sigma
tabelr[3,2]=MSPE_sigma
tabelr[4,2]=0
tabelr[0,3]=relu_vo[0:,6].mean()
tabelr[1,3]=scipy.stats.ttest_1samp(relu_vo[0:,6],MSPE_sigma)[0]
tabelr[2,3]=np.amin(relu_vo[0:,6])
tabelr[3,3]=np.amax(relu_vo[0:,6])
tabelr[4,3]=np.std(relu_vo[0:,6])






