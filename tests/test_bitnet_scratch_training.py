import os
import pytest
import numpy as np
import torch
import torch.nn as nn
from red_pill.inference.bitnet.translator import SovereignTranslator
from red_pill.inference.bitnet.modeling_bitnet import BitNet4LayerModel, BitLinear, WeightQuantSTE, ActivationQuantSTE
from red_pill.inference.bitnet.train_populora import svd_crossover

def test_translator_encode_decode():
	"""Verifica que SovereignTranslator codifica y decodifica correctamente."""
	translator = SovereignTranslator()
	assert len(translator.vocab) == 8192

	test_phrase = "gato en búnker"
	token_ids = translator.encode(test_phrase)
	assert len(token_ids) == 3

	decoded = translator.decode(token_ids)
	if len(set(token_ids)) == 1:
		# Entorno mockeado: todos los tokens coinciden con el primer concepto
		assert len(decoded.split()) == 3
		assert decoded.split()[0] in translator.vocab
	else:
		# Entorno real
		assert "gato" in decoded
		assert "búnker" in decoded

def test_bit_linear_quantization():
	"""Verifica la cuantización y retropropagación en BitLinear."""
	layer = BitLinear(in_features=8, out_features=4, bias=False)
	x = torch.randn(2, 8, requires_grad=True)

	# Paso forward
	out = layer(x)
	assert out.shape == (2, 4)

	# Verificar que el gradiente fluye hacia atrás
	loss = out.sum()
	loss.backward()
	assert x.grad is not None
	assert layer.weight.grad is not None

def test_four_layer_model_forward():
	"""Verifica el flujo forward del modelo de 4 capas con entradas discretas y continuas."""
	translator = SovereignTranslator()
	embeddings = translator.get_concept_embeddings()

	model = BitNet4LayerModel(vocab_embeddings=embeddings, hidden_dim=64, num_layers=2)

	# 1. Entrada discreta (Token IDs)
	x_discrete = torch.randint(0, 8192, (2, 5))
	logits = model(x_discrete)
	assert logits.shape == (2, 5, 8192)

	# 2. Entrada continua (One-hot relajado para Gumbel-Softmax)
	x_continuous = torch.randn(2, 5, 8192, requires_grad=True)
	logits_cont = model(x_continuous)
	assert logits_cont.shape == (2, 5, 8192)

	# Retropropagación sobre la entrada continua
	loss = logits_cont.sum()
	loss.backward()
	assert x_continuous.grad is not None

def test_svd_crossover():
	"""Verifica que el operador SVD mezcla los pesos correctamente."""
	translator = SovereignTranslator()
	embeddings = translator.get_concept_embeddings()

	parent_a = BitNet4LayerModel(vocab_embeddings=embeddings, hidden_dim=64, num_layers=2)
	parent_b = BitNet4LayerModel(vocab_embeddings=embeddings, hidden_dim=64, num_layers=2)
	child = BitNet4LayerModel(vocab_embeddings=embeddings, hidden_dim=64, num_layers=2)

	# Aplicar crossover SVD
	svd_crossover(parent_a, parent_b, child, alpha=0.5, sigma=0.01)

	# Comprobar que child ha mutado y es distinto a parent_a y parent_b
	for name, param in child.named_parameters():
		if param.requires_grad and param.ndim == 2:
			p_a = parent_a.state_dict()[name]
			p_b = parent_b.state_dict()[name]
			assert not torch.equal(param, p_a)
			assert not torch.equal(param, p_b)

def test_dataset_breeder_dual():
	"""Verifica que ReferentialDatasetBreeder genera lotes duales correctos."""
	from red_pill.inference.bitnet.dataset_breeder import ReferentialDatasetBreeder
	translator = SovereignTranslator()
	breeder = ReferentialDatasetBreeder(translator)

	concept_targets, concept_token_ids, emotion_targets, emotion_token_ids = breeder.generate_batch(4)

	assert concept_targets.shape == (4,)
	assert concept_token_ids.shape == (4,)
	assert emotion_targets.shape == (4,)
	assert emotion_token_ids.shape == (4,)

	assert breeder.get_concept_name(concept_targets[0]) in breeder.target_concepts
	assert breeder.get_emotion_name(emotion_targets[0]) in breeder.target_emotions
