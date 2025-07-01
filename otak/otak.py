# -*- coding: utf-8 -*-
# Copyright 2022 ONERA. 

"""Provide a class for AK algorithms.
"""

import openturns as ot
import numpy as np

from abc import ABC, abstractmethod


class AK_Algorithm(ABC):
    """
    Abstract base class for AK algorithms
        
    :event: ThresholdEvent based on composite vector of input variables on limit state function 
    
    :n_MC: integer, number of MC samples for the probability estimate
    
    :n_DoE: integer, number of samples in initial Kriging DoE
    
    :sim_budget: integer, total simulation budget available
    
    :basis: basis of kriging model
    
    :cov_model: covariance model of kriging
    
    :u_criterion: float, threshold value for `u criterion`
    
    :verbose: verbosity parameter 
        
    """

    def __init__(self,event,n_MC,n_DoE,sim_budget,basis,cov_model,u_criterion=2,verbose = False):
        self.n_MC = n_MC
        self.n_DoE = n_DoE
        self.event = event
        self.limit_state_function = event.getFunction()
        self.S = event.getThreshold()
        self.basis = basis
        self.cov_model = cov_model
        self.dim = event.getAntecedent().getDimension()
        self.proba = 0.
        self.cv = 0.
        self.distrib = event.getAntecedent().getDistribution()
        self.nb_eval = 0
        self.U_criterion = u_criterion
        self.DoE = None
        self.kriging_model = None
        self.verbose = verbose
        self.samples = None
        self.max_sim = sim_budget
        self.operator = event.getOperator()
        
    #Function determining the U criterion of AK
    def compute_U(self,my_krig,list_id_evaluated):
        """
        Function computing the infill criterion
        
        :my_krig: Kriging model, :py:class:`openturns.KrigingResult`
        
        :list_id_evaluated: list of evaluated :py:class:`openturns.Sample`
        """
        y_pred = my_krig.getConditionalMean(self.samples)
        y_var_pred = my_krig.getConditionalMarginalVariance(self.samples)
        
        list_id_non_evaluated = np.setdiff1d(np.arange(self.n_MC),list_id_evaluated)
        U = np.zeros((self.n_MC,1))
        
        U[list_id_non_evaluated] = np.abs(ot.Sample([ot.Point([self.S])]*int(len(list_id_non_evaluated)))-y_pred[list_id_non_evaluated])/np.sqrt(y_var_pred[list_id_non_evaluated])
        
        if len(list_id_evaluated)>0:
            U[list_id_evaluated] = 5e5
        return U
    
    @abstractmethod
    def generate_samples_and_weigts(self):
        """
        Abstract method to generate samples and weights for the algorithm.
        
        This method should be implemented in derived classes.
        
        """
        pass
    
    #Function computing the probability of failure
    def compute_proba(self):
        """
        Function computing failure probability using AK-MCS
        
        """
        self.samples, weights = self.generate_samples_and_weigts()
        
        # Generation of DoE
        DoE_inputs = self.samples[0:self.n_DoE]
        # Calculation of True function of the DoE
        DoE_responses = self.limit_state_function(DoE_inputs)
        list_id_samples_evaluated = np.linspace(0,self.n_DoE-1,self.n_DoE,dtype = int).tolist()

        # Definition of Kriging algorithm
        algokriging = ot.KrigingAlgorithm(DoE_inputs, 
                                          DoE_responses,
                                          self.cov_model,
                                          self.basis)
        algokriging.run()
        my_krig = algokriging.getResult()
        updated_cov = my_krig.getCovarianceModel()

        U_y_pred = self.compute_U(my_krig,list_id_samples_evaluated)
        id_opt_U = np.argmin(U_y_pred)
        current_min_U = np.min(U_y_pred)

        nb_pt_sim = 0
        list_id_samples_evaluated.append(id_opt_U)
        
        while nb_pt_sim<self.max_sim and current_min_U < self.U_criterion:
                #evaluation of true function
                x_new = self.samples[int(id_opt_U)]
                y_new = self.limit_state_function(x_new)

                DoE_inputs.add(x_new)
                DoE_responses.add(y_new)
                
                # Definition of Kriging model
                startingPoint = updated_cov.getScale()
                algokriging = ot.KrigingAlgorithm(DoE_inputs, 
                                                  DoE_responses,
                                                  updated_cov,
                                                  self.basis)
                
                
                solver_kriging = ot.NLopt('GN_DIRECT')
                solver_kriging.setStartingPoint(startingPoint)
                algokriging.setOptimizationAlgorithm(solver_kriging)
                algokriging.setOptimizationBounds(ot.Interval([0.01]*self.dim, [100]*self.dim))
                algokriging.run()

                my_krig = algokriging.getResult()
                updated_cov = my_krig.getCovarianceModel()

                # computation of U
                U_y_pred = self.compute_U(my_krig,list_id_samples_evaluated)
                current_min_U=np.min(U_y_pred)
                id_opt_U = np.argmin(U_y_pred)         
                nb_pt_sim = nb_pt_sim+1
                list_id_samples_evaluated.append(id_opt_U)

                y = my_krig.getConditionalMean(self.samples)
                I = [self.operator(y[i][0],self.S) for i in range(self.n_MC)]
                int_I = [int(i) for i in I]
                Pf = 1/self.n_MC*np.sum(np.array(int_I)*weights)

                self.proba = Pf
                self.nb_eval = self.n_DoE+nb_pt_sim
                self.DoE = [DoE_inputs,DoE_responses]
                self.kriging_model = my_krig
        
                if self.verbose == True:
                    if nb_pt_sim == 1:
                        print('current_min_U', '| Nb_sim',' | Probability estimate', ' | Coefficient of variation')
                        print('{:9e}'.format(current_min_U),' | ','{:5d}'.format(int(nb_pt_sim)),' |      ','{:11e}'.format(Pf),'   |      ','{:11e}'.format(self.cv))

                    else:
                        print('{:9e}'.format(current_min_U),' | ','{:5d}'.format(int(nb_pt_sim)),' |      ','{:11e}'.format(Pf),'   |      ','{:11e}'.format(self.cv))
        
        return

    #Accessor to the number of evaluated samples
    def getSimBudget(self):
        """
        Accessor to the simulation budget
        
        """
        return self.nb_eval
    
    #Accessor to the kriging model
    def getKrigingModel(self):
        """
        Accessor to Kriging model,  :py:class:`openturns.KrigingResult`
        
        """
        return self.kriging_model
                   
    #Accessor to the DoE
    def getDoE(self):
        """
        Accessor to the Design of Experiments, :py:class:`openturns.Sample`
        
        """
        return self.DoE
    
    #Accessor to the failure probability
    def getFailureProbability(self):
        """
        Accessor to failure probability
        
        """
        return self.proba
    
    #Accessor to the failure probability
    def getCoefficientOfVariation(self):
        """
        Accessor to coefficient of variation
        
        """
        return self.cv
    
    #Accessor to the MC samples
    def getSamples(self):
        """
        Accessor to samples,  :py:class:`openturns.Sample`
        
        """
        return self.samples


