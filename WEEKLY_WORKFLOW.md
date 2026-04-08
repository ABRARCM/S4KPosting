# S4K Bank Posting — Weekly Workflow

## Schedule
Run every week, typically Monday or Tuesday, covering the previous Mon–Sun period.

---

## Step 1: Export Data (15 min)

### A. CitiBank Build Report
1. Log into CitiBank Commercial Banking
2. Navigate to **Payments & Transfers > Transaction Search**
3. Filter by date range (Mon–Sun of prior week)
4. Export **PPO account (6881784489)** → save as `MM.DD to MM.DD PPO.csv`
5. Export **Medicaid account (6881784534)** → save as `MM.DD to MM.DD Medicaid.csv`
6. Place files in `Build Report/{Month}/`

### B. PNC Lockbox
1. Log into PNC ActivePay / Lockbox portal
2. Download transaction detail for the week
3. Save as `MM.DD-MM.DD.csv`
4. Place in `LockBox/{Month}/`

### C. Bank Statements (CCB)
1. Download checking account CSVs from CitiBank
2. PPO account: `CCB_CHECKING_6881784489_*.csv`
3. Medicaid account: `CCB_CHECKING_6881784534_*.csv`
4. Place in `Bank General/{Month}/`

## Step 2: Update Script Paths (2 min)

Open `bank_pivot.py` and update these file paths to match the new week's filenames:
- Line 5: PPO Build Report CSV path
- Line 7: Medicaid Build Report CSV path
- Line 276: LockBox CSV path
- Lines 368-369: Bank General CSV paths

## Step 3: Run the Script (1 min)

```bash
cd /Users/Admin/Desktop/Claude/BANK
python bank_pivot.py
```

This generates `Bank_Transaction_Pivot.html` in the same directory.

## Step 4: Review Output

Open `Bank_Transaction_Pivot.html` in a browser and verify:
- [ ] Deposit totals match expected card terminal batches
- [ ] EFT PPO tab shows all expected insurance payers
- [ ] EFT Medicaid tab shows Skygen, DentaQuest, Avesis entries
- [ ] Lockbox PPO (11234) and Medicaid (11233) check counts look reasonable
- [ ] Outgoing tab shows expected debits/fees
- [ ] Bank Statement totals reconcile with Build Report totals

## Step 5: Team Posting

RCM posting team (4 members) uses the dashboard to:
1. Track which EOBs have been received
2. Mark each transaction as Posted/Not Posted/Partial in Open Dental
3. Add remarks for exceptions or follow-ups

## Step 6: End-of-Week Reconciliation

- Verify all EFTs marked as "Posted"
- Follow up on any "Partial" or unmarked items
- Flag discrepancies between lockbox totals and bank statement

---

## File Naming Convention

| Source | Pattern | Example |
|--------|---------|---------|
| Build Report PPO | `MM.DD to MM.DD PPO.csv` | `04.01 to 04.07 PPO.csv` |
| Build Report Medicaid | `MM.DD to MM.DD Medicaid.csv` | `04.01 to 04.07 Medicaid.csv` |
| LockBox | `MM.DD-MM.DD.csv` | `04.01-04.08.csv` |
| Bank Statement PPO | `CCB_CHECKING_6881784489_*.csv` | `CCB_CHECKING_6881784489_08042026.csv` |
| Bank Statement Medicaid | `CCB_CHECKING_6881784534_*.csv` | `CCB_CHECKING_6881784534_08042026.csv` |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Script errors on CSV read | Check file paths and column names match expected format |
| Missing payer in EFT tab | New payer — add to `friendly_name()` function in script |
| Lockbox shows all $0.00 | Filter is working — those are "Correspondence Only" (EOBs without checks) |
| Bank Statement total doesn't match Build Report | Internal transfers are excluded from Bank Statement view — this is expected |
