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
import math
from keras.layers.advanced_activations import LeakyReLU, ReLU, ELU
from keras.layers import Input, Dense, GaussianNoise
from keras.models import Model, Sequential
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.utils import HDF5Matrix
import multiprocessing as mp
session_conf = tf.ConfigProto(intra_op_parallelism_threads=1,
                              inter_op_parallelism_threads=1)


def chi2test(u):
    num_pos = 0
    T = np.size(u, 0)
    N = np.size(u, 1)
    u = np.matrix(u)
    num_pos = sum(n > 0 for n in u).sum()
    chi2 = 4 * np.square(num_pos - 0.5 * N * T) / N / T
    return chi2


def pesarantest(u):
    T = np.size(u, 0)
    N = np.size(u, 1)
    CD = 0
    for i in range(0, N - 1):
        for j in range(i + 1, N):
            CD = CD + np.corrcoef(u.iloc[:, i], u.iloc[:, j])[0, 1]
    CD = np.sqrt(2 * T / N / (N - 1)) * CD
    return CD


def portmanteau(u, h):
    T = np.size(u, 0)
    N = np.size(u, 1)
    C = np.zeros((h + 1, N, N))
    Q = 0
    for k in range(0, h + 1):
        for i in range(1 + k, T):
            C[k, :, :] = np.add(C[k, :, :], np.outer(u.iloc[i, :], u.iloc[i - k, :]))
        C[k, :, :] = C[k, :, :] / T
    C0_inv = np.linalg.inv(C[0, :, :])
    for k in range(1, h + 1):
        Q = Q + 1 / (T - k) * np.trace(np.transpose(C[h, :, :]) * C0_inv * C[h, :, :] * C0_inv)
    Q = Q * T * T
    return Q


def advanced_autoencoder(x_in, x, epochs, batch_size, activations, depth, neurons):
    sess = tf.Session(graph=tf.get_default_graph(), config=session_conf)
    K.set_session(sess)
    num_stock = len(x_in.columns)

    # activation functions
    if activations == 'elu':
        function = ELU(alpha=1.0)
    elif activations == 'lrelu':
        function = LeakyReLU(alpha=0.1)
    else:
        function = ReLU(max_value=None, negative_slope=0.0, threshold=0.0)

    autoencoder = Sequential()
    # encoding layers of desired depth
    for n in range(1, depth + 1):
        # input layer
        if n == 1:
            # autoencoder.add(GaussianNoise(stddev=0.01, input_shape=(num_stock,)))
            autoencoder.add(Dense(int(neurons / n), input_shape=(num_stock,)))
            autoencoder.add(function)
        else:
            autoencoder.add(Dense(int(neurons / n)))
            autoencoder.add(function)
    # decoding layers of desired depth
    for n in range(depth, 1, -1):
        autoencoder.add(Dense(int(neurons / (n - 1))))
        autoencoder.add(function)
    # output layer
    autoencoder.add(Dense(num_stock, activation='linear'))

    # autoencoder.compile(optimizer='sgd', loss='mean_absolute_error', metrics=['accuracy'])

    autoencoder.compile(optimizer='adam', loss='mean_squared_error', metrics=['accuracy'])

    # checkpointer = ModelCheckpoint(filepath='weights.{epoch:02d}-{val_loss:.2f}.txt', verbose=0, save_best_only=True)
    earlystopper = EarlyStopping(monitor='val_loss', min_delta=0, patience=10, verbose=0, mode='auto', baseline=None,
                                 restore_best_weights=True)
    history = autoencoder.fit(x_in, x_in, epochs=epochs, batch_size=batch_size, \
                              shuffle=False, validation_split=0.15, verbose=0, callbacks=[earlystopper])
    # errors = np.add(autoencoder.predict(x_in),-x_in)
    y = autoencoder.predict(x)
    # saving results of error distribution tests
    # A=np.zeros((5))
    # A[0]=chi2test(errors)
    # A[1]=pesarantest(errors)
    # A[2]=portmanteau(errors,1)
    # A[3]=portmanteau(errors,3)
    # A[4]=portmanteau(errors,5)

    # autoencoder.summary()

    # plot accuracy and loss of autoencoder
    # plot_accuracy(history)
    # plot_loss(history)

    # plot original, encoded and decoded data for some stock
    # plot_two_series(x_in, 'Original data', auto_data, 'Reconstructed data')

    # the histogram of the data
    # make_histogram(x_in, 'Original data', auto_data, 'Reconstructed data')

    # CLOSE TF SESSION
    K.clear_session()
    return y

