import json
from openai import AsyncOpenAI
from app.core.config import settings
from typing import List, Dict, Any, Optional

client = AsyncOpenAI(api_key=settings.openai_api_key)

class LLMService:
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 1000,
        output_schema: Optional[Dict[str, Any]] = None
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        Generates a response from the LLM.
        If output_schema is provided, uses Structured Outputs.
        """
        params = {
            "model": model,
            "messages": messages
        }

        # Newer reasoning models (o1, o3, and likely gpt-5+) do not support 'max_tokens'
        # (they use 'max_completion_tokens' instead) and often reject 'temperature' entirely.
        is_reasoning_model = any(model.startswith(prefix) for prefix in ["o1", "o3", "gpt-5"])

        if is_reasoning_model:
            params["max_completion_tokens"] = max_tokens
        else:
            params["temperature"] = temperature
            params["max_tokens"] = max_tokens

        if output_schema:
            # We use tool calling instead of response_format so the AI can still
            # talk conversationally while deciding when to trigger the save action.
            params["tools"] = [{
                "type": "function",
                "function": {
                    "name": "save_structured_data",
                    "description": "Saves the extracted structured data. Call this when you have gathered all required information.",
                    "parameters": output_schema
                }
            }]
            # Optional: you could force it if you want, but auto is better for conversation
            params["tool_choice"] = "auto"

        try:
            response = await client.chat.completions.create(**params)
            message = response.choices[0].message
            content = message.content or ""

            structured_data = None

            if message.tool_calls:
                # If the AI decided to call the tool
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "save_structured_data":
                        try:
                            structured_data = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            print("Warning: Failed to parse tool arguments.")

            # If the model ONLY called a tool and returned no text, let's provide a generic confirmation
            if not content and structured_data:
                content = "I have successfully saved your information!"

            return content, structured_data

        except Exception as e:
            print(f"Error calling LLM: {e}")
            raise

llm_service = LLMService()