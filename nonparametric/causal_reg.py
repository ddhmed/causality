import pandas as pd
from statsmodels.nonparametric.kernel_density import KDEMultivariateConditional, KDEMultivariate
from statsmodels.nonparametric.kernel_regression import KernelReg
import itertools
from scipy.integrate import nquad
import numpy as np

class CausalEffect(object):
    def __init__(self, X, causes, effects, admissable_set=[], variable_types=None, expectation=False, density=True):
        """
        We want to calculate the causal effect of X and Y through
        back-door adjustment, P(Y|do(X)) = Sum( P(Y|X,Z)P(Z), Z) 
        for some admissable set of control variables, Z.  First we 
        calculate the conditional density P(Y|X,Z), then the density
        P(Z).  We find the support of Z so we can properly sum over
        it later.  variable_types are a dictionary with the column name
        pointing to an element of set(['o', 'u', 'c']), for 'ordered',
        'unordered discrete', or 'continuous'.
        """
        conditional_density_vars = causes + admissable_set
        self.causes = causes
        self.effects = effects
        self.admissable_set = admissable_set
        self.conditional_density_vars = conditional_density_vars
        
        if variable_types:
            self.variable_types = variable_types
            dep_type      = [variable_types[var] for var in effects]
            indep_type    = [variable_types[var] for var in conditional_density_vars]
            density_types = [variable_types[var] for var in admissable_set]
        else:
            self.variable_types = self.__infer_variable_types(X)

        if 'c' not in variable_types.values():
            bw = 'cv_ml'
        else:
            bw = 'normal_reference'


        if admissable_set:            
            self.density = KDEMultivariate(X[admissable_set], 
                                  var_type=''.join(density_types),
                                  bw=bw)
        #if density:
        self.conditional_density = KDEMultivariateConditional(endog=X[effects],
                                                         exog=X[conditional_density_vars],
                                                         dep_type=''.join(dep_type),
                                                         indep_type=''.join(indep_type),
                                                         bw=bw)
        if expectation:
            self.conditional_expectation = KernelReg(X[effects].values,
                                                 X[conditional_density_vars].values,
                                                 ''.join(indep_type),
                                                 bw='cv_ls')

        self.support = self.__get_support(X)
        
        self.discrete_variables = [ variable for variable, var_type in self.variable_types.items() if var_type in ['o', 'u']]
        self.discrete_Z = list(set(self.discrete_variables).intersection(set(admissable_set)))
        self.continuous_variables = [ variable for variable, var_type in self.variable_types.items() if var_type == 'c' ]
        self.continuous_Z = list(set(self.continuous_variables).intersection(set(admissable_set)))
       
 
    def __infer_variable_types(self,X):
        """
        fill this in later.
        """
        pass
       
 
    def __get_support(self, X):
        """
        find the smallest cube around which the densities are supported,
        allowing a little flexibility for variables with larger bandwidths.
        """
        data_support = { variable : (X[variable].min(), X[variable].max()) for variable in X.columns}
        variable_bandwidths = { variable : bw for variable, bw in zip(self.effects + self.conditional_density_vars, self.conditional_density.bw)}
        support = {}
        for variable in self.effects + self.conditional_density_vars:
            if self.variable_types[variable] == 'c':
                lower_support = data_support[variable][0] - 10. * variable_bandwidths[variable]
                upper_support = data_support[variable][1] + 10. * variable_bandwidths[variable]
                support[variable] = (lower_support, upper_support)
            else:
                support[variable] = data_support[variable]
        return support

    def biased_mutual_information(self, X, x1, x2):
        """
        compute the mutual information I(x1,x2) between x1 and x2 for continuous variables,
        I(x1,x2) = H(x2) - H(x2 | x1)
        """
        self.x1 = x1
        self.x2 = x2

        dep_type      = [self.variable_types[x1]]
        indep_type    = [self.variable_types[x2]]
        density_types = [self.variable_types[var] for var in [x1,x2]] 

        if 'c' not in density_types:
            bw = 'cv_ml'
        else:
            bw = 'normal_reference'
        self.mi_density = KDEMultivariate(X[[x2]],
                                  var_type=''.join(dep_type),
                                  bw=bw)
        self.mi_conditional_density = KDEMultivariateConditional(endog=X[x2],
                                                         exog=X[x1],
                                                         dep_type=''.join(dep_type),
                                                         indep_type=''.join(indep_type),
                                                         bw=bw)
        self.x1_integration_density = KDEMultivariate(X[[x2]],
                                  var_type=''.join(dep_type),
                                  bw=bw)
        x2_range = [self.support[x2] ]
        self.integration_density = self.mi_density
        self.cond_integration_density = self.mi_conditional_density
        Hx2 = nquad(self.entropy_integration_function, x2_range)[0]
        print "H%s" % x2 ,Hx2 
        x1x2_range = [self.support[x1], self.support[x2]]
        Hx2givenx1 = nquad(self.entropy_integration_function, x1x2_range)[0]
        print "H%s|%s" % (x2, x1), Hx2givenx1
        return Hx2 - Hx2givenx1
        
    def entropy_integration_function(self, *args):
        if len( args ) == 2:
            var = [self.x1, self.x2]
        elif len(args) == 1:
            var = [self.x2]
        else:
            raise Exception( "Too few args in entropy integration" )
        data = pd.DataFrame( {k : [v] for k, v in zip(var, args) } )
        if len(args) == 2:
            p = self.cond_integration_density.pdf(exog_predict=data[self.x1],
                                    endog_predict=data[self.x2]) 
            return - self.x1_integration_density.pdf( data_predict=data[self.x1] ) * p * np.log(p)
        else:
            p = self.integration_density.pdf( data_predict=data[self.x2] )
            return - p * np.log( p ) 
 

        
    def integration_function(self,*args):
        # takes continuous z, discrete z, then x
        data = pd.DataFrame({ k : [v] for k, v in zip(self.continuous_Z + self.discrete_Z + self.causes + self.effects, args)})
        conditional = self.conditional_density.pdf(exog_predict=data[self.conditional_density_vars].values[0], 
                                                   endog_predict=data[self.effects].values[0]) 
        density = self.density.pdf(data_predict=data[self.admissable_set])
        return conditional * density

    
    def expectation_integration_function(self, *args):
        data = pd.DataFrame({ k : [v] for k, v in zip(self.continuous_Z + self.discrete_Z + self.causes, args)})
        conditional = self.conditional_expectation.fit(data_predict=data[self.conditional_density_vars].values)[0]
        density = self.density.pdf(data_predict=data[self.admissable_set])
        return conditional * density

    
    def pdf(self, x):
        """
        Currently, this does the whole sum/integral over the cube support of Z.
        We may be able to improve this by taking into account how the joint
        and conditionals factorize, and/or finding a more efficient support.
        
        This should be reasonably fast for |Z| <= 2 or 3, and small enough discrete
        variable cardinalities.  It runs in O(n_1 n_2 ... n_k) in the cardinality of
        the discrete variables, |Z_1| = n_1, etc.  It likewise runs in O(V^n) for n
        continuous Z variables.  Factorizing the joint/conditional distributions in
        the sum could linearize the runtime.
        """
        causal_effect = 0.
        x = x[self.causes + self.effects]
        if self.discrete_Z:
            discrete_variable_ranges = [ xrange(*(int(self.support[variable][0]), int(self.support[variable][1])+1)) for variable in self.discrete_Z]
            for z_vals in itertools.product(*discrete_variable_ranges):
                z_discrete = pd.DataFrame({k : [v] for k, v in zip(self.discrete_Z, z_vals)})
                if self.continuous_Z:
                    continuous_Z_ranges = [self.support[variable] for variable in self.continuous_Z]
                    args = z_discrete.join(x).values[0]
                    causal_effect += nquad(self.integration_function,continuous_Z_ranges,args=args)[0]
                else:
                    z_discrete = z_discrete[self.admissable_set]
                    exog_predictors = x.join(z_discrete)[self.conditional_density_vars]
                    conditional = self.conditional_density.pdf(exog_predict=exog_predictors, 
                                                               endog_predict=x[self.effects]) 
                    density = self.density.pdf(data_predict=z_discrete)
                    dc = conditional * density
                    causal_effect += dc
            return causal_effect
        elif self.continuous_Z:
            continuous_Z_ranges = [self.support[var] for var in self.continuous_Z]
            causal_effect = nquad(self.integration_function,continuous_Z_ranges,args=tuple(x.values[0]))[0]
            return causal_effect
        else:
            return self.conditional_density.pdf(exog_predict=x[self.causes],endog_predict=x[self.effects])

       
 
    def expected_value( self, x):
        """
        Currently, this does the whole sum/integral over the cube support of Z.
        We may be able to improve this by taking into account how the joint
        and conditionals factorize, and/or finding a more efficient support.
        
        This should be reasonably fast for |Z| <= 2 or 3, and small enough discrete
        variable cardinalities.  It runs in O(n_1 n_2 ... n_k) in the cardinality of
        the discrete variables, |Z_1| = n_1, etc.  It likewise runs in O(V^n) for n
        continuous Z variables.  Factorizing the joint/conditional distributions in
        the sum could linearize the runtime.
        """
        causal_effect = 0.
        x = x[self.causes]
        if self.discrete_Z:
            discrete_variable_ranges = [ xrange(*(int(self.support[variable][0]), int(self.support[variable][1])+1)) for variable in self.discrete_Z]
            for z_vals in itertools.product(*discrete_variable_ranges):
                z_discrete = pd.DataFrame({k : [v] for k, v in zip(self.discrete_Z, z_vals)})
                if self.continuous_Z:
                    continuous_Z_ranges = [self.support[variable] for variable in self.continuous_Z]
                    args = z_discrete.join(x).values[0]
                    causal_effect += nquad(self.expectation_integration_function,continuous_Z_ranges,args=args)[0]
                else:
                    z_discrete = z_discrete[self.admissable_set]
                    exog_predictors = x.join(z_discrete)[self.conditional_density_vars]
                    causal_effect += self.conditional_expectation.fit(data_predict=exog_predictors.values)[0] * self.density.pdf(data_predict=z_discrete.values)
            return causal_effect
        elif self.continuous_Z:
            continuous_Z_ranges = [self.support[var] for var in self.continuous_Z]
            causal_effect = nquad(self.expectation_integration_function,continuous_Z_ranges,args=tuple(x.values[0]))[0]
            return causal_effect
        else:
            return self.conditional_expectation.fit(data_predict=x[self.causes])[0]
       


