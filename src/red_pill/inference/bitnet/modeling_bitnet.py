import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

class WeightQuantSTE(torch.autograd.Function):
	"""
	Cuantización Ternaria {-1, 0, 1} utilizando Straight-Through Estimator (STE).
	Mantiene los gradientes continuos en el paso backward.
	"""
	@staticmethod
	def forward(ctx, weight):
		scale = weight.abs().mean().clamp(min=1e-5)
		quant = (weight / scale).round().clamp(-1, 1) * scale
		return quant

	@staticmethod
	def backward(ctx, grad_output):
		return grad_output

class ActivationQuantSTE(torch.autograd.Function):
	"""
	Cuantización simétrica de 8 bits [-128, 127] utilizando Straight-Through Estimator (STE).
	Mantiene los gradientes continuos en el paso backward.
	"""
	@staticmethod
	def forward(ctx, x):
		scale = x.abs().max(dim=-1, keepdim=True).values.clamp(min=1e-5)
		quant = (x * 127 / scale).round().clamp(-128, 127) * scale / 127
		return quant

	@staticmethod
	def backward(ctx, grad_output):
		return grad_output

class BitLinear(nn.Module):
	"""
	Capa lineal de BitNet b1.58.
	Aplica WeightQuantSTE a los pesos y ActivationQuantSTE a las activaciones.
	"""
	def __init__(self, in_features: int, out_features: int, bias: bool = True):
		super().__init__()
		self.in_features = in_features
		self.out_features = out_features
		self.weight = nn.Parameter(torch.Tensor(out_features, in_features))
		if bias:
			self.bias = nn.Parameter(torch.Tensor(out_features))
		else:
			self.register_parameter('bias', None)
		self.reset_parameters()

	def reset_parameters(self):
		nn.init.kaiming_uniform_(self.weight, a=np.sqrt(5))
		if self.bias is not None:
			fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.weight)
			bound = 1 / np.sqrt(fan_in)
			nn.init.uniform_(self.bias, -bound, bound)

	def forward(self, x: torch.Tensor) -> torch.Tensor:
		quant_w = WeightQuantSTE.apply(self.weight)
		quant_x = ActivationQuantSTE.apply(x)
		return F.linear(quant_x, quant_w, self.bias)

class RMSNorm(nn.Module):
	"""Root Mean Square Layer Normalization."""
	def __init__(self, dim: int, eps: float = 1e-6):
		super().__init__()
		self.eps = eps
		self.weight = nn.Parameter(torch.ones(dim))

	def forward(self, x: torch.Tensor) -> torch.Tensor:
		variance = x.pow(2).mean(-1, keepdim=True)
		return x * torch.rsqrt(variance + self.eps) * self.weight

