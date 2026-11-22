import time
import threading
from typing import List, Dict

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer


# ============================================================
# LOCAL QWEN LLM
# ============================================================

_MODEL_ALIASES = {
    "qwen3:4b": "Qwen/Qwen3-4B",
    "Qwen3:4B": "Qwen/Qwen3-4B",
    "gpt-4o-mini": "Qwen/Qwen3-4B",
    "gpt-4o": "Qwen/Qwen3-4B",
    "gpt-4-turbo": "Qwen/Qwen3-4B",
    "gpt-4-turbo-preview": "Qwen/Qwen3-4B",
}


class _QwenBackend:
    def __init__(self, model_name: str, seed: int = None, temperature: float = None):
        self.model_name = _MODEL_ALIASES.get(model_name or "qwen3:4b", model_name)
        self.seed = seed
        self.temperature = temperature
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = (
            torch.bfloat16
            if self.device.type == "cuda" and torch.cuda.is_bf16_supported()
            else torch.float16
            if self.device.type == "cuda"
            else torch.float32
        )
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=self.dtype,
        ).to(self.device)
        self.model.eval()

    def _inputs(self, messages: List[Dict[str, str]]):
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        return self.tokenizer(prompt, return_tensors="pt").to(self.device)

    def _generation_kwargs(self):
        kwargs = {"max_new_tokens": 4096, "do_sample": self.temperature is not None}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.seed is not None:
            torch.manual_seed(self.seed)
        return kwargs

    def generate(self, messages: List[Dict[str, str]], stream: bool = False):
        inputs = self._inputs(messages)
        kwargs = self._generation_kwargs()
        if not stream:
            output = self.model.generate(**inputs, **kwargs)
            generated = output[0, inputs["input_ids"].shape[1]:]
            return self.tokenizer.decode(generated, skip_special_tokens=True), int(generated.shape[0])

        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )
        kwargs["streamer"] = streamer
        thread = threading.Thread(
            target=self.model.generate,
            kwargs={**inputs, **kwargs},
            daemon=True,
        )
        thread.start()
        response = "".join(streamer)
        thread.join()
        return response, len(self.tokenizer.encode(response, add_special_tokens=False))


class LLM:
    def __init__(
        self,
        model_name: str = "qwen3:4b",
        seed: int = None,
        temperature: float = None,
    ):
        self.backend = _QwenBackend(model_name, seed, temperature)
        self.model_name = self.backend.model_name

    def generate_response(self, messages: List[Dict[str, str]], stream: bool = False):
        start_time = time.time()
        try:
            response, token_usage = self.backend.generate(messages, stream)
            elapsed_time = time.time() - start_time
            print(f"\n[Response from local {self.model_name}]:\n{response}")
            print(f"[Response Time: {elapsed_time:.2f}s]")
            print(f"[Total Tokens: {token_usage}]")
            return response, elapsed_time, token_usage
        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"Error generating response from local model {self.model_name}: {e}")
            return f"Error: {e}", elapsed_time, 0


class LLM_stream(LLM):
    def generate_response(self, messages: List[Dict[str, str]], stream: bool = True):
        start_time = time.time()
        try:
            response, token_usage = self.backend.generate(messages, stream)
            if stream:
                print(response, end="", flush=True)
                print()
            elapsed_time = time.time() - start_time
            return response, elapsed_time, token_usage
        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"Error generating streaming response: {e}")
            return f"Error: {e}", elapsed_time, 0


# ============================================================
# AGENT
# ============================================================

class Agent:
    """
    Agent class representing an intelligent entity
    with a specific instructional role.
    """

    def __init__(
        self,
        name: str,
        role: str,
        llm: LLM,
        system_prompt: str = None,
        output_constraint: str = None
    ):
        """
        Initialize Agent.

        Args:
            name: Agent name
            role: Agent role description
            llm: Local LLM instance
            system_prompt: System prompt defining behavior
            output_constraint: Optional output constraints
        """

        self.name = name
        self.role = role
        self.llm = llm

        self.system_prompt = (
            system_prompt
            if system_prompt
            else f"You are {name}, {role}."
        )

        self.output_constraint = (
            output_constraint
        )

        self.message_history = []

    def reset_history(self):
        """Reset message history."""

        self.message_history = []

    def add_message_to_history(
        self,
        role: str,
        content: str
    ):
        """Add message to history."""

        self.message_history.append(
            {
                "role": role,
                "content": content
            }
        )

    def get_messages_with_system(
        self,
        prompt: str
    ) -> List[Dict[str, str]]:
        """
        Get complete message list including
        the agent's system prompt.
        """

        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            }
        ]

        if self.message_history:
            messages.extend(
                self.message_history
            )

        messages.append(
            {
                "role": "user",
                "content": prompt
            }
        )

        return messages

    def generate_response(
        self,
        prompt: str,
        stream: bool = True,
        save_to_history: bool = True
    ):
        """
        Generate an Agent response.
        """

        full_prompt = prompt

        if self.output_constraint:
            full_prompt += (
                f"\n\n{self.output_constraint}"
            )

        messages = (
            self.get_messages_with_system(
                full_prompt
            )
        )

        print(
            f"{'-' * 50}\n"
            f"{self.name} ({self.role}) "
            f"is thinking...\n"
        )

        response, elapsed_time, token_usage = (
            self.llm.generate_response(
                messages,
                stream
            )
        )

        if save_to_history:
            self.add_message_to_history(
                "user",
                prompt
            )

            self.add_message_to_history(
                "assistant",
                response
            )

        return (
            response,
            elapsed_time,
            token_usage
        )


