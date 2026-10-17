from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
r = client.chat.completions.create(
    model="llama3.2:3b",
    messages=[
        {"role": "system", "content": "Reply with JSON only."},
        {"role": "user", "content": 'You have 50 coins and no food. Choose one action: "work", "rest" or "buy_food". Return {"action": "...", "reason": "..."}'},
    ],
    response_format={"type": "json_object"},
    max_tokens=100,
)
print(r.choices[0].message.content)