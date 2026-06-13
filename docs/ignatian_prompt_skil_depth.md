This is a real and well-studied failure mode, and it's worth being precise about the mechanisms, because "the details get forgotten" actually conflates several different things.

There's no single token count where a prompt "breaks." But there are a few distinct degradation curves worth separating:

**1. Attention dilution (the soft one).** Transformers attend to everything, but attention is a finite, normalized resource. Every additional instruction competes for the same attention mass. A 400-token prompt where one sentence says "always reflect the consolation/desolation distinction back to the user" gives that sentence real weight. The same sentence buried in a 4,000-token persona doc gets a thin slice. Nothing is "forgotten" — it's just under-weighted relative to whatever the user just said and whatever is most recent. This degradation is gradual and starts almost immediately; it's not a cliff.

**2. Positional effects ("lost in the middle").** Models reliably attend better to the start and end of a long context than the middle. Instructions placed in the middle of a long system prompt are measurably less likely to be followed. This is robust across model families, though newer long-context models have softened it.

**3. Instruction conflict and precedence.** As a persona prompt grows, you stop adding *information* and start adding *constraints that interact*. Ignatian discernment is full of these: "don't rush the person" vs. "keep turns short for latency"; "don't give advice" vs. "guide toward the Examen." The model isn't forgetting — it's resolving a genuine contradiction you wrote, and you can't predict which side wins. This is usually the real culprit when people say a long prompt "ignores" an instruction.

**4. Salience decay over a conversation.** Even if the system prompt is perfect, after 30 turns the model's behavior is dominated by the *recent transcript*, not the system prompt. A persona established only at the top will drift. This is the one most relevant to a voice agent, which has long, meandering sessions.

For your specific case — Ignatian discernment as a moat — a few practical implications:

A long, rich persona prompt is not the enemy. A long, *flat* persona prompt is. The fix isn't fewer words; it's structure and reinforcement:

