from activation_functions import softmax_function
from cost_functions import softmax_cross_entropy_cost
from tools import dropout, add_bias, confirm
import numpy as np
import collections
import math

default_settings = {
    # Optional settings
    "weights_low"           : -0.1,     # Lower bound on initial weight range
    "weights_high"          : 0.1,      # Upper bound on initial weight range
    "save_trained_network"  : False,    # Whether to write the trained weights to disk
    
    "input_layer_dropout"   : 0.0,      # dropout fraction of the input layer
    "hidden_layer_dropout"  : 0.0,      # dropout fraction in all hidden layers
}

class NeuralNet:
    def __init__(self, settings ):
        self.__dict__.update( default_settings )
        self.__dict__.update( settings )
        
        assert not softmax_function in map(lambda (n_nodes, actfunc): actfunc, self.layers[:-1]),\
            "The softmax function can only be applied to the final layer in the network."
        
        assert not self.cost_function == softmax_cross_entropy_cost or self.layers[-1][1] == softmax_function,\
            "The `softmax_cross_entropy_cost` cost function can only be used in combination with the softmax activation function."
        
        assert not self.layers[-1][1] == softmax_function or self.cost_function == softmax_cross_entropy_cost,\
             "The current implementation of the softmax activation function require the cost function to be `softmax_cross_entropy_cost`."
        
        # Count the required number of weights. This will speed up the random number generation phase
        self.n_weights = (self.n_inputs + 1) * self.layers[0][0] +\
                         sum( (self.layers[i][0] + 1) * layer[0] for i, layer in enumerate( self.layers[1:] ) )
        
        # Initialize the network with new randomized weights
        self.set_weights( self.generate_weights( self.weights_low, self.weights_high ) )
        
        for i in xrange(len(self.weights)):
            self.weights[ i ][0,:] = 1.0
    #end
    
    
    def generate_weights(self, low = -0.1, high = 0.1):
        # Generate new random weights for all the connections in the network
        return np.random.uniform(low, high, size=(self.n_weights,))
    #end
    
    
    def unpack(self, weight_list ):
        # This method will create a list of weight matrices. Each list element
        # corresponds to the connection between two layers.
        
        start, stop     = 0, 0
        weight_layers   = [ ]
        previous_shape  = self.n_inputs + 1
        
        for n_neurons, activation_function in self.layers:
            stop += previous_shape * n_neurons
            weight_layers.append( weight_list[ start:stop ].reshape( previous_shape, n_neurons ))
            
            previous_shape = n_neurons + 1
            start = stop
        
        return weight_layers
    #end
    
    
    def set_weights(self, weight_list ):
        # This is a helper method for setting the network weights to a previously defined list.
        # This is useful for utilizing a previously optimized neural network weight set.
        self.weights = self.unpack( weight_list )
    #end
    
    
    def get_weights(self, ):
        # This will stack all the weights in the network on a list, which may be saved to the disk.
        return [w for l in self.weights for w in l.flat]
    #end
    
    def backpropagation(self, trainingset, ERROR_LIMIT = 1e-3, learning_rate = 0.03, momentum_factor = 0.9, max_iterations = ()  ):
        
        assert trainingset[0].features.shape[0] == self.n_inputs, \
                "ERROR: input size varies from the defined input setting"
        
        assert trainingset[0].targets.shape[0]  == self.layers[-1][0], \
                "ERROR: output size varies from the defined output setting"
        
        
        training_data              = np.array( [instance.features for instance in trainingset ] )
        training_targets           = np.array( [instance.targets  for instance in trainingset ] )
                                
        layer_indexes              = range( len(self.layers) )[::-1]    # reversed
        momentum                   = collections.defaultdict( int )
        epoch                      = 0
        
        input_signals, derivatives = self.update( training_data, trace=True )
        
        out                        = input_signals[-1]
        error                      = self.cost_function(out, training_targets )
        cost_derivative            = self.cost_function(out, training_targets, derivative=True).T
        delta                      = cost_derivative * derivatives[-1]
        
        while error > ERROR_LIMIT and epoch < max_iterations:
            epoch += 1
            
            for i in layer_indexes:
                # Loop over the weight layers in reversed order to calculate the deltas
                
                # perform dropout
                dropped = dropout( 
                            input_signals[i], 
                            # dropout probability
                            self.hidden_layer_dropout if i > 0 else self.input_layer_dropout
                        )
                
                # calculate the weight change
                dW = -learning_rate * np.dot( delta, add_bias(dropped) ).T + momentum_factor * momentum[i]
                
                if i != 0:
                    """Do not calculate the delta unnecessarily."""
                    # Skip the bias weight
                    weight_delta = np.dot( self.weights[ i ][1:,:], delta )
        
                    # Calculate the delta for the subsequent layer
                    delta = weight_delta * derivatives[i-1]
                
                # Store the momentum
                momentum[i] = dW
                                    
                # Update the weights
                self.weights[ i ] += dW
            #end weight adjustment loop
            
            input_signals, derivatives = self.update( training_data, trace=True )
            out                        = input_signals[-1]
            error                      = self.cost_function(out, training_targets )
            cost_derivative            = self.cost_function(out, training_targets, derivative=True).T
            delta                      = cost_derivative * derivatives[-1]
            
            
            if epoch%1000==0:
                # Show the current training status
                print "[training] Current error:", error, "\tEpoch:", epoch
        
        print "[training] Finished:"
        print "[training]   Converged to error bound (%.4g) with error %.4g." % ( ERROR_LIMIT, error )
        print "[training]   Trained for %d epochs." % epoch
        
        if self.save_trained_network and confirm( promt = "Do you wish to store the trained network?" ):
            self.save_to_file()
    # end backprop
    
    def resilient_backpropagation(self, trainingset, ERROR_LIMIT=1e-3, max_iterations = (), weight_step_max = 50., weight_step_min = 0., start_step = 0.5, learn_max = 1.2, learn_min = 0.5 ):
        # Implemented according to iRprop+ 
        # http://sci2s.ugr.es/keel/pdf/algorithm/articulo/2003-Neuro-Igel-IRprop+.pdf
        assert self.input_layer_dropout == 0 and self.hidden_layer_dropout == 0, \
                "ERROR: dropout should not be used with resilient backpropagation"
        
        assert trainingset[0].features.shape[0] == self.n_inputs, \
                "ERROR: input size varies from the defined input setting"
        
        assert trainingset[0].targets.shape[0]  == self.layers[-1][0], \
                "ERROR: output size varies from the defined output setting"
        
        training_data              = np.array( [instance.features for instance in trainingset ] )
        training_targets           = np.array( [instance.targets  for instance in trainingset ] )
        
        # Data structure to store the previous derivative
        previous_dEdW                  = [ 1 ] * len( self.weights )
        
        # Storing the current / previous weight step size
        weight_step                = [ np.full( weight_layer.shape, start_step ) for weight_layer in self.weights ]
        
        # Storing the current / previous weight update
        dW                         = [  np.ones(shape=weight_layer.shape) for weight_layer in self.weights ]
        
        
        input_signals, derivatives = self.update( training_data, trace=True )
        out                        = input_signals[-1]
        cost_derivative            = self.cost_function(out, training_targets, derivative=True).T
        delta                      = cost_derivative * derivatives[-1]
        error                      = self.cost_function(out, training_targets )
        
        layer_indexes              = range( len(self.layers) )[::-1] # reversed
        prev_error                   = ( )                             # inf
        epoch                      = 0
        
        while error > ERROR_LIMIT and epoch < max_iterations:
            epoch       += 1
            
            for i in layer_indexes:
                # Loop over the weight layers in reversed order to calculate the deltas
                       
                # Calculate the delta with respect to the weights
                dEdW = np.dot( delta, add_bias(input_signals[i]) ).T
                
                if i != 0:
                    """Do not calculate the delta unnecessarily."""
                    # Skip the bias weight
                    weight_delta = np.dot( self.weights[ i ][1:,:], delta )
        
                    # Calculate the delta for the subsequent layer
                    delta = weight_delta * derivatives[i-1]
                
                
                # Calculate sign changes and note where they have changed
                diffs            = np.multiply( dEdW, previous_dEdW[i] )
                pos_indexes      = np.where( diffs > 0 )
                neg_indexes      = np.where( diffs < 0 )
                zero_indexes     = np.where( diffs == 0 )
                
                
                # positive
                if np.any(pos_indexes):
                    # Calculate the weight step size
                    weight_step[i][pos_indexes] = np.minimum( weight_step[i][pos_indexes] * learn_max, weight_step_max )
                    
                    # Calculate the weight step direction
                    dW[i][pos_indexes] = np.multiply( -np.sign( dEdW[pos_indexes] ), weight_step[i][pos_indexes] )
                    
                    # Apply the weight deltas
                    self.weights[i][ pos_indexes ] += dW[i][pos_indexes]
                
                # negative
                if np.any(neg_indexes):
                    weight_step[i][neg_indexes] = np.maximum( weight_step[i][neg_indexes] * learn_min, weight_step_min )
                    
                    if error > prev_error:
                        # iRprop+ version of resilient backpropagation
                        self.weights[i][ neg_indexes ] -= dW[i][neg_indexes] # backtrack
                    
                    dEdW[ neg_indexes ] = 0
                
                # zeros
                if np.any(zero_indexes):
                    dW[i][zero_indexes] = np.multiply( -np.sign( dEdW[zero_indexes] ), weight_step[i][zero_indexes] )
                    self.weights[i][ zero_indexes ] += dW[i][zero_indexes]
                
                # Store the previous weight step
                previous_dEdW[i] = dEdW
            #end weight adjustment loop
            
            prev_error                 = error
            
            input_signals, derivatives = self.update( training_data, trace=True )
            out                        = input_signals[-1]
            cost_derivative            = self.cost_function(out, training_targets, derivative=True).T
            delta                      = cost_derivative * derivatives[-1]
            error                      = self.cost_function(out, training_targets )
            
            if epoch%1000==0:
                # Show the current training status
                print "[training] Current error:", error, "\tEpoch:", epoch
    
        print "[training] Finished:"
        print "[training]   Converged to error bound (%.4g) with error %.4g." % ( ERROR_LIMIT, error )
        print "[training]   Trained for %d epochs." % epoch
        
        if self.save_trained_network and confirm( promt = "Do you wish to store the trained network?" ):
            self.save_to_file()
    # end backprop
    
    def error(self, weight_vector, training_data, training_targets ):
        self.weights = self.unpack( np.array(weight_vector) )
        out          = self.update( training_data )
        
        return self.cost_function(out, training_targets )
    #end
    
    def gradient(self, weight_vector, training_data, training_targets ):
        layer_indexes              = range( len(self.layers) )[::-1]    # reversed
        self.weights               = self.unpack( np.array(weight_vector) )
        input_signals, derivatives = self.update( training_data, trace=True )
        
        out                        = input_signals[-1]
        cost_derivative            = self.cost_function(out, training_targets, derivative=True).T
        delta                      = cost_derivative * derivatives[-1]
        error                      = self.cost_function(out, training_targets )
        
        layers = []
        for i in layer_indexes:
            # Loop over the weight layers in reversed order to calculate the deltas
            
            # calculate the weight change
            dropped = dropout( 
                        input_signals[i], 
                        # dropout probability
                        self.hidden_layer_dropout if i > 0 else self.input_layer_dropout
                    )
                    
            layers.append(np.dot( delta, add_bias(dropped) ).T.flat)
            
            if i!= 0:
                """Do not calculate the delta unnecessarily."""
                # Skip the bias weight
                weight_delta = np.dot( self.weights[ i ][1:,:], delta )
    
                # Calculate the delta for the subsequent layer
                delta = weight_delta * derivatives[i-1]
        #end weight adjustment loop
        
        return np.hstack( reversed(layers) )
    # end gradient
    
    def scipyoptimize(self, trainingset, method = "Newton-CG", ERROR_LIMIT = 1e-6, max_iterations = ()  ):
        from scipy.optimize import minimize
        
        training_data        = np.array( [instance.features for instance in trainingset ] )
        training_targets     = np.array( [instance.targets  for instance in trainingset ] )
        minimization_options = {}
        
        if max_iterations < ():
            minimization_options["maxiter"] = max_iterations
            
        results = minimize( 
            self.error,                                     # The function we are minimizing
            self.get_weights(),                             # The vector (parameters) we are minimizing
            args    = (training_data, training_targets),    # Additional arguments to the error and gradient function
            method  = method,                               # The minimization strategy specified by the user
            jac     = self.gradient,                        # The gradient calculating function
            tol     = ERROR_LIMIT,                          # The error limit
            options = minimization_options,                 # Additional options
        )
        
        self.weights = self.unpack( results.x )
        
        
        if not results.success:
            print "[training] WARNING:", results.message
            print "[training]   Converged to error bound (%.4g) with error %.4g." % ( ERROR_LIMIT, results.fun )
        else:
            print "[training] Finished:"
            print "[training]   Converged to error bound (%.4g) with error %.4g." % ( ERROR_LIMIT, results.fun )
            
            if self.save_trained_network and confirm( promt = "Do you wish to store the trained network?" ):
                self.save_to_file()
    #end
    
    def scg(self, trainingset, ERROR_LIMIT = 1e-6, max_iterations = () ):
        # Implemented according to the paper by Martin F. Moller
        # http://citeseer.ist.psu.edu/viewdoc/summary?doi=10.1.1.38.3391
        
        assert self.input_layer_dropout == 0 and self.hidden_layer_dropout == 0, \
                "ERROR: dropout should not be used with scaled conjugated gradients training"
                
        assert trainingset[0].features.shape[0] == self.n_inputs, \
                "ERROR: input size varies from the defined input setting"
        
        assert trainingset[0].targets.shape[0]  == self.layers[-1][0], \
                "ERROR: output size varies from the defined output setting"
        
        
        training_data       = np.array( [instance.features for instance in trainingset ] )
        training_targets    = np.array( [instance.targets  for instance in trainingset ] )
        
    
        ## Variables
        sigma0              = 1.e-6
        lamb                = 1.e-6
        lamb_               = 0
    
        vector              = self.get_weights() # The (weight) vector we will use SCG to optimalize
        N                   = len(vector)
        grad_new            = -self.gradient( vector, training_data, training_targets )
        r_new               = grad_new
        # end
    
        success             = True
        k                   = 0
        while k < max_iterations:
            k               += 1
            r               = np.copy( r_new     )
            grad            = np.copy( grad_new  )
            mu              = np.dot(  grad,grad )
        
            if success:
                success     = False
                sigma       = sigma0 / math.sqrt(mu)
                s           = (self.gradient(vector+sigma*grad, training_data, training_targets)-self.gradient(vector,training_data, training_targets))/sigma
                delta       = np.dot( grad.T, s )
            #end
        
            # scale s
            zetta           = lamb-lamb_
            s               += zetta*grad
            delta           += zetta*mu
        
            if delta < 0:
                s           += (lamb - 2*delta/mu)*grad
                lamb_       = 2*(lamb - delta/mu)
                delta       -= lamb*mu
                delta       *= -1
                lamb        = lamb_
            #end
        
            phi             = np.dot( grad.T,r )
            alpha           = phi/delta
        
            vector_new      = vector+alpha*grad
            f_old, f_new    = self.error(vector,training_data, training_targets), self.error(vector_new,training_data, training_targets)
        
            comparison      = 2 * delta * (f_old - f_new)/np.power( phi, 2 )
            
            if comparison >= 0:
                if f_new < ERROR_LIMIT: 
                    break # done!
            
                vector      = vector_new
                f_old       = f_new
                r_new       = -self.gradient( vector, training_data, training_targets )
            
                success     = True
                lamb_       = 0
            
                if k % N == 0:
                    grad_new = r_new
                else:
                    beta    = (np.dot( r_new, r_new ) - np.dot( r_new, r ))/phi
                    grad_new = r_new + beta * grad
            
                if comparison > 0.75:
                    lamb    = 0.5 * lamb
            else:
                lamb_       = lamb
            # end 
        
            if comparison < 0.25: 
                lamb        = 4 * lamb
        
            if k%1000==0:
                print "[training] Current error:", f_new, "\tEpoch:", k
        #end
        
        self.weights = self.unpack( np.array(vector_new) )
        
        print "[training] Finished:"
        print "[training]   Converged to error bound (%.4g) with error %.4g." % ( ERROR_LIMIT, f_new )
        print "[training]   Trained for %d epochs." % k
        
        
        if self.save_trained_network and confirm( promt = "Do you wish to store the trained network?" ):
            self.save_to_file()
    #end scg
    
    def update(self, input_values, trace=False ):
        # This is a forward operation in the network. This is how we 
        # calculate the network output from a set of input signals.
        output          = input_values
        
        if trace: 
            derivatives = [ ]        # collection of the derivatives of the act functions
            outputs     = [ output ] # passed through act. func.
        
        for i, weight_layer in enumerate(self.weights):
            # Loop over the network layers and calculate the output
            signal = np.dot( output, weight_layer[1:,:] ) + weight_layer[0:1,:] # implicit bias
            output = self.layers[i][1]( signal )
            
            if trace: 
                outputs.append( output )
                # Calculate the derivative, used during weight update
                derivatives.append( self.layers[i][1]( signal, derivative = True ).T )
        
        if trace: 
            return outputs, derivatives
        
        return output
    #end
    
    def print_test(self, testset ):
        test_data    = np.array( [instance.features for instance in testset ] )
        test_targets = np.array( [instance.targets  for instance in testset ] )
        
        input_signals, derivatives = self.update( test_data, trace=True )
        out                        = input_signals[-1]
        error                      = self.cost_function(out, test_targets )
        
        print "[testing] Network error: %.4g" % error
        print "[testing] Network results:"
        print "[testing]   input\tresult\ttarget"
        for entry, result, target in zip(test_data, out, test_targets):
            print "[testing]   %s\t%s\t%s" % tuple(map(str, [entry, result, target]))
    #end
    
    def save_to_file(self, filename = "network0.pkl" ):
        import cPickle, os, re
        """
        This save method pickles the parameters of the current network into a 
        binary file for persistant storage.
        """
        
        if filename == "network0.pkl":
            while os.path.exists( os.path.join(os.getcwd(), filename )):
                filename = re.sub('\d(?!\d)', lambda x: str(int(x.group(0)) + 1), filename)
        
        with open( filename , 'wb') as file:
            store_dict = {
                "cost_function"        : self.cost_function,
                "n_inputs"             : self.n_inputs,
                "layers"               : self.layers,
                "n_weights"            : self.n_weights,
                "weights"              : self.weights,
            }
            cPickle.dump( store_dict, file, 2 )
    #end
    
    @staticmethod
    def load_from_file( filename = "network.pkl" ):
        """
        Load the complete configuration of a previously stored network.
        """
        network = NeuralNet( {"n_inputs":1, "layers":[[0,None]]} )
        
        with open( filename , 'rb') as file:
            import cPickle
            store_dict                   = cPickle.load(file)
            
            network.n_inputs             = store_dict["n_inputs"]            
            network.n_weights            = store_dict["n_weights"]           
            network.layers               = store_dict["layers"]
            network.weights              = store_dict["weights"]             
            network.cost_function        = store_dict["cost_function"]
        
        return network
    #end
#end class