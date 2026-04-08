# S4K Bank Posting Project

**Smiles 4 Keeps (S4K) — Weekly Bank Transaction Posting Workflow**

Managed by Abra Health Group RCM Team

---

## Overview

This project automates the weekly process of categorizing, reconciling, and posting bank transactions for the Smiles 4 Keeps Pediatric Dentistry practice. It processes data from CitiBank commercial accounts, PNC lockbox deposits, and insurance EFTs to produce an interactive HTML dashboard used by the RCM posting team.

## Bank Accounts

| Account | Number | Purpose |
|---------|--------|---------|
| S4K Ross Wez (PPO) | `6881784489` | PPO insurance deposits, card deposits, lockbox |
| S4K RWez ZBA (Medicaid) | `6881784534` | Medicaid insurance deposits (Skygen, DentaQuest, etc.) |

## Project Structure

```
S4KPosting/
├── README.md                    # This file
├── WEEKLY_WORKFLOW.md           # Step-by-step weekly process
├── DATA_DICTIONARY.md           # Column definitions & source mappings
├── bank_pivot.py                # Main processing script
├── index.html                   # Password-protected posting dashboard
├── Build Report/                # Weekly CitiBank transaction exports
│   └── {Month}/
│       ├── MM.DD to MM.DD PPO.csv
│       └── MM.DD to MM.DD Medicaid.csv
├── LockBox/                     # PNC-ECHO lockbox check data
│   └── {Month}/
│       └── MM.DD-MM.DD.csv
└── Bank General/                # CCB checking account statements
    └── {Month}/
        ├── CCB_CHECKING_6881784489_*.csv
        └── CCB_CHECKING_6881784534_*.csv
```

## Data Sources

### 1. Build Report (CitiBank Transaction Export)
- **Source:** CitiBank Commercial Banking portal
- **Format:** CSV with columns: Date, From Account Name, From Account Number, To Account Name, To Account Number, Type, Amount, ACH Individual ID, ACH Description, ACH Entry Description, Payment Status
- **Split:** Separate PPO and Medicaid files per week
- **Frequency:** Weekly export covering Mon–Sun

### 2. LockBox (PNC-ECHO)
- **Source:** PNC Bank lockbox portal
- **Format:** CSV with columns: Transaction ID, Processed Date, Amount, Lockbox Site, Item Type, Lockbox Number, Batch Number, Check Number, Check ABA/RT
- **Lockbox Numbers:**
  - `11234` = PPO checks
  - `11233` = Medicaid checks
- **Note:** Many rows are "Correspondence Only" (EOBs without checks) — filter to `Item Type == 'Check'` and `Amount > 0`

### 3. Bank General (Account Statements)
- **Source:** CCB (CitiBank) checking account CSV export
- **Format:** DATE, TRANSACTION TYPE, DESCRIPTION, AMOUNT (USD), BALANCE (USD)
- **Usage:** Cross-reference for reconciliation; credits only, excluding internal transfers

## Transaction Categories

The script classifies incoming transactions into:

| Category | Source Identifier | Description |
|----------|-------------------|-------------|
| **Deposits** | `BANKCARD-8740`, `MERCHANT BANKCD`, `SYNCHRONY BANK` | Card terminal batch deposits, merchant deposits, CareCredit |
| **Lockbox** | `PNC-ECHO` | Insurance check deposits via PNC lockbox |
| **EFT** | All other sources | Electronic Funds Transfers from insurance payers |
| **Outgoing** | Amount < 0 | Debits, fees, refunds |

## Merchant & Branch Mapping

### Card Deposits (BANKCARD-8740)
| ACH ID Contains | Location |
|-----------------|----------|
| `BARTO` | Bartonsville |
| `SCRAN` | Scranton |
| `HAZLE` | Hazleton |
| `WILKE` | Wilkes-Barre |
| `TILGHMAN` | Allentown (Tilghman) |
| `READI` | Reading |

### Merchant Deposits (MERCHANT BANKCD)
| ACH ID Contains | Location |
|-----------------|----------|
| `182885` | Reading (Merchant) |
| `416884` | S4K Pediatric (Merchant) |
| `222888` | Wilkes-Barre (Merchant) |

### Key Insurance Payers (EFT)
| From Account Name | Payer | Type |
|-------------------|-------|------|
| `ZP SKYGENOPT510` | Skygen | Medicaid |
| `DENTAQUEST NATL` | DentaQuest | Medicaid |
| `AVESIS THIRD PTY` | Avesis | Medicaid |
| `SUNLIFE` | SunLife | PPO |
| `DDPAR` | Delta Dental PAR | PPO |
| `SYNCHRONY BANK` | CareCredit | Patient Finance |

## Output

### Bank_Transaction_Pivot.html
Interactive dashboard with tabs:
1. **Deposits** — Overview by date + detail with payer, type, amount
2. **EFT PPO** — Electronic funds with EOB status, Posted status, Remarks
3. **EFT Medicaid** — Same structure for Medicaid payers
4. **Lockbox PPO** — Check-level detail from lockbox 11234
5. **Lockbox Medicaid** — Check-level detail from lockbox 11233
6. **Check Deposits** — PNC-ECHO deposit reconciliation
7. **Outgoing** — Debits and fees
8. **Bank Statement PPO** — Daily summary from CCB statement
9. **Bank Statement Medicaid** — Daily summary from CCB statement

Each detail row includes:
- **EOB** dropdown (Yes/No) — Has the Explanation of Benefits been received?
- **Posted** dropdown (Yes/No/Partial) — Has this been posted in Open Dental?
- **Remarks** — Free-text field for notes

## Running the Script

### Prerequisites
```bash
pip install pandas
```

### Weekly Execution
```bash
python bank_pivot.py
```

### Before Running — Update These Paths in `bank_pivot.py`:

1. **Build Report CSVs** (lines 5-7):
   ```python
   df_ppo = pd.read_csv("Build Report/{Month}/MM.DD to MM.DD PPO.csv")
   df_medicaid = pd.read_csv("Build Report/{Month}/MM.DD to MM.DD Medicaid.csv")
   ```

2. **LockBox CSV** (line 276):
   ```python
   lb = pd.read_csv("LockBox/{Month}/MM.DD-MM.DD.csv")
   ```

3. **Bank General CSVs** (lines 368-369):
   ```python
   bg_ppo = load_bank_general("Bank General/{Month}/CCB_CHECKING_6881784489_*.csv", "PPO")
   bg_med = load_bank_general("Bank General/{Month}/CCB_CHECKING_6881784534_*.csv", "Medicaid")
   ```

## RCM Posting Workflow

The posting team (4 staff members) follows two parallel tracks:

### PPO Track
1. Download lockbox data from PNC portal
2. Match lockbox checks to EOBs
3. Post payments in Open Dental
4. Mark as Posted in dashboard

### Medicaid Track
1. Route by payer (DentaQuest → Avesis → Skygen)
2. Download remittance/ERA from payer portals
3. Post payments in Open Dental
4. Mark as Posted in dashboard

---

*Maintained by Abra Health Group RCM Team*
