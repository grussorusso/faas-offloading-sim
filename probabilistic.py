import statistics
import numpy as np
from pacsltk import perfmodel

import conf
import optimizer, optimizer2
from policy import Policy, SchedulerDecision, ColdStartEstimation

COLD_START_PROB_INITIAL_GUESS = 0.0

class ProbabilisticPolicy(Policy):

    # Probability vector: p_e, p_o, p_d

    def __init__(self, simulation, node):
        super().__init__(simulation, node)
        cloud_region = node.region.default_cloud
        self.cloud = self.simulation.node_choice_rng.choice(self.simulation.infra.get_region_nodes(cloud_region), 1)[0]

        self.rng = self.simulation.policy_rng1
        self.stats_snapshot = None
        self.last_update_time = None
        self.arrival_rate_alpha = self.simulation.config.getfloat(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA,
                                                                  fallback=1.0)
        self.local_cold_start_estimation = ColdStartEstimation(self.simulation.config.get(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, fallback=ColdStartEstimation.NAIVE))
        self.cloud_cold_start_estimation = ColdStartEstimation(self.simulation.config.get(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, fallback=ColdStartEstimation.NAIVE))
        self.edge_cold_start_estimation = ColdStartEstimation(self.simulation.config.get(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY, fallback=ColdStartEstimation.NAIVE))

        self.arrival_rates = {}
        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}
        self.cold_start_prob_local = {}
        self.cold_start_prob_cloud = {}
        self.cloud_rtt = 0.0
        self.rt_percentile = self.simulation.config.getfloat(conf.SEC_POLICY, "rt-percentile", fallback=-1.0)

        self.possible_decisions = [SchedulerDecision.EXEC, SchedulerDecision.OFFLOAD_CLOUD, SchedulerDecision.DROP]
        self.probs = {(f, c): [0.8, 0.2, 0.] for f in simulation.functions for c in simulation.classes}

    def schedule(self, f, c, offloaded_from):
        probabilities = self.probs[(f, c)]
        decision = self.rng.choice(self.possible_decisions, p=probabilities)
        if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
            nolocal_prob = sum(probabilities[1:])
            if nolocal_prob > 0.0:
                decision = self.rng.choice([SchedulerDecision.OFFLOAD_CLOUD, SchedulerDecision.DROP],
                                           p=[probabilities[1] / nolocal_prob, probabilities[2] / nolocal_prob])
            else:
                decision = SchedulerDecision.OFFLOAD_CLOUD

        return decision

    def update(self):
        self.update_metrics()
        self.update_probabilities()

        self.stats_snapshot = self.simulation.stats.to_dict()
        self.last_update_time = self.simulation.t

    def update_metrics (self):
        stats = self.simulation.stats

        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}
        for f in self.simulation.functions:
            if stats.node2completions[(f, self.node)] > 0:
                self.estimated_service_time[f] = stats.execution_time_sum[(f, self.node)] / \
                                            stats.node2completions[(f, self.node)]
            else:
                self.estimated_service_time[f] = 0.1
            if stats.node2completions[(f, self.cloud)] > 0:
                self.estimated_service_time_cloud[f] = stats.execution_time_sum[(f, self.cloud)] / \
                                                  stats.node2completions[(f, self.cloud)]
            else:
                self.estimated_service_time_cloud[f] = 0.1

        if self.stats_snapshot is not None:
            arrival_rates = {}
            for f, c, n in stats.arrivals:
                if n != self.node:
                    continue
                new_arrivals = stats.arrivals[(f, c, self.node)] - self.stats_snapshot["arrivals"][repr((f, c, n))]
                new_rate = new_arrivals / (self.simulation.t - self.last_update_time)
                self.arrival_rates[(f, c)] = self.arrival_rate_alpha * new_rate + \
                                             (1.0 - self.arrival_rate_alpha) * self.arrival_rates[(f, c)]
        else:
            for f, c, n in stats.arrivals:
                if n != self.node:
                    continue
                self.arrival_rates[(f, c)] = stats.arrivals[(f, c, self.node)] / self.simulation.t

        self.estimate_cold_start_prob(stats)

        print(f"[{self.node}] Arrivals: {self.arrival_rates}")

        self.cloud_rtt = 2 * self.simulation.infra.get_latency(self.node, self.cloud)

    def estimate_cold_start_prob (self, stats):
        #
        # LOCAL NODE
        #
        if self.local_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, sum([self.arrival_rates.get((f,x), 0.0) for x in self.simulation.classes]))
                # XXX: we are ignoring initial warm pool....
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time[f],
                                                            self.estimated_service_time[f] + self.simulation.init_time[self.node],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob_local[f] = props1["cold_prob"]
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.node)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.node)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob_local[f] = node_cs / node_compl
                else:
                    self.cold_start_prob_local[f] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.node), 0) > 0:
                    self.cold_start_prob_local[f] = stats.cold_starts.get((f,self.node),0) / stats.node2completions.get((f,self.node),0)
                else:
                    self.cold_start_prob_local[f] = COLD_START_PROB_INITIAL_GUESS
        else: # No
            for f in self.simulation.functions:
                self.cold_start_prob_local[f] = 0

        # CLOUD
        #
        if self.cloud_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, \
                        sum([self.arrival_rates.get((f,x), 0.0)*self.probs[(f,x)][1] for x in self.simulation.classes]))
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time_cloud[f],
                                                            self.estimated_service_time_cloud[f] + self.simulation.init_time[self.node],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob_cloud[f] = props1["cold_prob"]
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.cloud)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.cloud)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob_cloud[f] = node_cs / node_compl
                else:
                    self.cold_start_prob_cloud[f] = COLD_START_PROB_INITIAL_GUESS
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.cloud), 0) > 0:
                    self.cold_start_prob_cloud[f] = stats.cold_starts.get((f,self.cloud),0) / stats.node2completions.get((f,self.cloud),0)
                else:
                    self.cold_start_prob_cloud[f] = COLD_START_PROB_INITIAL_GUESS
        else: # No
            for f in self.simulation.functions:
                self.cold_start_prob_cloud[f] = 0

        print(f"[{self.node}] Cold start prob: {self.cold_start_prob_local}")
        print(f"[{self.cloud}] Cold start prob: {self.cold_start_prob_cloud}")

    def update_probabilities (self):
        new_probs = optimizer.update_probabilities(self.node, self.cloud,
                                                   self.simulation,
                                                   self.arrival_rates,
                                                   self.estimated_service_time,
                                                   self.estimated_service_time_cloud,
                                                   self.simulation.init_time[self.node],
                                                   self.cloud_rtt,
                                                   self.cold_start_prob_local,
                                                   self.cold_start_prob_cloud,
                                                   self.rt_percentile)
        if new_probs is not None:
            self.probs = new_probs
            print(f"[{self.node}] Probs: {self.probs}")


