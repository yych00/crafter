"""
Micro Neural Network Framework in Pure NumPy
===========================================
Vectorized, efficient, autograd-compatible neural modules for world models.
Includes Linear, LayerNorm, ReLU, Tanh, Adam Optimizer, EMA, and Loss functions.
"""

import numpy as np


class Module:
    def forward(self, *args, **kwargs):
        raise NotImplementedError
    def backward(self, *args, **kwargs):
        raise NotImplementedError
    def parameters(self):
        return []


class Linear(Module):
    def __init__(self, in_features, out_features, init_scale=1.0):
        self.in_features = in_features
        self.out_features = out_features
        # He / Kaiming normal initialization
        std = np.sqrt(2.0 / in_features) * init_scale
        self.W = (np.random.randn(in_features, out_features) * std).astype(np.float32)
        self.b = np.zeros(out_features, dtype=np.float32)
        
        self.grad_W = np.zeros_like(self.W)
        self.grad_b = np.zeros_like(self.b)
        self.x = None

    def forward(self, x):
        self.x = x
        return x @ self.W + self.b

    def backward(self, grad_output):
        # grad_output: (B, out_features)
        self.grad_W += self.x.T @ grad_output
        self.grad_b += np.sum(grad_output, axis=0)
        grad_input = grad_output @ self.W.T
        return grad_input

    def parameters(self):
        return [(self.W, self.grad_W), (self.b, self.grad_b)]


class LayerNorm(Module):
    def __init__(self, dim, eps=1e-5):
        self.dim = dim
        self.eps = eps
        self.gamma = np.ones(dim, dtype=np.float32)
        self.beta = np.zeros(dim, dtype=np.float32)
        self.grad_gamma = np.zeros_like(self.gamma)
        self.grad_beta = np.zeros_like(self.beta)
        self.x_hat = None
        self.std_inv = None

    def forward(self, x):
        # x: (B, dim)
        mean = np.mean(x, axis=-1, keepdims=True)
        var = np.var(x, axis=-1, keepdims=True)
        self.std_inv = 1.0 / np.sqrt(var + self.eps)
        self.x_hat = (x - mean) * self.std_inv
        return self.gamma * self.x_hat + self.beta

    def backward(self, grad_output):
        B, D = grad_output.shape
        self.grad_gamma += np.sum(grad_output * self.x_hat, axis=0)
        self.grad_beta += np.sum(grad_output, axis=0)
        
        dx_hat = grad_output * self.gamma
        dvar = np.sum(dx_hat * self.x_hat * -0.5 * (self.std_inv ** 2), axis=-1, keepdims=True)
        dmean = np.sum(dx_hat * -self.std_inv, axis=-1, keepdims=True)
        dx = dx_hat * self.std_inv + dvar * 2.0 * self.x_hat / D + dmean / D
        return dx

    def parameters(self):
        return [(self.gamma, self.grad_gamma), (self.beta, self.grad_beta)]


class ReLU(Module):
    def __init__(self):
        self.mask = None

    def forward(self, x):
        self.mask = (x > 0)
        return np.maximum(0.0, x)

    def backward(self, grad_output):
        return grad_output * self.mask

    def parameters(self):
        return []


class Tanh(Module):
    def __init__(self):
        self.out = None

    def forward(self, x):
        self.out = np.tanh(x)
        return self.out

    def backward(self, grad_output):
        return grad_output * (1.0 - self.out ** 2)

    def parameters(self):
        return []


class Sequential(Module):
    def __init__(self, *layers):
        self.layers = list(layers)

    def forward(self, x):
        for layer in self.layers:
            x = layer.forward(x)
        return x

    def backward(self, grad_output):
        for layer in reversed(self.layers):
            grad_output = layer.backward(grad_output)
        return grad_output

    def parameters(self):
        params = []
        for layer in self.layers:
            params.extend(layer.parameters())
        return params