def adaptive_threshold_EWMA(e, tau, t):
    e = np.array(e)
    T,N = e.shape
    ecov_roll = np.array(pd.DataFrame(e).ewm(alpha=0.06).cov())
    ecov_roll = np.nan_to_num(ecov_roll)
    ecov = np.zeros((T,N,N))
    for t in range(T):
        ecov[t,:,:] = ecov_roll[t*N:t*N+N]
    adapted_ecov = np.array(ecov.copy())
    old_theta = np.zeros((N,N))
    new_theta = np.zeros((N,N))
    for t in range(T):
        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                else:
                    new_theta[i,j] = 0.06 * np.square(e[t,i] * e[t,j] - ecov[t,i,j]) + 0.94 * old_theta[i,j]

        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                elif np.abs(ecov[t,i,j]) < np.sqrt(new_theta[i,j]) * tau:
                    adapted_ecov[t,i,j] = 0
        old_theta = new_theta

    n_nonzeros = np.count_nonzero(adapted_ecov)-N
    fraction_restored = n_nonzeros/(T*N*(N-1))
    return adapted_ecov, fraction_restored

dataset = data.import_data('CDAX_without_penny_stocks')
np.random.seed(1)
rn.seed(12345)
tf.set_random_seed(1234)

num_obs = dataset.shape[0]

in_fraction = int(0.5 * num_obs)
first_period = num_obs
x_in = dataset.iloc[:in_fraction, :]
num_stock = dataset.shape[1]  # not including the risk free stock
chi2_bound = 6.635
z_bound = 2.58
runs = 1
labda = 0.94
s = 500
x = np.matrix(dataset.iloc[:first_period, :])
num_obs = first_period
# predictions standard
r_pred = np.zeros((num_obs, num_stock))
s_pred = np.zeros((num_obs, num_stock, num_stock))
s_pred[0, :num_stock, :num_stock] = np.outer((r_pred[0:1, :num_stock]), (r_pred[0:1, :num_stock]))
weights = np.zeros((num_obs - in_fraction, num_stock))
portfolio_ret = np.zeros((num_obs - in_fraction, 1))
portfolio_vol = np.zeros((num_obs - in_fraction, 1))
MSPE_sigma = 0

for i in range(1, num_obs):
    if i < s + 1:
        r_pred[i:i + 1, :num_stock] = x[0:i, :num_stock].mean(axis=0)
    else:
        r_pred[i:i + 1, :num_stock] = x[i - s:i, :num_stock].mean(axis=0)
    s_pred[i, :num_stock, :num_stock] = (1 - labda) * np.outer((x[i - 1:i, :num_stock] - r_pred[i - 1:i, :num_stock]), (
                x[i - 1:i, :num_stock] - r_pred[i - 1:i, :num_stock])) + labda * s_pred[i - 1, :num_stock, :num_stock]

f_errors = r_pred - x
MSPE_r = np.square(f_errors[num_obs - in_fraction:, :num_stock]).mean()
for i in range(in_fraction, num_obs):
    MSPE_sigma = MSPE_sigma + np.square(
        np.outer(f_errors[i:i + 1, :], f_errors[i:i + 1, :]) - s_pred[i, :num_stock, :num_stock]).mean()
MSPE_sigma = MSPE_sigma / (num_obs - in_fraction)

MSPE_sigma_auto_threshold = np.array(np.zeros((num_obs,1)))

outcomes = np.zeros((1, 7))
outcomes_rej_pes = np.zeros((1, 7))
outcomes_rej_chi2 = np.zeros((1, 7))
outcomes_rej_both = np.zeros((1, 7))

