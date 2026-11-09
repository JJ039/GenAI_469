---
name: route-model
description: Route a prompt to the right model based on length/complexity instead of one-size-fits-all. Only pick free models.
---

# Route by Model (Logic Cascade)

Instead of always calling the same model, pick per-prompt:

| Prompt shape | Model | Why |
|---|---|---|
| Short (< 300 chars) | `free-gemini` | Fast, cheap, free tier handles it fine |
| Long / complex | `free-openrouter` | More capable, better reasoning |

## Steps

1. Measure the incoming prompt.
2. If `len(prompt) < 300` → use the `free-gemini` alias.
3. Otherwise → use the `free-openrouter` alias.
4. If the chosen model errors, Hermes's built-in fallback chain (set with `hermes fallback add`) picks the next model automatically.

## When to use

- Cost-aware routing in a team setting.
- When you want simple queries cheap and complex ones strong — without manual switching.

## Notes

- Aliases are defined in `~/.hermes/config.yaml` (`model.aliases`).
- Fallback chain is session-level and set via `hermes fallback add <priority> <model>`.
- This skill is a guide for a human or an agent; you can package the routing logic in any wrapper script if you prefer.

## Do not

- Do not pick paid models. Only free.