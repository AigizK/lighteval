# Quicktour

We provide two main entry points to evaluate models:

- `lighteval accelerate` : evaluate models on CPU or one or more GPUs using [🤗
  Accelerate](https://github.com/huggingface/accelerate)
- `lighteval nanotron`: evaluate models in distributed settings using [⚡️
  Nanotron](https://github.com/huggingface/nanotron)

## Accelerate

### Evaluate a model on a GPU

To evaluate `GPT-2` on the Truthful QA benchmark, run:

```bash
lighteval accelerate \
     --model_args "pretrained=gpt2" \
     --tasks "leaderboard|truthfulqa:mc|0|0" \
     --override_batch_size 1 \
     --output_dir="./evals/"
```

Here, `--tasks` refers to either a comma-separated list of supported tasks from
the [tasks_list](tasks) in the format:

```bash
suite|task|num_few_shot|{0 or 1 to automatically reduce `num_few_shot` if prompt is too long}
```

or a file path like
[examples/tasks/recommended_set.txt](https://github.com/huggingface/lighteval/blob/main/examples/tasks/recommended_set.txt)
which specifies multiple task configurations.

Tasks details can be found in the
[file](https://github.com/huggingface/lighteval/blob/main/src/lighteval/tasks/default_tasks.py)
implementing them.

### Evaluate a model on one or more GPUs

#### Data parallelism

To evaluate a model on one or more GPUs, first create a multi-gpu config by running.

```bash
accelerate config
```

You can then evaluate a model using data parallelism on 8 GPUs like follows:

```bash
accelerate launch --multi_gpu --num_processes=8 -m \
    lighteval accelerate \
    --model_args "pretrained=gpt2" \
    --tasks "leaderboard|truthfulqa:mc|0|0" \
    --override_batch_size 1 \
    --output_dir="./evals/"
```

Here, `--override_batch_size` defines the batch size per device, so the effective
batch size will be `override_batch_size * num_gpus`.

#### Pipeline parallelism

To evaluate a model using pipeline parallelism on 2 or more GPUs, run:

```bash
    lighteval accelerate \
    --model_args "pretrained=gpt2,model_parallel=True" \
    --tasks "leaderboard|truthfulqa:mc|0|0" \
    --override_batch_size 1 \
    --output_dir="./evals/"
```

This will automatically use accelerate to distribute the model across the GPUs.

<Tip>
Both data and pipeline parallelism can be combined by setting
`model_parallel=True` and using accelerate to distribute the data across the
GPUs.
</Tip>

## Nanotron

To evaluate a model trained with nanotron on a single gpu.

<Tip warning={true}>
Nanotron models cannot be evaluated without torchrun.
</Tip>

```bash
 torchrun --standalone --nnodes=1 --nproc-per-node=1  \
 src/lighteval/__main__.py nanotron \
 --checkpoint_config_path ../nanotron/checkpoints/10/config.yaml \
 --lighteval_config_path examples/nanotron/lighteval_config_override_template.yaml
 ```

The `nproc-per-node` argument should match the data, tensor and pipeline
parallelism confidured in the `lighteval_config_override_template.yaml` file.
That is: `nproc-per-node = data_parallelism * tensor_parallelism *
pipeline_parallelism`.
