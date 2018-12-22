"""Some nn utilities."""
from typing import Tuple, Optional
import torch
from torch import Tensor
import torch.nn.functional as f
from torch.distributions import Normal
from abstract import ParametricFunction, Shape

def gmm_loss(batch: Tensor,
             mus: Tensor,
             sigmas: Tensor,
             logpi: Tensor,
             correction_factor: Optional[float] = None,
             reduce: bool = True) -> Tensor: # pylint: disable=too-many-arguments
    """ Computes the gmm loss.
    Compute minus the log probability of batch under the GMM model described
    by mus, sigmas, pi. Precisely, with bs1, bs2, ... the sizes of the batch
    dimensions (several batch dimension are useful when you have both a batch
    axis and a time step axis), gs the number of mixtures and fs the number of
    features.
    :args batch: (bs1, bs2, *, fs) torch tensor
    :args mus: (bs1, bs2, *, gs, fs) torch tensor
    :args sigmas: (bs1, bs2, *, gs, fs) torch tensor
    :args logpi: (bs1, bs2, *, gs) torch tensor
    :args reduce: if not reduce, the mean in the following formula is ommited
    :returns:
    loss(batch) = - mean_{i1=0..bs1, i2=0..bs2, ...} log(
        sum_{k=1..gs} pi[i1, i2, ..., k] * N(
            batch[i1, i2, ..., :] | mus[i1, i2, ..., k, :], sigmas[i1, i2, ..., k, :]))
    NOTE: The loss is not reduced along the feature dimension (i.e. it should scale ~linearily
    with fs).
    """
    batch = batch.unsqueeze(-2)
    normal_dist = Normal(mus, sigmas)
    g_log_probs = normal_dist.log_prob(batch)
    g_log_probs = logpi + torch.sum(g_log_probs, dim=-1)
    max_log_probs = torch.max(g_log_probs, dim=-1, keepdim=True)[0]
    g_log_probs = g_log_probs - max_log_probs

    g_probs = torch.exp(g_log_probs)
    if correction_factor is not None:
        mask = (g_probs[..., 0] == 1).float()
        g_probs = torch.stack([
            mask * g_probs[..., 0] * correction_factor + (1 - mask) * g_probs[..., 0],
            g_probs[..., 1]], dim=1)
    probs = torch.sum(g_probs, dim=-1)

    log_prob = max_log_probs.squeeze() + torch.log(probs)
    if reduce:
        return - torch.mean(log_prob)
    return - log_prob

class Scale(torch.nn.Module, ParametricFunction):
    def __init__(self, core: ParametricFunction, scale: Tuple[float, ...]) -> None:
        super().__init__()
        self._core = core
        assert(self._core.output_shape()[0][0] == len(scale))
        self._scale = None
        self.register_buffer('_scale', torch.Tensor(scale).view(1, len(scale)))

    def forward(self, *inputs):
        return self._core(*inputs) * self._scale

    def input_shape(self) -> Shape:
        return self._core.input_shape()

    def output_shape(self) -> Shape:
        return self._core.output_shape()

class LogSoftmax(torch.nn.Module, ParametricFunction):
    def __init__(self, core: ParametricFunction) -> None:
        super().__init__()
        self._core = core

    def forward(self, *inputs):
        return f.log_softmax(self._core(*inputs), dim=-1)

    def input_shape(self) -> Shape:
        return self._core.input_shape()

    def output_shape(self) -> Shape:
        return self._core.output_shape()

def copy_buffer(net: ParametricFunction, target_net: ParametricFunction):
    with torch.no_grad():
        for target_buf, buf in zip(target_net.buffers(), net.buffers()): # type: ignore
            target_buf.copy_(buf)

def soft_update(net: ParametricFunction, target_net: ParametricFunction, tau: float):
    copy_buffer(net, target_net)
    with torch.no_grad():
        for target_param, param in zip(target_net.parameters(), net.parameters()):
            target_param.add_(1 - tau, param - target_param)

def hard_update(net: ParametricFunction, target_net: ParametricFunction):
    copy_buffer(net, target_net)
    with torch.no_grad():
        for target_param, param in zip(target_net.parameters(), net.parameters()):
            target_param.copy_(param)