np.random.seed(5121)
rn.seed(51212345)
tf.set_random_seed(5121234)
# prediction autoencoded data
def run(times):
    res = np.zeros((1,7))
    outcomes_rej_chi2=np.zeros((1,7))
    outcomes_rej_pes=np.zeros((1,7))
    outcomes_rej_both=np.zeros((1,7))
    outcomes=np.zeros((1,7))

    for q in range(0, times):
        print(q)
        auto_data = advanced_autoencoder(x_in, x, 1000, 10, 'elu', 3, 100)
        auto_data = np.matrix(auto_data)
        errors = np.add(auto_data[:in_fraction, :], -x_in)
        A = np.zeros((5))
        A[0] = chi2test(errors)
        A[1] = pesarantest(errors)
        A[2] = portmanteau(errors, 1)
        A[3] = portmanteau(errors, 3)
        A[4] = portmanteau(errors, 5)
        r_pred_auto = np.zeros((num_obs, num_stock))
        s_pred_auto = np.zeros((num_obs, num_stock, num_stock))
        s_pred_auto[0, :num_stock, :num_stock] = np.outer((r_pred_auto[0:1, :num_stock]), (r_pred_auto[0:1, :num_stock]))

        weights_auto = np.zeros((num_obs - in_fraction, num_stock))
        portfolio_ret_auto = np.zeros((num_obs - in_fraction, 1))
        portfolio_vol_auto = np.zeros((num_obs - in_fraction, 1))
        MSPE_sigma_auto = 0

        for i in range(1, num_obs):
            if i < s + 1:
                r_pred_auto[i, :num_stock] = auto_data[0:i, :num_stock].mean(axis=0)
            else:
                r_pred_auto[i, :num_stock] = auto_data[i - s:i, :num_stock].mean(axis=0)
            s_pred_auto[i, :num_stock, :num_stock] = (1 - labda) * np.outer(
                (auto_data[i - 1, :num_stock] - r_pred_auto[i - 1, :num_stock]),
                (auto_data[i - 1, :num_stock] - r_pred_auto[i - 1, :num_stock])) + labda * s_pred_auto[i - 1, :num_stock,
                                                                                           :num_stock]
            for j in range(0, num_stock):
                s_pred_auto[i, j, j] = s_pred[i, j, j]

        f_errors_auto = r_pred_auto - x
        MSPE_r_auto = np.square(f_errors_auto[num_obs - in_fraction:, :num_stock]).mean()
        for i in range(num_obs - in_fraction, num_obs):
            MSPE_sigma_auto = MSPE_sigma_auto + np.square(
                np.outer(f_errors_auto[i:i + 1, :], f_errors_auto[i:i + 1, :]) - s_pred_auto[i, :num_stock,
                                                                                 :num_stock]).mean()

        resids = pd.DataFrame(auto_data - x)

        # Threshold
        adapted_ecov, fraction_restored = adaptive_threshold_EWMA(resids, 0.35, num_obs)
        s_pred_auto_threshold = s_pred_auto + adapted_ecov
        print(fraction_restored)
        for i in range(1, num_obs):
            for j in range(0, num_stock):
                s_pred_auto_threshold[i, j, j] = s_pred[i, j, j]

        for i in range(in_fraction,num_obs):
            MSPE_sigma_auto_threshold[i] = np.square(np.outer(f_errors_auto[i, :], f_errors_auto[i, :]) -
                                                     s_pred_auto_threshold[i, :num_stock, :num_stock]).mean()


        MSPE_sigma_auto = MSPE_sigma_auto_threshold[in_fraction:].mean()
        res = np.zeros((1, 7))
        res[0, :5] = A
        res[0, 5] = MSPE_r_auto
        res[0, 6] = MSPE_sigma_auto
        if (A[0] < chi2_bound and abs(A[1]) < z_bound):
            outcomes = np.concatenate((outcomes, res), axis=0)
        elif (A[0] < chi2_bound and abs(A[1]) >= z_bound):
            outcomes_rej_pes = np.concatenate((outcomes_rej_pes, res), axis=0)
        elif (A[0] >= chi2_bound and abs(A[1]) < z_bound):
            outcomes_rej_chi2 = np.concatenate((outcomes_rej_chi2, res), axis=0)
        else:
            outcomes_rej_both = np.concatenate((outcomes_rej_both, res), axis=0)

    return (outcomes, outcomes_rej_pes, outcomes_rej_chi2, outcomes_rej_both)



if __name__ == "__main__":
    pool = mp.Pool(processes=5)
    results = [pool.apply_async(run, args=(50,)) for i in range(5)]
    output = [p.get() for p in results]

    for p in range(5):
        outcomes = np.concatenate((outcomes, (output[p])[0]), axis=0)
        outcomes_rej_pes = np.concatenate((outcomes_rej_pes, (output[p])[1]), axis=0)
        outcomes_rej_chi2 = np.concatenate((outcomes_rej_chi2, (output[p])[2]), axis=0)
        outcomes_rej_both = np.concatenate((outcomes_rej_both, (output[p])[3]), axis=0)



outcomes_mooi = pd.DataFrame(outcomes, columns=['Chi2', 'Pesaran', 'Portmanteau1', 'Portmanteau3', 'Portmanteau5','MSPE_r', 'MSPE_sigma'])
outcomes_mooi.to_csv('./data/results/threshold_outcomes_not_rej_CDAX.csv')
outcomes_rej_pes_mooi = pd.DataFrame(outcomes_rej_pes, columns=['Chi2', 'Pesaran', 'Portmanteau1', 'Portmanteau3', 'Portmanteau5','MSPE_r', 'MSPE_sigma'])
outcomes_rej_pes_mooi.to_csv('./data/results/threshold_outcomes_rej_pes_CDAX.csv')
outcomes_rej_chi2_mooi = pd.DataFrame(outcomes_rej_chi2, columns=['Chi2', 'Pesaran', 'Portmanteau1', 'Portmanteau3', 'Portmanteau5','MSPE_r', 'MSPE_sigma'])
outcomes_rej_chi2_mooi.to_csv('./data/results/threshold_outcomes_rej_chi2_CDAX.csv')
outcomes_rej_both_mooi = pd.DataFrame(outcomes_rej_both, columns=['Chi2', 'Pesaran', 'Portmanteau1', 'Portmanteau3', 'Portmanteau5','MSPE_r', 'MSPE_sigma'])
outcomes_rej_both_mooi.to_csv('./data/results/threshold_outcomes_rej_both_CDAX.csv')