import time
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim


class Reinforce:

    def __init__(
            self,
            action_size,
            observation_shape,
            gamma=0.99,
            baseline=False,
            baseline_learning_rate=0.001,
            learning_rate=0.001):

        print("REINFORCE agent:")

        self._observation_shape = observation_shape
        self._gamma = gamma
        print("\tReward discount (gamma): {}".format(self._gamma))

        self._device = torch.device(
                "cuda" if torch.cuda.is_available() else "cpu")

        self._baseline_net = None
        if baseline:
            print("\tState-Value network will be created for " +
                    "providing baseline.")
            self._baseline_net = StateValueNet(observation_shape)
            self._baseline_net.to(self._device)

        self._policy_net = PolicyNet(
                observation_shape,
                action_size)
        self._policy_net.to(self._device)

        # Optimizer and loss
        self._loss_fn = nn.MSELoss(reduce=False)
        self._optimizer = optim.Adam(
                self._policy_net.parameters(),
                lr=learning_rate)
        print("\tLearning rate: {}".format(learning_rate))

        if baseline:
            self._baseline_optimizer = optim.Adam(
                    self._baseline_net.parameters(),
                    lr=baseline_learning_rate)
            print("\tLearning rate for baseline network: {}".format(
                baseline_learning_rate))

        # Variables which change during training
        self.prev_state = None
        self._trajectory = []

    def save_model(self, filename):
        torch.save(self._policy_net, filename)

    def _store_transition(self, reward):
        if self.eval:
            return
        if self.prev_state is None:  # beginning of the episode
            return
        self._trajectory.append((
            self.prev_state,
            self.prev_action,
            reward))

    def end_episode(self, reward, stats, traj_id=0):
        self._store_transition(reward)
        self.prev_state = None
        if not self.eval:
            self._optimize(stats)
        self._trajectory = []

    def step(self, state, prev_reward, stats, traj_id=0):
        self._store_transition(prev_reward)
        action = self._action(state)
        self.prev_action = action
        self.prev_state = state
        return action

    def _action(self, state):
        state_tensor = torch.from_numpy(
                state).float().unsqueeze(0).to(self._device)
        self._policy_net.train(False)
        with torch.no_grad():
            action_logits = self._policy_net(state_tensor)
            action_logits = action_logits.double()
            action_probs = torch.nn.Softmax()(action_logits)
            action_probs = torch.squeeze(action_probs)
            action_probs = action_probs.detach()

        return np.random.choice(
                len(action_probs),
                p=action_probs)

    def _optimize(self, stats):
        assert len(self._trajectory) > 0
        t0 = time.time()
        self._policy_net.train(True)

        batch_size = len(self._trajectory)
        states = np.zeros(
                (batch_size,) + self._observation_shape, dtype=np.float16)
        actions = np.zeros(batch_size, dtype=np.uint8)
        gs = np.zeros(batch_size, dtype=np.float16)
        gammas = np.zeros(batch_size, dtype=np.float16)

        for t in range(len(self._trajectory)):
            state, action, _ = self._trajectory[t]
            states[t] = state
            actions[t] = action

            g = 0
            for k in range(t, len(self._trajectory)):
                _, _, reward = self._trajectory[k]
                g += np.power(self._gamma, k - t - 1) * reward
            gs[t] = g

            gamma = np.power(self._gamma, t)
            gammas[t] = gamma

        states = torch.from_numpy(states).float().to(self._device)
        gs = torch.from_numpy(gs).float().to(self._device)
        gs = torch.unsqueeze(gs, dim=1)
        actions = torch.from_numpy(actions).long().to(self._device)
        actions = torch.unsqueeze(actions, dim=1)

        if self._baseline_net:
            v = self._baseline_net(states)
            baseline_loss = self._loss_fn(v, gs)
            baseline_loss = torch.mean(baseline_loss)

            self._baseline_optimizer.zero_grad()
            baseline_loss.backward()
            self._baseline_optimizer.step()

            with torch.no_grad():
                baselines = self._baseline_net(states).detach()
            stats.set('baseline', baselines.mean())
        else:
            baselines = torch.from_numpy(
                    np.zeros(batch_size, dtype=np.float16))
        baselines = baselines.float().to(self._device)

        stats.set('return', gs.mean().detach())

        gammas = torch.from_numpy(gammas).float().to(self._device)
        gammas = torch.unsqueeze(gammas, dim=1)

        action_logits = self._policy_net(states)

        log_softmax = torch.nn.LogSoftmax()
        action_log_probs = log_softmax(action_logits)
        action_log_probs = action_log_probs.gather(dim=1, index=actions)

        # -1 here because optimizer is going to *minimize* the
        # loss. If we were going to update the weights manually,
        # (without optimizer) we would remove the -1.
        loss = -1 * gammas * (gs - baselines) * action_log_probs
        loss = loss.mean()

        self._optimizer.zero_grad()
        loss.backward()
        self._optimizer.step()

        stats.set('loss', loss.detach())
        stats.set('optimization_time', time.time() - t0)


class PolicyNet(nn.Module):

    def __init__(
            self,
            observation_size,
            action_size):
        super(PolicyNet, self).__init__()

        self.is_dense = len(observation_size) == 1

        hidden_units = 128

        if self.is_dense:
            self.input = nn.Linear(observation_size[0], hidden_units)
            self.feature_size = hidden_units
        else:
            self.conv1 = nn.Conv2d(
                    observation_size[0],
                    32, kernel_size=8, stride=4)
            self.conv2 = nn.Conv2d(32, 64, kernel_size=4, stride=2)
            self.conv3 = nn.Conv2d(64, 64, kernel_size=3, stride=1)
            self.feature_size = self.conv3(self.conv2(self.conv1(
                torch.zeros(1, *observation_size)))).view(1, -1).size(1)

        self.fc1 = nn.Linear(hidden_units, hidden_units)
        self.fc2 = nn.Linear(hidden_units, action_size)

    def forward(self, x):
        if self.is_dense:
            x = F.relu(self.input(x))
        else:
            x = F.relu(self.conv1(x))
            x = F.relu(self.conv2(x))
            x = F.relu(self.conv3(x))
            x = x.view(x.size(0), -1)

        x = F.relu(self.fc1(x))
        a_logits = self.fc2(x)
        return a_logits


class StateValueNet(nn.Module):

    def __init__(
            self,
            observation_size):
        super(StateValueNet, self).__init__()

        self.is_dense = len(observation_size) == 1

        hidden_units = 128

        if self.is_dense:
            self.input = nn.Linear(observation_size[0], hidden_units)
            self.feature_size = hidden_units
        else:
            self.conv1 = nn.Conv2d(
                    observation_size[0],
                    32, kernel_size=8, stride=4)
            self.conv2 = nn.Conv2d(32, 64, kernel_size=4, stride=2)
            self.conv3 = nn.Conv2d(64, 64, kernel_size=3, stride=1)
            self.feature_size = self.conv3(self.conv2(self.conv1(
                torch.zeros(1, *observation_size)))).view(1, -1).size(1)

        self.fc1 = nn.Linear(hidden_units, hidden_units)
        self.fc2 = nn.Linear(hidden_units, 1)

    def forward(self, x):
        if self.is_dense:
            x = F.relu(self.input(x))
        else:
            x = F.relu(self.conv1(x))
            x = F.relu(self.conv2(x))
            x = F.relu(self.conv3(x))
            x = x.view(x.size(0), -1)

        x = F.relu(self.fc1(x))
        v = self.fc2(x)
        return v
