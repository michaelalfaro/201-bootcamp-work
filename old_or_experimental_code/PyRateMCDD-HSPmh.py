#!/usr/bin/env python 
import argparse, os,sys
from numpy import *
import numpy as np
from scipy.special import gamma
from scipy.special import beta as f_beta
import random as rand
import platform, time
import multiprocessing, thread
import multiprocessing.pool
import csv
from scipy.special import gdtr, gdtrix
from scipy.special import betainc
import scipy.stats
np.set_printoptions(suppress=True)
np.set_printoptions(precision=3)  
from multiprocessing import Pool, freeze_support
import thread
import imp
lib_updates_priors = imp.load_source("lib_updates_priors", "pyrate_lib/lib_updates_priors.py")
lib_DD_likelihood = imp.load_source("lib_DD_likelihood", "pyrate_lib/lib_DD_likelihood.py")
from lib_updates_priors import *
from lib_DD_likelihood  import *


#### DATA ###

p = argparse.ArgumentParser() #description='<input file>') 
p.add_argument('-d', type=str,   help='data set', default=0, metavar=0)
p.add_argument('-m', type=int,   help='model', default=0, metavar=0)
p.add_argument('-n', type=int,   help='MCMC iterations', default=5000000, metavar=5000000)
p.add_argument('-s', type=int,   help='sampling freq.', default=5000, metavar=5000)
p.add_argument('-p', type=int,   help='print freq.', default=5000000, metavar=5000000)
p.add_argument('-j', type=int,   help='replicate', default=0, metavar=0)
p.add_argument('-c', type=int, help='clade', default=0, metavar=0)
p.add_argument('-b', type=float, help='shape parameter (beta) of Be hyper=prior pn indicators', default=1, metavar=1)


args = p.parse_args()


dataset=args.d
n_iterations=args.n
sampling_freq=args.s
print_freq = args.p
#t_file=np.genfromtxt(dataset, names=True, delimiter='\t', dtype=float)
t_file=np.loadtxt(dataset, skiprows=1)

clade_ID=t_file[:,0]
clade_ID=clade_ID.astype(int)
ts=t_file[:,2+2*args.j]
te=t_file[:,3+2*args.j]

constr=args.m

single_focal_clade = True
if args.c==0: fixed_focal_clade=0
else: fixed_focal_clade = args.c-1
clade_name = "_c%s" % (fixed_focal_clade) #args.c)

Be_shape_beta = args.b
beta_value = "_hsp"

all_events=sort(np.concatenate((ts,te),axis=0))[::-1] # events are speciation/extinction that change the diversity trajectory
n_clades,n_events=max(clade_ID)+1,len(all_events)
Dtraj=init_Dtraj(n_clades,n_events)


##### get indexes
s_list = []
e_list = []
s_or_e_list=[]
clade_inx_list=[]
unsorted_events = []
for i in range(n_clades):
	"used for Dtraj"
	s_list.append(ts[clade_ID==i])
	e_list.append(te[clade_ID==i])
	"used for lik calculation"
	s_or_e_list += list(np.repeat(1,len(ts[clade_ID==i]))) # index 1 for s events
	s_or_e_list += list(np.repeat(2,len(te[clade_ID==i]))) # index 2 for e events
	clade_inx_list += list(np.repeat(i,2*len(te[clade_ID==i])))
	unsorted_events += list(ts[clade_ID==i])
	unsorted_events += list(te[clade_ID==i])

s_or_e_array= np.array(s_or_e_list)
unsorted_events= np.array(unsorted_events)
s_or_e_array[unsorted_events==0] = 3
""" so now: s_or_e_array = 1 (s events), s_or_e_array = 2 (e events), s_or_e_array = 3 (e=0 events)"""


""" concatenate everything:
                          1st row: all events  2nd row index s,e     3rd row clade index """
all_events_temp= np.array([unsorted_events,    s_or_e_array,         np.array(clade_inx_list)])
# sort by time
idx = np.argsort(all_events_temp[0])[::-1] # get indexes of sorted events
all_events_temp2=all_events_temp[:,idx] # sort by time of event
#print all_events_temp2
#print shape(all_events_temp2),len(all_events)
all_time_eve=all_events_temp2[0]

