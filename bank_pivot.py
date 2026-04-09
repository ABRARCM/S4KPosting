import pandas as pd
import hashlib
from datetime import datetime

def stable_id(prefix, *parts):
    """Generate a stable ID from transaction data so Firebase keys survive regeneration.
    Uses date + amount + payer/description to create a consistent hash.
    This means the same transaction always gets the same ID, even when
    new data is added and the HTML is regenerated."""
    raw = '|'.join(str(p).strip() for p in parts)
    short_hash = hashlib.md5(raw.encode()).hexdigest()[:10]
    return f"{prefix}-{short_hash}"

# ============================================================
# DATA SOURCE: Reads ALL CSVs from OneDrive Reports Builder folder
# AND any local Build Report files. New weekly exports are additive —
# old data is never lost, new data just gets appended.
#
# PPO vs Medicaid auto-detected by account:
#   S4K Ross Wez (6881784489) = PPO
#   S4K RWez ZBA (6881784534) = Medicaid
# ============================================================
import glob
import os

ONEDRIVE_BASE = "/Users/Admin/Library/CloudStorage/OneDrive-ChildSmilesGroup,LLC(2)/ABRA RCM - PA/PA Posting/Citi Bank"
MONTH_FOLDER = "04. April"
REPORTS_BUILDER = f"{ONEDRIVE_BASE}/{MONTH_FOLDER}/Reports Builder"

# Classify PPO vs Medicaid by destination account
def detect_source(row):
    to_acct = str(row.get('To Account Name', '')).strip()
    from_acct = str(row.get('From Account Name', '')).strip()
    if to_acct == 'S4K RWez ZBA' or from_acct == 'S4K RWez ZBA':
        return 'Medicaid'
    return 'PPO'

# Read ALL CSVs from OneDrive Reports Builder (combined format)
all_frames = []
report_files = sorted(glob.glob(f"{REPORTS_BUILDER}/*.csv"), key=os.path.getmtime)
for rf in report_files:
    print(f"Reading OneDrive: {os.path.basename(rf)}")
    tmp = pd.read_csv(rf)
    tmp['_source'] = tmp.apply(detect_source, axis=1)
    all_frames.append(tmp)


if not all_frames:
    raise FileNotFoundError("No CSV files found in OneDrive Reports Builder or local Build Report folder")

df = pd.concat(all_frames, ignore_index=True)

# Deduplicate — same date + amount + from account + ACH ID = same transaction
df['_dedup_key'] = (
    df['Date'].astype(str) + '|' +
    df['Amount'].astype(str) + '|' +
    df['From Account Name'].astype(str).str.strip() + '|' +
    df['ACH Individual ID'].astype(str).str.strip()
)
before = len(df)
df = df.drop_duplicates(subset='_dedup_key', keep='first')
dupes = before - len(df)
if dupes > 0:
    print(f"Removed {dupes} duplicate transactions")
df = df.drop(columns=['_dedup_key'])

# Clean columns
df.columns = df.columns.str.strip()
df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
df['Date'] = pd.to_datetime(df['Date'])
df['From Account Name'] = df['From Account Name'].str.strip()
df['To Account Name'] = df['To Account Name'].astype(str).str.strip()
df['ACH Individual ID'] = df['ACH Individual ID'].astype(str).str.strip()
df['ACH Description'] = df['ACH Description'].astype(str).str.strip() if 'ACH Description' in df.columns else ''
df['ACH Entry Description'] = df['ACH Entry Description'].astype(str).str.strip() if 'ACH Entry Description' in df.columns else ''

# Exclude internal funding transfers (Payment Method = "Other Transactions")
# These are money moves between PPO and Medicaid accounts, not real payments.
# Example: Skygen pays $524K to Medicaid → internal transfer moves it to PPO.
# Without this filter, the transfer shows as a duplicate "nan" EFT under PPO.
if 'Payment Method' in df.columns:
    transfers = df['Payment Method'].astype(str).str.strip() == 'Other Transactions'
    num_transfers = transfers.sum()
    if num_transfers > 0:
        print(f"Excluded {num_transfers} internal funding transfers")
    df = df[~transfers]

incoming = df[df['Amount'] > 0].copy()
outgoing = df[df['Amount'] < 0].copy()

deposit_sources = ['BANKCARD-8740', 'MERCHANT BANKCD', 'SYNCHRONY BANK']
lockbox_sources = ['PNC-ECHO']

def classify(row):
    name = row['From Account Name']
    if name in deposit_sources:
        return 'Deposits'
    elif name in lockbox_sources:
        return 'Lockbox'
    else:
        return 'EFT'

incoming['Category'] = incoming.apply(classify, axis=1)
incoming = incoming.sort_values(['Date', 'Amount'], ascending=[False, False])

def friendly_name(row):
    from_name = row['From Account Name']
    if from_name == 'BANKCARD-8740':
        ach_id = row['ACH Individual ID']
        if 'BARTO' in ach_id: return 'Bartonsville'
        if 'SCRAN' in ach_id: return 'Scranton'
        if 'HAZLE' in ach_id: return 'Hazleton'
        if 'WILKE' in ach_id: return 'Wilkes-Barre'
        if 'TILGHMAN' in ach_id: return 'Allentown (Tilghman)'
        if 'READI' in ach_id: return 'Reading'
        return ach_id
    if from_name == 'MERCHANT BANKCD':
        ach_id = row['ACH Individual ID']
        if '182885' in ach_id: return 'Reading (Merchant)'
        if '416884' in ach_id: return 'S4K Pediatric (Merchant)'
        if '222888' in ach_id: return 'Wilkes-Barre (Merchant)'
        return f'Merchant ({ach_id})'
    if from_name == 'SYNCHRONY BANK':
        return 'Synchrony (CareCredit)'
    return from_name

incoming['Payer'] = incoming.apply(friendly_name, axis=1)

def deposit_type_label(row):
    entry = row.get('ACH Entry Description', '')
    if 'BTOT' in str(entry): return 'Batch'
    if 'MTOT' in str(entry): return 'Monthly'
    if 'DEPOSIT' in str(entry): return 'Deposit'
    return str(entry)[:15] if entry else ''

incoming['DepositType'] = incoming.apply(deposit_type_label, axis=1)

def fmt_money(val):
    return f"${val:,.2f}"

deposits = incoming[incoming['Category'] == 'Deposits']
eft_all = incoming[incoming['Category'] == 'EFT']
eft = eft_all[eft_all['_source'] == 'PPO']
eft_medicaid = eft_all[eft_all['_source'] == 'Medicaid']
lockbox = incoming[incoming['Category'] == 'Lockbox']

total_deposits = deposits['Amount'].sum()
total_eft = eft['Amount'].sum()
total_eft_medicaid = eft_medicaid['Amount'].sum()
total_lockbox = lockbox['Amount'].sum()
total_outgoing_all = outgoing['Amount'].sum()
total_incoming = incoming['Amount'].sum()
net_total = total_incoming + total_outgoing_all

date_min = df['Date'].min().strftime('%m/%d/%Y')
date_max = df['Date'].max().strftime('%m/%d/%Y')

# === Build overview rows ===
def overview_rows(data, category):
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    rows = ""
    for date_key in sorted(grouped.groups.keys(), reverse=True):
        group = grouped.get_group(date_key)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        total = group['Amount'].sum()
        count = len(group)
        rows += f"""<tr>
            <td>{date_display}</td>
            <td><span class="cat-badge cat-{category.lower()}">{category}</span></td>
            <td class="count-col">{count}</td>
            <td class="amount">{fmt_money(abs(total))}</td>
        </tr>"""
    return rows

# Overview for outgoing
def overview_out_rows(data):
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    rows = ""
    for date_key in sorted(grouped.groups.keys(), reverse=True):
        group = grouped.get_group(date_key)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        total = group['Amount'].sum()
        count = len(group)
        rows += f"""<tr>
            <td>{date_display}</td>
            <td><span class="cat-badge cat-outgoing">Outgoing</span></td>
            <td class="count-col">{count}</td>
            <td class="amount negative">({fmt_money(abs(total))})</td>
        </tr>"""
    return rows

