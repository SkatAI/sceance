     /plugin install frontend-design@claude-plugins-official

- time limit to 1mn if user not logged in
- time limit to 5mn if user logged in
- requires user email and name ?
- select French or English
- record all the logs and parse
- I need to know the latency, number of tokens, costs etc

- send a recap of what was said during the session by email.

- session analysis

- round robin : models and prompts and voices


user account :
input email, input first name, get magic link
no password
stays logged in ?


fr and en versions

images of loyola

# Next


the user can also talk


## User information persistence
ok now I'd like to persist information across session

I will modify the system prompt of the agent so that the goal is to gather information about the user

I want this information to be stored in a structured way in a json file for the user

when the user calls again, the information is reloaded into the agent context


## Two agents are talking
what would be the strategy, the code architecture to have not one buy two agents talking as well as the user ?

⏺ Three patterns, in order of how I'd evolve into them:

  Pattern A — Director + per-turn config swap (recommended MVP)

  One LLM service, one TTS service in the pipeline, but a Director picks the next speaker before each generation and mutates the services' Settings (system prompt, model, voice) right
  before LLMRunFrame is queued. Pipecat's Settings dataclasses are runtime-updatable for exactly this.

  event: user_stopped_speaking
     ↓
  director.pick_next_speaker(context) → "spirit_zola"
     ↓
  llm.update_settings(system_instruction=zola.prompt, model=zola.model)
  tts.update_settings(voice=zola.voice_id)
     ↓
  queue LLMRunFrame

  - Single shared LLMContext holds the whole transcript. Tag each assistant message with name: <speaker> (OpenAI message field) so the LLM sees who said what.
  - Director v1: a tiny rule-based class (e.g. medium handles meta, spirit answers first-person). v2: a small router LLM call returning {"speaker": "..."}.
  - Agent-to-agent banter: after LLMFullResponseEndFrame, if director.continue_without_user() returns true, queue another LLMRunFrame. Cap turns per scene.

  Files I'd add:
  server/
    personas/medium.json, spirit_zola.json   # one file per persona
    roster.json                              # which personas are active
    director.py                              # pick_next_speaker(context)

  Plus add a speaker column to the messages table.

  Cost: ~1 hour of work. Maps cleanly onto the existing pipeline — no forking.

  Pattern B — Parallel pipelines + mixer

  Two LLM→TTS branches, a gate chooses whose audio reaches the transport. Lower perceived latency (the unchosen branch is wasted), but coordination is messy and pipecat doesn't have a
  first-class "audio mixer with priority gating." Skip for now.

  Pattern C — Single LLM, multiple voices in one generation

  One LLM call emits structured chunks like <medium>...</medium><zola>...</zola>; a custom processor between LLM and TTS routes chunks to the right voice. Lets the agents banter inside
  one generation, very cheap. But persona distinctness gets weaker (one model is playing both), and you need disciplined structured output. Worth trying for a v2 "the spirits argue with
   each other" demo, not for the MVP.

  Tradeoff to weigh now

  The real question is whether agents-to-agents banter is part of the demo, or just user↔one-agent-at-a-time. If the séance is always user-driven (user asks, one agent answers), Pattern
   A is overkill in director complexity — you could just have the user-facing UI pick which persona answers next. If agents must talk to each other while the user listens, Pattern A's
  "queue another LLMRunFrame" loop is the load-bearing piece.

  Want me to implement Pattern A — personas as files, a Director, per-turn settings swap, speaker column in SQLite?