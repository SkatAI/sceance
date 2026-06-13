# Evaluation

following
https://hamel.dev/blog/posts/evals/

## Unit tests

break down the scope of your LLM into features and scenarios.

=> continuously update them based on new failures we observe in the data as users challenge the AI or the product evolves

- no markdown in the LLM response
- answers are limited in size
- answers in the proper language
- greets the user by first name if first name is known
- guardrails : gently refuses to comply with harmful requests
- easter eggs : when asked about a specific predifined topic, responds with a joke

