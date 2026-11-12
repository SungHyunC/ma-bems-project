"""Run the MA-BEMS fine-tuning on Modal instead of the desktop GPU: the same scripts/train.py (QLoRA, NF4 base), then
an A/B/C evaluation (original, v1 adapter, new adapter) with vLLM on the held-out sets.

    modal run ft/modal_ft.py::prepare                 # base weights (HF) + v1 adapter (GitHub release) into the volume
    modal run ft/modal_ft.py::train --data data/v2/train.jsonl --name v2
    modal run ft/modal_ft.py::evaluate --names base,v1,v2
    modal volume get bems-ft out/v2 ./out/qwen3-bems-lora-v2

v2.2 (run from ft/; `modal deploy modal_ft.py` first: train_spawn calls the deployed app, so it must hold the new scripts):
    modal run modal_ft.py::train_spawn --data data/v22/train_v22.jsonl --name v22 --max-len 6144 --decision-weight 3
    modal run modal_ft.py::status --name v22
    modal run modal_ft.py::evaluate --names base,v21,v22 --sets data/v22/eval22_chat.jsonl,data/v22/eval22_tasks.jsonl,data/v22/eval22_nothing.jsonl,data/v22/eval22_request.jsonl,data/eval.jsonl,data/v2/eval_nothing.jsonl --realq data/v22/realq_contexts.json --out out/eval_v22_summary.json --tag v22
    modal volume get bems-ft adapters/v22/adapter_model.safetensors out/qwen3-bems-lora-v22/
    modal volume get bems-ft adapters/v22/adapter_config.json out/qwen3-bems-lora-v22/

Everything lives in the Modal volume `bems-ft`: models/Qwen3-8B, adapters/<name>, data/, eval/.
"""
import json
import subprocess
import time
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
vol = modal.Volume.from_name('bems-ft', create_if_missing=True)
V = '/vol'

train_image = (modal.Image.debian_slim(python_version='3.12')
               .pip_install('torch==2.14.1', 'transformers==5.22.2', 'peft==0.21.2', 'trl==1.17.1', 'bitsandbytes==0.50.2',
                            'datasets==5.2.0', 'accelerate==1.15.0', 'huggingface_hub', 'hf_transfer')
               .env({'HF_HUB_ENABLE_HF_TRANSFER': '1'})
               .add_local_dir(HERE / 'scripts', '/ft/scripts'))
eval_image = (modal.Image.debian_slim(python_version='3.12')
              .pip_install('vllm==0.33.0')
              .env({'VLLM_USE_FLASHINFER_SAMPLER': '0'})    # its top-k/top-p kernel is JIT-built and needs nvcc
              .add_local_dir(HERE / 'scripts', '/ft/scripts')
              .add_local_dir(HERE.parent / 'server', '/server'))
app = modal.App('ma-bems-ft')


@app.function(image=train_image, volumes={V: vol}, timeout=3600, secrets=[modal.Secret.from_name('huggingface')])
def prepare():
    from huggingface_hub import snapshot_download
    import urllib.request
    snapshot_download('Qwen/Qwen3-8B', local_dir=f'{V}/models/Qwen3-8B')
    v1 = Path(f'{V}/adapters/v1')
    v1.mkdir(parents=True, exist_ok=True)
    for f in ('adapter_config.json', 'adapter_model.safetensors'):
        urllib.request.urlretrieve(f'https://github.com/SungHyunC/ma-bems-project/releases/download/ft-lora-v1/{f}', v1 / f)
    vol.commit()
    print(subprocess.run(['du', '-sh', f'{V}/models/Qwen3-8B', str(v1)], capture_output=True, text=True).stdout)


# Timeouts: on 2026-11-12 GPU calls with long timeouts often stayed unscheduled for 15-20+ min (3-4 h never started; 1-2 h
# sometimes did) while 5- and 25-min calls started within a minute. So training runs in 30-min pieces that resume from the
# last checkpoint (train_chain re-spawns until the adapter is written; checkpoints are committed every 2 min, so a timeout
# loses at most the steps since the last one), and the evaluation runs one model per call (about 6 min each).
@app.function(image=train_image, volumes={V: vol}, gpu='H100', timeout=1800)
def train_remote(data_name: str, name: str, epochs: float, max_len: int, extra: list):
    out = f'{V}/adapters/{name}'
    cmd = ['python', '/ft/scripts/train.py', '--model', f'{V}/models/Qwen3-8B', '--data', f'{V}/data/{data_name}',
           '--out', out, '--epochs', str(epochs), '--max-len', str(max_len)] + extra
    print(' '.join(cmd), flush=True)
    t0 = time.time()
    log = Path(f'{V}/logs/train-{name}.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    if any(Path(out).glob('checkpoint-*')):                 # a re-spawn after a timeout continues where it stopped
        cmd.append('--resume')
    import threading
    stop = threading.Event()

    def committer():                                  # keep checkpoints durable if the container hits its timeout
        while not stop.wait(120):
            try:
                vol.commit()
            except Exception as e:                    # a busy volume: try again next round
                print('commit skipped:', e, flush=True)
    threading.Thread(target=committer, daemon=True).start()
    with open(log, 'a') as f:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end='', flush=True)
            f.write(line)
            f.flush()
    stop.set()
    vol.commit()
    if p.wait():
        raise RuntimeError('train.py failed')
    return round((time.time() - t0) / 60, 1)


