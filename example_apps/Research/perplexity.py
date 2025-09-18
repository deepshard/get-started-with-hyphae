import requests

class PerplexitySearcher:
    def __init__(self):
        self.system_prompt = ""
        self.model = "sonar"
        self.url = "https://api.perplexity.ai/chat/completions"

    def run(self, query: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": query}
        ]
        response = requests.post(
            self.url,
            json={
                "model": self.model,
                "messages": messages
            },
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {'ADD_YOUR_PERPLEXITY_TOKEN_HERE'}"
            }
        )

        return response.json()["choices"][0]["message"]["content"]
    