# XAUUSD microstructure research state

Decision: INCONCLUSIVE

No strategy was promoted. Exploratory cells are not confirmatory. The locked span was not used to choose a test.

## CLOCK

- Status: BLOCKED
- MetaQuotes' copy_ticks_range page says obtained tick times are UTC. The project live-tick path says server-local time and a measured offset. This archive's manifest does not confirm either reading for these rows.

## HYPOTHESES

- H-QD-01: REJECTED — predicted effect 0.00642567 is below the floor 0.02
- H-QD-02: REJECTED — predicted effect 0.0194731 is below the floor 0.02
- H-INT-01: REJECTED — predicted effect -0.0538568 is below the floor 0.05
- H-SP-01: TESTED — process structure is present; it is not a return predictor and not a strategy
- H-MV-01: REJECTED — predicted effect -0.00203678 is below the floor 0.02
- H-VOL-01: REJECTED — predicted effect 0.139398 is below the floor 0.25
- H-SPR-01: REJECTED — predicted effect -0.0316419 is below the floor 0.10000000000000009

## DESCRIPTIVE

- Rows: 139930971
- Discovery rows: 70834426
- Mutual information of the next quote state, bits: 0.12950981420361188
- Half-cent composition: {'zero': 489666, 'one_half_cent': 6455869, 'one_cent': 16946148, 'larger': 46942742}
- State counts: {'bid_down_ask_down': 27804552, 'bid_down_ask_same': 3146866, 'spread_widen': 1117020, 'bid_same_ask_down': 3187007, 'unchanged': 10, 'bid_same_ask_up': 3107044, 'spread_tighten': 1185363, 'bid_up_ask_same': 3240075, 'bid_up_ask_up': 28046488}

Edge claim: NOT ESTABLISHED
Orders submitted: 0