@app.local_entrypoint()
def train(data: str, name: str = 'v2', epochs: float = 1.0, max_len: int = 4096, lr: float = 2e-4):
    with vol.batch_upload(force=True) as b:
        b.put_file(data, f'/data/{Path(data).name}')
    print('minutes', train_remote.remote(Path(data).name, name, epochs, max_len, ['--lr', str(lr)]))


@app.function(image=eval_image, volumes={V: vol}, gpu='H100', timeout=1500)
def eval_remote(sets: list, names: list, realq_ctx: str = '', realq_samples: int = 3, tag: str = ''):
    import sys
    sys.path.insert(0, '/ft/scripts')
    import eval_vllm
    realq = None
    if realq_ctx:                                     # the 66 visitor questions on fresh contexts, routed like the page
        realq = (f'{V}/data/realq.json', json.loads(Path(f'{V}/data/{realq_ctx}').read_text(encoding='utf-8')))
    res = eval_vllm.run(f'{V}/models/Qwen3-8B', {n: (None if n == 'base' else f'{V}/adapters/{n}') for n in names},
                        [f'{V}/data/{s}' for s in sets], f'{V}/eval' + (f'/{tag}' if tag else ''), realq, realq_samples)
    vol.commit()
    return res


@app.local_entrypoint()
def evaluate(names: str = 'base,v1,v2', sets: str = 'data/eval.jsonl,data/v2/eval_gen.jsonl,data/v2/eval_nothing.jsonl',
             realq: str = '', realq_samples: int = 3, out: str = 'out/eval_vllm_summary.json', tag: str = ''):
    """Per-item answers stay in the volume (eval/<tag>/<model>_<set>.json); the summary is written to `out`."""
    paths = sets.split(',')
    with vol.batch_upload(force=True) as b:
        for s in paths:
            b.put_file(s, f'/data/{Path(s).name}')
        if realq:
            b.put_file(realq, f'/data/{Path(realq).name}')
            b.put_file(str(HERE / 'data' / 'realq.json'), '/data/realq.json')
    calls = [eval_remote.spawn([Path(s).name for s in paths], [n], Path(realq).name if realq else '', realq_samples, tag)
             for n in names.split(',')]                  # one model per container, in parallel
    res = {}
    for c in calls:
        res.update(c.get())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))


@app.local_entrypoint()
def train_spawn(data: str, name: str = 'v2', epochs: float = 1.0, max_len: int = 4096, lr: float = 2e-4,
                decision_weight: float = 1.0, rank: int = 16):
    """Upload the data and start training on the deployed app (`modal deploy ft/modal_ft.py` first): the run no longer
    depends on this client's connection. Progress: logs/train-<name>.log in the volume; result: adapters/<name>.
    --decision-weight > 1 weights the first answer tokens of proposals (train.py first_token_weights)."""
    with vol.batch_upload(force=True) as b:
        b.put_file(data, f'/data/{Path(data).name}')
    fn = modal.Function.from_name('ma-bems-ft', 'train_remote')
    extra = ['--lr', str(lr), '--decision-weight', str(decision_weight), '--rank', str(rank)]
    call = fn.spawn(Path(data).name, name, epochs, max_len, extra)
    print('spawned', call.object_id)


@app.local_entrypoint()
def train_chain(data: str, name: str = 'v22b', epochs: float = 1.0, max_len: int = 4096, lr: float = 2e-4,
                decision_weight: float = 1.0, rank: int = 16, pieces: int = 4):
    """train_spawn in 30-min pieces on the deployed app: spawn, wait, and spawn again (train_remote adds --resume when a
    checkpoint exists) until adapters/<name>/adapter_model.safetensors is written. Keep this client running."""
    with vol.batch_upload(force=True) as b:
        b.put_file(data, f'/data/{Path(data).name}')
    fn = modal.Function.from_name('ma-bems-ft', 'train_remote')
    extra = ['--lr', str(lr), '--decision-weight', str(decision_weight), '--rank', str(rank)]
    for i in range(pieces):
        call = fn.spawn(Path(data).name, name, epochs, max_len, extra)
        print('piece', i + 1, 'spawned', call.object_id, time.strftime('%H:%M:%S'), flush=True)
        try:
            print('piece', i + 1, 'finished: minutes', call.get(), time.strftime('%H:%M:%S'), flush=True)
        except Exception as e:                        # FunctionTimeoutError after 30 min: resume in the next piece
            print('piece', i + 1, 'ended:', type(e).__name__, time.strftime('%H:%M:%S'), flush=True)
        try:
            done = any(x.path.rstrip('/').endswith(f'adapters/{name}/adapter_model.safetensors') for x in vol.listdir(f'adapters/{name}'))
        except Exception:                             # nothing committed yet
            done = False
        if done:
            print('adapter written', flush=True)
            return
    print('not finished after', pieces, 'pieces', flush=True)


@app.local_entrypoint()
def status(name: str = 'v22', lines: int = 12):
    """Tail of logs/train-<name>.log in the volume (the training progress of a detached run)."""
    try:
        text = b''.join(vol.read_file(f'logs/train-{name}.log')).decode('utf-8', 'replace')
    except Exception as e:                            # not started yet
        print('no log yet:', e)
        return
    rows = [l for l in text.replace('\r', '\n').splitlines() if l.strip()]
    print('\n'.join(rows[-lines:]))