overview_deposit_rows = overview_rows(deposits, 'Deposits')
overview_eft_rows = overview_rows(eft, 'EFT')
overview_outgoing_rows = overview_out_rows(outgoing)

# === Build detail rows with Posted dropdown ===
# NOTE: All data-row IDs use stable_id() which hashes transaction data (date+amount+payer+ACH).
# This ensures Firebase keys survive when the HTML is regenerated with new data.
# Old transactions keep their IDs (and their Posted/EOB/Remarks state), new ones get new IDs.

def detail_deposit_rows(data):
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    html = ""
    date_keys = sorted(grouped.groups.keys(), reverse=True)
    for date_key in date_keys:
        group = grouped.get_group(date_key).sort_values('Amount', ascending=False)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        date_total = group['Amount'].sum()
        date_count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="5">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{date_count} deposits &bull; <strong>{fmt_money(date_total)}</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            html += f"""<tr>
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge deposit-badge">{row['Payer']}</span></td>
            <td class="type-col">{row['DepositType']}</td>
            <td class="amount">{fmt_money(row['Amount'])}</td>
            <td class="ach-col">{row['ACH Individual ID']}</td>
        </tr>"""
    return html

def detail_eft_rows(data):
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    html = ""
    date_keys = sorted(grouped.groups.keys(), reverse=True)
    for date_key in date_keys:
        group = grouped.get_group(date_key).sort_values('Amount', ascending=False)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        date_total = group['Amount'].sum()
        date_count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="8">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{date_count} EFTs &bull; <strong>{fmt_money(date_total)}</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            sid = stable_id('eft', date_key, row['From Account Name'], row['Amount'], row['ACH Individual ID'])
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge eft-badge">{row['From Account Name']}</span></td>
            <td class="amount">{fmt_money(row['Amount'])}</td>
            <td class="ach-col">{row['ACH Individual ID']}</td>
            <td class="desc-col">{row['ACH Description']}</td>
            <td class="posted-col">
                <select class="posted-select eob-select" data-row="eob-{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                </select>
            </td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
            <td class="remarks-col">
                <input type="text" class="remarks-input" data-row="rmk-{sid}" placeholder="Add remarks..." onchange="saveRemark(this)">
            </td>
        </tr>"""
    return html

def detail_lockbox_rows(data):
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    html = ""
    date_keys = sorted(grouped.groups.keys(), reverse=True)
    for date_key in date_keys:
        group = grouped.get_group(date_key).sort_values('Amount', ascending=False)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        date_total = group['Amount'].sum()
        date_count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="6">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{date_count} checks &bull; <strong>{fmt_money(date_total)}</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            sid = stable_id('lb', date_key, row['From Account Name'], row['Amount'], row['ACH Individual ID'])
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge lockbox-badge">PNC Lockbox</span></td>
            <td class="amount">{fmt_money(row['Amount'])}</td>
            <td class="ach-col">{row['ACH Individual ID']}</td>
            <td class="desc-col">{row['ACH Description']}</td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
        </tr>"""
    return html

def detail_outgoing_rows(data):
    data = data.sort_values(['Date', 'Amount'], ascending=[False, True])
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    html = ""
    date_keys = sorted(grouped.groups.keys(), reverse=True)
    for date_key in date_keys:
        group = grouped.get_group(date_key).sort_values('Amount')
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        date_total = group['Amount'].sum()
        date_count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="6">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{date_count} debits &bull; <strong class="negative">({fmt_money(abs(date_total))})</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            to_name = row['To Account Name'] if pd.notna(row.get('To Account Name')) else ''
            sid = stable_id('out', date_key, to_name, row['Amount'], row['ACH Individual ID'])
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge outgoing-badge">{to_name}</span></td>
            <td class="amount negative">({fmt_money(abs(row['Amount']))})</td>
            <td class="ach-col">{row['ACH Individual ID']}</td>
            <td class="desc-col">{row['ACH Entry Description'] if pd.notna(row.get('ACH Entry Description')) else ''}</td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
        </tr>"""
    return html

# === LOCKBOX CSV DATA ===
# Read ALL lockbox CSVs from OneDrive + local folder, combine and deduplicate
ONEDRIVE_LOCKBOX = f"{ONEDRIVE_BASE}/{MONTH_FOLDER}/LockBox"

lb_frames = []
for lb_path in [ONEDRIVE_LOCKBOX]:
    for lf in sorted(glob.glob(f"{lb_path}/*.csv")):
        print(f"Reading Lockbox: {os.path.basename(lf)}")
        tmp = pd.read_csv(lf)
        tmp.columns = tmp.columns.str.strip()
        lb_frames.append(tmp)

if lb_frames:
    lb = pd.concat(lb_frames, ignore_index=True)
else:
    lb = pd.DataFrame()

lb['Amount'] = pd.to_numeric(lb['Amount'], errors='coerce')
lb['Processed Date'] = pd.to_datetime(lb['Processed Date'], format='%Y%m%d')
lb['Lockbox Number'] = lb['Lockbox Number'].astype(str).str.strip()
lb['Item Type'] = lb['Item Type'].astype(str).str.strip()

# Only use Check rows (not Coupon). Check rows have the actual check numbers and amounts.
lb = lb[(lb['Item Type'] == 'Check') & (lb['Amount'] > 0)]

# Deduplicate by Transaction ID
if 'Transaction ID' in lb.columns:
    before_lb = len(lb)
    lb = lb.drop_duplicates(subset='Transaction ID', keep='first')
    lb_dupes = before_lb - len(lb)
    if lb_dupes > 0:
        print(f"Removed {lb_dupes} duplicate lockbox rows")

lb_checks = lb.copy()

# Format check numbers as integers (avoid scientific notation like 1.000400e+09)
lb_checks['Check Number'] = lb_checks['Check Number'].apply(
    lambda x: str(int(float(x))) if pd.notna(x) and str(x).strip() not in ['', 'nan'] else ''
)
lb_checks = lb_checks.sort_values(['Processed Date', 'Amount'], ascending=[False, False])

lb_ppo = lb_checks[lb_checks['Lockbox Number'] == '11234']
lb_medicaid = lb_checks[lb_checks['Lockbox Number'] == '11233']
total_lb_ppo = lb_ppo['Amount'].sum()
total_lb_medicaid = lb_medicaid['Amount'].sum()

def detail_lockbox_detail_rows(data, prefix):
    grouped = data.groupby(data['Processed Date'].dt.strftime('%Y-%m-%d'))
    html = ""
    date_keys = sorted(grouped.groups.keys(), reverse=True)
    for date_key in date_keys:
        group = grouped.get_group(date_key).sort_values('Amount', ascending=False)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        date_total = group['Amount'].sum()
        date_count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="6">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{date_count} checks &bull; <strong>{fmt_money(date_total)}</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            chk = row['Check Number'] if pd.notna(row['Check Number']) and row['Check Number'] != 'nan' else ''
            sid = stable_id(prefix, date_key, row['Amount'], chk, row.get('Transaction ID', ''))
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td class="check-col">{chk}</td>
            <td class="amount">{fmt_money(row['Amount'])}</td>
            <td class="posted-col">
                <select class="posted-select eob-select" data-row="eob-{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                </select>
            </td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
            <td class="remarks-col">
                <input type="text" class="remarks-input" data-row="rmk-{sid}" placeholder="Add remarks..." onchange="saveRemark(this)">
            </td>
        </tr>"""
    return html

lb_ppo_rows = detail_lockbox_detail_rows(lb_ppo, 'lbppo')
lb_medicaid_rows = detail_lockbox_detail_rows(lb_medicaid, 'lbmed')

