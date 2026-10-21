"""Provider adapter with bounded calls and one structured-format retry."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Protocol, TypeVar
from pydantic import BaseModel, ValidationError
from app.config import Settings

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parents[1] / "agent" / "prompts"


class ModelUnavailable(Exception):
    pass


class LLM(Protocol):
    async def complete(self, stage: str, payload: dict, output: type[T]) -> T: ...


class ProviderLLM:
    def __init__(self, settings: Settings):
        key = (
            settings.LLM_API_KEY.get_secret_value()
            or (
                settings.GROQ_API_KEY
                if settings.LLM_PROVIDER == "groq"
                else settings.GEMINI_API_KEY
            ).get_secret_value()
        )
        if not key or key.startswith("placeholder"):
            raise ValueError("Configure LLM_API_KEY or the selected provider key")
        self.timeout = settings.MODEL_TIMEOUT_SECONDS
        self.models = {}
        for stage, model in [
            ("router", settings.ROUTER_MODEL),
            ("sql_generator", settings.SQL_MODEL),
            ("answer", settings.ANSWER_MODEL),
        ]:
            if settings.LLM_PROVIDER == "groq":
                from langchain_groq import ChatGroq

                client = ChatGroq(
                    model=model,
                    api_key=key,
                    temperature=0,
                    timeout=self.timeout,
                    max_retries=0,
                )
            else:
                from langchain_google_genai import ChatGoogleGenerativeAI

                client = ChatGoogleGenerativeAI(
                    model=model,
                    google_api_key=key,
                    temperature=0,
                    timeout=self.timeout,
                    max_retries=0,
                )
            self.models[stage] = client

    async def complete(self, stage: str, payload: dict, output: type[T]) -> T:
        from langchain_core.messages import HumanMessage, SystemMessage

        system = (PROMPTS / f"{stage}.md").read_text()
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=json.dumps(payload, default=str)),
        ]
        for attempt in range(2):
            try:
                async with asyncio.timeout(self.timeout):
                    result = (
                        await self.models[stage]
                        .with_structured_output(output)
                        .ainvoke(messages)
                    )
                return output.model_validate(result)
            except (ValidationError, ValueError) as exc:
                if attempt:
                    raise ModelUnavailable("Invalid structured model output") from exc
                messages.append(
                    HumanMessage(
                        content="Return valid output matching the requested schema. Do not change the task."
                    )
                )
            except Exception as exc:
                logger.warning(
                    "model_call_failed stage=%s error_type=%s",
                    stage,
                    type(exc).__name__,
                )
                raise ModelUnavailable("Model service unavailable") from exc
        raise ModelUnavailable("Invalid model output")

    async def close(self):
        # Close SDK-owned transports where exposed; never create clients per request.
        for model in self.models.values():
            client = getattr(model, "async_client", None)
            root = getattr(client, "_client", None)
            if root is not None and hasattr(root, "close"):
                await root.close()
