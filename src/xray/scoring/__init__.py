"""The score engine, computed over the panel and written to data/marts and data/serving.

- anchors: the breakpoint table every indicator maps through, and the pillar weights
- events: proxy distress labels, the ruler the score is calibrated and measured against
- score: indicators, pillars and the level per group per month (or per company)
- validate: discrimination, trajectory, stability and pillar ablation, split by group
- trend: smoothing, slope, CUSUM state machine over a level series
- monitor: jumps and sustained shifts on the level, the alert feed
- notify: alert rows to Slack or email messages, idempotent
- rules: who is told where, at which urgency: the rule book behind `notify --channel rules`
- explain: additive driver decomposition, what moved since last month
- offer: working-capital limit, price and ranked actions
- serve: assemble every serving table from the real score
- submit: score a directory of CSVs the system has never seen
- mock: invented serving tables, kept for the product to develop against archetypes
"""
