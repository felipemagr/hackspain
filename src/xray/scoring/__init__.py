"""The score engine, computed over the panel and written to data/marts for the API.

Built:
- anchors: the breakpoint table every indicator maps through
- events: proxy distress labels, the ruler the score is calibrated and measured against
- score: indicators, pillars and the level per group per month
- validate: discrimination, trajectory, stability and pillar ablation, split by group

Planned:
- explain: additive driver decomposition, what moved since last month
- monitor: bump vs fall, when to raise an alert
- offer: working-capital limit, price and ranked actions
- submit: predictions for the hidden test
"""
