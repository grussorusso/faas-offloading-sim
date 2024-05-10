SEC_CONTAINER = "container"
EXPIRATION_TIMEOUT = "expiration-timeout"

SEC_SIM = "simulation"
SEED = "seed"
CLOSE_DOOR_TIME = "close-door-time"
PLOT_RESP_TIMES = "plot-rt"
STAT_PRINT_INTERVAL = "stats-print-interval"
STAT_PRINT_FILE = "stats-print-file"
PRINT_FINAL_STATS = "print-final-stats"
SPEC_FILE = "spec-file"
EDGE_NEIGHBORS = "edge-neighbors"
EDGE_EXPOSED_FRACTION = "edge-exposed-fraction"
RESP_TIMES_FILE = "resp-times-file"
VERBOSITY = "verbosity"
RATE_UPDATE_INTERVAL = "rate-update-interval"

SEC_POLICY = "policy"
POLICY_NAME = "name"
POLICY_UPDATE_INTERVAL = "update-interval"
POLICY_ARRIVAL_RATE_ALPHA = "arrival-alpha"
ADAPTIVE_LOCAL_MEMORY = "adaptive-local-memory"
EDGE_OFFLOADING_ENABLED = "edge-offloading-enabled"
LOCAL_COLD_START_EST_STRATEGY = "local-cold-start-estimation"
CLOUD_COLD_START_EST_STRATEGY = "cloud-cold-start-estimation"
EDGE_COLD_START_EST_STRATEGY = "edge-cold-start-estimation"
HOURLY_BUDGET = "budget"
QOS_OPTIMIZER = "optimizer"
SPLIT_BUDGET_AMONG_EDGE_NODES = "split-budget-edge"
MULTIPLE_OFFLOADING_ALLOWED = "multiple-offloading-allowed"
FALLBACK_ON_LOCAL_REJECTION = "local-rejection-fallback"
NONLINEAR_OPT_ALGORITHM = "nonlinear-optimization-alg"
NONLINEAR_USE_LP_FOR_BOUNDS = "nonlinear-use-lp-for-bounds"
NONLINEAR_APPROXIMATE_BLOCKING = "nonlinear-approximate-blocking"
ITERATED_LP_MAX_PBLOCK = "iterated-lp-max-pblock"


SEC_STATEFUL = "stateful"

import configparser

def parse_config_file(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    return config
