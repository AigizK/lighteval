import asyncio
from typing import Coroutine, List, Optional, Union

import torch
from huggingface_hub import (
    AsyncInferenceClient,
    InferenceClient,
    InferenceEndpoint,
    create_inference_endpoint,
    get_inference_endpoint,
)
from huggingface_hub.inference._text_generation import TextGenerationResponse
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers import AutoTokenizer

from lighteval.data import GenerativeTaskDataset, LoglikelihoodDataset
from lighteval.logging.hierarchical_logger import hlog, hlog_warn
from lighteval.models.abstract_model import LightevalModel
from lighteval.models.model_config import EnvConfig, InferenceEndpointModelConfig, InferenceModelConfig
from lighteval.models.model_output import GenerateReturn, LoglikelihoodReturn, LoglikelihoodSingleTokenReturn
from lighteval.tasks.requests import (
    GreedyUntilRequest,
    GreedyUntilWithLogitsRequest,
    LoglikelihoodRequest,
    LoglikelihoodRollingRequest,
    LoglikelihoodSingleTokenRequest,
)
from lighteval.utils import as_list


DATASET_SPLITS = 4
BATCH_SIZE = 50


class InferenceEndpointModel(LightevalModel):
    """InferenceEndpointModels can be used both with the free inference client, or with inference
    endpoints, which will use text-generation-inference to deploy your model for the duration of the evaluation.
    """

    _DEFAULT_MAX_LENGTH = 2048

    def __init__(
        self, config: Union[InferenceEndpointModelConfig, InferenceModelConfig], env_config: EnvConfig
    ) -> None:
        if isinstance(config, InferenceEndpointModelConfig):
            if config.should_reuse_existing:
                self.endpoint = get_inference_endpoint(name=config.name, token=env_config.token)
            else:
                self.endpoint: InferenceEndpoint = create_inference_endpoint(
                    name=config.name,
                    repository=config.repository,
                    framework=config.framework,
                    task="text-generation",
                    accelerator=config.accelerator,
                    vendor=config.vendor,
                    region=config.region,
                    type=config.endpoint_type,
                    instance_size=config.instance_size,
                    instance_type=config.instance_type,
                    token=env_config.token,
                    custom_image={
                        "health_route": "/health",
                        "env": {
                            "MAX_BATCH_PREFILL_TOKENS": "2048",
                            "MAX_INPUT_LENGTH": "1024",
                            "MAX_TOTAL_TOKENS": "1512",
                            "MODEL_ID": "/repository",
                        },
                        "url": "ghcr.io/huggingface/text-generation-inference:1.1.0",
                    },
                )
            hlog("Deploying your endpoint. Please wait.")
            self.endpoint.wait(timeout=600)  # Waits for the endpoint to be deployed
            hlog("Endpoint successfully deployed!")
            self.name = config.repository
            self.revision = self.endpoint.revision
            self.async_client: AsyncInferenceClient = self.endpoint.async_client
            self.client: InferenceClient = self.endpoint.client

        else:  # Free inference client
            self.endpoint = None
            self.name = config.model
            self.revision = "default"
            self.async_client = AsyncInferenceClient(model=config.model, token=env_config.token)
            self.client = InferenceClient(model=config.model, token=env_config.token)

        self.use_async = False  # for debug - async use is faster

        self.tokenizer = AutoTokenizer.from_pretrained(self.name)

    def cleanup(self):
        if self.endpoint is not None:
            self.endpoint.delete()
            hlog_warn(
                "You deleted your endpoint after using it. You'll need to create it again if you need to reuse it."
            )

    def max_length(self):
        if self._max_length is not None:
            return self._max_length

        if hasattr(self.tokenizer, "model_max_length"):
            self._max_length = self.tokenizer.model_max_length
        else:
            self._max_length = self._DEFAULT_MAX_LENGTH
        return self._max_length

    def tok_encode(self, str_to_encode: str | list[str], add_special_tokens: Optional[bool] = None):
        if add_special_tokens is None:
            add_special_tokens = False
        if isinstance(str_to_encode, str):
            return self.tokenizer.encode(str_to_encode, add_special_tokens=add_special_tokens)
        return self.tokenizer(
            str_to_encode,
            padding=True,
            add_special_tokens=add_special_tokens,
            return_tensors="pt",
        )

    def tok_decode(self, tokens: torch.LongTensor) -> list[str]:
        return self.tokenizer.batch_decode(tokens, skip_special_tokens=True)

    def __async_process_request(
        self, context: str, stop_tokens: list[str], max_tokens: int
    ) -> Coroutine[None, list[TextGenerationResponse], str]:
        # Todo: add an option to launch with conversational instead for chat prompts
        # https://huggingface.co/docs/huggingface_hub/v0.20.3/en/package_reference/inference_client#huggingface_hub.AsyncInferenceClient.conversational
        generated_text = self.async_client.text_generation(
            prompt=context,
            details=True,
            decoder_input_details=True,
            max_new_tokens=max_tokens,
            stop_sequences=stop_tokens,
            # truncate=,
        )

        return generated_text

    def __process_request(self, context: str, stop_tokens: list[str], max_tokens: int) -> TextGenerationResponse:
        # Todo: add an option to launch with conversational instead for chat prompts
        # https://huggingface.co/docs/huggingface_hub/v0.20.3/en/package_reference/inference_client#huggingface_hub.AsyncInferenceClient.conversational
        generated_text = self.client.text_generation(
            prompt=context,
            details=True,
            decoder_input_details=True,
            max_new_tokens=max_tokens,
            stop_sequences=stop_tokens,
            # truncate=,
        )

        return generated_text

    async def __async_process_batch_generate(
        self,
        requests: list[GreedyUntilRequest | GreedyUntilWithLogitsRequest],
    ) -> list[TextGenerationResponse]:
        return await asyncio.gather(
            *[
                self.__async_process_request(
                    context=request.context,
                    stop_tokens=as_list(request.stop_sequence),
                    max_tokens=request.generation_size,
                )
                for request in requests
            ]
        )

    def __process_batch_generate(
        self,
        requests: list[GreedyUntilRequest | GreedyUntilWithLogitsRequest],
    ) -> list[TextGenerationResponse]:
        return [
            self.__process_request(
                context=request.context,
                stop_tokens=as_list(request.stop_sequence),
                max_tokens=request.generation_size,
            )
            for request in requests
        ]

    async def __async_process_batch_logprob(
        self, requests: list[LoglikelihoodRequest], rolling: bool = False
    ) -> list[TextGenerationResponse]:
        return await asyncio.gather(
            *[
                self.__async_process_request(
                    context=request.context if rolling else request.context + request.choice,
                    stop_tokens=[],
                    max_tokens=1,
                )
                for request in requests
            ]
        )

    def __process_batch_logprob(
        self, requests: list[LoglikelihoodRequest], rolling: bool = False
    ) -> list[TextGenerationResponse]:
        return [
            self.__process_request(
                context=request.context if rolling else request.context + request.choice,
                stop_tokens=[],
                max_tokens=1,
            )
            for request in requests
        ]

    def greedy_until_with_logits(
        self,
        requests: list[GreedyUntilWithLogitsRequest],
        disable_tqdm: bool = False,
        override_bs: Optional[int] = None,
        dataset_splits: int = 4,
    ) -> list[GenerateReturn]:
        """
        Generates sequences greedily until a stopping condition is met,
        returning both the generated sequences and the logits.

        Args:
            requests (list[tuple[str, dict]]): A list of input requests,
                where each request is a tuple containing a prompt string and a dictionary of additional parameters.
            disable_tqdm (bool, optional): Whether to disable the tqdm progress bar. Defaults to False.
            override_bs (Optional[int], optional): Overrides the batch size for generation. Defaults to None.
            dataset_splits (int, optional): Number of splits to divide the dataset into for parallel generation. Defaults to 4.

        Returns:
            list[GenerateReturn]: A list of GenerateReturn objects,
                where each object contains the generated sequence and the corresponding logits.
        """

        return self.greedy_until(
            requests,
            returns_logits=True,
            disable_tqdm=disable_tqdm,
            override_bs=override_bs,
            dataset_splits=dataset_splits,
        )

    def greedy_until(
        self,
        requests: List[GreedyUntilRequest],
        returns_logits: bool = False,
        disable_tqdm: bool = False,
        override_bs: Optional[int] = None,
    ) -> List[GenerateReturn]:
        for request in requests:
            request.stop_sequence = request.stop_sequence + [self.tokenizer.eos_token]

        dataset = GenerativeTaskDataset(requests=requests, dataset_splits=DATASET_SPLITS)
        batch_size = override_bs if override_bs is not None else BATCH_SIZE
        results: List[str] = []

        for _, _ in tqdm(
            dataset.splits_start_end_iterator(), total=DATASET_SPLITS, desc="Splits", position=0, disable=disable_tqdm
        ):
            dataloader = DataLoader(dataset, batch_size=batch_size, collate_fn=lambda batch: batch)

            for batch in tqdm(dataloader, desc="Greedy generation", position=1, leave=False, disable=disable_tqdm):
                if self.use_async:
                    responses = asyncio.run(self.__async_process_batch_generate(batch, returns_logits))
                else:
                    responses = self.__process_batch_generate(batch, returns_logits)
                for response in responses:
                    results.append(
                        GenerateReturn(
                            result=response.generated_text,
                            logits=[item.logprob for item in response.details.prefill] if returns_logits else None,
                            truncated_tokens_count=-1,
                            padded_tokens_count=-1,
                        )
                    )

        return results

    def loglikelihood(
        self, requests: list[LoglikelihoodRequest], disable_tqdm: bool = False, override_bs: Optional[int] = None
    ) -> list[LoglikelihoodReturn]:
        for request in requests:
            request.tokenized_context = self.tok_encode(request.context)
            request.tokenized_continuation = self.tok_encode(request.choice)
        dataset = LoglikelihoodDataset(requests=requests, dataset_splits=DATASET_SPLITS)
        batch_size = override_bs if override_bs is not None else BATCH_SIZE
        results: List[str] = []

        for _, _ in tqdm(
            dataset.splits_start_end_iterator(), total=DATASET_SPLITS, desc="Splits", position=0, disable=disable_tqdm
        ):
            dataloader = DataLoader(dataset, batch_size=batch_size, collate_fn=lambda batch: batch)

            for batch in tqdm(dataloader, desc="Loglikleihoods", position=1, leave=False, disable=disable_tqdm):
                if self.use_async:
                    responses = asyncio.run(self.__async_process_batch_logprob(batch))
                else:
                    responses = self.__process_batch_logprob(batch)
                for ix, response in enumerate(responses):
                    len_choice = len(batch[ix].tokenized_continuation)
                    results.append(
                        LoglikelihoodReturn(
                            result=[
                                t.logprob for t in response.details.prefill[-len_choice:] if t.logprob is not None
                            ],
                            input_tokens=[t.id for t in response.details.prefill[:-len_choice]],
                            generated_tokens=[t.id for t in response.details.prefill[-len_choice:]],
                            truncated_tokens_count=-1,
                            padded_tokens_count=-1,
                        )
                    )

        return results

    def loglikelihood_rolling(
        self, requests: list[LoglikelihoodRollingRequest], disable_tqdm: bool = False, override_bs=None
    ) -> list[LoglikelihoodReturn]:
        """This function is used to compute the log likelihood of the context for perplexity metrics."""
        for request in requests:
            request.tokenized_context = [self.tokenizer.eos_token_id]
            request.tokenized_continuation = self.tok_encode(request.context)

        dataset = LoglikelihoodDataset(requests=requests, dataset_splits=DATASET_SPLITS)
        batch_size = override_bs if override_bs is not None else BATCH_SIZE
        results: List[str] = []

        for _, _ in tqdm(
            dataset.splits_start_end_iterator(), total=DATASET_SPLITS, desc="Splits", position=0, disable=disable_tqdm
        ):
            dataloader = DataLoader(dataset, batch_size=batch_size, collate_fn=lambda batch: batch)

            for batch in tqdm(dataloader, desc="Loglikleihoods", position=1, leave=False, disable=disable_tqdm):
                if self.use_async:
                    responses = asyncio.run(self.__async_process_batch_logprob(batch, rolling=True))
                else:
                    responses = self.__process_batch_logprob(batch, rolling=True)
                for response in responses:
                    results.append(
                        LoglikelihoodReturn(
                            result=[t.logprob for t in response.details.tokens[:-1]],
                            input_tokens=[t.id for t in response.details.prefill],
                            generated_tokens=[t.id for t in response.details.tokens[:-1]],
                            truncated_tokens_count=-1,
                            padded_tokens_count=-1,
                        )
                    )

        return results

    def loglikelihood_single_token(
        self,
        requests: list[LoglikelihoodSingleTokenRequest],
        disable_tqdm: bool = False,
        override_bs: Optional[int] = None,
    ) -> list[LoglikelihoodSingleTokenReturn]:
        raise ValueError("Endpoint models can't use single token metrics. Change the metric to the standard version")