class Adam:
    def __init__(self, params, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8, weight_decay=1e-5):
        self.params = params
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0
        
        self.m = [np.zeros_like(p[0]) for p in self.params]
        self.v = [np.zeros_like(p[0]) for p in self.params]

    def zero_grad(self):
        for p, grad in self.params:
            grad.fill(0.0)

    def step(self):
        self.t += 1
        lr_t = self.lr * np.sqrt(1.0 - self.beta2 ** self.t) / (1.0 - self.beta1 ** self.t)
        
        for i, (p, grad) in enumerate(self.params):
            if self.weight_decay > 0:
                grad_val = grad + self.weight_decay * p
            else:
                grad_val = grad
                
            # Clip gradient norm to avoid explosion
            gnorm = np.linalg.norm(grad_val)
            if gnorm > 5.0:
                grad_val = grad_val * (5.0 / gnorm)
                
            self.m[i] = self.beta1 * self.m[i] + (1.0 - self.beta1) * grad_val
            self.v[i] = self.beta2 * self.v[i] + (1.0 - self.beta2) * (grad_val ** 2)
            
            step_val = lr_t * self.m[i] / (np.sqrt(self.v[i]) + self.eps)
            p -= step_val


def copy_parameters(source_params, target_params):
    """Deep copy weights from source to target."""
    for (sp, _), (tp, _) in zip(source_params, target_params):
        tp[:] = sp[:]


def ema_update(online_params, target_params, tau=0.99):
    """Exponential Moving Average update: target = tau * target + (1 - tau) * online"""
    for (op, _), (tp, _) in zip(online_params, target_params):
        tp[:] = tau * tp + (1.0 - tau) * op


def one_hot(actions, num_classes=5):
    """Convert integer action array to one-hot matrix."""
    B = actions.shape[0]
    out = np.zeros((B, num_classes), dtype=np.float32)
    out[np.arange(B), actions] = 1.0
    return out


def mse_loss(pred, target):
    """Mean squared error and analytical gradient."""
    diff = pred - target
    loss = float(np.mean(diff ** 2))
    grad = (2.0 / pred.size) * diff
    return loss, grad


def softmax_cross_entropy(logits, target_labels):
    """Softmax cross entropy loss and gradient for multi-class classification."""
    B = logits.shape[0]
    max_logits = np.max(logits, axis=-1, keepdims=True)
    exp_logits = np.exp(logits - max_logits)
    probs = exp_logits / (np.sum(exp_logits, axis=-1, keepdims=True) + 1e-12)
    
    # Loss
    correct_log_probs = np.log(probs[np.arange(B), target_labels] + 1e-12)
    loss = -float(np.mean(correct_log_probs))
    
    # Grad
    grad = probs.copy()
    grad[np.arange(B), target_labels] -= 1.0
    grad /= B
    return loss, grad, probs


def vicreg_loss(z, gamma=1.0, eps=1e-4):
    """
    VICReg variance & covariance regularizer on batch z: (B, D).
    Encourages:
    1. Variance of each dimension >= 1.0 (anti-collapse)
    2. Off-diagonal covariance -> 0 (decorrelation)
    """
    B, D = z.shape
    # Center z
    z_mean = np.mean(z, axis=0, keepdims=True)
    z_centered = z - z_mean
    
    # 1. Variance regularization: L_var = (1/D) * sum_j max(0, gamma - std_j)
    var = np.mean(z_centered ** 2, axis=0) # (D,)
    std = np.sqrt(var + eps)
    hinge = np.maximum(0.0, gamma - std)
    var_loss = float(np.mean(hinge))
    
    # Grad of var_loss w.r.t z
    # d(hinge)/d(std) = -1 if std < gamma else 0
    dstd = np.where(std < gamma, -1.0 / D, 0.0) # (D,)
    dvar = dstd * 0.5 / std
    grad_var = dvar * 2.0 * z_centered / B # (B, D)
    
    # 2. Covariance regularization: L_cov = (1/D) * sum_{i != j} Cov_ij^2
    cov = (z_centered.T @ z_centered) / (B - 1 + 1e-12) # (D, D)
    np.fill_diagonal(cov, 0.0)
    cov_loss = float(np.sum(cov ** 2) / D)
    
    # Grad of cov_loss w.r.t z
    grad_cov = (4.0 / (D * (B - 1 + 1e-12))) * (z_centered @ cov)
    
    return var_loss, cov_loss, grad_var + grad_cov
