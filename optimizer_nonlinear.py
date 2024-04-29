import conf
import numpy as np
import math
import lp_optimizer 
from scipy.optimize import minimize, LinearConstraint
from optimization import OptProblemParams, Optimizer

class NonlinearOptimizer (Optimizer):

    def __init__ (self, initial_guess="lp", method="trust-region", verbose=False):
        super().__init__(verbose)
        self.initial_guess = initial_guess
        self.method = method

    def optimize (self, lp_probs, params, pDeadlineL, pDeadlineC, pDeadlineE):
        FC=list(params.fun_classes())
        N=len(FC)
        EDGE_ENABLED = True if params.aggregated_edge_memory > 0.0 else False
        NVARS = 3 if EDGE_ENABLED else 2


        p = np.zeros(NVARS*N)

        # Load the LP solution as the initial point
        if lp_probs is not None:
            for i,fc in enumerate(FC):
                p[NVARS*i+0] = lp_probs[fc][0]
                p[NVARS*i+1] = lp_probs[fc][1]
                if EDGE_ENABLED:
                    p[NVARS*i+2] = lp_probs[fc][2]


        def kaufman (_p):
            M = int(params.usable_local_memory_coeff*params.local_node.total_memory)
            mem_demands = [fc[0].memory for fc in FC]
            alpha = np.zeros(len(mem_demands))
            for i,fc in enumerate(FC):
                alpha[i] = params.arrival_rates[fc]*_p[NVARS*i]*params.serv_time_local[fc[0]]

            q = np.zeros(M+1)
            q[0] = 1
            for j in range(1, M+1):
                for i,m in enumerate(mem_demands):
                    if j-m < 0:
                        continue
                    q[j] += q[j-m] * m * alpha[i]
                q[j] /= j


            G = np.sum(q)

            bp_per_fun = np.zeros(len(FC))
            for i,m in enumerate(mem_demands):
                for j in range(0, m):
                    bp_per_fun[i] += q[M - j]
            bp_per_fun /= G
            return bp_per_fun



        def lp_obj (_p):
            v = 0
            for i,fc in enumerate(FC):
                f,c = fc
                gammaL = c.utility*pDeadlineL[fc] - c.deadline_penalty*(1-pDeadlineL[fc]) + c.drop_penalty
                gammaC = c.utility*pDeadlineC[fc] - c.deadline_penalty*(1-pDeadlineC[fc]) + c.drop_penalty
                gammaE = c.utility*pDeadlineE[fc] - c.deadline_penalty*(1-pDeadlineE[fc]) + c.drop_penalty
                v += params.arrival_rates[(f,c)] * (_p[NVARS*i]*gammaL + _p[NVARS*i+1]*gammaC)
                if EDGE_ENABLED:
                    v += params.arrival_rates[(f,c)] * _p[NVARS*i+2]*gammaE
            return v

        def obj (_p):
            blocking_p = kaufman(_p)
            v = 0
            for i,fc in enumerate(FC):
                f,c = fc
                gammaL = c.utility*pDeadlineL[fc] - c.deadline_penalty*(1-pDeadlineL[fc]) + c.drop_penalty
                gammaC = c.utility*pDeadlineC[fc] - c.deadline_penalty*(1-pDeadlineC[fc]) + c.drop_penalty
                gammaE = c.utility*pDeadlineE[fc] - c.deadline_penalty*(1-pDeadlineE[fc]) + c.drop_penalty
                v += params.arrival_rates[(f,c)] * (\
                        _p[NVARS*i]*(1-blocking_p[i])*gammaL +\
                        _p[NVARS*i+1]*gammaC)
                if EDGE_ENABLED:
                    v += params.arrival_rates[(f,c)] * _p[NVARS*i+2]*gammaE
            return v

        print(f"LP obj: {obj(p)} ({lp_obj(p)})")

        # sum <= 1
        A = np.zeros((N, NVARS*N))
        for i in range(N):
            A[i,NVARS*i]=1
            A[i,NVARS*i+1]=1
            if EDGE_ENABLED:
                A[i,NVARS*i+2]=1
        sumLC = LinearConstraint(A=A, lb=0, ub=1, keep_feasible=False)
        
        A2 = np.zeros(NVARS*N)
        for i,fc in enumerate(FC):
            # cloud usage
            A2[NVARS*i+1]=params.cloud.cost*params.arrival_rates[fc]*params.serv_time_cloud[fc[0]]*fc[0].memory/1024
        budgetLC = LinearConstraint(A=A2, lb=0, ub=params.budget/3600, keep_feasible=False)

        constraints = [sumLC, budgetLC]
        
        if EDGE_ENABLED:
            A3 = np.zeros(NVARS*N)
            for i,fc in enumerate(FC):
                # edge mem
                A3[NVARS*i+2]=params.arrival_rates[fc]*params.serv_time_edge[fc[0]]*fc[0].memory
            edgeMemLC = LinearConstraint(A=A3, lb=0, ub=params.aggregated_edge_memory, keep_feasible=False)
            constraints.append(edgeMemLC)

        #constraints = []
        #for i in range(N):
        #    c1 = lambda x: 1-x[3*i]-x[3*i+1]-x[3*i+2]
        #    c2 = lambda x: x[3*i]+x[3*i+1]+x[3*i+2]
        #    print(f"C1-{i}: {c1(p)}")
        #    print(c2(p))
        #    constraints.append({"type":"ineq", "fun": c1})
        #    constraints.append({"type":"ineq", "fun": c2})
        bounds = [(0,1) for i in range(NVARS*N)]

        if self.method == "trust-region":
            res = minimize(lambda x: -1*obj(x), p, method="trust-constr", bounds=bounds, constraints=constraints, tol=1e-6, options={"maxiter": 200000})
            print(res)
            x = res.x
            obj_val = -res.fun
        elif self.method == "none" or self.method is None:
            x = p 
            obj_val = obj(x)
        else:
            raise RuntimeError(f"Unknown optimization method: '{self.method}'")

        if EDGE_ENABLED:
            probs = {(fc[0],fc[1]): [x[NVARS*i], x[NVARS*i+1], x[NVARS*i+2], max(0.0,1.0-x[NVARS*i]-x[NVARS*i+1]-x[NVARS*i+2])]
                        for i,fc in enumerate(FC)}
        else:
            probs = {(fc[0],fc[1]): [x[NVARS*i], x[NVARS*i+1], 0, max(0.0,1.0-x[NVARS*i]-x[NVARS*i+1])]
                        for i,fc in enumerate(FC)}
        print(probs)
        return probs, obj_val


    def optimize_probabilities (self, params: OptProblemParams):
        F = params.functions
        C = params.classes

        pDeadlineL, pDeadlineC, pDeadlineE = lp_optimizer.compute_deadline_satisfaction_probs(params)


        if self.initial_guess == "lp":
            print("Computing initial sol")
            lp_probs, _ = lp_optimizer.LPOptimizer(verbose=False).optimize_probabilities(params)
        elif self.initial_guess == "" or self.initial_guess is None:
            lp_probs = None
        else:
            raise RuntimeError(f"Unknown initial_guess config: '{self.initial_guess}'")

        probs, obj_val = self.optimize(lp_probs, params, pDeadlineL, pDeadlineC, pDeadlineE)

        #Workaround to avoid numerical issues
        for f,c in params.fun_classes():
            s = sum(probs[(f,c)])
            probs[(f,c)] = [x/s for x in probs[(f,c)]]
            if self.verbose > 0:
                print(f"{f}-{c}: {probs[(f,c)]}")


        return probs, obj_val
