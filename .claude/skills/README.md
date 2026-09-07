# Vendored design skills

Third-party skills, copied into the repository rather than symlinked, so that a fresh clone has them
without anyone running an installer and so that what the agent reads is reviewable in a diff. They are
prompt files: **they carry no code and execute nothing**, but they do steer an agent that has full
permissions, so read one before trusting it.

Installed with the [`skills`](https://github.com/vercel-labs/agent-skills) CLI. `skills-lock.json` at
the repository root records the source and a content hash of each.

| Skill | Source | Licence | What it is for |
|---|---|---|---|
| `design-taste-frontend` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) `skills/taste-skill` | MIT | Anti-generic frontend direction for landing pages, portfolios and redesigns |
| `image-to-code` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) `skills/image-to-code-skill` | MIT | Generate a design image first, analyse it, then implement to match |
| `web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/web-design-guidelines` | MIT | Review UI code against Vercel's Web Interface Guidelines |

## Reinstalling or updating

```bash
npx skills add https://github.com/Leonxlnx/taste-skill   --skill design-taste-frontend --agent claude-code --copy -y
npx skills add https://github.com/Leonxlnx/taste-skill   --skill image-to-code         --agent claude-code --copy -y
npx skills add https://github.com/vercel-labs/agent-skills --skill web-design-guidelines --agent claude-code --copy -y
```

The install name is the `name:` field in the skill's frontmatter and is **not** always the folder name
in the source repository — `design-taste-frontend` lives in `skills/taste-skill/`. `npx skills list`
shows what is installed; `npx skills update` upgrades in place.

## Two things worth knowing before using them

**`web-design-guidelines` fetches at run time.** The SKILL.md is a four-kilobyte instruction to pull
the current rules from
`https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`. That is the
skill as published, not a truncated copy — but it means the skill needs network access and that its
rules can change under you. Verified reachable at install time.

**`image-to-code` is written for Codex** and says so in its own description; it also assumes the agent
can generate images. It works as design *direction* under Claude Code, and the image-generation half
needs a tool this project does not have.

## How these relate to `DESIGN.md`

`DESIGN.md` in the repository root is the authority on how **this** interface looks, and it describes
the system that is already implemented in `src/orderorder/web/static/app.css`. These skills are
general-purpose taste and review instruction; where a skill's default aesthetic disagrees with
`DESIGN.md`, `DESIGN.md` wins. Its "Don't" section is not stylistic preference — the ban on inline
script and style is a Content-Security-Policy boundary that `tests/test_hardening.py` enforces.
