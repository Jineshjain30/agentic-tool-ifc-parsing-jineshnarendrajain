#!/usr/bin/env python3
"""
Simple tool example for use with Google Gemini API.
This demonstrates how to define and use function calling with Gemini.
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from calculator_tool import calculate, calculate_tool


def _safe_args(args: object) -> dict[str, object]:
    """Normalize function-call args to a plain dictionary."""
    if isinstance(args, dict):
        return args

    try:
        return dict(args)  # type: ignore[arg-type]
    except Exception:
        return {}


def _generate_with_retry(
    client: genai.Client,
    model: str,
    contents: list[types.Content],
    tools: list[types.Tool],
    attempts: int = 5,
) -> types.GenerateContentResponse:
    """Retry transient 503 errors with exponential backoff."""
    delay_seconds = 1
    for attempt in range(1, attempts + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(tools=tools),
            )
        except errors.ServerError as exc:
            is_transient = exc.code == 503
            if not is_transient or attempt == attempts:
                raise

            print(
                f"Gemini temporarily unavailable (503). Retrying in {delay_seconds}s "
                f"({attempt}/{attempts})..."
            )
            time.sleep(delay_seconds)
            delay_seconds *= 2

    raise RuntimeError("Unexpected retry loop exit")


def main() -> None:
    """Main function to demonstrate the tool usage with Gemini."""

    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set")
        return

    client = genai.Client(api_key=api_key)
    model = "gemini-2.5-flash"

    prompt = "What is 25 multiplied by 4, and then add 10 to that result?"
    print(f"User: {prompt}\n")

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]

    response = _generate_with_retry(
        client=client,
        model=model,
        contents=contents,
        tools=[calculate_tool],
    )

    while response.function_calls:
        function_call = response.function_calls[0]
        args = _safe_args(function_call.args)

        print(f"Tool called: {function_call.name}")
        print(f"Arguments: {args}\n")

        if function_call.name == "calculate":
            result = calculate(
                operation=str(args.get("operation", "")),
                a=float(args.get("a", 0)),
                b=float(args.get("b", 0)),
            )
        else:
            result = {"error": "Unknown function"}

        print(f"Tool result: {result}\n")

        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        contents.append(
            types.Content(
                role="tool",
                parts=[
                    types.Part.from_function_response(
                        name=function_call.name,
                        response=result,
                    )
                ],
            )
        )

        response = _generate_with_retry(
            client=client,
            model=model,
            contents=contents,
            tools=[calculate_tool],
        )

    print(f"Assistant: {response.text}")


if __name__ == "__main__":
    main()