class AK_ISAlgorithm(AK_Algorithm):
    """
    Class implementing AK IS algorithm
        
    :event: ThresholdEvent based on composite vector of input variables on limit state function 
    
    :n_IS: integer, number of IS samples at the MPP found by FORM
    
    :n_DoE: integer, number of samples in initial Kriging DoE
    
    :sim_budget: integer, total simulation budget available
    
    :basis: basis of kriging model
    
    :cov_model: covariance model of kriging
    
    :FORM_solver: FORM solver 
    
    :u_criterion: float, threshold value for `u criterion`
    
    :verbose: verbosity parameter 
        
    """
	
    def __init__(self,event,n_IS,n_DoE,sim_budget,basis,cov_model,FORM_solver,u_criterion=2,verbose = False):

        super().__init__(event,n_IS,n_DoE,sim_budget,basis,cov_model,u_criterion,verbose)

        self.FORM_solver = FORM_solver
        self.inv_isoprobtrans = self.distrib.getInverseIsoProbabilisticTransformation()
        self.FORM_result = None
    
    def generate_samples_and_weigts(self):
        """
        Function to generate samples and weights for the AK-IS algorithm.
        
        This method generates samples in the standard space, transforms them to the physical space,
        and computes the weights based on the importance sampling distribution.
        
        Returns:
            samples: :py:class:`openturns.Sample` of generated samples in physical space
            weights: list of weights corresponding to each sample
        """
        # Computation of FORM
        vect = ot.RandomVector(self.distrib)
        G = ot.CompositeRandomVector(self.limit_state_function, vect)
        event = ot.ThresholdEvent(G,self.operator, self.S)
        
        #FORM algorithm to get the MPP
        algo = ot.FORM(self.FORM_solver, event, self.distrib.getMean())
        algo.run()
        result_FORM = algo.getResult()
        if self.verbose == True:
            print('Estimation of probability with FORM',result_FORM.getEventProbability())
        self.FORM_result = result_FORM
        
        # Derivation of auxiliary density and sampling
        myImportance = ot.Normal(self.dim)
        myImportance.setMu(self.FORM_result.getStandardSpaceDesignPoint())
        samples_std_space = myImportance.getSample(self.n_MC)
        samples_std_space = samples_std_space
        samples = self.inv_isoprobtrans(samples_std_space)
        
        #Calculation of weights in standard space
        norm_law = ot.Normal(np.zeros(self.dim), np.ones(self.dim), ot.IdentityMatrix(self.dim))
        weights = [norm_law.computePDF(x)/myImportance.computePDF(x) for x in samples_std_space]
        
        return samples, weights


