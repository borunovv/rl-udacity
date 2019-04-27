import argparse
import torch
import numpy as np
from collections import deque

from rl import QLearning, UnityEnvAdapter

from unityagents import UnityEnvironment
import gym
from gym import spaces


class SpartaWrapper(gym.Wrapper):

    def step(self, action):
        """ Pain only → reward = -1, that's why this is Sparta!!! """
        state, reward, done, debug = self.env.step(action)
        reward = -1.0 if done else 0.0
        return state, reward, done, debug


def createGymEnv(env_id):
    env = gym.make(env_id)
    if env_id == "CartPole-v1":
        env = SpartaWrapper(env)
    training_done_fn = lambda x: False
    return env, training_done_fn


def createBananaEnv():
    env = UnityEnvironment(file_name="./Banana_Linux_NoVis/Banana.x86_64")
    env = UnityEnvAdapter(env)

    rewards = deque(maxlen=100)
    def training_done_fn(reward_acc):
        rewards.append(reward_acc)
        return np.asarray(rewards).mean() > 13.0

    print("Created Banana environment")
    return env, training_done_fn


def main(session, env_id, dueling, double, noisy, priority, episodes, seed):
    if env_id == "banana":
        env, done_fn = createBananaEnv()
    else:
        env, done_fn = createGymEnv(env_id)

    # Reproducibility
    torch.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)

    ql = QLearning(
        env,
        session,
        dueling=dueling,
        double=double,
        noisy=noisy,
        priority=priority,
        max_episode_steps=2000,
        target_update_freq=100,
        epsilon_start=0.5,
        epsilon_end=0.01,
        epsilon_decay=3000,
        batch_size=128,
        gamma=0.99,
        learning_rate=0.001,
        training_done_fn=done_fn,
        replay_buffer_size=100000)
    ql.train(episodes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--sess")
    parser.add_argument("--env")
    parser.add_argument("--dueling", action="store_true")
    parser.add_argument("--double", action="store_true")
    parser.add_argument("--noisy", action="store_true")
    parser.add_argument("--priority", action="store_true")
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--seeds", type=int, default=3)
    parser.set_defaults(dueling=False)
    parser.set_defaults(double=False)
    parser.set_defaults(noisy=False)
    parser.set_defaults(priority=False)
    args = parser.parse_args()

    for seed in range(args.seeds):
        sess_id = "{}-{}".format(args.sess, seed)
        main(sess_id,
            env_id=args.env,
            dueling=args.dueling,
            double=args.double,
            noisy=args.noisy,
            episodes=args.steps,
            priority=args.priority,
            seed=seed,
        )
