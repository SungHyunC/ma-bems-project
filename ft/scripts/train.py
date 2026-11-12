"""QLoRA fine-tuning of Qwen3-8B for the MA-BEMS assistant (data from make_data.py).

    ..\\.venv\\Scripts\\python scripts\\train.py --model models\\Qwen3-8B --data data\\train.jsonl --out out\\qwen3-bems-lora

The base stays frozen in 4-bit (NF4); only LoRA adapters (r=16 on every attention and MLP projection) are trained,
so it fits a 16 GB GPU. The prompt is rendered with Qwen3's own chat template exactly as Ollama renders it for the
gateway (think=false → an empty <think></think> block), and the loss covers the assistant answer only.
"""
import argparse
import json
import time

import torch
import torch.nn.functional as F
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer


def first_token_weights(tgt, start, weight, k):
    """Per-token loss weights for one example (batch size 1): `weight` on the first k answer tokens when the answer starts
    with the token ids `start` (a proposal: '{"actions": ['), 1 elsewhere. With Ollama's alphabetical key order the
    proposal's first free choice is the token after '{"actions": [': ']' (nothing to change) or '{' (an action). v2.1
    learned it poorly (6-13 of 37 held-out "nothing to do" states), so --decision-weight can give it more weight."""
    w = torch.ones(tgt.numel(), dtype=torch.float32, device=tgt.device)
    if weight == 1.0 or not start:
        return w
    flat = tgt.reshape(-1)
    valid = (flat != -100).nonzero().flatten()
    if len(valid) >= len(start) and flat[valid[:len(start)]].tolist() == list(start):
        w[valid[:k]] = weight
    return w


class AnswerOnlySFTTrainer(SFTTrainer):
    """Computes logits only where the loss is: the answer at the end of each example (batch size 1).

    The default path materializes [sequence × 152k vocabulary] logits over the whole ~3k-token prompt, about 3 GB at
    this length. On a 16 GB card shared with the desktop that pushed training into shared system memory and made it
    4-30x slower. The loss is the same token cross-entropy over the answer tokens, normalized like the Trainer's."""

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs['labels']
        mask = labels != -100
        T = labels.size(1)
        pos = mask.any(0).nonzero()
        first = int(pos[0]) if len(pos) else T - 1
        keep = T - first + 1                              # positions first-1 … T-1 predict tokens first … T
        fwd = {k: inputs[k] for k in ('input_ids', 'attention_mask', 'position_ids') if k in inputs}
        out = model(**fwd, logits_to_keep=keep, use_cache=False)
        logits = out.logits[:, :-1, :].float()
        tgt = labels[:, T - keep + 1:]
        ce = F.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt.reshape(-1), ignore_index=-100, reduction='none')
        loss_sum = (ce * first_token_weights(tgt, PROPOSAL_START, a.decision_weight, a.decision_tokens)).sum()
        if num_items_in_batch is not None:                # normalized over the whole accumulation window
            self.loss_is_scaled_for_ga = True
            loss = loss_sum / num_items_in_batch
        else:                                             # per micro-batch; the Trainer divides by the accumulation steps
            self.loss_is_scaled_for_ga = False
            loss = loss_sum / mask.sum().clamp(min=1)
        return (loss, out) if return_outputs else loss

ap = argparse.ArgumentParser()
ap.add_argument('--model', required=True)
ap.add_argument('--data', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--epochs', type=float, default=2.0)
ap.add_argument('--lr', type=float, default=2e-4)
ap.add_argument('--max-steps', type=int, default=-1)
ap.add_argument('--limit', type=int, default=0)
ap.add_argument('--max-len', type=int, default=3072)
ap.add_argument('--accum', type=int, default=8)
ap.add_argument('--decision-weight', type=float, default=1.0, help='loss weight of the first answer tokens of proposals (1 = off)')
ap.add_argument('--decision-tokens', type=int, default=12, help='first answer tokens weighted: the empty-or-not token is the 4th, the first action text starts at the 9th')
ap.add_argument('--rank', type=int, default=16)
ap.add_argument('--resume', action='store_true', help='continue from the last checkpoint in --out')
a = ap.parse_args()

tok = AutoTokenizer.from_pretrained(a.model)
PROPOSAL_START = tok('{"actions": [', add_special_tokens=False)['input_ids'][:2]   # '{"' 'actions': the rest merges with what follows
rows = [json.loads(line) for line in open(a.data, encoding='utf-8')]
if a.limit:
    rows = rows[:a.limit]


def fmt(r):
    m = r['messages']
    prompt = tok.apply_chat_template(m[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    return {'prompt': prompt, 'completion': m[-1]['content'] + tok.eos_token}   # ends on <|im_end|>: no extra EOS appended


ds = Dataset.from_list([fmt(r) for r in rows])
lens = [len(tok(x['prompt'] + x['completion'])['input_ids']) for x in ds]
print('examples %d · tokens/example mean %.0f max %d · eos %r · decision weight %g on %d tokens after %r' % (
    len(ds), sum(lens) / len(lens), max(lens), tok.eos_token, a.decision_weight, a.decision_tokens, tok.decode(PROPOSAL_START)), flush=True)
if max(lens) > a.max_len:
    print('warning: %d examples longer than --max-len %d will be truncated' % (sum(x > a.max_len for x in lens), a.max_len), flush=True)

model = AutoModelForCausalLM.from_pretrained(
    a.model, device_map={'': 0}, dtype=torch.bfloat16, attn_implementation='sdpa',
    quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))
lora = LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, bias='none', task_type='CAUSAL_LM',
                  target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'])
cfg = SFTConfig(
    output_dir=a.out, num_train_epochs=a.epochs, max_steps=a.max_steps, per_device_train_batch_size=1,
    gradient_accumulation_steps=a.accum, learning_rate=a.lr, lr_scheduler_type='cosine', warmup_steps=10,
    logging_steps=5, save_strategy='steps', save_steps=50, save_total_limit=2, bf16=True,
    gradient_checkpointing=True, gradient_checkpointing_kwargs={'use_reentrant': False}, max_length=a.max_len,
    completion_only_loss=True, packing=False, optim='paged_adamw_8bit', report_to='none', dataloader_num_workers=0, seed=42)
trainer = AnswerOnlySFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok, peft_config=lora)
t0 = time.time()
trainer.train(resume_from_checkpoint=True if a.resume else None)
trainer.save_model(a.out)
tok.save_pretrained(a.out)
print('done in %.1f min · peak GPU memory %.1f GB' % ((time.time() - t0) / 60, torch.cuda.max_memory_allocated() / 1e9), flush=True)