class AK_MCSAlgorithm(AK_Algorithm):
    """
    Class implementing AK MCS algorithm
	 
    :event: ThresholdEvent based on composite vector of input variables on limit state function 
    
    :n_MC: integer, number of MCS samples
    
    :n_DoE: integer, number of samples in initial Kriging DoE
    
    :sim_budget: integer, total simulation budget available
    
    :basis: basis of kriging model
    
    :cov_model: covariance model of kriging
        
    :u_criterion: float, threshold value for `u criterion`
    
    :verbose: verbosity parameter 
        
    """
    
    def __init__(self,event,n_MC,n_DoE,sim_budget,basis, cov_model,u_criterion = 2,verbose = False):
        super().__init__(event,n_MC,n_DoE,sim_budget,basis,cov_model,u_criterion,verbose)
    
    def generate_samples_and_weigts(self):
        """
        Function to generate samples and weights for the AK-MCS algorithm.
        
        This method generates samples using a Monte Carlo experiment and returns the samples
        along with uniform weights.
        
        Returns:
            samples: :py:class:`openturns.Sample` of generated samples
            weights: list of uniform weights corresponding to each sample
        """
        # Generation of experiment
        myExperiment = ot.MonteCarloExperiment(self.distrib, self.n_MC)
        samples = myExperiment.generate()
        
        # Uniform weights for MCS
        weights = [1.0] * self.n_MC
        
        return samples, weights


