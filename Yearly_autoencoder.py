# -*- coding: utf-8 -*-
"""
Created on Mon Mar 18 09:46:47 2019

@author: tobiashoogteijling
"""
import multiprocessing as mp
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
from scipy.optimize import minimize
from read_data import get_rf, join_risky_with_riskless
session_conf = tf.ConfigProto(intra_op_parallelism_threads=1,
                              inter_op_parallelism_threads=1)
import math

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

    autoencoder.compile(optimizer='adam', loss='mae', metrics=['accuracy'])

    # checkpointer = ModelCheckpoint(filepath='weights.{epoch:02d}-{val_loss:.2f}.txt', verbose=0, save_best_only=True)
    earlystopper = EarlyStopping(monitor='val_loss', min_delta=0, patience=50, verbose=0, mode='auto', baseline=None,
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

def MVO(mu, Sigma, min_ret):
    mu = np.array(mu)
    Sigma = np.array(Sigma)
    N = mu.shape[0]

    # Define optimization problem
    objective_function = lambda w : np.transpose(w) @ Sigma @ w
    weight_constraint = lambda w : np.sum(w) - 1
    return_constraint = lambda w : np.transpose(w) @ mu - min_ret

    # Initialize
    w0 = np.zeros((1, N))
    w0[:] = 1/N
    b = [0, 1] # bounds
    bnds = [np.transpose(b)] * N
    cons = ({'type': 'eq', 'fun': weight_constraint},
            {'type': 'ineq', 'fun': return_constraint})

    # Minimize
    solution = minimize(objective_function, w0, method='SLSQP', bounds=bnds, constraints=cons)
    weights = solution.x
    return weights

dataset = data.import_data('CDAX_without_penny_stocks')
mktrf, rf = get_rf('daily', True)
dataset = join_risky_with_riskless(dataset, rf)
rf_merged = np.array(dataset['rf'])
rf_merged = rf_merged.reshape((rf_merged.shape[0],1))

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
for i in range(num_obs - in_fraction, num_obs):
    MSPE_sigma = MSPE_sigma + np.square(
        np.outer(f_errors[i:i + 1, :], f_errors[i:i + 1, :]) - s_pred[i, :num_stock, :num_stock]).mean()
MSPE_sigma = MSPE_sigma / (num_obs - in_fraction)

np.random.seed(121)
rn.seed(1212345)
tf.set_random_seed(121234)
out_fraction = num_obs - in_fraction

Y = int(out_fraction/252)
# prediction autoencoded data
def run(times,t):
    MSPE_sigma_auto = np.array(np.zeros((num_obs,1)))
    x_in_norf = x_in.iloc[:, :-1]
    x_norf = np.matrix(np.array(x)[:, :-1])
    finished = False
    res = np.zeros((1,7))
    outcomes_rej_chi2=np.zeros((1,7))
    outcomes_rej_pes=np.zeros((1,7))
    outcomes_rej_both=np.zeros((1,7))
    outcomes=np.zeros((1,7))
    counter = 0
    for q in range(0, times):
        print(q)
        auto_data = advanced_autoencoder(x_in_norf, x_norf, 1000, 10, 'elu', 3, 100)
        auto_data = np.matrix(auto_data)
        errors = np.add(auto_data[:in_fraction, :], -x_in_norf)
        A = np.zeros((5))
        A[0] = chi2test(errors)
        A[1] = pesarantest(errors)
        A[2] = portmanteau(errors, 1)
        A[3] = portmanteau(errors, 3)
        A[4] = portmanteau(errors, 5)
        auto_data = np.append(auto_data, np.array(x[:, -1]), axis=1)
        num_stock = auto_data.shape[1]
        r_pred_auto = np.zeros((num_obs, num_stock))
        s_pred_auto = np.zeros((num_obs, num_stock, num_stock))
        s_pred_auto[0, :num_stock, :num_stock] = np.outer((r_pred_auto[0:1, :num_stock]),
                                                          (r_pred_auto[0:1, :num_stock]))

        for i in range(1, num_obs):
            if i < s + 1:
                r_pred_auto[i, :num_stock] = auto_data[0:i, :num_stock].mean(axis=0)
            else:
                r_pred_auto[i, :num_stock] = auto_data[i - s:i, :num_stock].mean(axis=0)
            s_pred_auto[i, :num_stock, :num_stock] = (1 - labda) * np.outer(
                (auto_data[i - 1, :num_stock] - r_pred_auto[i - 1, :num_stock]),
                (auto_data[i - 1, :num_stock] - r_pred_auto[i - 1, :num_stock])) + labda * s_pred_auto[i - 1,
                                                                                           :num_stock, :num_stock]
            for j in range(0, num_stock-1):
                s_pred_auto[i, j, j] = s_pred[i, j, j]

        f_errors_auto = r_pred_auto - x
        MSPE_r_auto = np.square(f_errors_auto[t:t+252, :num_stock]).mean()
        for i in range(t, t+252):
            MSPE_sigma_auto[t] = np.square(np.outer(f_errors_auto[i:i + 1, :], f_errors_auto[i:i + 1, :]) -
                                           s_pred_auto[i, :num_stock, :num_stock]).mean()
        MSPE_r_year = MSPE_r_auto.mean()
        MSPE_sigma_year = MSPE_sigma_auto.mean()
        res[0, :5] = A
        res[0, 5] = MSPE_r_year
        res[0, 6] = MSPE_sigma_year
        if (A[0]<chi2_bound and abs(A[1])<z_bound):
            outcomes=np.concatenate((outcomes,res),axis=0)
        elif (A[0]<chi2_bound and abs(A[1])>=z_bound):
            outcomes_rej_pes=np.concatenate((outcomes_rej_pes,res),axis=0)
        elif (A[0]>=chi2_bound and abs(A[1])<z_bound):
            outcomes_rej_chi2=np.concatenate((outcomes_rej_chi2,res),axis=0)
        else:
            outcomes_rej_both=np.concatenate((outcomes_rej_both,res),axis=0)
    counter += 1
    separator = np.array([counter, counter, counter, counter, counter, counter, counter]).reshape((1,7))
    outcomes = np.concatenate((outcomes, separator), axis=0)
    outcomes_rej_pes = np.concatenate((outcomes_rej_pes, separator), axis=0)
    outcomes_rej_chi2 = np.concatenate((outcomes_rej_chi2, separator), axis=0)
    outcomes_rej_both = np.concatenate((outcomes_rej_both, separator), axis=0)

    return (outcomes, outcomes_rej_pes, outcomes_rej_chi2, outcomes_rej_both)


start_dates = [in_fraction, in_fraction+252, in_fraction+252*2, in_fraction+252*4, in_fraction+252*4, in_fraction+252*5, in_fraction+252*6]

outcomes_rej_chi2 = np.zeros((1, 7))
outcomes_rej_pes = np.zeros((1, 7))
outcomes_rej_both = np.zeros((1, 7))
outcomes = np.zeros((1, 7))

if __name__ == "__main__":
    pool = mp.Pool(processes=7)
    results = [pool.apply_async(run, args=(500, t)) for t in start_dates]
    output = [p.get() for p in results]

    for p in range(7):
        separator = np.array([p, p, p, p, p, p, p]).reshape((1, 7))
        outcomes = np.concatenate((outcomes, separator), axis=0)
        outcomes_rej_pes = np.concatenate((outcomes_rej_pes, separator), axis=0)
        outcomes_rej_chi2 = np.concatenate((outcomes_rej_chi2, separator), axis=0)
        outcomes_rej_both = np.concatenate((outcomes_rej_both, separator), axis=0)
        outcomes = np.concatenate((outcomes, (output[p])[0]), axis=0)
        outcomes_rej_pes = np.concatenate((outcomes_rej_pes, (output[p])[1]), axis=0)
        outcomes_rej_chi2 = np.concatenate((outcomes_rej_chi2, (output[p])[2]), axis=0)
        outcomes_rej_both = np.concatenate((outcomes_rej_both, (output[p])[3]), axis=0)


## Last year


outcomes = outcomes[~np.all(outcomes == 0, axis=1)]
outcomes_rej_both = outcomes_rej_both[~np.all(outcomes_rej_both == 0, axis=1)]
outcomes_rej_chi2 = outcomes_rej_chi2[~np.all(outcomes_rej_chi2 == 0, axis=1)]
outcomes_rej_pes = outcomes_rej_pes[~np.all(outcomes_rej_pes == 0, axis=1)]

pd.DataFrame(outcomes).to_csv('Yearly_autoencoder_outcomes_mp.csv')
pd.DataFrame(outcomes_rej_pes).to_csv('Yearly_autoencoder_outcomes_rej_pes_mp.csv')
pd.DataFrame(outcomes_rej_chi2).to_csv('Yearly_autoencoder_outcomes_rej_chi2_mp.csv')
pd.DataFrame(outcomes_rej_both).to_csv('Yearly_autoencoder_outcomes_rej_both_mp.csv')
