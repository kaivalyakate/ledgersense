import abc
import json
import os
from typing import Optional

CATEGORIZATION_TOOL_SCHEMA = {
    "name": "submit_categorization",
    "description": "Submit the categorization result for the transaction.",
    "input_schema": {
        "type": "object",
        "properties": {
            "predicted_category": {"type": "string", "description": "Chart-of-accounts category name"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
            "signals_used": {
                "type": "object",
                "properties": {
                    "vendor_pattern": {"type": "string"},
                    "amount_signal": {"type": "string"},
                    "similar_txns_influence": {"type": "string"},
                },
                "required": ["vendor_pattern", "amount_signal", "similar_txns_influence"],
            },
        },
        "required": ["predicted_category", "confidence", "reasoning", "signals_used"],
    },
}


class AgentProvider(abc.ABC):
    model_provider: str
    model_name: str

    @abc.abstractmethod
    def _run(self, prompt: str, tool: dict = None) -> dict: ...

    def categorize(self, vendor_name, description, amount, categories, similar_txns) -> dict:
        return self._run(_build_prompt(vendor_name, description, amount, categories, similar_txns))

    def respond_to_challenge(self, vendor_name, description, amount, categories, similar_txns,
                              original_category, original_reasoning, user_message) -> dict:
        return self._run(_build_challenge_prompt(
            vendor_name, description, amount, categories, similar_txns,
            original_category, original_reasoning, user_message,
        ))


def _build_prompt(vendor_name, description, amount, categories, similar_txns) -> str:
    cats = "\n".join(f"  - {c}" for c in categories)
    similar = json.dumps(similar_txns, default=str) if similar_txns else "none"
    return f"""Categorize this transaction into one of the chart-of-accounts categories below.

Transaction:
  Vendor: {vendor_name}
  Description: {description}
  Amount: ${amount}

Categories:
{cats}

Similar resolved transactions (for context):
{similar}

Use the submit_categorization tool to return your answer."""


def _build_challenge_prompt(vendor_name, description, amount, categories, similar_txns,
                             original_category, original_reasoning, user_message) -> str:
    cats = "\n".join(f"  - {c}" for c in categories)
    similar = json.dumps(similar_txns, default=str) if similar_txns else "none"
    return f"""A user is challenging a previous categorization. Review and either justify or revise it.

Transaction:
  Vendor: {vendor_name}
  Description: {description}
  Amount: ${amount}

Categories:
{cats}

Similar resolved transactions:
{similar}

Previous categorization: {original_category}
Previous reasoning: {original_reasoning}

User challenge: {user_message}

Use the submit_categorization tool to return your confirmed or revised categorization."""


class AnthropicProvider(AgentProvider):
    model_provider = "anthropic"

    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def _run(self, prompt: str, tool: dict = None) -> dict:
        import anthropic
        t = tool or CATEGORIZATION_TOOL_SCHEMA
        resp = self.client.messages.create(
            model=self.model_name,
            max_tokens=1024,
            tools=[t],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        raise ValueError("No tool_use block in Anthropic response")


class OpenAIProvider(AgentProvider):
    model_provider = "openai"

    def __init__(self):
        import openai
        self.client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")

    def _run(self, prompt: str, tool: dict = None) -> dict:
        t = tool or CATEGORIZATION_TOOL_SCHEMA
        func = {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}
        resp = self.client.chat.completions.create(
            model=self.model_name,
            tools=[{"type": "function", "function": func}],
            tool_choice={"type": "function", "function": {"name": t["name"]}},
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(resp.choices[0].message.tool_calls[0].function.arguments)


class MockProvider(AgentProvider):
    model_provider = "mock"
    model_name = "mock-v1"

    def _run(self, prompt: str, tool: dict = None) -> dict:
        if "answer the following question" in prompt.lower():
            return {
                "answer": "Mock answer: total spend was $1,234.56 across 42 transactions.",
                "follow_up_suggestions": [
                    "What was the largest single transaction?",
                    "Which vendor had the highest total spend?",
                    "How does this compare to last month?",
                ],
                "data_sufficient": True,
            }
        return {
            "predicted_category": "Cost of Goods Sold",
            "confidence": 0.92,
            "reasoning": "Mock: vendor pattern matches food supplier.",
            "signals_used": {
                "vendor_pattern": "Mock vendor signal",
                "amount_signal": "Mock amount signal",
                "similar_txns_influence": "Mock: 3 similar transactions resolved to COGS",
            },
        }


_PROVIDERS = {"anthropic": AnthropicProvider, "openai": OpenAIProvider, "mock": MockProvider}


def get_provider(name: Optional[str] = None) -> AgentProvider:
    key = name or os.environ.get("AGENT_PROVIDER", "mock")
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(f"Unknown provider '{key}'. Choose from: {list(_PROVIDERS)}")
    return cls()