"""The score engine, computed over the panel and written to data/marts for the API.

Built:
- anchors: the breakpoint table every indicator maps through
- events: proxy distress labels, the ruler the score is calibrated and measured against
- score: indicators, pillars and the level per group per month
- validate: discrimination, trajectory, stability and pillar ablation, split by group
- trend: smoothing, slope and the CUSUM state machine over a level series
- monitor: jumps and sustained shifts, bump vs fall, the alert feed
- notify: alerts as messages, sent once, over Slack or email

Planned:
- explain: additive driver decomposition, what moved since last month
- offer: working-capital limit, price and ranked actions
- submit: predictions for the hidden test
"""