if __name__ == "__main__":
        import numpy.random as npr
        import matplotlib.pyplot as pp
        """
        generate some toy data where a -> b, a-> c, b -> d, and c doesn't effect d.
        find the effect of c on d.
        """

        n = 1000
        a = npr.beta(2.5, 2.5, n)
        b = npr.binomial( 1000, a)
        c = npr.binomial( 1000, a)
        d = 5. * b + 2. * c
        X = pd.DataFrame( { 'a' : a, 'b' : b, 'c' : c, 'd' : d})   
        causes = ['c']
        effects = ['d']
        admissable_set = ['a']
        variable_types={'a': 'c','b': 'c','c': 'c','d' : 'c'}
        conditional_density_vars = causes + admissable_set

        effect = CausalEffect(X,causes,effects,admissable_set,variable_types,expectation=True)
        pp.plot( xrange(400,601,50), [effect.expected_value(pd.DataFrame({'c' : [xi]})) for xi in xrange(400,601,50)])
        pp.xlabel( 'c' )
        pp.ylabel( 'd' )
        pp.title( 'c on d controlling a: slope = 2')
        pp.show()  

        n = 1000
        a = npr.beta(2.5, 2.5, n)
        b = npr.binomial( 1000, a)
        c = npr.binomial( 1000, a)
        d = 5. * b + 2. * c
        X = pd.DataFrame( { 'a' : a, 'b' : b, 'c' : c, 'd' : d})   
        causes = ['c']
        effects = ['d']
        admissable_set = []
        variable_types={'a': 'c','b': 'c','c': 'c','d' : 'c'}
        conditional_density_vars = causes + admissable_set

        effect = CausalEffect(X,causes,effects,admissable_set,variable_types,expectation=True)
        pp.plot( xrange(400,601,50), [effect.expected_value(pd.DataFrame({'c' : [xi]})) for xi in xrange(400,601,50)])
        pp.xlabel( 'c' )
        pp.ylabel( 'd' )
        pp.title( 'c on d not controlling a')
        pp.show()  



 

    
