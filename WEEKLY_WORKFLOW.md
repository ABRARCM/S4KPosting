# S4K Bank Posting — Weekly Workflow

## Schedule
Run every week, typically Monday or Tuesday, covering the previous Mon–Sun period.

---

## Step 1: Upload New Data to OneDrive

All files go to: **OneDrive > ABRA RCM - PA > PA Posting > Citi Bank > {Month}**

Drop new files into the appropriate subfolder. **Do NOT delete old files** — the script reads everything and deduplicates automatically.

### A. Reports Builder (CitiBank Transaction Export)
- Export from CitiBank Commercial Banking (combined PPO + Medicaid)
- Save to `Reports Builder/` folder

### B. LockBox (PNC Lockbox)
- Download from PNC ActivePay / Lockbox portal
- Save to `LockBox/` folder

### C. General Statement (CCB Account Statements)
- Download PPO account (6881784489) and Medicaid account (6881784534)
- Save to `General Statement/` folder

### D. Deposited Checks (if any new deposits)
- Download deposit detail CSVs from CitiBank
- Save to `Deposited Checks/` folder

## Step 2: Tell Claude to Update

Just say: **"Update the S4K dashboard with new data"**

Claude will:
1. Run `bank_pivot.py` (reads all files from OneDrive, deduplicates, generates HTML)
2. Copy the output to the GitHub repo
3. Push to GitHub — live site updates automatically

### What Happens Automatically
- New transactions appear with blank dropdowns (unposted)
- Old transactions keep their Posted/EOB/Remarks status (Firebase stable IDs)
- Duplicates across files are removed
- Internal funding transfers are excluded
- Lockbox uses only Check rows (not Coupon)
- General Statement deduplicates by date + amount

## Step 3: Verify Reconciliation

Check the **Overview tab** at https://abrarcm.github.io/S4KPosting/

| Section | What it Compares | When it Should Match |
|---------|------------------|---------------------|
| EFT Summary | Reports Builder PPO + Medicaid totals | Always (same source) |
| Lockbox Reconciliation | LockBox folder vs General Statement lockbox entries | When all data is uploaded for the period |
| Deposited Checks | Checks folder vs General Statement deposit entries | When all data is uploaded for the period |

If there's a DIFF, it usually means the General Statement hasn't been updated to cover the same date range as the LockBox or Deposited Checks files.

## Step 4: Team Posts

Team uses the dashboard to:
1. Track EOB receipt (Yes/No)
2. Mark transactions as Posted in Open Dental (Yes/No/Partial)
3. Add remarks for follow-ups
4. All changes sync in real-time via Firebase across all team members

---

## Key Rules

| Rule | Reason |
|------|--------|
| Never delete old files from OneDrive | Script accumulates data, deduplicates automatically |
| Lockbox: only Check rows count | Coupon rows have wrong amounts and $1 placeholders |
| Funding transfers are excluded | Internal money moves between PPO ↔ Medicaid, not real payments |
| PPO = S4K Ross Wez (6881784489) | Auto-detected from account name |
| Medicaid = S4K RWez ZBA (6881784534) | Auto-detected from account name |
| Change MONTH_FOLDER when month changes | In bank_pivot.py line ~22: e.g., "05. May" |

## Monthly Rollover

When a new month starts:
1. Create new subfolders in OneDrive under `Citi Bank/{New Month}/` (Reports Builder, LockBox, General Statement, Deposited Checks)
2. Update `MONTH_FOLDER` in `bank_pivot.py` (e.g., `"05. May"`)
3. Firebase data from the old month stays until manually cleared
4. Old month's data remains in OneDrive for reference