Dtraj_new=Dtraj
idx_s = []
idx_e = []
for i in range(n_clades): # make trajectory curves for each clade
	Dtraj_new[:,i]=getDT(all_events_temp2[0],s_list[i],e_list[i])
	ind_clade_i = np.arange(len(all_events_temp2[0]))[all_events_temp2[2]==i]
	ind_sp = np.arange(len(all_events_temp2[0]))[all_events_temp2[1]==1]
	ind_ex = np.arange(len(all_events_temp2[0]))[all_events_temp2[1]==2]
	idx_s.append(np.intersect1d(ind_clade_i,ind_sp))
	idx_e.append(np.intersect1d(ind_clade_i,ind_ex))




##### HORSESHOE PRIOR FUNCTIONS
def pdf_gamma(L,a,b): 
	return scipy.stats.gamma.logpdf(L, a, scale=1./b,loc=0)

def pdf_normal(L,sd): 
	return scipy.stats.norm.logpdf(L,loc=0,scale=sd)

def pdf_cauchy(x,s=1):
	return scipy.stats.cauchy.logpdf(x,scale=s,loc=0)
 
def sample_lambda_vec(lam,G_vec,tau):
	eta_vec = 1./(lam**2)
	mu_vec  = G_vec/tau
	
	u_vec  = np.random.uniform(0,1./(1+eta_vec),len(eta_vec))
	scale_exp = (2./(mu_vec**2))
	n_attempts=1000
	scale_exp = np.repeat(scale_exp,n_attempts).reshape(len(eta_vec),n_attempts)
	random_exp = np.random.exponential(scale=scale_exp,size=(len(eta_vec),n_attempts))
	u_vec_2D = np.repeat(u_vec,n_attempts).reshape(len(eta_vec),n_attempts)
	
	ind=(random_exp<u_vec_2D).nonzero() # x, y indexes of random_exp < u_vec
	uni_index=np.unique(ind[0],return_index=1)[1]
	random_exp_trunc = random_exp[ind[0],ind[1]][uni_index]
	
	new_lam = sqrt(1./random_exp_trunc)
	return new_lam

#####

scale_factor = 1./np.max(Dtraj)
MAX_G = np.inf #0.30/scale_factor # loc_shrinkage
MAX_G = 0.30/scale_factor

GarrayA=init_Garray(n_clades) # 3d array so:
                                 # Garray[i,:,:] is the 2d G for one clade
			         # Garray[0,0,:] is G_lambda, Garray[0,1,:] is G_mu for clade 0
GarrayA[fixed_focal_clade,:,:] += np.random.normal(0,1,np.shape(GarrayA[fixed_focal_clade,:,:]))

LAM=init_Garray(n_clades)
LAM[fixed_focal_clade,:,:] = 1.
Constr_matrix=make_constraint_matrix(n_clades, constr)

l0A,m0A=init_BD(n_clades),init_BD(n_clades)

out_file_name="%s_%s_m%s_MCDD%s%s.log" % (dataset,args.j,constr,clade_name,beta_value)
logfile = open(out_file_name , "wb") 
wlog=csv.writer(logfile, delimiter='\t')

lik_head=""
head="it\tposterior\tlikelihood\tprior"
head+="\tl%s" % (fixed_focal_clade)
head+="\tm%s" % (fixed_focal_clade)
for j in range(n_clades): 
	head+="\tGl%s_%s" % (fixed_focal_clade,j)
for j in range(n_clades): 
	head+="\tGm%s_%s" % (fixed_focal_clade,j)
for j in range(n_clades): 
	head+="\tkl%s_%s" % (fixed_focal_clade,j)
for j in range(n_clades): 
	head+="\tkm%s_%s" % (fixed_focal_clade,j)

head+="\tLAM_mu"		
head+="\tLAM_sd"		
head+="\tTau"		
head+="\thypR"
wlog.writerow(head.split('\t'))
logfile.flush()

TauA=np.array([1.]) # np.ones(1) # P(G==0)
hypRA=np.ones(1)
Tau=TauA

