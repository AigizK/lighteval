# MIT License

# Copyright (c) 2024 The HuggingFace Team

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import copy
import json
import os
import re
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from tempfile import TemporaryDirectory

import torch
from datasets import Dataset, load_dataset
from datasets.utils.metadata import MetadataConfigs
from huggingface_hub import DatasetCard, DatasetCardData, HfApi, hf_hub_url

from lighteval.logging.hierarchical_logger import hlog, hlog_warn
from lighteval.logging.info_loggers import (
    DetailsLogger,
    GeneralConfigLogger,
    MetricsLogger,
    TaskConfigLogger,
    VersionsLogger,
)
from lighteval.utils.imports import NO_TENSORBOARDX_WARN_MSG, is_nanotron_available, is_tensorboardX_available
from lighteval.utils.io import FsspecDataResource
from lighteval.utils.utils import obj_to_markdown


if is_nanotron_available():
    from nanotron.config import GeneralArgs


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Provides a proper json encoding for the loggers and trackers json dumps.
    Notably manages the json encoding of dataclasses.
    """

    def default(self, o):
        if is_dataclass(o):
            try:
                return asdict(o)
            except Exception:
                return str(o)
        if callable(o):
            return o.__name__
        if isinstance(o, torch.dtype):
            return str(o)
        if isinstance(o, Enum):
            return o.name
        return super().default(o)


class EvaluationTracker:
    """
    Keeps track of the overall evaluation process and relevant informations.

    The [`EvaluationTracker`] contains specific loggers for experiments details
    ([`DetailsLogger`]), metrics ([`MetricsLogger`]), task versions
    ([`VersionsLogger`]) as well as for the general configurations of both the
    specific task ([`TaskConfigLogger`]) and overall evaluation run
    ([`GeneralConfigLogger`]).  It compiles the data from these loggers and
    writes it to files, which can be published to the Hugging Face hub if
    requested.
    """

    details_logger: DetailsLogger
    metrics_logger: MetricsLogger
    versions_logger: VersionsLogger
    general_config_logger: GeneralConfigLogger
    task_config_logger: TaskConfigLogger
    hub_results_org: str

    def __init__(
        self,
        output_dir: str,
        save_results: bool,
        save_details: bool,
        save_tensorboard: bool,
        token: str = "",
        nanotron_run_info: "GeneralArgs" = None,
    ) -> None:
        """)
        Creates all the necessary loggers for evaluation tracking.

        Args:
            output_dir (str): Local folder path where you want results to be saved
            hub_results_org (str): The organisation to push the results to. See
                more details about the datasets organisation in
                [`EvaluationTracker.save`]
            push_results_to_hub (bool): If True, results are pushed to the hub.
                Results will be pushed either to `{hub_results_org}/results`, a public dataset, if `public` is True else to `{hub_results_org}/private-results`, a private dataset.
            push_details_to_hub (bool): If True, details are pushed to the hub.
                Results are pushed to `{hub_results_org}/details__{sanitized model_name}` for the model `model_name`, a public dataset,
                if `public` is True else `{hub_results_org}/details__{sanitized model_name}_private`, a private dataset.
            push_results_to_tensorboard (bool): If True, will create and push the results for a tensorboard folder on the hub
            public (bool): If True, results and details are pushed in private orgs
            token (str): Token to use when pushing to the hub. This token should
                have write access to `hub_results_org`.
            nanotron_run_info (GeneralArgs): Reference to informations about Nanotron models runs
        """
        self.details_logger = DetailsLogger()
        self.metrics_logger = MetricsLogger()
        self.versions_logger = VersionsLogger()
        self.general_config_logger = GeneralConfigLogger()
        self.task_config_logger = TaskConfigLogger()

        self.api = HfApi(token=token)

        self.output_res = FsspecDataResource.from_uri(output_dir)
        self.save_results = save_results
        self.save_details = save_details
        self.save_tensorboard = save_tensorboard
        self.nanotron_run_info = nanotron_run_info

    def save(self) -> None:
        """Saves the experiment information and results to files, and to the hub if requested.
        Note:
            In case of save failure, this function will only print a warning, with the error message.

        Args:
            output_dir (str): Local folder path where you want results to be saved.
            save_results (bool): If True, results are saved to the specified logging URI.
            save_details (bool): If True, detailed results are saved to the specified logging URI.
            save_tensorboard (bool, optional): If True, tensorboard logs are saved to the specified logging URI. Defaults to False.
        """

        hlog("Saving experiment tracker")
        date_id = datetime.now().isoformat().replace(":", "-")
        config_general = copy.deepcopy(self.general_config_logger)
        config_general.config = (
            config_general.config.as_dict() if is_dataclass(config_general.config) else config_general.config
        )
        config_general = asdict(config_general)

        to_dump = {
            "config_general": config_general,
            "results": self.metrics_logger.metric_aggregated,
            "versions": self.versions_logger.versions,
            "config_tasks": self.task_config_logger.tasks_configs,
            "summary_tasks": self.details_logger.compiled_details,
            "summary_general": asdict(self.details_logger.compiled_details_over_all_tasks),
        }
        dumped = json.dumps(to_dump, cls=EnhancedJSONEncoder, indent=2, ensure_ascii=False)

        if self.save_results:
            output_results_res = self.output_res / "results" / self.general_config_logger.model_name
            hlog(f"Saving results to {output_results_res}")
            output_results_res.fs.mkdirs(output_results_res.path, exist_ok=True)
            output_results_file = output_results_res / f"results_{date_id}.json"
            with output_results_file.fs.open(output_results_file.path, "w") as f:
                f.write(dumped)

        if self.save_details:
            output_details_res = self.output_res / "details" / self.general_config_logger.model_name
            hlog(f"Saving details to {output_details_res}")
            output_details_res.fs.mkdirs(output_details_res.path, exist_ok=True)

            for task_name, task_details in self.details_logger.details.items():
                output_task_details_file = output_details_res / f"details_{task_name}_{date_id}.parquet"
                # Create a dataset from the dictionary
                try:
                    dataset = Dataset.from_list([asdict(detail) for detail in task_details])
                except Exception:
                    # We force cast to str to avoid formatting problems for nested objects
                    dataset = Dataset.from_list(
                        [{k: str(v) for k, v in asdict(detail).items()} for detail in task_details]
                    )

                # We don't keep 'id' around if it's there
                column_names = dataset.column_names
                if "id" in dataset.column_names:
                    column_names = [t for t in dataset.column_names if t != "id"]

                # Sort column names to make it easier later
                dataset = dataset.select_columns(sorted(column_names))
                # Save the dataset to a Parquet file
                with output_task_details_file.fs.open(output_task_details_file.path, "wb") as f:
                    dataset.to_parquet(f)

        if self.save_tensorboard:
            self.push_to_tensorboard(
                results=self.metrics_logger.metric_aggregated, details=self.details_logger.details
            )

    def generate_final_dict(self) -> dict:
        """Aggregates and returns all the logger's experiment information in a dictionary.

        This function should be used to gather and display said information at the end of an evaluation run.
        """
        to_dump = {
            "config_general": asdict(self.general_config_logger),
            "results": self.metrics_logger.metric_aggregated,
            "versions": self.versions_logger.versions,
            "config_tasks": self.task_config_logger.tasks_configs,
            "summary_tasks": self.details_logger.compiled_details,
            "summary_general": asdict(self.details_logger.compiled_details_over_all_tasks),
        }

        final_dict = {
            k: {eval_name.replace("|", ":"): eval_score for eval_name, eval_score in v.items()}
            for k, v in to_dump.items()
        }

        return final_dict

    def recreate_metadata_card(self, repo_id: str) -> None:  # noqa: C901
        """Fully updates the details repository metadata card for the currently evaluated model

        Args:
            repo_id (str): Details dataset repository path on the hub (`org/dataset`)
        """
        # Add a nice dataset card and the configuration YAML
        files_in_repo = self.api.list_repo_files(repo_id=repo_id, repo_type="dataset")
        results_files = [f for f in files_in_repo if ".json" in f]
        parquet_files = [f for f in files_in_repo if ".parquet" in f]
        multiple_results = len(results_files) > 1

        # Get last eval results date for each task (evals might be non overlapping)
        last_eval_date_results = {}
        for sub_file in parquet_files:
            # We focus on details only
            if "results_" in sub_file:
                continue

            # subfile have this general format:
            # `2023-09-03T10-57-04.203304/details_harness|hendrycksTest-us_foreign_policy|5_2023-09-03T10-57-04.203304.parquet`
            # in the iso date, the `:` are replaced by `-` because windows does not allow `:` in their filenames
            task_name = (
                os.path.basename(sub_file).replace("details_", "").split("_202")[0]
            )  # 202 for dates, 2023, 2024, ...
            # task_name is then equal to `leaderboard|mmlu:us_foreign_policy|5`

            # to be able to parse the filename as iso dates, we need to re-replace the `-` with `:`
            # iso_date[13] = iso_date[16] = ':'
            dir_name = os.path.dirname(sub_file)
            iso_date = ":".join(dir_name.rsplit("-", 2))
            eval_date = datetime.fromisoformat(iso_date)

            last_eval_date_results[task_name] = (
                max(last_eval_date_results[task_name], eval_date) if task_name in last_eval_date_results else eval_date
            )

        max_last_eval_date_results = list(last_eval_date_results.values())[0]
        # Now we convert them in iso-format
        for task in last_eval_date_results:
            if max_last_eval_date_results < last_eval_date_results[task]:
                max_last_eval_date_results = last_eval_date_results[task]
            last_eval_date_results[task] = last_eval_date_results[task].isoformat()
        max_last_eval_date_results = max_last_eval_date_results.isoformat()

        # Add the YAML for the configs
        card_metadata = MetadataConfigs()

        # Add the results config and add the result file as a parquet file
        for sub_file in parquet_files:
            if "results_" in sub_file:
                eval_date = os.path.basename(sub_file).replace("results_", "").replace(".parquet", "")
                sanitized_task = "results"
                sanitized_last_eval_date_results = re.sub(r"[^\w\.]", "_", max_last_eval_date_results)
                repo_file_name = os.path.basename(sub_file)
            else:
                task_name = os.path.basename(sub_file).replace("details_", "").split("_2023")[0].split("_2024")[0]
                sanitized_task = re.sub(r"\W", "_", task_name)
                eval_date = os.path.dirname(sub_file)
                sanitized_last_eval_date_results = re.sub(r"[^\w\.]", "_", last_eval_date_results[task_name])
                repo_file_name = os.path.join("**", os.path.basename(sub_file))

            sanitized_eval_date = re.sub(r"[^\w\.]", "_", eval_date)

            if multiple_results:
                if sanitized_task not in card_metadata:
                    card_metadata[sanitized_task] = {
                        "data_files": [{"split": sanitized_eval_date, "path": [repo_file_name]}]
                    }
                else:
                    former_entry = card_metadata[sanitized_task]
                    card_metadata[sanitized_task] = {
                        "data_files": former_entry["data_files"]
                        + [{"split": sanitized_eval_date, "path": [repo_file_name]}]
                    }
            else:
                if sanitized_task in card_metadata:
                    raise ValueError(
                        f"Entry for {sanitized_task} already exists in {former_entry} for repo {repo_id} and file {sub_file}"
                    )
                card_metadata[sanitized_task] = {
                    "data_files": [{"split": sanitized_eval_date, "path": [repo_file_name]}]
                }

            if sanitized_eval_date == sanitized_last_eval_date_results:
                all_entry = card_metadata[sanitized_task]["data_files"]
                card_metadata[sanitized_task] = {
                    "data_files": all_entry + [{"split": "latest", "path": [repo_file_name]}]
                }

            if "results_" in sub_file:
                continue

            # Special case for MMLU with a single split covering it all
            # We add another config with all MMLU splits results together for easy inspection
            SPECIAL_TASKS = [
                "lighteval|mmlu",
                "original|mmlu",
            ]
            for special_task in SPECIAL_TASKS:
                sanitized_special_task = re.sub(r"\W", "_", special_task)
                if sanitized_special_task in sanitized_task:
                    task_info = task_name.split("|")
                    # We have few-shot infos, let's keep them in our special task name
                    if len(task_info) == 3:
                        sanitized_special_task += f"_{task_info[-1]}"
                    elif len(task_info) == 4:
                        sanitized_special_task += f"_{task_info[-2]}_{task_info[-1]}"
                    if sanitized_special_task not in card_metadata:
                        card_metadata[sanitized_special_task] = {
                            "data_files": [{"split": sanitized_eval_date, "path": [repo_file_name]}]
                        }
                    else:
                        former_entry = card_metadata[sanitized_special_task]["data_files"]
                        # Any entry for this split already?
                        try:
                            split_index = next(
                                index
                                for index, dictionary in enumerate(former_entry)
                                if dictionary.get("split", None) == sanitized_eval_date
                            )
                        except StopIteration:
                            split_index = None
                        if split_index is None:
                            card_metadata[sanitized_special_task] = {
                                "data_files": former_entry + [{"split": sanitized_eval_date, "path": [repo_file_name]}]
                            }
                        else:
                            former_entry[split_index]["path"] += [repo_file_name]
                            card_metadata[sanitized_special_task] = {"data_files": former_entry}

                    if sanitized_eval_date == sanitized_last_eval_date_results:
                        former_entry = card_metadata[sanitized_special_task]["data_files"]
                        try:
                            split_index = next(
                                index
                                for index, dictionary in enumerate(former_entry)
                                if dictionary.get("split", None) == "latest"
                            )
                        except StopIteration:
                            split_index = None
                        if split_index is None:
                            card_metadata[sanitized_special_task] = {
                                "data_files": former_entry + [{"split": "latest", "path": [repo_file_name]}]
                            }
                        else:
                            former_entry[split_index]["path"] += [repo_file_name]
                            card_metadata[sanitized_special_task] = {"data_files": former_entry}

        # Cleanup a little the dataset card
        # Get the top results
        last_results_file = [f for f in results_files if max_last_eval_date_results.replace(":", "-") in f][0]
        last_results_file_path = hf_hub_url(repo_id=repo_id, filename=last_results_file, repo_type="dataset")
        f = load_dataset("json", data_files=last_results_file_path, split="train")
        results_dict = f["results"][0]
        new_dictionary = {"all": results_dict}
        new_dictionary.update(results_dict)
        results_string = json.dumps(new_dictionary, indent=4)

        # If we are pushing to the Oppen LLM Leaderboard, we'll store specific data in the model card.
        is_open_llm_leaderboard = repo_id.split("/")[0] == "open-llm-leaderboard"
        if is_open_llm_leaderboard:
            org_string = (
                "on the [Open LLM Leaderboard](https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard)."
            )
            leaderboard_url = "https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard"
            point_of_contact = "clementine@hf.co"
        else:
            org_string = ""
            leaderboard_url = None
            point_of_contact = None

        card_data = DatasetCardData(
            dataset_summary=f"Dataset automatically created during the evaluation run of model "
            f"[{self.general_config_logger.model_name}](https://huggingface.co/{self.general_config_logger.model_name})"
            f"{org_string}.\n\n"
            f"The dataset is composed of {len(card_metadata) - 1} configuration, each one coresponding to one of the evaluated task.\n\n"
            f"The dataset has been created from {len(results_files)} run(s). Each run can be found as a specific split in each "
            f'configuration, the split being named using the timestamp of the run.The "train" split is always pointing to the latest results.\n\n'
            f'An additional configuration "results" store all the aggregated results of the run.\n\n'
            f"To load the details from a run, you can for instance do the following:\n"
            f'```python\nfrom datasets import load_dataset\ndata = load_dataset("{repo_id}",\n\t"{sanitized_task}",\n\tsplit="train")\n```\n\n'
            f"## Latest results\n\n"
            f'These are the [latest results from run {max_last_eval_date_results}]({last_results_file_path.replace("/resolve/", "/blob/")})'
            f"(note that their might be results for other tasks in the repos if successive evals didn't cover the same tasks. "
            f'You find each in the results and the "latest" split for each eval):\n\n'
            f"```python\n{results_string}\n```",
            repo_url=f"https://huggingface.co/{self.general_config_logger.model_name}",
            pretty_name=f"Evaluation run of {self.general_config_logger.model_name}",
            leaderboard_url=leaderboard_url,
            point_of_contact=point_of_contact,
        )

        card_metadata.to_dataset_card_data(card_data)
        card = DatasetCard.from_template(
            card_data,
            pretty_name=card_data.pretty_name,
        )
        card.push_to_hub(repo_id, repo_type="dataset")

    def push_to_tensorboard(  # noqa: C901
        self, results: dict[str, dict[str, float]], details: dict[str, DetailsLogger.CompiledDetail]
    ):
        if not is_tensorboardX_available:
            hlog_warn(NO_TENSORBOARDX_WARN_MSG)
            return

        if not is_nanotron_available():
            hlog_warn("You cannot push results to tensorboard without having nanotron installed. Skipping")
            return

        from tensorboardX import SummaryWriter

        prefix = self.tensorboard_metric_prefix

        if self.nanotron_run_info is not None:
            global_step = self.nanotron_run_info.step
            run = f"{self.nanotron_run_info.run}_{prefix}"
        else:
            global_step = 0
            run = prefix

        with TemporaryDirectory() as tmp_dir:
            tb_context = SummaryWriter(
                logdir=tmp_dir,
            )
            bench_averages = {}
            for name, values in results.items():
                splited_name = name.split("|")
                if len(splited_name) == 3:
                    _, task_name, _ = splited_name
                else:
                    task_name = name
                bench_suite = None
                if ":" in task_name:
                    bench_suite = task_name.split(":")[0]  # e.g. MMLU
                    hlog(f"bench_suite {bench_suite} in {task_name}")
                    for metric, value in values.items():
                        if "stderr" in metric:
                            continue
                        if bench_suite not in bench_averages:
                            bench_averages[bench_suite] = {}
                        bench_averages[bench_suite][metric] = bench_averages[bench_suite].get(metric, []) + [
                            float(value)
                        ]
                hlog(f"Pushing {task_name} {values} to tensorboard")
                for metric, value in values.items():
                    if "stderr" in metric:
                        tb_context.add_scalar(f"stderr_{prefix}/{task_name}/{metric}", value, global_step=global_step)
                    elif bench_suite is not None:
                        tb_context.add_scalar(
                            f"{prefix}_{bench_suite}/{task_name}/{metric}", value, global_step=global_step
                        )
                    else:
                        tb_context.add_scalar(f"{prefix}/{task_name}/{metric}", value, global_step=global_step)
            # Tasks with subtasks
            for name, values in bench_averages.items():
                for metric, values in values.items():
                    hlog(f"Pushing average {name} {metric} {sum(values) / len(values)} to tensorboard")
                    tb_context.add_scalar(
                        f"{prefix}/{name}/{metric}", sum(values) / len(values), global_step=global_step
                    )

            tb_context.add_text("eval_config", obj_to_markdown(results), global_step=global_step)

            for task_name, task_details in details.items():
                tb_context.add_text(
                    f"eval_details_{task_name}",
                    obj_to_markdown({"0": task_details[0], "1": task_details[1] if len(task_details) > 1 else {}}),
                    global_step=global_step,
                )

            # We are doing parallel evaluations of multiple checkpoints and recording the steps not in order
            # This messes up with tensorboard, so the easiest is to rename files in the order of the checkpoints
            # See: https://github.com/tensorflow/tensorboard/issues/5958
            # But tensorboardX don't let us control the prefix of the files (only the suffix), so we need to do it ourselves before commiting the files

            tb_context.close()  # flushes the unfinished write operations
            time.sleep(5)
            files = os.listdir(tmp_dir)
            for file in files:
                os.rename(os.path.join(tmp_dir, file), os.path.join(tmp_dir, f"{global_step:07d}_{file}"))

            output_dir_tb = self.output_res / "tb" / run
            output_dir_tb.fs.mkdirs(output_dir_tb.path, exist_ok=True)
            for root, _, files in os.walk(tmp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    with output_dir_tb.fs.open(output_dir_tb / file, "wb") as output_f, open(
                        file_path, "rb"
                    ) as input_f:
                        output_f.write(input_f.read())

            hlog(f"Pushed to tensorboard at {output_dir_tb}" f"at global_step {global_step}")