# ============================================================
# DELIBERATION
# ============================================================

class Deliberation:
    """
    Manages interactions between multiple
    instructional agents.
    """

    def __init__(
        self,
        id: str,
        name: str,
        agents: List[Agent],
        summary_agent: Agent = None,
        max_rounds: int = 1,
        instruction_prompt: str = "",
        input_files=None,
        output_format: str = "md"
    ):
        """
        Initialize Deliberation.

        Args:
            id: Unique identifier
            name: Deliberation name
            agents: Participating agents
            summary_agent: Agent responsible for summary
            max_rounds: Number of discussion rounds
            instruction_prompt: Main instruction
            input_files: Additional input
            output_format: Expected output format
        """

        self.id = id
        self.name = name
        self.agents = agents
        self.max_rounds = max_rounds

        self.summary_agent = (
            summary_agent
            if summary_agent
            else agents[0]
        )

        self.discussion_history = []

        self.instruction_prompt = (
            instruction_prompt
        )

        self.input_files = input_files

        self.output_format = (
            output_format
        )

    def add_to_discussion(
        self,
        agent_name: str,
        content: str
    ):
        """Add content to discussion history."""

        self.discussion_history.append(
            {
                "agent": agent_name,
                "content": content
            }
        )

    def format_discussion_history(
        self
    ) -> str:
        """Format discussion history."""

        formatted = (
            "Discussion History:\n\n"
        )

        for entry in self.discussion_history:
            formatted += (
                f"{entry['agent']}: "
                f"{entry['content']}\n\n"
            )

        return formatted

    def run(
        self,
        current_context: str = None,
        user_suggestion: str = None
    ):
        """
        Run multi-agent deliberation.
        """

        print(
            f"\n{'=' * 50}\n"
            f"Starting Deliberation: "
            f"{self.name}\n"
            f"{'=' * 50}\n"
        )

        # Preserve behavior of the original implementation.
        file_contents = str(
            self.input_files
        )

        print(
            f"Instruction prompt: "
            f"{self.instruction_prompt}\n"
        )

        full_prompt = (
            self.instruction_prompt
        )

        if user_suggestion:
            full_prompt += (
                "\n\nUser Suggestion: "
                f"{user_suggestion}"
            )

        if current_context:
            full_prompt += (
                "\n\nCurrent Context:\n"
                f"{current_context}"
            )

        if file_contents:
            full_prompt += (
                "\n\nAdditional input "
                "from files:\n"
                f"{file_contents}"
            )

        current_prompt = full_prompt

        # Reset all agent histories.
        for agent in self.agents:
            agent.reset_history()

        # Clear discussion history.
        self.discussion_history = []

        elapsed_time = 0
        token_usage = 0

        # Main multi-agent discussion.
        for round_num in range(
            self.max_rounds
        ):
            print(
                f"\n{'-' * 50}\n"
                f"Round {round_num + 1} "
                f"of {self.max_rounds}\n"
                f"{'-' * 50}\n"
            )

            for agent in self.agents:

                if self.discussion_history:
                    agent_prompt = (
                        f"{current_prompt}\n\n"
                        f"{self.format_discussion_history()}"
                        "\n\nIt's now your turn "
                        "to provide your thoughts."
                    )

                else:
                    agent_prompt = (
                        current_prompt
                    )

                response, et, tu = (
                    agent.generate_response(
                        agent_prompt,
                        save_to_history=False
                    )
                )

                self.add_to_discussion(
                    agent.name,
                    response
                )

                elapsed_time += et
                token_usage += tu

        # Generate final summary of the deliberation.
        summary, et, tu = (
            self.summary_agent.generate_response(
                self.format_discussion_history(),
                save_to_history=False
            )
        )

        elapsed_time += et
        token_usage += tu

        print(
            f"\n{'=' * 50}\n"
            "Deliberation Complete\n"
            f"{'=' * 50}\n"
        )

        return (
            summary,
            elapsed_time,
            token_usage
        )