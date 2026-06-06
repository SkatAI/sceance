# Jun 6 & 7

- ran out of credits on cartesia, need to find other voice provider, or add credits. voice gen is expensive
- flow is not fluid. lots of waiting, sometimes stalling. need to stabilize
- I want to see the transcript of the conversation, it helps
- I want to hear some connection sound as the agent starts the session


end of session :
- The platform is solid. basically works.
- I have a version ready to beta test
- I have a test plan. what do I want to test for the next phase

how do I evaluate the quality of the conversation ?

I should be able to start new conversation with or without the memory


# Landing page positionning

Let's find out. Let's talk!

The decision making method the jesuits have refined for over 500 years, designed for the moment you're in.

Ignatius of Loyola a 16th century Spanish soldier, spent his life on one question : what do you actually want ?
Something brought you here even if you can't say what.
Let's find out. Let's talk!


The jesuitic method to understand what you actually want.
Call up the counselor

(AI inspired by igniatian discernement)



The Jesuit method for understanding what you actually want.
Something brought you here, even if you can't say what.
Let's find out.  Call Inigo



Tu es venu ici sans trop savoir pourquoi. C'est déjà un début.
Une méthode vieille de cinq siècles pour mettre des mots sur ce que tu cherches.
Appelle Ignace, parle-lui.


You're not sure why you're here. Well, that's a start.
The Jesuit method for putting words to what you're after.
Call Inigo. Talk to him.

Inigo is on the line.




---
The Supabase project console must have Email provider enabled and the site URL + redirect allowlist set to the deploy origin (http://localhost:8080,
  https://voice.alexisperrier.com). Confirmation email template should be the "Magic Link" template.


  Verification

 1. Run 002_auth.sql against the Supabase project (via SQL editor or psql $SUPABASE_DB_URL).
 2. cd server && uv sync && uv run server.py (or the Make target).
 3. Visit http://localhost:8080:
   - Confirm landing shows username+email form, agent picker hidden.
   - Submit form → magic-link email arrives.
   - Click link → redirected back to /, header now shows username + logout, agent picker visible.
   - Start a session → bot connects as before.
 4. select id, user_id, persona_name from sessions order by started_at desc limit 1; → row has the user's user_id.
 5. Visit /dashboard while logged in as non-admin → bounced to /. /api/sessions returns 403.
 6. update profiles set is_admin = true where username = '…'; → reload / → dashboard link appears in header → /dashboard loads, /api/* returns 200.
 7. Reload the browser → still logged in (session restored from localStorage).
 8. Click logout → header reverts to logged-out form.

Already supported (no code change — just edit the persona)

  ┌──────────────────────────────────────┬──────────────┬────────────────────────────────────────────┬──────────────────────────┐
  │          persona llm_model           │ typical TTFB │         quality on a 14k FR prompt         │ cost / M tok (in / out)  │
  ├──────────────────────────────────────┼──────────────┼────────────────────────────────────────────┼──────────────────────────┤
  │ anthropic:claude-haiku-4-5 (current) │ ~0.5s        │ very good                                  │ $1 / $5                  │
  ├──────────────────────────────────────┼──────────────┼────────────────────────────────────────────┼──────────────────────────┤
  │ openai:gpt-4o-mini                   │ ~0.4–0.6s    │ decent, sometimes drifts persona           │ $0.15 / $0.60 ← cheapest │
  ├──────────────────────────────────────┼──────────────┼────────────────────────────────────────────┼──────────────────────────┤
  │ openai:gpt-4.1-mini                  │ ~0.5–0.7s    │ better instruction following than 4o-mini  │ $0.40 / $1.60            │
  ├──────────────────────────────────────┼──────────────┼────────────────────────────────────────────┼──────────────────────────┤
  │ openai:gpt-4.1-nano                  │ ~0.3–0.5s    │ weakest of the four; OK for plumbing tests │ $0.10 / $0.40            │
  └──────────────────────────────────────┴──────────────┴────────────────────────────────────────────┴──────────────────────────┘

  These all use providers your build_llm already wires. Make a copy of the persona JSON, change llm_model, set active: true, refresh the page — they
  show up as new buttons.

  Needs a small backend addition — but the latency win is real

  Groq-hosted Llama 3.3 70B. Groq's hardware does ~200–400ms TTFB even on a 70B model — substantially faster than anything from Anthropic/OpenAI at
  comparable quality. French is solid (Llama 3.3 is multilingual). Pipecat has pipecat.services.groq.GroqLLMService (OpenAI-compatible). Adding it to
  build_llm is a ~10-line branch. Cost is ~$0.6 / $0.8.

  Cerebras-hosted Llama 3.3 70B. Same idea, even faster (sub-200ms TTFB), similar pricing. Less battle-tested in pipecat.

  Worth knowing about, less compelling for your case

  Gemini 2.5 Flash / Flash-Lite. Pipecat has the service; multilingual is strong; TTFB is ~0.5–0.8s — competitive with Haiku 4.5, not noticeably faster.
   Useful as a third opinion on persona behavior, not as a latency win.

  My suggestion for an A/B sweep

  Make four persona copies with active: true:

  - inigo_haiku.json — anthropic:claude-haiku-4-5 (your current baseline)
  - inigo_4omini.json — openai:gpt-4o-mini
  - inigo_41mini.json — openai:gpt-4.1-mini
  - inigo_41nano.json — openai:gpt-4.1-nano

  Same system prompt, same TTS voice. Do one short FR call on each, open them in the dashboard, compare the Response latency block. That's a 15-minute
  experiment, costs cents, and gives you a real latency × quality matrix.

  If after that you're still chasing latency, say the word and I'll wire Groq into build_llm — that's where you'd realistically break under 800ms on a
  14k-char prompt.

✻ Sautéed for 28s



# Next

- costs tracing, cost estimation
- memory across sessions
- monitoring
- time limit per session
- user credits
- scripting for first caller
- tests models and prompts and voices


## Memory, monitoring, reporting

- all transcript recorded and stored. with step timing. everything is logged
- can be dumped into a log file, per session, and then parsed into a session sql table
- after each session, report is produced. session length, recap, performance, costs

## User account
- user fills in first name and email, opens an account, asked to verify the email, remembered on browser
- user can ask to delete all previous session informations
- user session dashboard shows all previous sessions with recap, performance, costs




## Other

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