# Installation

You can install Lighteval either from PyPi or from source.

## From PyPi

```bash
pip install lighteval
```

## From source

```bash
git clone https://github.com/huggingface/lighteval.git
cd lighteval
pip install -e .
```

### Extras

Lighteval has optional dependencies that you can install by specifying the
appropriate extras group.
`pip install lighteval[<group>]` or `pip install -e .[<group>]`.

| extra name   | description                                                               |
|--------------|---------------------------------------------------------------------------|
| accelerate   | To use accelerate for model and data parallelism with transformers models |
| tgi          | To use Text Generation Inference API to evaluate your model               |
| nanotron     | To evaluate nanotron models                                               |
| quantization | To evaluate quantized models                                              |
| adapters     | To evaluate adapters models (delta and peft)                              |
| tensorboardX | To upload your results to tensorboard                                     |
| vllm         | To use vllm as backend for inference                                      |

## Hugging Face login

If you want to push your results to the Hugging Face Hub or evaluate your own
private models, don't forget to add your access token to the environment
variable `HF_TOKEN`. You can do this by running:

```bash
huggingface-cli login
```