class BitNetAttention(nn.Module):
	"""Mecanismo de atención multi-cabezal utilizando BitLinear."""
	def __init__(self, dim: int, num_heads: int = 4):
		super().__init__()
		self.dim = dim
		self.num_heads = num_heads
		self.head_dim = dim // num_heads

		self.q_proj = BitLinear(dim, dim, bias=False)
		self.k_proj = BitLinear(dim, dim, bias=False)
		self.v_proj = BitLinear(dim, dim, bias=False)
		self.out_proj = BitLinear(dim, dim, bias=False)

	def forward(self, x: torch.Tensor) -> torch.Tensor:
		batch_size, seq_len, _ = x.shape
		q = self.q_proj(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
		k = self.k_proj(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
		v = self.v_proj(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)

		scores = torch.matmul(q, k.transpose(-2, -1)) / np.sqrt(self.head_dim)
		attn = F.softmax(scores, dim=-1)
		context = torch.matmul(attn, v).transpose(1, 2).contiguous().view(batch_size, seq_len, self.dim)
		return self.out_proj(context)

class BitNetMLP(nn.Module):
	"""Feed-Forward Network utilizando BitLinear y GELU."""
	def __init__(self, dim: int, hidden_dim: int):
		super().__init__()
		self.up_proj = BitLinear(dim, hidden_dim, bias=False)
		self.down_proj = BitLinear(hidden_dim, dim, bias=False)

	def forward(self, x: torch.Tensor) -> torch.Tensor:
		return self.down_proj(F.gelu(self.up_proj(x)))

class BitNetTransformerBlock(nn.Module):
	"""Bloque transformer de BitNet con RMSNorm."""
	def __init__(self, dim: int, num_heads: int = 4, mlp_ratio: int = 4):
		super().__init__()
		self.attn_norm = RMSNorm(dim)
		self.attn = BitNetAttention(dim, num_heads)
		self.mlp_norm = RMSNorm(dim)
		self.mlp = BitNetMLP(dim, dim * mlp_ratio)

	def forward(self, x: torch.Tensor) -> torch.Tensor:
		x = x + self.attn(self.attn_norm(x))
		x = x + self.mlp(self.mlp_norm(x))
		return x

class BitNet4LayerModel(nn.Module):
	"""
	Modelo de 4 capas acoplado al vocabulario conceptual discreto.
	Implementa la ruta diferenciable para Gumbel-Softmax en el juego referencial.
	"""
	def __init__(self, vocab_embeddings: np.ndarray, hidden_dim: int = 256, num_layers: int = 4):
		super().__init__()
		self.vocab_size, self.vocab_dim = vocab_embeddings.shape
		self.hidden_dim = hidden_dim

		# Registrar los embeddings del vocabulario conceptual como un buffer no entrenable (Capa 1 fija)
		self.register_buffer("vocab_embeddings", torch.from_numpy(vocab_embeddings).float())

		# Capa 2: Inbound Translator (Proyección del embedding de 384-dim al espacio oculto del Core de 256-dim)
		self.inbound_proj = nn.Linear(self.vocab_dim, hidden_dim, bias=False)

		# Capa 3: Specialist Core (Ternary Transformer)
		self.core_layers = nn.ModuleList([
			BitNetTransformerBlock(dim=hidden_dim, num_heads=4, mlp_ratio=4)
			for _ in range(num_layers)
		])
		self.norm = RMSNorm(hidden_dim)

		# Capa 4: Outbound Translator (Proyección del espacio oculto de 256-dim al espacio conceptual de 384-dim)
		self.outbound_proj = nn.Linear(hidden_dim, self.vocab_dim, bias=False)

	def forward(self, x: torch.Tensor) -> torch.Tensor:
		"""
		Paso forward.
		x puede ser:
		- Un tensor de enteros de tamaño (batch_size, seq_len) conteniendo Token IDs discretos.
		- Un tensor float de tamaño (batch_size, seq_len, vocab_size) conteniendo vectores one-hot relajados (Gumbel-Softmax).
		"""
		# Capa 1 a Capa 2: Proyección al espacio oculto
		if x.ndim == 2:
			# Ruta discreta convencional (Token IDs)
			# Indexación directa sobre los embeddings fijos
			embeds = F.embedding(x, self.vocab_embeddings)  # (batch_size, seq_len, 384)
		else:
			# Ruta continua diferenciable (Gumbel-Softmax)
			# x es (batch_size, seq_len, 8192)
			embeds = torch.matmul(x, self.vocab_embeddings)  # (batch_size, seq_len, 384)

		h = self.inbound_proj(embeds)  # (batch_size, seq_len, 256)

		# Capa 3: Specialist Core
		for layer in self.core_layers:
			h = layer(h)
		h = self.norm(h)

		# Capa 4: Outbound Translator
		# Proyectar el espacio oculto al espacio conceptual de Capa 1
		concept_proj = self.outbound_proj(h)  # (batch_size, seq_len, 384)

		# Mapear a logits multiplicando por la transpuesta de los embeddings del vocabulario fijos
		# (batch_size, seq_len, 384) x (384, 8192) -> (batch_size, seq_len, 8192)
		logits = torch.matmul(concept_proj, self.vocab_embeddings.T)
		return logits

	def generate_message(self, x: torch.Tensor, tau: float = 1.0, hard: bool = True) -> torch.Tensor:
		"""
		Genera un mensaje utilizando Gumbel-Softmax para mantener la diferenciabilidad del canal.
		Devuelve un tensor de vectores one-hot relajados.
		"""
		logits = self.forward(x)
		# Aplicamos Gumbel-Softmax sobre la dimensión del vocabulario
		message = F.gumbel_softmax(logits, tau=tau, hard=hard, dim=-1)
		return message
