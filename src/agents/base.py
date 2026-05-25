"""Base class for all agents."""
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel

from src.config.settings import get_settings
from src.llm.router import get_llm
from src.utils.logging import get_logger

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """All agents inherit from this.

    Generics let each subclass declare its input and output types,
    so the IDE knows exactly what `.run()` accepts and returns.
    """

    name: str = "base"

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> None:
        settings = get_settings()
        self.provider = provider or settings.default_llm_provider
        self.model = model
        self.temperature = temperature

        self.logger = get_logger(f"agent.{self.name}")
        self.llm: BaseChatModel = get_llm(
            provider=self.provider,
            model=self.model,
            temperature=self.temperature,
        )

        self.logger.info(
            "agent.init",
            agent=self.name,
            provider=self.provider,
            model=self.model,
        )

    @abstractmethod
    def run(self, input_data: InputT) -> OutputT:
        """Execute the agent. Each subclass implements this."""
        ...