# === BANK GENERAL (STATEMENT) DATA — Credits only, no transfers ===
def load_bank_general(path, acct_name):
    bg = pd.read_csv(path, names=['DATE','TYPE','DESCRIPTION','AMOUNT','BALANCE','_extra'], skiprows=1)
    bg = bg.drop(columns=['_extra'], errors='ignore')
    bg['AMOUNT'] = pd.to_numeric(bg['AMOUNT'], errors='coerce')
    bg['DATE'] = pd.to_datetime(bg['DATE'])
    bg['DESCRIPTION'] = bg['DESCRIPTION'].astype(str)
    bg['TYPE'] = bg['TYPE'].astype(str).str.strip()
    bg['ACCT'] = acct_name
    # Only credits (positive amounts), exclude debits and transfers
    bg = bg[bg['AMOUNT'] > 0].copy()
    # Classify
    def classify_bg(desc):
        d = desc.upper()
        if 'BANKCARD' in d or 'MERCHANT BANKCD' in d or 'SYNCHRONY' in d:
            return 'Card Deposits'
        if 'LOCKBOX' in d:
            return 'Lockbox'
        if 'FUNDING TRANSFER' in d:
            return 'Transfer'
        if d.startswith('DEPOSIT') and 'LOCKBOX' not in d:
            return 'Deposit'
        return 'EFT'
    bg['BG_CAT'] = bg['DESCRIPTION'].apply(classify_bg)
    # Exclude transfers
    bg = bg[bg['BG_CAT'] != 'Transfer'].copy()
    return bg

# Bank General Statements — read ALL CSVs per account, combine and deduplicate
ONEDRIVE_GENERAL = f"{ONEDRIVE_BASE}/{MONTH_FOLDER}/General Statement"

def find_bank_general(acct_num, acct_label):
    """Read ALL bank general CSVs for a given account and combine them."""
    files = sorted(glob.glob(f"{ONEDRIVE_GENERAL}/*{acct_num}*.csv"), key=os.path.getmtime)
    if not files:
        print(f"Warning: No Bank General file found for {acct_label} ({acct_num})")
        return pd.DataFrame(columns=['DATE','TYPE','DESCRIPTION','AMOUNT','BALANCE','ACCT','BG_CAT'])
    frames = []
    for f in files:
        print(f"Reading Bank General ({acct_label}): {os.path.basename(f)}")
        frames.append(load_bank_general(f, acct_label))
    combined = pd.concat(frames, ignore_index=True)
    # Deduplicate by date + amount only.
    # Same transaction can have different description formats across statement files
    # (e.g., "ACH ELECTRONIC CREDIT..." vs "ACH-ZP SKYGENOPT510TRN...")
    combined['_bg_dedup'] = combined['DATE'].astype(str) + '|' + combined['AMOUNT'].astype(str)
    before = len(combined)
    combined = combined.drop_duplicates(subset='_bg_dedup', keep='first')
    dupes = before - len(combined)
    if dupes > 0:
        print(f"  Removed {dupes} duplicate Bank General rows")
    combined = combined.drop(columns=['_bg_dedup'])
    return combined

bg_ppo = find_bank_general('6881784489', 'PPO')
bg_med = find_bank_general('6881784534', 'Medicaid')

# Check Deposits from Build Report (PNC-ECHO rows)
check_deposits = incoming[incoming['Category'] == 'Lockbox']
total_check_deposits = check_deposits['Amount'].sum()

def detail_check_deposit_rows(data):
    grouped = data.groupby(data['Date'].dt.strftime('%Y-%m-%d'))
    html = ""
    date_keys = sorted(grouped.groups.keys(), reverse=True)
    for date_key in date_keys:
        group = grouped.get_group(date_key).sort_values('Amount', ascending=False)
        date_display = datetime.strptime(date_key, '%Y-%m-%d').strftime('%m/%d/%Y')
        date_total = group['Amount'].sum()
        date_count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="7">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{date_count} check deposits &bull; <strong>{fmt_money(date_total)}</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            sid = stable_id('chk', date_key, row['From Account Name'], row['Amount'], row['ACH Individual ID'])
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge eft-badge">{row['From Account Name']}</span></td>
            <td class="amount">{fmt_money(row['Amount'])}</td>
            <td class="ach-col">{row['ACH Individual ID']}</td>
            <td class="desc-col">{row['ACH Description']}</td>
            <td class="posted-col">
                <select class="posted-select eob-select" data-row="eob-{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                </select>
            </td>
            <td class="remarks-col">
                <input type="text" class="remarks-input" data-row="rmk-{sid}" placeholder="Add remarks..." onchange="saveRemark(this)">
            </td>
        </tr>"""
    return html

chk_dep_rows = detail_check_deposit_rows(check_deposits)

# Build overview for each account — EFT and Lockbox only
def build_acct_overview(bg_data):
    # Group by date, then by category
    bg_data = bg_data.sort_values('DATE', ascending=False)
    dates = sorted(bg_data['DATE'].dt.strftime('%Y-%m-%d').unique(), reverse=True)
    rows = ""
    grand_eft = 0
    grand_lb = 0
    grand_total = 0
    for dt in dates:
        day = bg_data[bg_data['DATE'].dt.strftime('%Y-%m-%d') == dt]
        date_display = datetime.strptime(dt, '%Y-%m-%d').strftime('%m/%d/%Y')
        day_eft = day[day['BG_CAT'] == 'EFT']['AMOUNT'].sum()
        day_lb = day[day['BG_CAT'] == 'Lockbox']['AMOUNT'].sum()
        # Also catch generic "Deposit" rows
        day_dep = day[day['BG_CAT'] == 'Deposit']['AMOUNT'].sum()
        day_eft += day_dep
        day_total = day_eft + day_lb
        grand_eft += day_eft
        grand_lb += day_lb
        grand_total += day_total
        rows += f"""<tr>
            <td class="date-col" style="font-weight:600;color:#023E8A">{date_display}</td>
            <td class="amount">{fmt_money(day_eft) if day_eft > 0 else '—'}</td>
            <td class="amount" style="color:#A855F7">{fmt_money(day_lb) if day_lb > 0 else '—'}</td>
            <td class="amount" style="font-weight:800">{fmt_money(day_total)}</td>
        </tr>"""
    rows += f"""<tr class="total-row">
        <td><strong>TOTAL</strong></td>
        <td class="amount"><strong>{fmt_money(grand_eft)}</strong></td>
        <td class="amount" style="color:#A855F7"><strong>{fmt_money(grand_lb)}</strong></td>
        <td class="amount" style="font-weight:800"><strong>{fmt_money(grand_total)}</strong></td>
    </tr>"""
    return rows, grand_eft, grand_lb, grand_total

ppo_overview_rows, ppo_eft, ppo_lb, ppo_total = build_acct_overview(bg_ppo)
med_overview_rows, med_eft, med_lb, med_total = build_acct_overview(bg_med)

# === BANK DEPOSITS TAB — Lockbox deposits from Bank General, reconciled with Lockbox detail ===
# Get all deposit/lockbox rows from Bank General (both accounts)
def get_bank_deposits(bg_data, lockbox_num, acct_label):
    deposits_lb = bg_data[bg_data['BG_CAT'] == 'Lockbox'].copy()
    deposits_other = bg_data[bg_data['BG_CAT'] == 'Deposit'].copy()
    all_dep = pd.concat([deposits_lb, deposits_other], ignore_index=True)
    all_dep = all_dep.sort_values('DATE', ascending=False)
    all_dep['LB_NUM'] = lockbox_num
    all_dep['ACCT_LABEL'] = acct_label
    return all_dep

bank_dep_ppo = get_bank_deposits(bg_ppo, '11234', 'PPO')
bank_dep_med = get_bank_deposits(bg_med, '11233', 'Medicaid')

# Build the deposits tab rows with lockbox reconciliation
def build_bank_deposit_rows(bank_deps, lb_detail, lockbox_num, prefix):
    html = ""
    bank_deps = bank_deps.sort_values('DATE', ascending=False)
    dates = sorted(bank_deps['DATE'].dt.strftime('%Y-%m-%d').unique(), reverse=True)

    for dt in dates:
        day = bank_deps[bank_deps['DATE'].dt.strftime('%Y-%m-%d') == dt]
        date_display = datetime.strptime(dt, '%Y-%m-%d').strftime('%m/%d/%Y')

        # Split lockbox vs check deposits
        day_lb = day[day['BG_CAT'] == 'Lockbox']
        day_chk = day[day['BG_CAT'] == 'Deposit']
        lb_bank_total = day_lb['AMOUNT'].sum()
        chk_total = day_chk['AMOUNT'].sum()

        # Get lockbox detail for same date
        lb_day = lb_detail[lb_detail['Processed Date'].dt.strftime('%Y-%m-%d') == dt]
        lb_detail_total = lb_day['Amount'].sum() if not lb_day.empty else 0
        lb_count = len(lb_day)

        matched = abs(lb_bank_total - lb_detail_total) < 0.01
        match_class = 'match-yes' if matched else 'match-no'
        match_text = 'YES' if matched else f'NO — diff {fmt_money(abs(lb_bank_total - lb_detail_total))}'

        # Date header — only reconcile lockbox portion
        stats = f'Lockbox: <strong>{fmt_money(lb_bank_total)}</strong> vs Detail: <strong>{fmt_money(lb_detail_total)}</strong> ({lb_count} checks) &bull; <span class="{match_class}">{match_text}</span>'
        if chk_total > 0:
            stats += f' &bull; Check Deposits: <strong>{fmt_money(chk_total)}</strong>'

        html += f"""<tr class="date-header">
            <td colspan="5">
                <span class="date-label">{date_display}</span>
                <span class="date-stats">{stats}</span>
            </td>
        </tr>"""

        # Lockbox rows first
        for _, r in day_lb.iterrows():
            sid = stable_id(f'bdep-{prefix}', dt, r['AMOUNT'], r['DESCRIPTION'][:40])
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge lockbox-badge">Lockbox #{lockbox_num}</span></td>
            <td class="desc-col">{r['DESCRIPTION'][:60]}</td>
            <td class="amount">{fmt_money(r['AMOUNT'])}</td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
        </tr>"""

        # Check deposit rows separate
        for _, r in day_chk.iterrows():
            sid = stable_id(f'bchk-{prefix}', dt, r['AMOUNT'], r['DESCRIPTION'][:40])
            html += f"""<tr data-row="{sid}">
            <td class="date-col">{date_display}</td>
            <td><span class="payer-badge deposit-badge">Check Deposit</span></td>
            <td class="desc-col">{r['DESCRIPTION'][:60]}</td>
            <td class="amount">{fmt_money(r['AMOUNT'])}</td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
        </tr>"""
    return html