t1=time.time()
for iteration in range(n_iterations):	
	hasting=0
	gibbs_sampling=0
	if iteration==0:
		actualGarray=GarrayA*scale_factor
		likA,priorA,postA=np.zeros(n_clades),0,0
		
	l0,m0=l0A,m0A
	Garray=GarrayA
	Tau=TauA
	lik,priorBD=np.zeros(n_clades),0
	LAMtemp=LAM
	lik_test=np.zeros(n_clades)	
	
	
	if iteration==0:
		uniq_eve=np.unique(all_events,return_index=True)[1]  # indexes of unique values
		Garray_temp=Garray
		prior_r=0
		#for i in range(n_clades):
		i = fixed_focal_clade
		l_at_events=trasfMultiRate(l0[i],-Garray_temp[i,0,:],Dtraj)
		m_at_events=trasfMultiRate(m0[i],Garray_temp[i,1,:],Dtraj)
		l_s1a=l_at_events[idx_s[i]]
		m_e1a=m_at_events[idx_e[i]]
		lik[i] = (sum(log(l_s1a))-sum(abs(np.diff(all_events))*l_at_events[0:len(l_at_events)-1]*(Dtraj[:,i][1:len(l_at_events)])) \
		         +sum(log(m_e1a))-sum(abs(np.diff(all_events))*m_at_events[0:len(m_at_events)-1]*(Dtraj[:,i][1:len(l_at_events)])) )
		likA=lik

	else:	
		##### START FOCAL CLADE ONLY
		sampling_freqs=[.40,.60]		
		if iteration<1000: rr = np.random.uniform(0,sampling_freqs[1])
		else: rr = np.random.random()

		#if single_focal_clade is True and rr > sampling_freqs[1]: 
		focal_clade=fixed_focal_clade
		#else: focal_clade= np.random.random_integers(0,(n_clades-1),1)[0]
		
		if rr<sampling_freqs[0]:
			rr2 = np.random.random()
			if rr2<.15: 
				l0=np.zeros(n_clades)+l0A
				l0[focal_clade],hasting=update_multiplier_proposal(l0A[focal_clade],1.2)
			elif rr2<.3: 	
				m0=np.zeros(n_clades)+m0A
				m0[focal_clade],hasting=update_multiplier_proposal(m0A[focal_clade],1.2)
			if iteration> 2000:
				Tau_t,hasting = update_multiplier_proposal(TauA,1.2)
				Tau = np.zeros(1)+Tau_t
		elif rr<sampling_freqs[1]:
				LAMtemp    = init_Garray(n_clades)
				LAMtemp[focal_clade,0,:],U1 = update_multiplier_proposal(0+LAM[focal_clade,0,:],1.2)
				LAMtemp[focal_clade,1,:],U2 = update_multiplier_proposal(0+LAM[focal_clade,1,:],1.2)
				hasting = U1+U2
				
			
		
		elif rr<sampling_freqs[1]+.01: #sampling_freqs[1]: # update hypZ and hypR
			gibbs_sampling=1
			G_hp_alpha,G_hp_beta=1.,.01
			g_shape=G_hp_alpha+len(l0A)+len(m0A)
			rate=G_hp_beta+sum(l0A)+sum(m0A)
			hypRA = np.random.gamma(shape= g_shape, scale= 1./rate, size=1)		
		else: # update Garray (effect size) 
			Garray_temp= update_parameter_normal_2d_freq((GarrayA[focal_clade,:,:]),.35,m=-MAX_G,M=MAX_G) 			
			#__ Garray_temp,hasting=multiplier_proposal_pos_neg_vec(GarrayA[focal_clade,:,:],1.5)
			Garray=np.zeros(n_clades*n_clades*2).reshape(n_clades,2,n_clades)+GarrayA
			Garray[focal_clade,:,:]=Garray_temp
			#print GarrayA[focal_clade,:,:]-Garray[focal_clade,:,:]

		
		Garray_temp=Garray
		i=focal_clade 
		l_at_events=trasfMultiRate(l0[i],-Garray_temp[i,0,:],Dtraj)
		m_at_events=trasfMultiRate(m0[i], Garray_temp[i,1,:],Dtraj)
		### calc likelihood - clade i ###
		l_s1a=l_at_events[idx_s[i]]
		m_e1a=m_at_events[idx_e[i]]
		lik_clade = (sum(log(l_s1a))-sum(abs(np.diff(all_events))*l_at_events[0:len(l_at_events)-1]*(Dtraj[:,i][1:len(l_at_events)])) \
		         +sum(log(m_e1a))-sum(abs(np.diff(all_events))*m_at_events[0:len(m_at_events)-1]*(Dtraj[:,i][1:len(l_at_events)])) )
		ind_focal=np.ones(n_clades)
		ind_focal[focal_clade]=0
		lik = likA*ind_focal
		lik[focal_clade] = lik_clade
		###### END FOCAL

	""" len(Rtemp[Rtemp==0]), where Rtemp=R[i,:,:]
	should be equal to n_clades*2 - sum(R[i,:,:]) and len(Rtemp[Rtemp==0]) = sum(R[i,:,:]
	BTW, it is n_clades*2 because the same prior is used for both l0 and m0
	
	THUS:
	
	sum_R_per_clade = np.sum(RA,axis=(1,2))
	log(TauA) * (1-sum_R_per_clade) + log(1-TauA)*(sum_R_per_clade))
	
	"""
	#print np.shape(LAMtemp),np.shape(LAM)
	prior = sum(pdf_normal(Garray[fixed_focal_clade,:,:],sd=LAMtemp[fixed_focal_clade,:,:] * Tau))
	prior +=sum(pdf_cauchy(LAMtemp[fixed_focal_clade,:,:]))
	prior +=sum(pdf_cauchy(Tau))	
	prior += prior_exponential(l0,hypRA)+prior_exponential(m0,hypRA)
	
	if (sum(lik) + prior) - postA + hasting >= log(rand.random()) or iteration==0 or gibbs_sampling==1:
		postA=sum(lik)+prior
		likA=lik
		priorA=prior
		l0A=l0
                m0A=m0
		GarrayA=Garray
		actualGarray=GarrayA[fixed_focal_clade,:,:]*scale_factor
		LAM=LAMtemp
		TauA=Tau
		#hypRA=hypR
	
	if iteration % print_freq ==0: 
		k= 1./(1+TauA**2 * LAM[fixed_focal_clade,:,:]**2) # Carvalho 2010 Biometrika, p. 471
		loc_shrinkage = (1-k) # if loc_shrinkage > 0.5 is signal, otherwise it's noise (cf. Carvalho 2010 Biometrika, p. 474)
		print iteration, array([postA]), TauA, mean(LAM[fixed_focal_clade,:,:]), len(loc_shrinkage[loc_shrinkage>0]) #, sum(likA),sum(lik),prior, hasting
		#print likA
		#print "l:",l0A
		#print "m:", m0A
		#print "G:", actualGarray.flatten()
		#print "R:", RA.flatten()
		#print "Gr:", GarrayA.flatten()
		#print "Hmu:", TauA, 1./hypRA[0] #,1./hypRA[1],hypRA[2]
	if iteration % sampling_freq ==0:
		k= 1./(1+TauA**2 * LAM[fixed_focal_clade,:,:]**2) # Carvalho 2010 Biometrika, p. 471
		loc_shrinkage = (1-k) # so if loc_shrinkage > 0 is signal, otherwise it's noise (cf. Carvalho 2010 Biometrika, p. 474)
		#loc_shrinkage =LAM[fixed_focal_clade,:,:]**2
		log_state=[iteration,postA,sum(likA)]+[priorA]+[l0A[fixed_focal_clade]]+[m0A[fixed_focal_clade]]+list(actualGarray.flatten())+list(loc_shrinkage.flatten())+[mean(LAM[fixed_focal_clade,:,:]),std(LAM[fixed_focal_clade,:,:])] +list(TauA) +[hypRA[0]]
		wlog.writerow(log_state)
		logfile.flush()

print time.time()-t1
quit()










