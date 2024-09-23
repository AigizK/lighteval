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

from typing import Callable

from typing_extensions import NotRequired, TypedDict

from lighteval.tasks.requests import Doc
from lighteval.tasks.templates.utils.formatting_utils import capitalize, fix_ending_punct
from lighteval.tasks.templates.utils.formulation import Formulation, MCFFormulation, build_answers, build_options
from lighteval.tasks.templates.utils.translation_literals import TRANSLATION_LITERALS
from lighteval.tasks.templates.utils.utils import create_adapter_from_dict
from lighteval.utils.language import Language
from lighteval.utils.utils import as_list


MULTI_CHOICE_QA_QUERY = (
    "{instruction}{context}{question_word}{colon}{sentence_space}{question}\n{options}{answer_word}{colon}"
)


# NO idea how to ensure we have the same keys in these typedicts in python :(
class MCQInput(TypedDict):
    question: str
    choices: list[str]
    gold_idx: list[int] | int
    context: NotRequired[str]
    instruction: NotRequired[str]


class MCQDictAdapter(TypedDict):
    question: str
    choices: str
    gold_idx: str
    context: NotRequired[str]
    instruction: NotRequired[str]


# Python too dumb to do fancy inference :(


def get_mcq_prompt_function(
    language: Language,
    adapter: Callable[[dict], MCQInput] | MCQDictAdapter,
    formulation: Formulation = MCFFormulation(),
):
    """
    Create a templated prompt function for a Multiple Choice Question (MCQ) task.
    Example tasks:
    - ARC
    - TruthfulQA

    Format:
    Question: xxx
    Answer: | Answer

    Args:
        language (Language): The language of the MCQ task.
        adapter (Callable[[dict], MCQInput] | MCQDictAdapter): A function or dictionary to adapt the input data to the required MCQInput format.
            Must map data from the dataset row to the MCQInput format.
        formulation (Formulation, optional): The formulation to use for the task. Defaults to MCFFormulation().

    Returns:
        Callable: A function that generates MCQ prompts based on the given parameters.
    """

    adapter_fn: Callable[[dict], MCQInput] = (
        create_adapter_from_dict(adapter) if isinstance(adapter, dict) else adapter  # type: ignore
    )

    def prompt_fn(line, task_name: str):
        mcq_input = adapter_fn(line)
        translation_literals = TRANSLATION_LITERALS[language]

        instruction_val = mcq_input.get("instruction")
        instruction = f"{instruction_val}\n" if instruction_val else ""

        context_val = mcq_input.get("context")
        context = f"{capitalize(fix_ending_punct(context_val, translation_literals))}\n" if context_val else ""

        question = capitalize(fix_ending_punct(mcq_input["question"], translation_literals))
        answers = [capitalize(fix_ending_punct(answer, translation_literals)) for answer in mcq_input["choices"]]

        options = build_options(answers, formulation, translation_literals)
        options = f"{options}\n" if options else ""
        answers = build_answers(answers, formulation, translation_literals)

        answer_word = capitalize(translation_literals.answer)
        question_word = capitalize(translation_literals.question_word)

        query = MULTI_CHOICE_QA_QUERY.format(
            instruction=instruction,
            question=question,
            context=context,
            question_word=question_word,
            answer_word=answer_word,
            colon=translation_literals.colon,
            sentence_space=translation_literals.sentence_space,
            options=options,
        )

        return Doc(
            task_name=task_name,
            query=query,
            gold_index=as_list(mcq_input["gold_idx"]),
            choices=answers,
            instruction=instruction_val,
            unconditioned_query=f"{answer_word}{translation_literals.colon}",
        )

    return prompt_fn