bank_dep_ppo_rows = build_bank_deposit_rows(bank_dep_ppo, lb_ppo, '11234', 'bppo')
bank_dep_med_rows = build_bank_deposit_rows(bank_dep_med, lb_medicaid, '11233', 'bmed')

total_bank_dep_ppo = bank_dep_ppo['AMOUNT'].sum()
total_bank_dep_med = bank_dep_med['AMOUNT'].sum()

# Pre-compute match badges for reconciliation
def match_badge(val_a, val_b):
    if abs(val_a - val_b) < 0.01:
        return '<span class="match-yes">MATCH</span>'
    else:
        return f'<span class="match-no">DIFF {fmt_money(abs(val_a - val_b))}</span>'

# General Statement totals for lockbox and deposits (per account)
gs_lb_ppo = bg_ppo[bg_ppo['BG_CAT'] == 'Lockbox']['AMOUNT'].sum() if not bg_ppo.empty else 0
gs_lb_med = bg_med[bg_med['BG_CAT'] == 'Lockbox']['AMOUNT'].sum() if not bg_med.empty else 0
gs_dep_ppo = bg_ppo[bg_ppo['BG_CAT'] == 'Deposit']['AMOUNT'].sum() if not bg_ppo.empty else 0
gs_dep_med = bg_med[bg_med['BG_CAT'] == 'Deposit']['AMOUNT'].sum() if not bg_med.empty else 0
gs_dep_total = gs_dep_ppo + gs_dep_med

# Reconciliation badges (match_dep_checks computed after deposited checks are loaded below)


# === DEPOSITED CHECKS (from CitiBank Deposited Checks folder) ===
# These are the individual checks that make up the "Deposit" line items in the Bank General statement.
# Each CSV file = one deposit slip with individual check breakdowns.
DEPOSITED_CHECKS_PATH = f"{ONEDRIVE_BASE}/{MONTH_FOLDER}/Deposited Checks"
dep_check_files = sorted(glob.glob(f"{DEPOSITED_CHECKS_PATH}/*.csv"), key=os.path.getmtime, reverse=True)

all_dep_checks = []
for dcf in dep_check_files:
    try:
        dc = pd.read_csv(dcf)
        dc.columns = dc.columns.str.strip()
        # First row is "Deposit Slip" with total — extract deposit date/total info
        slip_row = dc[dc['Item'] == 'Deposit Slip']
        deposit_total = 0
        deposit_acct = ''
        if not slip_row.empty:
            amt_str = str(slip_row.iloc[0].get('Amount', '0'))
            amt_str = amt_str.replace('"', '').replace(',', '')
            deposit_total = float(amt_str) if amt_str else 0
            deposit_acct = str(slip_row.iloc[0].get('To Account Number', ''))
        # Get individual checks
        checks = dc[dc['Item'] == 'Check'].copy()
        checks['_deposit_total'] = deposit_total
        checks['_deposit_acct'] = deposit_acct
        checks['_source_file'] = os.path.basename(dcf)
        # Clean amount — handle quoted amounts with commas
        checks['Amount'] = checks['Amount'].astype(str).str.replace('"', '').str.replace(',', '')
        checks['Amount'] = pd.to_numeric(checks['Amount'], errors='coerce')
        checks['Check #'] = checks['Check #'].astype(str).str.strip()
        all_dep_checks.append(checks)
    except Exception as e:
        print(f"Warning: Could not read {dcf}: {e}")

if all_dep_checks:
    dep_checks_df = pd.concat(all_dep_checks, ignore_index=True)
    dep_checks_df = dep_checks_df.sort_values('Amount', ascending=False)
else:
    dep_checks_df = pd.DataFrame()

total_dep_checks = dep_checks_df['Amount'].sum() if not dep_checks_df.empty else 0
num_dep_checks = len(dep_checks_df)

def detail_deposited_check_rows(data):
    if data.empty:
        return ""
    html = ""
    # Group by deposit slip (source file = one deposit)
    for source_file in data['_source_file'].unique():
        group = data[data['_source_file'] == source_file].sort_values('Amount', ascending=False)
        slip_total = group['_deposit_total'].iloc[0]
        slip_acct = group['_deposit_acct'].iloc[0]
        acct_label = 'PPO' if '6881784489' in str(slip_acct) else 'Medicaid'
        count = len(group)
        html += f"""<tr class="date-header">
            <td colspan="8">
                <span class="date-label">Deposit Slip — {acct_label}</span>
                <span class="date-stats">{count} checks &bull; Slip Total: <strong>{fmt_money(slip_total)}</strong></span>
            </td>
        </tr>"""
        for _, row in group.iterrows():
            chk_num = row['Check #'] if pd.notna(row['Check #']) and row['Check #'] != 'nan' else ''
            from_acct = str(row.get('From Account', '')) if pd.notna(row.get('From Account')) else ''
            routing = str(row.get('Routing Number', '')) if pd.notna(row.get('Routing Number')) else ''
            sid = stable_id('depchk', chk_num, row['Amount'], from_acct)
            html += f"""<tr data-row="{sid}">
            <td class="check-col">{chk_num}</td>
            <td class="amount">{fmt_money(row['Amount'])}</td>
            <td class="ach-col">{from_acct}</td>
            <td class="ach-col">{routing}</td>
            <td class="posted-col">
                <select class="posted-select eob-select" data-row="eob-{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                </select>
            </td>
            <td class="posted-col">
                <select class="posted-select" data-row="{sid}" onchange="updateStatus(this)">
                    <option value="">--</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                    <option value="partial">Partial</option>
                </select>
            </td>
            <td class="remarks-col">
                <input type="text" class="remarks-input" data-row="rmk-{sid}" placeholder="Add remarks..." onchange="saveRemark(this)">
            </td>
        </tr>"""
    return html

