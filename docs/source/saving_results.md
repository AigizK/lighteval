# Saving results

## Saving results locally

Lighteval will automatically save results and evaluation details in the directory
set with the `--output_dir` argument. The results will be saved in
`{output_dir}/results/{model_org}/{model_name}/results_{timestamp}.json`.
[Here is an example of a result file](#example-of-a-result-file).

To save the details of the evaluation, you can use the `--save_details`
argument. The details will be saved in a parquet file
`{output_dir}/details/{model_org}/{model_name}/{timestamp}/details_{task}_{timestamp}.parquet`.

## Pushing results to the HuggingFace hub

You can push the results and evaluation details to the HuggingFace hub. To do
so, you need to set the `--push_results_to_hub` as well as the `--results_org`
argument. The results will be saved in a dataset with the name at
`{results_org}/{model_org}/{model_name}`. To push the details, you need to set
the `--push_details_to_hub` argument.
The dataset created will be private by default, you can make it public by
setting the `--public_run` argument.


## Pushing results to Tensorboard

You can push the results to Tensorboard by setting the `--push_results_to_tensorboard`.


## How to load and investigate details

### Load from local detail files

```python
from datasets import load_dataset
import os

output_dir = "evals_doc"
model = "HuggingFaceH4/zephyr-7b-beta"
model_org = model.split("/")[0]
model_name = model.split("/")[1]
timestamp = "2024-09-03T15-06-11.234678"
task = "lighteval|gsm8k|0"

details_path = f"{output_dir}/details/{model_org}/{model_name}/{timestamp}/details_{task}_{timestamp}.parquet"

# Load the details
details = load_dataset("parquet", data_files=details_path, split="train")

for detail in details:
    print(detail)
```

### Load from the HuggingFace hub

```python
from datasets import load_dataset

output_dir = "evals_doc"
results_org = "SaylorTwift"
model = "HuggingFaceH4/zephyr-7b-beta"
model_org = model.split("/")[0]
model_name = model.split("/")[1]
timestamp = "2024-09-03T15-06-11.234678"
task = "lighteval|gsm8k|0"
public_run = False

dataset_path = f"{results_org}/details_{model_name}{'_private' if not public_run else ''}"
details = load_dataset(dataset_path, task.replace("|", "_"), split="latest")

for detail in details:
    print(detail)
```


The detail file contains the following columns:
- `choices`: The choices presented to the model in the case of mutlichoice tasks.
- `gold`: The gold answer.
- `gold_index`: The index of the gold answer in the choices list.
- `cont_tokens`: The continuation tokens.
- `example`: The input in text form.
- `full_prompt`: The full prompt, that will be inputed to the model.
- `input_tokens`: The tokens of the full prompt.
- `instruction`: The instruction given to the model.
- `metrics`: The metrics computed for the example.
- `num_asked_few_shots`: The number of few shots asked to the model.
- `num_effective_few_shots`: The number of effective few shots.
- `padded`: Whether the input was padded.
- `pred_logits`: The logits of the model.
- `predictions`: The predictions of the model.
- `specifics`: The specifics of the task.
- `truncated`: Whether the input was truncated.


## Example of a result file

```json
{
  "config_general": {
    "lighteval_sha": "203045a8431bc9b77245c9998e05fc54509ea07f",
    "num_fewshot_seeds": 1,
    "override_batch_size": 1,
    "max_samples": 1,
    "job_id": "",
    "start_time": 620979.879320166,
    "end_time": 621004.632108041,
    "total_evaluation_time_secondes": "24.752787875011563",
    "model_name": "gpt2",
    "model_sha": "607a30d783dfa663caf39e06633721c8d4cfcd7e",
    "model_dtype": null,
    "model_size": "476.2 MB"
  },
  "results": {
    "lighteval|gsm8k|0": {
      "qem": 0.0,
      "qem_stderr": 0.0,
      "maj@8": 0.0,
      "maj@8_stderr": 0.0
    },
    "all": {
      "qem": 0.0,
      "qem_stderr": 0.0,
      "maj@8": 0.0,
      "maj@8_stderr": 0.0
    }
  },
  "versions": {
    "lighteval|gsm8k|0": 0
  },
  "config_tasks": {
    "lighteval|gsm8k": {
      "name": "gsm8k",
      "prompt_function": "gsm8k",
      "hf_repo": "gsm8k",
      "hf_subset": "main",
      "metric": [
        {
          "metric_name": "qem",
          "higher_is_better": true,
          "category": "3",
          "use_case": "5",
          "sample_level_fn": "compute",
          "corpus_level_fn": "mean"
        },
        {
          "metric_name": "maj@8",
          "higher_is_better": true,
          "category": "5",
          "use_case": "5",
          "sample_level_fn": "compute",
          "corpus_level_fn": "mean"
        }
      ],
      "hf_avail_splits": [
        "train",
        "test"
      ],
      "evaluation_splits": [
        "test"
      ],
      "few_shots_split": null,
      "few_shots_select": "random_sampling_from_train",
      "generation_size": 256,
      "generation_grammar": null,
      "stop_sequence": [
        "Question="
      ],
      "output_regex": null,
      "num_samples": null,
      "frozen": false,
      "suite": [
        "lighteval"
      ],
      "original_num_docs": 1319,
      "effective_num_docs": 1,
      "trust_dataset": true,
      "must_remove_duplicate_docs": null,
      "version": 0
    }
  },
  "summary_tasks": {
    "lighteval|gsm8k|0": {
      "hashes": {
        "hash_examples": "8517d5bf7e880086",
        "hash_full_prompts": "8517d5bf7e880086",
        "hash_input_tokens": "29916e7afe5cb51d",
        "hash_cont_tokens": "37f91ce23ef6d435"
      },
      "truncated": 2,
      "non_truncated": 0,
      "padded": 0,
      "non_padded": 2,
      "effective_few_shots": 0.0,
      "num_truncated_few_shots": 0
    }
  },
  "summary_general": {
    "hashes": {
      "hash_examples": "5f383c395f01096e",
      "hash_full_prompts": "5f383c395f01096e",
      "hash_input_tokens": "ac933feb14f96d7b",
      "hash_cont_tokens": "9d03fb26f8da7277"
    },
    "truncated": 2,
    "non_truncated": 0,
    "padded": 0,
    "non_padded": 2,
    "num_truncated_few_shots": 0
  }
}
```