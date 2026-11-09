"""Merge the trained LoRA adapter into the full-precision Qwen3-8B and save it as safetensors for Ollama.

    .venv\\Scripts\\python scripts\\merge.py models\\Qwen3-8B out\\qwen3-bems-lora out\\merged

Ollama no longer applies separate LoRA adapters (ADAPTER), so the adapter is folded into the bf16 base weights
(on the CPU, ~17 GB RAM) and Ollama imports the merged model with `ollama create -q q4_K_M`, the same quantization as
qwen3-8b-local.
"""
import sys
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base, adapter, out = sys.argv[1:4]
t0 = time.time()
model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16, device_map='cpu', low_cpu_mem_usage=True)
model = PeftModel.from_pretrained(model, adapter)
model = model.merge_and_unload()
model.save_pretrained(out, safe_serialization=True, max_shard_size='5GB')
AutoTokenizer.from_pretrained(adapter).save_pretrained(out)
print('merged and saved to %s in %.1f min' % (out, (time.time() - t0) / 60), flush=True)
