# S4K Bank Posting — Data Dictionary

## Build Report CSV (CitiBank Export)

| Column | Type | Description |
|--------|------|-------------|
| Date | date | Transaction date (YYYY-MM-DD) |
| From Account Name | string | Originating account/payer name |
| From Account Number | string | Originating account number |
| To Account Name | string | Receiving account name |
| To Account Number | string | Receiving account number |
| Type | string | `Incoming` or `Outgoing` |
| Foreign/Domestic | string | Always `Domestic` |
| Amount | decimal | Transaction amount (positive = incoming, negative = outgoing) |
| Payout Currency | string | Always `USD` |
| ACH Individual ID | string | Key identifier — contains merchant codes, routing info |
| ACH Description | string | Payer description (e.g., "ROSS M WEZMAR DDS") |
| ACH Entry Description | string | Transaction type code (e.g., `HCCLAIMPMT`, `BTOT`, `MTOT`, `MonthlyFee`) |
| Payment Status | string | Always `Complete` for processed transactions |

### ACH Entry Description Codes
| Code | Meaning |
|------|---------|
| `HCCLAIMPMT` | Healthcare claim payment |
| `BTOT` | Batch total (daily card deposit) |
| `MTOT` | Monthly total |
| `MonthlyFee` | Monthly service fee |
| `DEPOSIT` | Generic deposit |

## LockBox CSV (PNC-ECHO)

| Column | Type | Description |
|--------|------|-------------|
| Transaction ID | string | PNC transaction identifier |
| Processed Date | integer | Date as YYYYMMDD (needs parsing) |
| Amount | decimal | Check amount ($0.00 for correspondence-only) |
| Lockbox Site | string | Always `New York` |
| Item Type | string | `Check` or `Corr` (Correspondence Only) |
| Lockbox Number | string | `11234` = PPO, `11233` = Medicaid |
| Batch Number | string | Processing batch identifier |
| Check Number | string | Physical check number (if applicable) |
| Check ABA/RT | string | Bank routing number from check |

### Important Notes
- **Correspondence Only** rows (`Item Type = Corr`) are EOBs received without payment — filter these out for amount totals
- Lockbox number determines PPO vs Medicaid routing

## Bank General CSV (CCB Statement)

| Column | Type | Description |
|--------|------|-------------|
| DATE | date | Transaction date |
| TRANSACTION TYPE | string | `Credit` or `Debit` |
| DESCRIPTION | string | Full transaction description with timestamps and codes |
| AMOUNT (USD) | decimal | Transaction amount |
| BALANCE (USD) | decimal | Running account balance |

### Description Parsing Patterns
| Pattern in Description | Category |
|------------------------|----------|
| `BANKCARD` or `MERCHANT BANKCD` or `SYNCHRONY` | Card Deposits |
| `LOCKBOX` | Lockbox |
| `FUNDING TRANSFER` | Internal Transfer (excluded) |
| `DEPOSIT` (without LOCKBOX) | Deposit |
| Everything else | EFT |

## Derived Fields (Created by bank_pivot.py)

| Field | Source | Description |
|-------|--------|-------------|
| `_source` | Script | `PPO` or `Medicaid` — which CSV the row came from |
| `Category` | Script | `Deposits`, `Lockbox`, or `EFT` — based on From Account Name |
| `Payer` | Script | Human-readable payer/location name |
| `DepositType` | Script | `Batch`, `Monthly`, `Deposit`, or raw entry description |
| `BG_CAT` | Script | Bank General category: `Card Deposits`, `Lockbox`, `EFT`, `Deposit`, `Transfer` |