dep_check_rows_html = detail_deposited_check_rows(dep_checks_df)

# Reconciliation badges (computed after all data is loaded)
match_lb_ppo = match_badge(total_lb_ppo, gs_lb_ppo)
match_lb_med = match_badge(total_lb_medicaid, gs_lb_med)
match_dep_checks = match_badge(total_dep_checks, gs_dep_total)

dep_rows = detail_deposit_rows(deposits)
eft_rows_html = detail_eft_rows(eft)
eft_med_rows_html = detail_eft_rows(eft_medicaid)
# Filter outgoing to insurance payers only (exclude card processing/fees)
non_insurance_out = ['BANKCARD-8740', 'MERCHANT BANKCD', 'CLEARENT LLC', 'SYNCHRONY BANK']
outgoing_ins = outgoing[~outgoing['To Account Name'].str.strip().isin(non_insurance_out)]
total_outgoing = outgoing_ins['Amount'].sum()
out_rows = detail_outgoing_rows(outgoing_ins)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smiles 4 Keeps PA — Bank Posting — {date_min} to {date_max}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'Poppins', sans-serif;
        background: #f0f4f8;
        color: #1a1a2e;
        padding: 0;
        font-size: 15px;
    }}

    .header {{
        background: linear-gradient(135deg, #023E8A 0%, #0077B6 50%, #00B4D8 100%);
        color: white;
        padding: 24px 36px;
        display: flex;
        align-items: center;
        gap: 20px;
        box-shadow: 0 4px 20px rgba(2, 62, 138, 0.3);
    }}
    .header img {{ height: 50px; }}
    .header h1 {{ font-size: 28px; font-weight: 800; }}
    .header .subtitle {{ font-size: 14px; opacity: 0.85; }}
    .header .date-range {{
        margin-left: auto;
        font-size: 18px;
        font-weight: 600;
        background: rgba(255,255,255,0.15);
        padding: 8px 18px;
        border-radius: 10px;
    }}

    /* TABS */
    .tab-bar {{
        background: #023E8A;
        padding: 0 36px;
        display: flex;
        gap: 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }}
    .tab-btn {{
        padding: 14px 28px;
        color: rgba(255,255,255,0.6);
        font-size: 15px;
        font-weight: 600;
        cursor: pointer;
        border: none;
        background: none;
        font-family: 'Poppins', sans-serif;
        border-bottom: 3px solid transparent;
        transition: all 0.2s;
    }}
    .tab-btn:hover {{ color: rgba(255,255,255,0.9); }}
    .tab-btn.active {{
        color: white;
        border-bottom-color: #00B4D8;
        background: rgba(255,255,255,0.08);
    }}
    .tab-btn .tab-count {{
        font-size: 11px;
        background: rgba(255,255,255,0.15);
        padding: 2px 8px;
        border-radius: 10px;
        margin-left: 6px;
    }}
    .tab-btn.active .tab-count {{ background: #00B4D8; }}

    .tab-content {{ display: none; padding: 24px 36px; }}
    .tab-content.active {{ display: block; }}

    /* SUMMARY CARDS */
    .summary-row {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
        margin-bottom: 24px;
    }}
    .card {{
        background: white;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        position: relative;
        overflow: hidden;
    }}
    .card::before {{
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 5px;
    }}
    .card.c-deposit::before {{ background: linear-gradient(90deg, #00D2A0, #00B4D8); }}
    .card.c-eft::before {{ background: linear-gradient(90deg, #0077B6, #023E8A); }}
    .card.c-lockbox::before {{ background: linear-gradient(90deg, #A855F7, #7c3aed); }}
    .card.c-out::before {{ background: linear-gradient(90deg, #FF6B6B, #e05555); }}
    .card.c-net::before {{ background: linear-gradient(90deg, #FF9F43, #e08a2e); }}
    .card .card-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #888; font-weight: 600; }}
    .card .card-value {{ font-size: 24px; font-weight: 800; margin: 6px 0 2px; }}
    .card.c-deposit .card-value {{ color: #00a882; }}
    .card.c-eft .card-value {{ color: #0077B6; }}
    .card.c-lockbox .card-value {{ color: #A855F7; }}
    .card.c-out .card-value {{ color: #FF6B6B; }}
    .card.c-net .card-value {{ color: #FF9F43; }}
    .card .card-count {{ font-size: 12px; color: #aaa; }}

    /* HOW-TO */
    .howto {{
        background: white;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 24px;
        border-left: 5px solid #00B4D8;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }}
    .howto h3 {{ font-size: 17px; color: #023E8A; margin-bottom: 10px; }}
    .howto ul {{ list-style: none; padding: 0; }}
    .howto li {{ padding: 5px 0; font-size: 14px; display: flex; align-items: center; gap: 10px; }}
    .step-icon {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; border-radius: 50%;
        background: #023E8A; color: white;
        font-size: 12px; font-weight: 700; flex-shrink: 0;
    }}

    /* OVERVIEW TABLE */
    .overview-table {{
        width: 100%;
        border-collapse: collapse;
        background: white;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
    }}
    .overview-table th {{
        padding: 14px 20px;
        text-align: left;
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #666;
        background: #f8f9fb;
        border-bottom: 2px solid #e8ecf0;
    }}
    .overview-table td {{
        padding: 12px 20px;
        font-size: 15px;
        border-bottom: 1px solid #f0f0f0;
    }}
    .overview-table tr:hover td {{ background: #fafcff; }}

    .cat-badge {{
        display: inline-block;
        padding: 5px 16px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
    }}
    .cat-deposits {{ background: #e6fbf5; color: #00875a; }}
    .cat-eft {{ background: #e6f0ff; color: #0055b3; }}
    .cat-lockbox {{ background: #f3e8ff; color: #7c3aed; }}
    .cat-outgoing {{ background: #ffe8e8; color: #cc3333; }}

    .count-col {{ text-align: center; font-weight: 600; }}

    /* DETAIL TABLES */
    .detail-block {{
        background: white;
        border-radius: 14px;
        margin-bottom: 20px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        overflow: hidden;
    }}
    .detail-header {{
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 18px 24px;
        color: white;
    }}
    .dh-deposit {{ background: linear-gradient(135deg, #00D2A0, #00B4D8); }}
    .dh-eft {{ background: linear-gradient(135deg, #0077B6, #023E8A); }}
    .dh-lockbox {{ background: linear-gradient(135deg, #A855F7, #7c3aed); }}
    .dh-medicaid {{ background: linear-gradient(135deg, #7c3aed, #5b21b6); }}
    .dh-outgoing {{ background: linear-gradient(135deg, #FF6B6B, #d44); }}
    .detail-icon {{ font-size: 26px; }}
    .detail-title {{ font-size: 20px; font-weight: 700; }}
    .detail-sub {{ font-size: 13px; opacity: 0.85; margin-top: 2px; }}
    .detail-total {{
        margin-left: auto;
        font-size: 22px;
        font-weight: 800;
        background: rgba(255,255,255,0.2);
        padding: 8px 18px;
        border-radius: 10px;
    }}

    table {{ width: 100%; border-collapse: collapse; }}
    th {{
        padding: 12px 16px;
        text-align: left;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #777;
        background: #f8f9fb;
        border-bottom: 2px solid #e8ecf0;
    }}
    td {{
        padding: 10px 16px;
        font-size: 14px;
        border-bottom: 1px solid #f2f2f2;
        vertical-align: middle;
    }}
    tr:hover td {{ background: #fafcff; }}
    .date-header td {{
        background: #f0f4ff !important;
        padding: 13px 16px;
        border-bottom: 2px solid #c7d2fe;
    }}
    .date-label {{ font-weight: 800; font-size: 16px; color: #023E8A; }}
    .date-stats {{ float: right; font-size: 14px; color: #555; font-weight: 500; }}
    .amount {{ text-align: right; font-weight: 700; font-size: 15px; font-variant-numeric: tabular-nums; color: #1a7a5a; }}
    .negative {{ color: #FF6B6B !important; }}
    .date-col {{ color: #888; font-size: 13px; }}
    .ach-col {{ font-family: 'Courier New', monospace; font-size: 12px; color: #666; }}
    .desc-col {{ font-size: 13px; color: #888; }}
    .type-col {{ font-size: 12px; color: #666; }}
    .check-col {{ font-family: 'Courier New', monospace; font-size: 13px; font-weight: 600; color: #333; }}

    .payer-badge {{
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 600;
    }}
    .deposit-badge {{ background: #e6fbf5; color: #00875a; }}
    .eft-badge {{ background: #e6f0ff; color: #0055b3; }}
    .lockbox-badge {{ background: #f3e8ff; color: #7c3aed; }}
    .outgoing-badge {{ background: #ffe8e8; color: #cc3333; }}

    /* POSTED DROPDOWN */
    .posted-col {{ text-align: center; }}
    .posted-select {{
        font-family: 'Poppins', sans-serif;
        font-size: 13px;
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 8px;
        border: 2px solid #ddd;
        cursor: pointer;
        background: white;
        min-width: 90px;
        transition: all 0.2s;
    }}
    .posted-select:focus {{ outline: none; border-color: #0077B6; }}
    .posted-select.status-yes {{ background: #e6fbf5; border-color: #00D2A0; color: #00875a; }}
    .posted-select.status-no {{ background: #ffe8e8; border-color: #FF6B6B; color: #cc3333; }}
    .posted-select.status-partial {{ background: #fff8e6; border-color: #FF9F43; color: #c77a20; }}

    /* REMARKS INPUT */
    .remarks-col {{ padding: 6px 8px !important; }}
    .remarks-input {{
        font-family: 'Poppins', sans-serif;
        font-size: 12px;
        padding: 6px 10px;
        border: 2px solid #ddd;
        border-radius: 8px;
        width: 100%;
        min-width: 140px;
        transition: border-color 0.2s;
        background: white;
    }}
    .remarks-input:focus {{ outline: none; border-color: #0077B6; background: #f8fbff; }}
    .remarks-input.has-text {{ border-color: #00B4D8; background: #f0faff; }}

    /* ROW STATUS */
    tr.row-yes td {{ background: #f0fdf4 !important; }}
    tr.row-no td {{ background: #fff5f5 !important; }}
    tr.row-partial td {{ background: #fffbeb !important; }}

    /* PROGRESS BAR */
    .progress-bar {{
        background: white;
        border-radius: 12px;
        padding: 16px 24px;
        margin-bottom: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        display: flex;
        align-items: center;
        gap: 16px;
    }}
    .progress-bar .prog-label {{ font-size: 14px; font-weight: 600; color: #555; white-space: nowrap; }}
    .prog-track {{
        flex: 1;
        height: 12px;
        background: #e8ecf0;
        border-radius: 6px;
        overflow: hidden;
    }}
    .prog-fill {{
        height: 100%;
        background: linear-gradient(90deg, #00D2A0, #00B4D8);
        border-radius: 6px;
        transition: width 0.4s;
        width: 0%;
    }}
    .prog-text {{ font-size: 14px; font-weight: 700; color: #023E8A; min-width: 50px; text-align: right; }}

    /* DUAL ACCOUNT OVERVIEW */
    .dual-acct {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
        margin-bottom: 24px;
    }}
    .acct-block {{
        background: white;
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }}
    .acct-header {{
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 18px 24px;
        color: white;
    }}
    .ppo-header {{ background: linear-gradient(135deg, #0077B6, #023E8A); }}
    .med-header {{ background: linear-gradient(135deg, #7c3aed, #5b21b6); }}
    .acct-icon {{ font-size: 26px; }}
    .acct-title {{ font-size: 20px; font-weight: 700; }}
    .acct-num {{ font-size: 13px; opacity: 0.8; }}
    .acct-total {{
        margin-left: auto;
        font-size: 22px;
        font-weight: 800;
        background: rgba(255,255,255,0.2);
        padding: 8px 18px;
        border-radius: 10px;
    }}
    .total-row td {{
        border-top: 3px solid #023E8A;
        background: #f0f4ff !important;
        font-size: 16px;
    }}
    .cat-transfer {{ background: #fff3e0; color: #e65100; }}
    .match-col {{ text-align: center; }}
    .match-yes {{ background: #e6fbf5; color: #00875a; padding: 4px 14px; border-radius: 20px; font-weight: 700; font-size: 13px; }}
    .match-no {{ background: #ffe8e8; color: #cc3333; padding: 4px 14px; border-radius: 20px; font-weight: 700; font-size: 13px; }}
    .dh-checkdep {{ background: linear-gradient(135deg, #00B4D8, #0077B6); }}

    /* RECON BLOCK */
    .recon-block {{
        background: white;
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }}
    .recon-header {{
        background: linear-gradient(135deg, #FF9F43, #e08a2e);
        color: white;
        padding: 16px 24px;
        font-size: 18px;
        font-weight: 700;
    }}

    @media print {{
        body {{ font-size: 11px; }}
        .tab-bar {{ display: none; }}
        .tab-content {{ display: block !important; padding: 12px; }}
        .posted-select {{ border: 1px solid #ccc; }}
    }}
</style>
</head>
<body>

<div class="header">
    <img src="https://abrahealthgroup.com/wp-content/uploads/2022/09/Asset-48@4x-copy.png" alt="Abra Health">
    <div>
        <h1>Smiles 4 Keeps PA — Bank Posting</h1>
        <div class="subtitle">What needs to be posted in Open Dental</div>
    </div>
    <div class="date-range">{date_min} - {date_max}</div>
</div>

<div class="tab-bar">
    <button class="tab-btn active" onclick="showTab('overview')">Overview</button>
    <button class="tab-btn" onclick="showTab('bankdep')">Deposits</button>
    <button class="tab-btn" onclick="showTab('eft')">PPO EFT <span class="tab-count">{len(eft)}</span></button>
    <button class="tab-btn" onclick="showTab('eftmed')">Medicaid EFT <span class="tab-count">{len(eft_medicaid)}</span></button>
    <button class="tab-btn" onclick="showTab('lbppo')">Lockbox PPO <span class="tab-count">{len(lb_ppo)}</span></button>
    <button class="tab-btn" onclick="showTab('lbmed')">Lockbox Medicaid <span class="tab-count">{len(lb_medicaid)}</span></button>
    <button class="tab-btn" onclick="showTab('depchk')">Deposited Checks <span class="tab-count">{num_dep_checks}</span></button>
    <button class="tab-btn" onclick="showTab('outgoing')">Outgoing <span class="tab-count">{len(outgoing_ins)}</span></button>
    <button class="tab-btn" onclick="showTab('deposits')">Card Deposits <span class="tab-count">{len(deposits)}</span></button>
    <button class="tab-btn" onclick="showTab('checkdep')">PNC <span class="tab-count">{len(check_deposits)}</span></button>
</div>

<!-- ==================== OVERVIEW TAB ==================== -->
<div id="tab-overview" class="tab-content active">

    <div class="howto">
        <h3>How to Use This Report</h3>
        <ul>
            <li><span class="step-icon">1</span> <strong>CARD DEPOSITS</strong> (green) = Credit card batches by location. Match to CC batch reports in Open Dental.</li>
            <li><span class="step-icon">2</span> <strong>PNC</strong> (teal) = PNC-ECHO cash deposits showing on bank statement. Match to EOBs.</li>
            <li><span class="step-icon">3</span> <strong>PPO EFT / MEDICAID EFT</strong> (blue) = Insurance electronic payments. Match to ERA/835 files.</li>
            <li><span class="step-icon">4</span> <strong>LOCKBOX PPO / MEDICAID</strong> (purple) = Lockbox detail with check numbers. Use to match individual checks.</li>
            <li><span class="step-icon">!</span> <strong>OUTGOING</strong> (red) = Insurance debits only. Review for accuracy.</li>
        </ul>
    </div>

    <div class="progress-bar">
        <div class="prog-label">Posting Progress:</div>
        <div class="prog-track"><div class="prog-fill" id="progressFill"></div></div>
        <div class="prog-text" id="progressText">0%</div>
    </div>

    <!-- DUAL ACCOUNT OVERVIEW -->
    <div class="dual-acct">
        <div class="acct-block">
            <div class="acct-header ppo-header">
                <div class="acct-icon">🏦</div>
                <div>
                    <div class="acct-title">PPO Account</div>
                    <div class="acct-num">Checking ...4489</div>
                </div>
                <div class="acct-total">{fmt_money(ppo_total)}</div>
            </div>
            <table class="overview-table">
                <thead><tr>
                    <th>Date</th>
                    <th style="text-align:right">EFT</th>
                    <th style="text-align:right">Lockbox</th>
                    <th style="text-align:right">Day Total</th>
                </tr></thead>
                <tbody>{ppo_overview_rows}</tbody>
            </table>
        </div>
        <div class="acct-block">
            <div class="acct-header med-header">
                <div class="acct-icon">🏦</div>
                <div>
                    <div class="acct-title">Medicaid Account</div>
                    <div class="acct-num">Checking ...4534</div>
                </div>
                <div class="acct-total">{fmt_money(med_total)}</div>
            </div>
            <table class="overview-table">
                <thead><tr>
                    <th>Date</th>
                    <th style="text-align:right">EFT</th>
                    <th style="text-align:right">Lockbox</th>
                    <th style="text-align:right">Day Total</th>
                </tr></thead>
                <tbody>{med_overview_rows}</tbody>
            </table>
        </div>
    </div>

    <!-- EFT SUMMARY — Reports Builder -->
    <div class="recon-block">
        <div class="recon-header">EFT Summary — Reports Builder</div>
        <table class="overview-table">
            <thead><tr>
                <th>Category</th>
                <th style="text-align:center">Count</th>
                <th style="text-align:right">Total Amount</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td><span class="cat-badge cat-eft">PPO EFT</span></td>
                    <td class="count-col">{len(eft)}</td>
                    <td class="amount">{fmt_money(total_eft)}</td>
                </tr>
                <tr>
                    <td><span class="cat-badge cat-eft">Medicaid EFT</span></td>
                    <td class="count-col">{len(eft_medicaid)}</td>
                    <td class="amount">{fmt_money(total_eft_medicaid)}</td>
                </tr>
                <tr style="border-top:2px solid #023E8A">
                    <td><strong>Total EFT</strong></td>
                    <td class="count-col"><strong>{len(eft) + len(eft_medicaid)}</strong></td>
                    <td class="amount"><strong>{fmt_money(total_eft + total_eft_medicaid)}</strong></td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- LOCKBOX RECONCILIATION — LockBox Folder vs General Statement -->
    <div class="recon-block" style="margin-top:16px">
        <div class="recon-header">Lockbox Reconciliation — LockBox Folder vs General Statement</div>
        <table class="overview-table">
            <thead><tr>
                <th>Category</th>
                <th style="text-align:center">Count</th>
                <th style="text-align:right">LockBox Folder</th>
                <th style="text-align:right">General Statement</th>
                <th style="text-align:center">Status</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td><span class="cat-badge cat-lockbox">PPO Lockbox #11234</span></td>
                    <td class="count-col">{len(lb_ppo)}</td>
                    <td class="amount">{fmt_money(total_lb_ppo)}</td>
                    <td class="amount">{fmt_money(gs_lb_ppo)}</td>
                    <td class="match-col">{match_lb_ppo}</td>
                </tr>
                <tr>
                    <td><span class="cat-badge cat-lockbox">Medicaid Lockbox #11233</span></td>
                    <td class="count-col">{len(lb_medicaid)}</td>
                    <td class="amount">{fmt_money(total_lb_medicaid)}</td>
                    <td class="amount">{fmt_money(gs_lb_med)}</td>
                    <td class="match-col">{match_lb_med}</td>
                </tr>
                <tr style="border-top:2px solid #023E8A">
                    <td><strong>Total Lockbox</strong></td>
                    <td class="count-col"><strong>{len(lb_ppo) + len(lb_medicaid)}</strong></td>
                    <td class="amount"><strong>{fmt_money(total_lb_ppo + total_lb_medicaid)}</strong></td>
                    <td class="amount"><strong>{fmt_money(gs_lb_ppo + gs_lb_med)}</strong></td>
                    <td class="match-col">{match_badge(total_lb_ppo + total_lb_medicaid, gs_lb_ppo + gs_lb_med)}</td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- DEPOSITED CHECKS RECONCILIATION — Checks Folder vs General Statement -->
    <div class="recon-block" style="margin-top:16px">
        <div class="recon-header">Deposited Checks Reconciliation — Checks Folder vs General Statement</div>
        <table class="overview-table">
            <thead><tr>
                <th>Category</th>
                <th style="text-align:center">Count</th>
                <th style="text-align:right">Checks Folder</th>
                <th style="text-align:right">General Statement</th>
                <th style="text-align:center">Status</th>
            </tr></thead>
            <tbody>
                <tr>
                    <td><span class="cat-badge cat-deposits">Deposited Checks</span></td>
                    <td class="count-col">{num_dep_checks}</td>
                    <td class="amount">{fmt_money(total_dep_checks)}</td>
                    <td class="amount">{fmt_money(gs_dep_total)}</td>
                    <td class="match-col">{match_dep_checks}</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>

<!-- ==================== BANK DEPOSITS TAB ==================== -->
<div id="tab-bankdep" class="tab-content">
    <div class="detail-block">
        <div class="detail-header ppo-header">
            <div class="detail-icon">🏦</div>
            <div>
                <div class="detail-title">PPO Deposits — Bank Statement vs Lockbox #11234</div>
                <div class="detail-sub">Each date shows bank deposit total vs lockbox detail total</div>
            </div>
            <div class="detail-total">{fmt_money(total_bank_dep_ppo)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Type</th>
                <th>Description</th>
                <th style="width:120px">Amount</th>
                <th style="width:100px">Reconciled</th>
            </tr></thead>
            <tbody>{bank_dep_ppo_rows}</tbody>
        </table>
    </div>

    <div class="detail-block" style="margin-top:24px">
        <div class="detail-header med-header">
            <div class="detail-icon">🏦</div>
            <div>
                <div class="detail-title">Medicaid Deposits — Bank Statement vs Lockbox #11233</div>
                <div class="detail-sub">Each date shows bank deposit total vs lockbox detail total</div>
            </div>
            <div class="detail-total">{fmt_money(total_bank_dep_med)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Type</th>
                <th>Description</th>
                <th style="width:120px">Amount</th>
                <th style="width:100px">Reconciled</th>
            </tr></thead>
            <tbody>{bank_dep_med_rows}</tbody>
        </table>
    </div>
</div>

<!-- ==================== CARD DEPOSITS TAB ==================== -->
<div id="tab-deposits" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-deposit">
            <div class="detail-icon">💳</div>
            <div>
                <div class="detail-title">DEPOSITS — Credit Card & Merchant Processing</div>
                <div class="detail-sub">Match these to credit card batch reports in Open Dental</div>
            </div>
            <div class="detail-total">{fmt_money(total_deposits)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Location / Source</th>
                <th style="width:80px">Type</th>
                <th style="width:110px">Amount</th>
                <th>ACH Individual ID</th>
            </tr></thead>
            <tbody>{dep_rows}</tbody>
        </table>
    </div>
</div>

<!-- ==================== CHECK DEPOSITS TAB ==================== -->
<div id="tab-checkdep" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-checkdep">
            <div class="detail-icon">🏦</div>
            <div>
                <div class="detail-title">PNC — Cash Deposits</div>
                <div class="detail-sub">PNC-ECHO cash deposits — match to EOBs and post in Open Dental</div>
            </div>
            <div class="detail-total">{fmt_money(total_check_deposits)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Payer</th>
                <th style="width:110px">Amount</th>
                <th>ACH Individual ID</th>
                <th>Payer Name</th>
                <th style="width:120px">EOB Downloaded</th>
                <th style="width:180px">Remarks</th>
            </tr></thead>
            <tbody>{chk_dep_rows}</tbody>
        </table>
    </div>
</div>

<!-- ==================== EFT TAB ==================== -->
<div id="tab-eft" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-eft">
            <div class="detail-icon">🏥</div>
            <div>
                <div class="detail-title">PPO EFT — Insurance Electronic Payments</div>
                <div class="detail-sub">Match to ERA/835 files and post insurance payments in Open Dental</div>
            </div>
            <div class="detail-total">{fmt_money(total_eft)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Insurance Payer</th>
                <th style="width:110px">Amount</th>
                <th>ACH Individual ID</th>
                <th>Payer Name</th>
                <th style="width:120px">EOB Downloaded</th>
                <th style="width:100px">OD Posted</th>
                <th style="width:180px">Remarks</th>
            </tr></thead>
            <tbody>{eft_rows_html}</tbody>
        </table>
    </div>
</div>

<!-- ==================== MEDICAID EFT TAB ==================== -->
<div id="tab-eftmed" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-eft">
            <div class="detail-icon">🏥</div>
            <div>
                <div class="detail-title">Medicaid EFT — Insurance Electronic Payments</div>
                <div class="detail-sub">Match to ERA/835 files and post insurance payments in Open Dental</div>
            </div>
            <div class="detail-total">{fmt_money(total_eft_medicaid)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Insurance Payer</th>
                <th style="width:110px">Amount</th>
                <th>ACH Individual ID</th>
                <th>Payer Name</th>
                <th style="width:120px">EOB Downloaded</th>
                <th style="width:100px">OD Posted</th>
                <th style="width:180px">Remarks</th>
            </tr></thead>
            <tbody>{eft_med_rows_html}</tbody>
        </table>
    </div>
</div>

<!-- ==================== LOCKBOX PPO TAB (11234) ==================== -->
<div id="tab-lbppo" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-lockbox">
            <div class="detail-icon">📬</div>
            <div>
                <div class="detail-title">LOCKBOX PPO — #11234</div>
                <div class="detail-sub">PPO insurance checks — match to EOBs and post in Open Dental</div>
            </div>
            <div class="detail-total">{fmt_money(total_lb_ppo)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Check Number</th>
                <th style="width:110px">Amount</th>
                <th style="width:120px">EOB Downloaded</th>
                <th style="width:100px">OD Posted</th>
                <th style="width:180px">Remarks</th>
            </tr></thead>
            <tbody>{lb_ppo_rows}</tbody>
        </table>
    </div>
</div>

<!-- ==================== LOCKBOX MEDICAID TAB (11233) ==================== -->
<div id="tab-lbmed" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-medicaid">
            <div class="detail-icon">📬</div>
            <div>
                <div class="detail-title">LOCKBOX MEDICAID — #11233</div>
                <div class="detail-sub">Medicaid checks — match to EOBs and post in Open Dental</div>
            </div>
            <div class="detail-total">{fmt_money(total_lb_medicaid)}</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>Check Number</th>
                <th style="width:110px">Amount</th>
                <th style="width:120px">EOB Downloaded</th>
                <th style="width:100px">OD Posted</th>
                <th style="width:180px">Remarks</th>
            </tr></thead>
            <tbody>{lb_medicaid_rows}</tbody>
        </table>
    </div>
</div>

<!-- ==================== DEPOSITED CHECKS TAB ==================== -->
<div id="tab-depchk" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-deposit">
            <div class="detail-icon">🏦</div>
            <div>
                <div class="detail-title">DEPOSITED CHECKS — Individual Check Breakdown</div>
                <div class="detail-sub">Checks deposited at the bank — match to General Deposit line items</div>
            </div>
            <div class="detail-total">{fmt_money(total_dep_checks)}</div>
        </div>
        <table>
            <thead><tr>
                <th>Check #</th>
                <th style="width:110px">Amount</th>
                <th>From Account</th>
                <th>Routing #</th>
                <th style="width:80px">EOB</th>
                <th style="width:100px">OD Posted</th>
                <th style="width:180px">Remarks</th>
            </tr></thead>
            <tbody>{dep_check_rows_html}</tbody>
        </table>
    </div>
</div>

<!-- ==================== OUTGOING TAB ==================== -->
<div id="tab-outgoing" class="tab-content">
    <div class="detail-block">
        <div class="detail-header dh-outgoing">
            <div class="detail-icon">📤</div>
            <div>
                <div class="detail-title">OUTGOING — Debits & Returns</div>
                <div class="detail-sub">Review for accuracy — do NOT post these as income</div>
            </div>
            <div class="detail-total">({fmt_money(abs(total_outgoing))})</div>
        </div>
        <table>
            <thead><tr>
                <th style="width:90px">Date</th>
                <th>To Account</th>
                <th style="width:110px">Amount</th>
                <th>ACH Individual ID</th>
                <th>Description</th>
                <th style="width:100px">OD Posted</th>
            </tr></thead>
            <tbody>{out_rows}</tbody>
        </table>
    </div>
</div>

<script>
function showTab(name) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    event.target.closest('.tab-btn').classList.add('active');
}}

function updateStatus(select) {{
    const row = select.closest('tr');
    const val = select.value;

    // Remove all status classes
    select.classList.remove('status-yes', 'status-no', 'status-partial');
    row.classList.remove('row-yes', 'row-no', 'row-partial');

    if (val) {{
        select.classList.add('status-' + val);
        row.classList.add('row-' + val);
    }}

    // Save to localStorage
    const rowId = select.dataset.row;
    const stored = JSON.parse(localStorage.getItem('bankPivotStatus') || '{{}}');
    stored[rowId] = val;
    localStorage.setItem('bankPivotStatus', JSON.stringify(stored));

    updateProgress();
}}

function saveRemark(input) {{
    const rowId = input.dataset.row;
    const stored = JSON.parse(localStorage.getItem('bankPivotRemarks') || '{{}}');
    stored[rowId] = input.value;
    localStorage.setItem('bankPivotRemarks', JSON.stringify(stored));
    if (input.value.trim()) {{
        input.classList.add('has-text');
    }} else {{
        input.classList.remove('has-text');
    }}
}}

function updateProgress() {{
    const selects = document.querySelectorAll('.posted-select');
    const total = selects.length;
    let done = 0;
    selects.forEach(s => {{ if (s.value === 'yes') done++; }});
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressText').textContent = pct + '%';
}}

// Restore saved statuses on load
window.addEventListener('DOMContentLoaded', function() {{
    const stored = JSON.parse(localStorage.getItem('bankPivotStatus') || '{{}}');
    Object.keys(stored).forEach(rowId => {{
        const select = document.querySelector('.posted-select[data-row="' + rowId + '"]');
        if (select && stored[rowId]) {{
            select.value = stored[rowId];
            select.classList.add('status-' + stored[rowId]);
            const row = select.closest('tr');
            if (row) row.classList.add('row-' + stored[rowId]);
        }}
    }});
    // Restore saved remarks
    const remarks = JSON.parse(localStorage.getItem('bankPivotRemarks') || '{{}}');
    Object.keys(remarks).forEach(rowId => {{
        const input = document.querySelector('.remarks-input[data-row="' + rowId + '"]');
        if (input && remarks[rowId]) {{
            input.value = remarks[rowId];
            input.classList.add('has-text');
        }}
    }});

    updateProgress();
}});
</script>

</body>
</html>"""

output_path = "/Users/Admin/Desktop/Claude/BANK/Bank_Transaction_Pivot.html"
with open(output_path, 'w') as f:
    f.write(html)

print(f"Saved to: {output_path}")
print(f"\nSummary:")
print(f"  Deposits (Cards):   {len(deposits)} txns = {fmt_money(total_deposits)}")
print(f"  EFT (Insurance):    {len(eft)} txns = {fmt_money(total_eft)}")
print(f"  Lockbox PPO:        {len(lb_ppo)} checks = {fmt_money(total_lb_ppo)}")
print(f"  Lockbox Medicaid:   {len(lb_medicaid)} checks = {fmt_money(total_lb_medicaid)}")
print(f"  Outgoing/Debits:    {len(outgoing_ins)} txns = ({fmt_money(abs(total_outgoing))})")
print(f"  Net Activity:       {fmt_money(net_total)}")
