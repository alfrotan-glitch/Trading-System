# XAUUSD research state

Decision: INCONCLUSIVE

No strategy was promoted. A hypothesis result is not a validation pass and is not Demo-ready.

## DATA FACTS

- Rows measured: 139930971
- Raw time_msc range: 1726746013452 .. 1789775939790
- `time` equal to `time_msc // 1000`: 139930971 of 139930971
- `time_msc` divisible by 1000: 137378
- Bid on a 0.01 grid: 139930971 of 139930971
- Bid on a 0.001 grid: 139930971 of 139930971
- Volume zero / positive: 139930971 / 0
- Last zero / equal bid / equal ask / inside spread / outside spread: 139930971 / 0 / 0 / 0 / 0
- Adjacent quote changes, bid only / ask only / both / neither: 8153716 / 8005622 / 123767511 / 4121
- Minimum positive adjacent bid change: 0.009999999999308784
- Timezone: UNAVAILABLE
- Session calendar: UNAVAILABLE
- Equal raw-span bins are data facts. Bins 3 and 4 overlap the locked span and were not used to fit a hypothesis.
- Repairs applied: none
- Bin 0: rows 23682649, mean spread 0.24439241995268296, locked-span overlap False
- Bin 1: rows 22345383, mean spread 0.2617868644274299, locked-span overlap False
- Bin 2: rows 24806394, mean spread 0.2800656084878762, locked-span overlap False
- Bin 3: rows 36299244, mean spread 0.30494294233786284, locked-span overlap True
- Bin 4: rows 32797301, mean spread 0.2513711884401708, locked-span overlap True

## RESEARCH ASSUMPTIONS

- next quote means the next row in ledger order, not the next distinct timestamp
- prevailing spread is the spread of the quote before the move
- one spread cost is the spread at the event quote, subtracted in price
- discovery is time_msc < min + (span * 60) // 100
- a triple touching the validation span is excluded, not repaired
- iid binomial p-values on adjacent events are not inferential

## DERIVED FEATURES

- mid
- spread
- next mid change
- spread-scaled absolute next mid change

## HYPOTHESES

- Discovery cutoff time_msc: 1764563969254
- Discovery rows: 70834426
- Locked-span rows, counted only as a data fact: 69096545
- H-MS-01 result: REJECTED — non-overlapping reversal frequency is not above 0.5; mean residual after one spread is not positive
- H-MS-01 non-overlapping reversal frequency: 0.4994081016294421
- H-MS-01 non-overlapping mean residual bps: -0.8030316442969817
- H-MS-02 result: REJECTED — wide-spread half does not have a larger spread-scaled next absolute move
- H-MS-02 median spread: 0.23999999999978172
- H-MS-02 non-overlapping wide-minus-narrow difference: -0.044767032609947216
- H-TOD-01: NOT TESTED — BLOCKED — timestamp basis is not confirmed

## BLOCKED

- H-TOD-01
- hour-of-day
- session
- day-of-week

## NOT TESTED

- Regimes, event/state sequences, and cross-feature conditionals beyond H-MS-01 and H-MS-02.
- No machine-learning model was fit.

Edge claim: NOT ESTABLISHED
Orders submitted: 0

