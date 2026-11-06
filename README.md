# Hermes OpenRouter + Gemini Cascading

A reproducible Hermes Agent config so your team can run **OpenRouter + Google AI Studio / Gemini** with **free models**, and cascade between them (use cheap models for simple prompts, stronger models for complex ones).

No codebase needed — this is pure config + a routing skill.

---

## Quick Start

```bash
# 1) Clone
git clone <repo> && cd hermes-openrouter-gemini-cascade

# 2) Create your local secrets file (never commit .env)
cp .env.example .env
# → edit .env and paste your OPENROUTER_API_KEY and GOOGLE_API_KEY

# 3) Install the config
cp config.yaml.example ~/.hermes/config.yaml
# → back up any existing ~/.hermes/config.yaml first

# 4) Create the model aliases (or they're already in config.yaml)
hermes config set model.aliases.free-gemini gemini/gemini-2.0-flash
hermes config set model.aliases.free-openrouter openrouter/openai/gemini-2.0-flash

# 5) Verify
hermes model list | grep free
```

That's it. You can now use `/model free-gemini` or `/model free-openrouter` in the desktop app or CLI.

---

## How the two "cascades" work

### 1. Resilience cascade (automatic, on error)
Hermes walks a fallback chain when the active model fails. Set it once:

```bash
hermes fallback add 0 gemini/gemini-2.0-flash
hermes fallback add 1 openrouter/openai/gemini-2.0-flash
hermes fallback list
```

### 2. Logic cascade (pick a model by complexity)
The `skills/route-model` skill (or a small wrapper script) decides which model to use per prompt:

- Short prompt (`< 300 chars`) → `free-gemini`
- Long/complex prompt → `free-openrouter`

---

## Repo contents

| File | Purpose |
|---|---|
| `.env.example` | Template for your API keys — copy to `.env`, commit nothing. |
| `config.yaml.example` | Aliases + fallback setup — copy to `~/.hermes/config.yaml`. |
| `skills/route-model/SKILL.md` | The routing logic: pick model by prompt length. |
| `README.md` | This file. |

---

## What "free" means here

- **Google AI Studio / Gemini**: genuine free tier (`gemini-2.0-flash`, `gemini-flash-lite`) with daily quotas.
- **OpenRouter**: generally pay-per-token through its providers. A few models have free tiers — check the [OpenRouter catalog](https://openrouter.ai/models) for a free one to alias instead of `openai/gemini-2.0-flash`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No `free-gemini` alias | Run `hermes config set model.aliases.free-gemini gemini/gemini-2.0-flash`, then `/reset`. |
| `hermes: command not found` | Install Hermes: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash`. |
| Gateway won't start | `hermes doctor`, then check `~/.hermes/.env` has both keys. |
| Cascade isn't picking a model | Confirm the alias resolves: `hermes model get <alias>`. |

---

## For the team

- Share the repo URL, not the `.env`.
- Each teammate runs steps 2–4 (their keys differ).
- Drop `skills/route-model` (or a wrapper script) into your own repo if you want per-team routing rules.
