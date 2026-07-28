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
        output_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> tuple[str, Optional[Dict[str, Any]], Optional[str]]:
        """
        Generates a response from the LLM.
        Returns: (content_string, structured_data_dict, tool_name_called)
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
            params["tool_choice"] = "auto"
        elif tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        try:
            response = await client.chat.completions.create(**params)
            message = response.choices[0].message
            content = message.content or ""

            structured_data = None
            tool_name_called = None

            if message.tool_calls:
                # If the AI decided to call the tool
                for tool_call in message.tool_calls:
                    tool_name_called = tool_call.function.name
                    try:
                        parsed_args = json.loads(tool_call.function.arguments)
                        if tool_call.function.name == "save_structured_data":
                            structured_data = parsed_args
                        else:
                            # For other generic tools (like advance_to_demonstration), we can pass
                            # the arguments back via the structured_data dict so the backend can read 'rationale'
                            structured_data = parsed_args
                    except json.JSONDecodeError:
                        print("Warning: Failed to parse tool arguments.")

            # If the model ONLY called a tool and returned no text, don't override it with a generic
            # message if the tool itself contains a 'reply' string.
            if not content and structured_data:
                if "reply" in structured_data:
                    content = "" # Let chat_service pick up the reply
                else:
                    content = "I have successfully saved your information!"

            return content, structured_data, tool_name_called

        except Exception as e:
            print(f"Error calling LLM: {e}")
            raise

    async def generate_sub_objectives(
        self,
        lesson_context: str,
        model: str = "gpt-4o",
    ) -> List[str]:
        """Break a lesson goal into three short, sequenced assessment steps."""
        fallback_objectives = [
            "Identify the key idea in the lesson goal.",
            "Explain how the key idea works in a simple example.",
            "Apply the key idea independently to show understanding."
        ]

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You break a lesson learning objective into exactly three short, concrete, "
                            "sequenced sub-objectives for a formative assessment. Return only JSON "
                            "with this shape: {\"sub_objectives\": [\"...\", \"...\", \"...\"]}."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            "Create exactly three student-facing sub-objectives that build toward this lesson goal. "
                            "Each should be 12 words or fewer and should be assessable in conversation.\n\n"
                            f"{lesson_context}"
                        )
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=300
            )
            raw_content = response.choices[0].message.content or "{}"
            data = json.loads(raw_content)
            objectives = data.get("sub_objectives") or data.get("objectives") or []
            clean_objectives = [str(item).strip() for item in objectives if str(item).strip()]
            if len(clean_objectives) >= 3:
                return clean_objectives[:3]
        except Exception as e:
            print(f"Warning: Failed to generate assessment sub-objectives: {e}")

        return fallback_objectives

llm_service = LLMService()
