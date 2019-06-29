import argparse

from rl import Runner, TrajectoryBuffer, create_env
from rl import Reinforce, QLearning, ActorCritic, PPO, MultiPPO

from google.cloud import storage

import torch

BUCKET = 'rl-1'


def main(**args):
    envs_count = args['env_count']
    env = create_env(args['env'], envs_count)

    iterations = args['iterations']
    training_steps = args['steps']
    evaluation_steps = args['eval_steps']
    gcp = args['gcp']

    sess = args['sess']
    sess += '-' + args['agent']
    sess_options = [
            'double', 'priority', 'dueling',
            'noisy', 'soft', 'baseline']
    for opt in sess_options:
        if args[opt]:
            sess += '-' + opt

    action_space = env.action_space
    observation_shape = env.observation_space.shape

    bucket = None
    if gcp:
        client = storage.Client()
        bucket = client.get_bucket(BUCKET)

    ref_net = args['ref_net']
    if ref_net is not None:
        if not ref_net.endswith(".pth"):
            ref_net += ".pth"
        ref_net = "checkpoints/{}".format(ref_net)

        if gcp:
            blob = storage.Blob(ref_net, bucket)
            with open(ref_net, "wb") as f:
                blob.download_to_file(f)
        print("Loading ref_net from {}".format(ref_net))
        ref_net = torch.load(ref_net, map_location='cpu')

    agent_type = args["agent"]
    baseline = args["baseline"]
    baseline_learning_rate = args["baseline_learning_rate"]
    gamma = args["gamma"]
    learning_rate = args["learning_rate"]

    if agent_type == "qlearning":
        agent = QLearning(
                action_size=action_space.n,
                observation_shape=observation_shape,
                beta_decay=(iterations * training_steps),
                ref_net=ref_net,
                gamma=gamma,
                learning_rate=learning_rate,
                soft=args["soft"],
                dueling=args["dueling"],
                double=args["double"],
                noisy=args["noisy"],
                priority=args["priority"],
                replay_buffer_size=args["replay_buffer_size"],
                min_replay_buffer_size=args["min_replay_buffer_size"],
                target_update_freq=args["target_update_freq"],
                train_freq=args["train_freq"],
                tau=args["tau"],
                batch_size=args["batch_size"],
                epsilon_start=args["epsilon_start"],
                epsilon_end=args["epsilon_end"],
                epsilon_decay=args["epsilon_decay"])
    elif agent_type == "reinforce":
        agent = Reinforce(
                action_size=action_space.n,
                observation_shape=observation_shape,
                gamma=gamma,
                learning_rate=learning_rate,
                baseline=baseline,
                baseline_learning_rate=baseline_learning_rate)
    elif agent_type == "actor-critic":
        agent = ActorCritic(
                action_size=action_space.n,
                observation_shape=observation_shape,
                gamma=gamma,
                learning_rate=learning_rate)
    elif agent_type == "ppo":
        agent = PPO(
                action_space=action_space,
                observation_shape=observation_shape,
                n_agents=envs_count,
                gamma=gamma,
                horizon=args["horizon"],
                epochs=args["ppo_epochs"],
                gae_lambda=args["gae_lambda"],
                learning_rate=learning_rate)
    elif agent_type == 'multippo':
        agent = MultiPPO(
                action_space=action_space,
                observation_shape=observation_shape,
                n_agents=envs_count,
                gamma=gamma,
                horizon=args["horizon"],
                epochs=args["ppo_epochs"],
                gae_lambda=args["gae_lambda"],
                learning_rate=learning_rate)

    traj_buffer = None
    if args["save_traj"]:
        traj_buffer = TrajectoryBuffer(
                observation_shape=observation_shape,
                action_space=action_space)
        print("Saving trajectories is enabled")

    runner = Runner(
            env,
            agent,
            sess,
            bucket=bucket,
            traj_buffer=traj_buffer,
            num_iterations=iterations,
            training_steps=training_steps,
            evaluation_steps=evaluation_steps)
    runner.run_experiment()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--sess", type=str)
    parser.add_argument("--env", type=str)
    parser.add_argument("--env_count", type=int, default=1)
    parser.add_argument("--agent", type=str, default="qlearning",
            help="qlearning|reinforce|actor-critic")
    parser.add_argument("--dueling", action="store_true")
    parser.add_argument("--double", action="store_true")
    parser.add_argument("--noisy", action="store_true",
            help="Enables noisy network")
    parser.add_argument("--priority", action="store_true",
            help="Enables prioritirized replay buffer")
    parser.add_argument("--soft", action="store_true",
            help="Enables soft update of target network")
    parser.add_argument("--baseline", action="store_true",
            help="Enables baseline for the REINFORCE agent.")
    parser.add_argument("--epsilon_decay", type=int, default=3000)
    parser.add_argument("--steps", type=int, default=100,
            help="Number of steps for training phase in one iteration")
    parser.add_argument("--eval_steps", type=int, default=100,
            help="Number of steps for evaluation phase in one iteration")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--target_update_freq", type=int, default=100,
            help="Update target network each N steps")
    parser.add_argument("--epsilon_start", type=float, default=0.5)
    parser.add_argument("--epsilon_end", type=float, default=0.01)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--learning_rate", type=float, default=0.0001)
    parser.add_argument("--baseline_learning_rate", type=float, default=0.0001)
    parser.add_argument("--replay_buffer_size", type=int, default=100000,
            help="Maximum size of the replay buffer")
    parser.add_argument("--min_replay_buffer_size", type=int, default=128,
            help="Size of the replay buffer before optimization starts")
    parser.add_argument("--hidden_units", type=int, default=128)
    parser.add_argument("--gcp", action="store_true",
            help="Sets if Google Cloud Platform storage bucket should " +
            "be used for storing training results.")
    parser.add_argument("--tau", type=float, default=0.001,
            help="Soft update parameter")
    parser.add_argument("--train_freq", type=int, default=1)
    parser.add_argument("--ref_net", type=str,
        help="Used for debugging of Q values overestimation. " +
        "This checkpoint should point to an already trained network. " +
        "The network is used for extimation of V_next* " +
        "(true next state values).")
    parser.add_argument("--horizon", type=int, default=128,
        help="PPO parameter. How many timesteps collect experience " +
        "before starting optimization phase.")
    parser.add_argument("--ppo_epochs", type=int, default=12,
        help="PPO parameter. Epochs count in the optimization phase.")
    parser.add_argument("--gae_lambda", type=float, default=0.95,
        help="lambda parameter for Advantage Function Estimation (GAE)")
    parser.add_argument("--save_traj", action="store_true",
            help="Enables persisting trajectories on disk during " +
            "training/execution time.")

    parser.set_defaults(dueling=False)
    parser.set_defaults(double=False)
    parser.set_defaults(noisy=False)
    parser.set_defaults(priority=False)
    parser.set_defaults(soft=False)
    parser.set_defaults(baseline=False)
    parser.set_defaults(gcp=False)
    parser.set_defaults(save_traj=False)
    args = parser.parse_args()

    d = vars(args)
    main(**d)