- **Separate identity from procedure.** Who the director *is* (contemplative, unhurried, attentive to interior movements) can be prose. What the agent *does* (the discernment flow, the questions it asks, when it names consolation vs. desolation) should be an explicit, ordered procedure, not narrative. Procedures survive dilution far better than vibes.
- **Put the non-negotiables at the very end** of the system prompt, in a short block. End-of-prompt is the highest-salience position and it's where you control what's last before the user turn.
- **Re-inject the core persona mid-conversation**, not just at the top. For a voice agent this means a lightweight system reminder every N turns, or appended to context when you detect drift. This directly counters #4 and is probably your single highest-leverage move.
- **Test for conflict explicitly.** Write down every pair of instructions that could compete and decide the precedence yourself, in the prompt ("If brevity and depth conflict, choose depth and let the turn run long"). Don't let the model arbitrate.
- **Move stable knowledge out of the prompt.** The *content* of Ignatian spirituality (the Rules for Discernment, the structure of the Examen, Ignatius's distinctions) is reference material — it belongs in retrieval or a tool the agent consults, not dissolved into the persona. The system prompt should hold *behavior and voice*; retrieved chunks hold *doctrine*. This keeps the prompt short enough that behavior stays sharp while the knowledge stays accurate.

On the moat question specifically: the durable advantage is probably not the system prompt at all — prompts are trivially copyable and degrade as above. The defensibility is more likely to come from (a) a well-structured discernment *flow* with evaluation showing it actually produces good interior reflection, (b) a curated knowledge base of Ignatian material that's correct and well-chunked, and (c) eval data showing the persona holds up over long sessions. The prompt is the least defensible layer; the flow design and the eval evidence are the moat.

If you want, I can sketch what a structured Ignatian discernment agent prompt would look like with the identity/procedure split — that'd make the dilution question concrete.


Yes — and the "skill" framing is exactly the right mental model, but it's worth being precise about *which* parts move out, because not all of the method should.

There are really three categories in an Ignatian discernment agent, and they want different homes:

**1. Voice and stance — stays in the system prompt.** Who the director is: unhurried, contemplative, attentive to interior movements, doesn't problem-solve. This is short, it's behavioral, and it must be active on *every* turn. It can't be retrieved on demand because it conditions how the agent speaks even when no procedure is firing.

**2. The discernment procedure — stays in the prompt, but as structure, not prose.** The actual flow — how a session opens, when the agent moves from listening to naming consolation/desolation, when it invites the Examen, when it closes. This needs to be live every turn too, because the agent is always *somewhere* in that flow and needs to know where. But it should be an explicit ordered procedure, not narrative. This is the part people wrongly try to write as rich prose, and that's what dilutes.

**3. The doctrinal content — this is what becomes the "skill."** The Rules for Discernment, the full structure of the Examen, Ignatius's specific distinctions, worked examples, edge cases ("what desolation looks like vs. genuine sadness"). This is reference material: large, stable, only relevant *sometimes*, and accuracy-critical. It should not live in the prompt at all.

The distinction that matters: a skill is something the agent *consults when a trigger fires*, not something that conditions every token. The "Anthropic skill" pattern you're familiar with — a SKILL.md the model reads when the task calls for it — works precisely because the model decides *I need this now*, pulls it in, and acts on it. That's perfect for "the user is describing something that sounds like desolation; load the Rules for Discernment and apply them." It's wrong for "be contemplative," which has no trigger — it's always on.

One caveat specific to a *voice* agent, though. A skill-style consult adds a step: detect trigger → retrieve → reason over retrieved content → respond. That's latency you can feel in a spoken conversation. Two ways people handle it:

- **Pre-fetch on prediction.** If the flow is at a stage where discernment-of-spirits is likely next, load that material into context *before* the user finishes their turn, so it's resident when you need it.
- **Tier the knowledge.** A compressed version of the core distinctions (a few hundred tokens) lives in the prompt as a fast path; the full doctrinal treatment is the skill, consulted only when the compressed version isn't enough. This trades a little prompt budget for not paying retrieval latency on the common case.

So: yes, externalize the *method-as-knowledge*. Keep the *method-as-flow* and the *voice* in the prompt. The test for any given chunk — "does this need to influence every turn, or only when a specific situation arises?" Every-turn stays; situational becomes the skill.

Want me to sketch the actual split for an Ignatian agent — i.e. what the ~few-hundred-token in-prompt fast path looks like vs. what goes into the discernment skill?

--- the prompt and skill

Here's the split. I'll write the in-prompt fast path in full so it's concrete, then describe the skill's contents and triggers.

## The system prompt (everything live every turn)

**Identity block** — prose, short:

You are a companion for Ignatian spiritual discernment. You are unhurried and contemplative. You do not solve problems, give advice, or push toward conclusions. Your work is to help the person notice and name what is happening in their interior life — the movements of consolation and desolation — so that *they* can discern. You listen far more than you speak. You are comfortable with silence and with not resolving things in one session.

**Procedure block** — ordered, explicit, not prose:

A session moves through stages. Track which stage you are in.
1. Gathering — invite the person to describe what they bring. Stay here until there is something concrete to discern about. Do not advance early.
2. Noticing — help them attend to the interior movements around what they described: where there is life, peace, drawing-toward (consolation); where there is unrest, heaviness, drawing-away (desolation). Reflect movements back; do not interpret them for the person.
3. Examining — when there is material, invite a structured looking-back (the Examen). Consult the discernment skill before guiding this.
4. Resting — help them name what they noticed and what, if anything, they feel invited toward. Do not manufacture a decision.

**The fast-path knowledge** — the compressed core, a few hundred tokens, so the common case needs no retrieval:

Consolation is movement toward God: increase of faith, hope, love; interior peace; being drawn toward the good. Desolation is the opposite: darkness, turmoil, sluggishness, being pulled toward what is lesser; separation from God. Two cautions you apply constantly: (a) a *feeling* of sadness is not necessarily desolation, and ease is not necessarily consolation — what matters is the direction of the movement, not its surface comfort; (b) in desolation, never help the person make or change a major decision; help them hold steady until it passes.

**Precedence block — at the very end, short:**

If brevity and depth conflict, choose depth; let the turn run long. If the person pushes for advice, do not give it — return them to their own noticing. If you are unsure whether something is desolation, consult the skill rather than guessing. Never name a movement as consolation or desolation faster than the person can recognize it themselves.

That's the whole prompt. Notice the doctrine in it is *minimal* — just enough to behave correctly in the ordinary flow.

## The discernment skill (consulted on trigger)

This is the SKILL.md-style document. It holds what's too large or too situational for the prompt, and accuracy matters too much to compress:

- **The full Rules for Discernment** — Ignatius's first-week and second-week rules, with the distinctions the fast path omits (e.g. the second-week rules on the "good spirit" and the subtle counterfeit, the "what comes before / during / after" analysis of a movement).
- **The full Examen structure** — the five movements (gratitude, petition for light, review of the day, sorrow, resolve for tomorrow), with how to guide each conversationally.
- **Edge-case discrimination** — desolation vs. clinical depression vs. ordinary grief; consolation vs. mere enthusiasm or relief; "false consolation." This is where you put the *out-of-scope* boundary too: signs the conversation has moved from discernment to mental-health territory and the agent should gently say so and stop.
- **Worked examples** — two or three transcripts showing a movement correctly named and guided, so the model has patterns, not just rules.

**Triggers — when the agent consults it:**

- Entering Stage 3 (Examining) — always; the Examen structure lives only in the skill.
- The precedence block fires "consult the skill" — i.e. genuine uncertainty about whether something is desolation.
- Anything that pattern-matches to the edge cases — the person describes something that *might* be depression rather than desolation, or a "consolation" that the agent suspects is the subtle counterfeit.

**The latency handling:** Stage 3 is predictable — you know you're heading there once Stage 2 has material. Pre-fetch the Examen portion of the skill while the person is still talking in late Stage 2, so it's resident before you need it. The edge-case lookups are rarer and less predictable; those you pay the retrieval cost on, which is acceptable because they're uncommon and getting them right matters more than speed.

The line that determines every placement: **does this shape how the agent speaks on a turn where nothing special is happening?** Identity, the four-stage skeleton, and the compressed consolation/desolation definition all do — they stay. The Rules in full, the Examen steps, the edge cases only matter when a specific situation arises — they're the skill.

One thing worth flagging back to your moat question: the skill is the part actually worth building carefully. The prompt above is good but copyable in an afternoon. A well-curated, theologically sound, well-chunked discernment skill with real worked examples and honest edge-case boundaries — that takes genuine work and Ignatian literacy to get right, and it's what would be hard for someone to replicate.