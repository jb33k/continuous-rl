import numpy as np
from typing import Optional
import torch
from torch import Tensor
from torch.distributions import Distribution
from torch.distributions.kl import kl_divergence
from abstract import ParametricFunction
from actors.online_actor import OnlineActorContinuous, OnlineActorDiscrete
from gym.spaces import Box, Discrete
from models import ContinuousRandomPolicy, DiscreteRandomPolicy


def loss(distr: Distribution, actions: Tensor, critic_value: Tensor,
         c_entropy: float, eps_clamp: float, c_kl: float, old_logp: Tensor,
         old_distr: Optional[Distribution] = None) -> None:
    logp_action = distr.log_prob(actions)
    logr = (logp_action - old_logp)

    r_clipped = torch.where(
        critic_value.detach() > 0,
        torch.clamp(logr, max=np.log(1 + eps_clamp)),
        torch.clamp(logr, min=np.log(1 - eps_clamp))
    ).exp()

    loss = - r_clipped * critic_value.detach()
    if c_entropy != 0.:
        loss -= c_entropy * distr.entropy()

    if c_kl != 0.:
        if old_distr is None:
            raise ValueError(
                "Optional argument old_distr is required if c_kl > 0")
        loss += c_kl * kl_divergence(old_distr, distr)

    return loss.mean()


class PPOActorContinuous(OnlineActorContinuous):
    def __init__(self, policy_function: ParametricFunction,
                 dt: float, c_entropy: float, eps_clamp: float, c_kl: float):

        OnlineActorContinuous.__init__(self, policy_function=policy_function,
                                       dt=dt, c_entropy=c_entropy)
        self._eps_clamp = eps_clamp
        self._c_kl = c_kl

    def loss(self, distr: Distribution, actions: Tensor, critic_value: Tensor,
             old_logp: Tensor, old_distr: Optional[Distribution] = None) -> Tensor:
        return loss(distr, actions, critic_value, self._c_entropy,
                    self._eps_clamp, self._c_kl, old_logp, old_distr)


class PPOActorDiscrete(OnlineActorDiscrete):
    def __init__(self, policy_function: ParametricFunction,
                 dt: float, c_entropy: float, eps_clamp: float, c_kl: float):

        OnlineActorDiscrete.__init__(self, policy_function=policy_function,
                                     dt=dt, c_entropy=c_entropy)
        self._eps_clamp = eps_clamp
        self._c_kl = c_kl

    def loss(self, distr: Distribution, actions: Tensor, critic_value: Tensor,
             old_logp: Tensor, old_distr: Optional[Distribution] = None) -> Tensor:
        return loss(distr, actions, critic_value, self._c_entropy,
                    self._eps_clamp, self._c_kl, old_logp, old_distr)

class PPOActor(object):
    @staticmethod
    def configure(**kwargs):
        action_space = kwargs['action_space']
        observation_space = kwargs['observation_space']
        assert isinstance(observation_space, Box)

        nb_state_feats = observation_space.shape[-1]
        if isinstance(action_space, Box):
            nb_actions = action_space.shape[-1]
            policy_generator, actor_generator = ContinuousRandomPolicy, PPOActorContinuous
        elif isinstance(action_space, Discrete):
            nb_actions = action_space.n
            policy_generator, actor_generator = DiscreteRandomPolicy, PPOActorDiscrete
        policy_function = policy_generator(
            nb_state_feats, nb_actions, kwargs['nb_layers'], kwargs['hidden_size'])

        return actor_generator(policy_function, kwargs['dt'], kwargs['c_entropy'],
                               kwargs["eps_clamp"], kwargs["c_kl"])
