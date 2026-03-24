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
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        if output_schema:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "schema": output_schema,
                    "strict": True
                }
            }

        try:
            response = await client.chat.completions.create(**params)
            content = response.choices[0].message.content

            structured_data = None
            if output_schema:
                try:
                    structured_data = json.loads(content)
                    # Often the model might wrap the intended content in the required format.
                    # Or it just returns the JSON as text.
                except json.JSONDecodeError:
                    structured_data = {}
                    print("Warning: Failed to parse expected JSON output.")

            return content, structured_data

        except Exception as e:
            print(f"Error calling LLM: {e}")
            raise

llm_service = LLMService()