"""Run the MA-BEMS fine-tuning on Modal instead of the desktop GPU: the same scripts/train.py (QLoRA, NF4 base), then
an A/B/C evaluation (original, v1 adapter, new adapter) with vLLM on the held-out sets.

    modal run ft/modal_ft.py::prepare                 # base weights (HF) + v1 adapter (GitHub release) into the volume
    modal run ft/modal_ft.py::train --data data/v2/train.jsonl --name v2
    modal run ft/modal_ft.py::evaluate --names base,v1,v2
    modal volume get bems-ft out/v2 ./out/qwen3-bems-lora-v2

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


@app.function(image=train_image, volumes={V: vol}, gpu='H100', timeout=4 * 3600)
def train_remote(data_name: str, name: str, epochs: float, max_len: int, extra: list):
    out = f'{V}/adapters/{name}'
    cmd = ['python', '/ft/scripts/train.py', '--model', f'{V}/models/Qwen3-8B', '--data', f'{V}/data/{data_name}',
           '--out', out, '--epochs', str(epochs), '--max-len', str(max_len)] + extra
    print(' '.join(cmd), flush=True)
    t0 = time.time()
    log = Path(f'{V}/logs/train-{name}.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, 'w') as f:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end='', flush=True)
            f.write(line)
    vol.commit()
    if p.wait():
        raise RuntimeError('train.py failed')
    return round((time.time() - t0) / 60, 1)


@app.local_entrypoint()
def train(data: str, name: str = 'v2', epochs: float = 1.0, max_len: int = 4096, lr: float = 2e-4):
    with vol.batch_upload(force=True) as b:
        b.put_file(data, f'/data/{Path(data).name}')
    print('minutes', train_remote.remote(Path(data).name, name, epochs, max_len, ['--lr', str(lr)]))


@app.function(image=eval_image, volumes={V: vol}, gpu='H100', timeout=3 * 3600)
def eval_remote(sets: list, names: list):
    import sys
    sys.path.insert(0, '/ft/scripts')
    import eval_vllm
    return eval_vllm.run(f'{V}/models/Qwen3-8B', {n: (None if n == 'base' else f'{V}/adapters/{n}') for n in names},
                         [f'{V}/data/{s}' for s in sets], f'{V}/eval')


@app.local_entrypoint()
def evaluate(names: str = 'base,v1,v2', sets: str = 'data/eval.jsonl,data/v2/eval_gen.jsonl,data/v2/eval_nothing.jsonl'):
    paths = sets.split(',')
    with vol.batch_upload(force=True) as b:
        for s in paths:
            b.put_file(s, f'/data/{Path(s).name}')
    res = eval_remote.remote([Path(s).name for s in paths], names.split(','))
    Path('out').mkdir(exist_ok=True)
    Path('out/eval_vllm_summary.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))


@app.local_entrypoint()
def train_spawn(data: str, name: str = 'v2', epochs: float = 1.0, max_len: int = 4096, lr: float = 2e-4):
    """Upload the data and start training on the deployed app (`modal deploy ft/modal_ft.py` first): the run no longer
    depends on this client's connection. Progress: logs/train-<name>.log in the volume; result: adapters/<name>."""
    with vol.batch_upload(force=True) as b:
        b.put_file(data, f'/data/{Path(data).name}')
    fn = modal.Function.from_name('ma-bems-ft', 'train_remote')
    call = fn.spawn(Path(data).name, name, epochs, max_len, ['--lr', str(lr)])
    print('spawned', call.object_id)
