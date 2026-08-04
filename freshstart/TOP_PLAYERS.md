# How the top teams build their agents

Source: the community discussion post *"Top players' methods, revealed by 30,000 games"* by
Abhyuday (401st), plus the replies from ranked competitors. Reproduced here because it's the
best public read on what the leaderboard is actually running.

Timing: the post is from roughly **2026-07-10**, and the leaderboard placements quoted for each
commenter are their rank *at the time they wrote*. The architectural picture holds; individual
ranks and the identity of "the top player" have moved since (see [META.md](META.md) for the
current standings).

## The method

Each agent gets a **600-second-per-game** budget, and the environment records how long the
agent thinks on every move. That timing signature leaks the architecture:

| Signature | Implies |
|---|---|
| Answers almost instantly, flat across positions | Hand-written rules / heuristics |
| Long pause at the very start, then fast and steady | A trained model being loaded, then cheap inference |
| Think time scales with board complexity | Search |

Plot per-move time against startup time and the field separates into clusters.

## What the field runs

- **About half the field is rule-based** — hand-written bots or lightly modified copies of the
  public example agents.
- **Most agents answer in ~0.03 s per move.** A small group thinks for whole seconds. There is
  very little in between — the field is bimodal, not a spectrum.
- **The #1 player is doing something nobody else is:** loading a heavy model *and* consuming
  most of the in-game time budget. Most likely **RL + bounded search**.
- **The rest of the top does not appear to be using search at all** — heavy model load, then
  fast inference.

## What competitors said about their own agents

- **Aji Samudra (573rd)** — confirmed: RL agent, **1.7 M parameters**, up to **8 s** load time.
- **Belati Jagad Bintang Syuhada (1132nd)** — a **5 M** parameter model peaked at **1032** and
  took **40 s** of startup.
- **Aliy Elbekov (35th)** — a **700 k** parameter model plus a heuristic search used only *when
  the model's decision isn't clear*. Notes that bots with **zero** thinking time still crush
  his, i.e. dynamic thinking isn't obviously paying.
- **李秉叡 / ntumlnoob (9th)** — believes many agents classified as rule-based or search are
  actually RL or RL+search. The timing classifier under-counts learned agents.
- **Abhyuday (author, 401st)** on why search underperforms here:

  > "Search only works well when you're able to determine the value of the states accurately.
  > In my case search doesn't help precisely because my value head can't tell whether action A
  > or B is better, and the raw policy's decision is often one of the best. I do think search is
  > difficult here since it's an imperfect information game with high uncertainty."

The author's own caveat: **all of this is inferred from behaviour**, so individual
classifications will be wrong.

## What to take from it

1. **A trained policy is the mainstream top approach.** Model sizes at the top are modest —
   0.7 M to 5 M parameters — and load times of 8–40 s are affordable inside a 600 s game budget.
   Nobody needs a large model here.
2. **Search is the minority position, and its value is bounded by your state evaluator.** In an
   imperfect-information game, searching with an inaccurate value estimate or an unrealistic
   opponent model amplifies the error rather than averaging it out. The #1 player pairs search
   *with* a learned model; several strong players deliberately skip search.
3. **Speed is not the differentiator.** Zero-thinking-time agents beat second-scale ones
   throughout the leaderboard. Time spent only pays if it buys a better decision.
4. **Half the field is beatable with rules.** A careful hand-written agent that respects the
   structural facts of the format (prize math, effect immunity, attacking ends your turn) clears
   the median.