class ProbabilisticPolicy2 (ProbabilisticPolicy):

    # Probability vector: p_L, p_C, p_E, p_D
    # LP Model v2

    def __init__(self, simulation, node):
        super().__init__(simulation, node)

        self.aggregated_edge_memory = 0.0
        self.estimated_service_time_edge = {}
        self.edge_rtt = 0.0
        self.cold_start_prob_edge = {}

        self.possible_decisions = list(SchedulerDecision)
        self.probs = {(f, c): [0.8, 0.2, 0., 0.] for f in simulation.functions for c in simulation.classes}

    def schedule(self, f, c, offloaded_from):
        probabilities = self.probs[(f, c)].copy()
        
        # If the request has already been offloaded, cannot offload again to
        # Edge
        if len(offloaded_from) > 0: 
            probabilities[SchedulerDecision.OFFLOAD_EDGE.value-1] = 0
            s = sum(probabilities)
            if not s > 0.0:
                return SchedulerDecision.OFFLOAD_CLOUD
            probabilities = [x/s for x in probabilities]
        if not self.can_execute_locally(f):
            probabilities[SchedulerDecision.EXEC.value-1] = 0
            s = sum(probabilities)
            if not s > 0.0:
                return SchedulerDecision.OFFLOAD_CLOUD
            probabilities = [x/s for x in probabilities]

        return self.rng.choice(self.possible_decisions, p=probabilities)

    def update_metrics(self):
        super().update_metrics()
        stats = self.simulation.stats

        neighbors = self.simulation.infra.get_neighbors(self.node, self.simulation.node_choice_rng, self.simulation.max_neighbors)
        exposed_fraction = self.simulation.config.getfloat(conf.SEC_SIM, conf.EDGE_EXPOSED_FRACTION, fallback=0.25)
        if len(neighbors) == 0:
            self.aggregated_edge_memory = 1
        else:
            self.aggregated_edge_memory = max(1,sum([x.curr_memory*exposed_fraction for x in neighbors]))
        
        neighbor_probs = [x.curr_memory*exposed_fraction/self.aggregated_edge_memory for x in neighbors]

        self.edge_rtt = sum([self.simulation.infra.get_latency(self.node, x)*prob for x,prob in zip(neighbors, neighbor_probs)])

        self.estimated_service_time_edge = {}
        for f in self.simulation.functions:
            servtime = 0.0
            for neighbor, prob in zip(neighbors, neighbor_probs):
                if stats.node2completions[(f, neighbor)] > 0:
                    servtime += prob* stats.execution_time_sum[(f, neighbor)] / stats.node2completions[(f, neighbor)]
            if servtime == 0.0:
                servtime = self.estimated_service_time[f]
            self.estimated_service_time_edge[f] = servtime

        self.estimate_edge_cold_start_prob(stats, neighbors, neighbor_probs)

    def estimate_edge_cold_start_prob (self, stats, neighbors, neighbor_probs):
        # TODO: Here we are using istantaneous info to estimate cold start probs
        for fun in self.simulation.functions:
            cs_prob = 0.0
            for neighbor, prob in zip(neighbors, neighbor_probs):
                if not fun in neighbor.warm_pool:
                    cs_prob += prob * 0.2 # TODO: magic number 20% prob if currently no warm
            self.cold_start_prob_edge[fun] = cs_prob


    def update_probabilities(self):
        new_probs = optimizer2.update_probabilities(self.node, self.cloud,
                                                   self.aggregated_edge_memory,
                                                   self.simulation,
                                                   self.arrival_rates,
                                                   self.estimated_service_time,
                                                   self.estimated_service_time_cloud,
                                                   self.estimated_service_time_edge,
                                                   self.simulation.init_time[self.node],
                                                   self.cloud_rtt,
                                                   self.edge_rtt,
                                                   self.cold_start_prob_local,
                                                   self.cold_start_prob_cloud,
                                                   self.cold_start_prob_edge)
        if new_probs is not None:
            self.probs = new_probs
            print(f"[{self.node}] Probs: {self.probs}")



class RandomPolicy(Policy):

    def __init__(self, simulation, node):
        super().__init__(simulation, node)
        self.rng = self.simulation.policy_rng1

    def schedule(self, f, c, offloaded_from):
        return self.rng.choice(list(SchedulerDecision))

    def update(self):
        pass

