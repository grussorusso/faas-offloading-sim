import json
import conf

class Stats:

    def __init__ (self, sim, functions, classes, infra):
        self.sim = sim
        self.infra = infra
        self.functions = functions
        self.classes = classes
        self.nodes = infra.get_nodes()
        fun_classes = [(f,c) for f in functions for c in classes]
        fcn = [(f,c,n) for f in functions for c in classes for n in self.nodes]
        
        self.arrivals = {x: 0 for x in fcn}
        self.ext_arrivals = {x: 0 for x in fcn}
        self.offloaded = {x: 0 for x in fcn}
        self.dropped_reqs = {c: 0 for c in fcn}
        self.dropped_offloaded = {c: 0 for c in fcn}
        self.completions = {x: 0 for x in fcn}
        self.violations = {c: 0 for c in fcn}
        self.resp_time_sum = {c: 0.0 for c in fcn}
        self.cold_starts = {(f,n): 0 for f in functions for n in self.nodes}
        self.execution_time_sum = {(f,n): 0 for f in functions for n in self.nodes}
        self.node2completions = {(f,n): 0 for n in self.nodes for f in functions}
        self.cost = 0.0
        self.raw_utility = 0.0
        self.utility = 0.0
        self.utility_detail = {x: 0.0 for x in fcn}
        self.penalty = 0.0
        self.optimizer_obj_value = {x: 0.0 for x in self.nodes}
        self._memory_usage_area = {x: 0.0 for x in self.nodes}
        self._memory_usage_t0 = {x: 0.0 for x in self.nodes}
        self._policy_update_time_sum = {x: 0.0 for x in self.nodes}
        self._policy_updates = {x: 0 for x in self.nodes}
        self.rejected_requests = 0

        self.budget = self.sim.config.getfloat(conf.SEC_POLICY, conf.HOURLY_BUDGET, fallback=-1.0)

    def to_dict (self):
        stats = {}
        raw = vars(self)
        for metric in raw:
            t = type(raw[metric])
            if t is float or t is int:
                # no change required
                stats[metric] = raw[metric]
            elif t is dict:
                # replace with a new dict, w reformatted keys
                new_metric = {repr(x): raw[metric][x] for x in raw[metric]}
                stats[metric] = new_metric

        avg_rt = {repr(x): self.resp_time_sum[x]/self.completions[x] for x in self.completions if self.completions[x] > 0}
        stats["avgRT"] = avg_rt

        avg_exec = {repr(x): self.execution_time_sum[x]/self.node2completions[x] for x in self.node2completions if self.node2completions[x] > 0}
        stats["avgExecTime"] = avg_exec

        completed_perc = {repr(x): self.completions[x]/self.arrivals[x] for x in self.completions if self.arrivals[x] > 0}
        stats["completedPercentage"] = completed_perc

        violations_perc = {repr(x): self.violations[x]/self.completions[x] for x in self.completions if self.completions[x] > 0}
        stats["violationsPercentage"] = violations_perc

        cold_start_prob = {repr(x): self.cold_starts[x]/self.node2completions[x] for x in self.node2completions if self.node2completions[x] > 0}
        stats["coldStartProb"] = cold_start_prob

        class_completions = {}
        class_rt = {}
        for c in self.classes:
            class_completions[repr(c)] = sum([self.completions[(f,c,n)] for f in self.functions for n in self.infra.get_nodes() if c in self.classes])
            if class_completions[repr(c)] == 0:
                continue
            rt_sum = sum([self.resp_time_sum[(f,c,n)] for f in self.functions for n in self.infra.get_nodes()])
            class_rt[repr(c)] = rt_sum/class_completions[repr(c)]
        stats["perClassCompleted"] = class_completions
        stats["perClassAvgRT"] = class_rt

        stats["budgetExceededPercentage"] = max(0, (self.cost-self.budget)/self.budget)

        stats["_Time"] = self.sim.t

        avgMemUtil = {}
        for n in self._memory_usage_t0:
            avgMemUtil[repr(n)] = self._memory_usage_area[n]/self.sim.t/n.total_memory
        stats["avgMemoryUtilization"] = avgMemUtil

        avg_policy_upd_time = {}
        for n in self._policy_update_time_sum:
            if self._policy_updates[n] > 0:
                avg_policy_upd_time[repr(n)] = self._policy_update_time_sum[n]/self._policy_updates[n]
        stats["avgPolicyUpdateTime"] = avg_policy_upd_time


        return stats
    
    def update_memory_usage (self, node, t):
        used_mem = node.total_memory-node.curr_memory
        self._memory_usage_area[node] += used_mem*(t-self._memory_usage_t0[node])
        self._memory_usage_t0[node] = t

    def update_policy_upd_time (self, node, t):
        self._policy_update_time_sum[node] += t
        self._policy_updates[node] += 1

    def print (self, out_file):
        print(json.dumps(self.to_dict(), indent=4, sort_keys=True), file=out_file)