class AK_SSAlgorithm(AK_Algorithm):
    """
    Class implementing AK SS algorithm
	 
    :event: ThresholdEvent based on composite vector of input variables on limit state function 
    
    :n_SS: integer, number of SS samples
    
    :n_DoE: integer, number of samples in initial Kriging DoE
    
    :sim_budget: integer, total simulation budget available
    
    :basis: basis of kriging model
    
    :cov_model: covariance model of kriging
	
    :proposal_range: proposal range of SubsetSampling
    
    :target_proba: targetProbability of SubsetSampling
    
    :cv_target: target coefficient of variation 
        
    :u_criterion: float, threshold value for `u criterion`
    
    :verbose: verbosity parameter 
        
    """
    
    def __init__(self,event,n_SS,n_DoE,sim_budget,basis, cov_model,proposal_range = 1.,target_proba=0.5,cv_target = 0.05,u_criterion = 2,verbose = False):
        super().__init__(event,n_SS,n_DoE,sim_budget,basis,cov_model,u_criterion,verbose)

        self.cv = 1e4
        self.cv_target = cv_target
        self.proposal_range = proposal_range
        self.target_proba = target_proba
        self.discrepancy_LHS = 5


    #Function computing the probability of failure
    def compute_proba(self):
        """
        Function computing failure probability using AK-SS
        
        
        """                       
        #Generation of DoE using LHS
        liste_densite = []
        for i in range(self.distrib.getDimension()):
            liste_densite.append(ot.Uniform(self.distrib.getMarginal(i).getMean()[0]- self.discrepancy_LHS*self.distrib.getMarginal(i).getStandardDeviation()[0],
                                            self.distrib.getMarginal(i).getMean()[0]+ self.discrepancy_LHS*self.distrib.getMarginal(i).getStandardDeviation()[0]))

        dist_LHS = ot.ComposedDistribution(liste_densite)   
        exp_LHS = ot.LHSExperiment(dist_LHS,self.n_DoE)    
        
        DoE_inputs = exp_LHS.generate()
    
        # Calculation of True function of the DoE
        DoE_responses = self.limit_state_function(DoE_inputs)
        
        current_iter = 1
        nb_pt_sim=0
        
        while (self.cv>self.cv_target and nb_pt_sim<self.max_sim) :                
            if current_iter ==1: #first iter
                #Generation of experiment ### modification of initial algorithm --> not taking into account the first iteration of SS but another sampling 
                
                ot.RandomGenerator.SetSeed(1)
                myExperiment = ot.MonteCarloExperiment(self.distrib, self.n_MC)
                self.samples = myExperiment.generate()
                
                list_id_samples_evaluated=[]
                
                #Generation of Kriging model
                    
                algokriging = ot.KrigingAlgorithm(DoE_inputs, 
                                                  DoE_responses,
                                                  self.cov_model,
                                                  self.basis)
                
                
                solver_kriging = ot.NLopt('GN_DIRECT')
                algokriging.setOptimizationAlgorithm(solver_kriging)
                algokriging.setOptimizationBounds(ot.Interval([0.01]*self.dim, [100]*self.dim))
                algokriging.run()
                my_krig = algokriging.getResult()
                metamodel = my_krig.getMetaModel()

                updated_cov = my_krig.getCovarianceModel()
                U_y_pred = self.compute_U(my_krig,list_id_samples_evaluated)
                id_opt_U=np.argmin(U_y_pred)
                current_min_U = np.min(U_y_pred)
                list_id_samples_evaluated.append(id_opt_U)
                
            else: # Add points to current first iter of MC algo
                samples_additional_MC = myExperiment.generate()
                self.samples = ot.Sample(np.concatenate((self.samples,samples_additional_MC)))
                self.n_MC=  self.samples.getSize()
                #Compute u criterion on these samples
                U_y_pred = self.compute_U(my_krig,list_id_samples_evaluated)
                id_opt_U=np.argmin(U_y_pred)
                current_min_U = np.min(U_y_pred)
                list_id_samples_evaluated.append(id_opt_U)

            while nb_pt_sim<self.max_sim and current_min_U < self.U_criterion:
                    #evaluation of true function
                    x_new = self.samples[int(id_opt_U)]
                    y_new = self.limit_state_function(x_new)

                    DoE_inputs.add(x_new)
                    DoE_responses.add(y_new)
                    # Definition of Kriging model

                    startingPoint = updated_cov.getScale()
                    algokriging = ot.KrigingAlgorithm(DoE_inputs, 
                                                      DoE_responses,
                                                      self.cov_model,
                                                      self.basis)
                    
                    solver_kriging = ot.NLopt('GN_DIRECT')
                    solver_kriging.setStartingPoint(startingPoint)
                    algokriging.setOptimizationAlgorithm(solver_kriging)
                    algokriging.setOptimizationBounds(ot.Interval([0.01]*self.dim, [100]*self.dim))
                    algokriging.run()
                    my_krig = algokriging.getResult()
                    metamodel = my_krig.getMetaModel()
            
                    updated_cov = my_krig.getCovarianceModel()
                    # computation of U
                    U_y_pred = self.compute_U(my_krig,list_id_samples_evaluated)
                    current_min_U = np.min(U_y_pred)
                    id_opt_U = np.argmin(U_y_pred)         
                    nb_pt_sim = nb_pt_sim+1
                    list_id_samples_evaluated.append(id_opt_U)
                    

                    self.nb_eval = self.n_DoE+nb_pt_sim
                    self.DoE = [DoE_inputs,DoE_responses]
                    self.kriging_model = my_krig

                    '''if self.verbose == True:
                        if nb_pt_sim == 1:
                            print('current_min_U', '| Nb_sim')
                            print('{:9e}'.format(current_min_U),' | ','{:5d}'.format(int(nb_pt_sim)))

                        else:
                            print('{:9e}'.format(current_min_U),' | ','{:5d}'.format(int(nb_pt_sim)))'''

            #run of subsetsampling algorithm
            
            inputVector = ot.RandomVector(self.distrib)
            Y_kr = ot.CompositeRandomVector(metamodel, inputVector)
            my_eventkriging = ot.ThresholdEvent(Y_kr,self.operator,self.S)               
            SS_kr = ot.SubsetSampling(my_eventkriging,self.proposal_range,self.target_proba)
            SS_kr.setMaximumOuterSampling(self.n_MC)
            SS_kr.setKeepSample(True)
            SS_kr.run()
            res = SS_kr.getResult()
            self.proba = res.getProbabilityEstimate()
            self.cv = res.getCoefficientOfVariation()
            self.samples = SS_kr.getInputSample(SS_kr.getStepsNumber() - 1)
            if self.verbose == True:
                if current_iter ==1 :

                    print('current_iter', '| Nb_sim',' | Probability estimate', ' | Coefficient of variation')
                    print('{:9d}'.format(int(current_iter)),'   | ','{:5d}'.format(int(nb_pt_sim)),' |      ','{:11e}'.format(self.proba),'   |      ','{:11e}'.format(self.cv))
                
                else: 
                    print('{:9d}'.format(int(current_iter)),'   | ','{:5d}'.format(int(nb_pt_sim)),' |      ','{:11e}'.format(self.proba),'   |      ','{:11e}'.format(self.cv))
                    
            
            current_iter+=1

        return 