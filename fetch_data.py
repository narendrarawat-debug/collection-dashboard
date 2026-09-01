import json, requests, os

TENANT_ID = "b7d6697c-4617-438d-9e38-a24db9a09087"
CLIENT_ID = "3541ac5b-3a01-4e8b-b4fb-381718e108e4"
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")  # set via env var or run_local.ps1
DATASET_ID = "1a2f4bf9-37a6-4f06-acc2-285e76fccdfe"


def get_token():
    r = requests.post(
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
        data={"grant_type": "client_credentials", "client_id": CLIENT_ID,
              "client_secret": CLIENT_SECRET,
              "scope": "https://analysis.windows.net/powerbi/api/.default"})
    r.raise_for_status()
    return r.json()["access_token"]


def run_dax(token, query):
    url = f"https://api.powerbi.com/v1.0/myorg/datasets/{DATASET_ID}/executeQueries"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}}
    r = requests.post(url, headers=headers, json=body)
    r.raise_for_status()
    rows = r.json()["results"][0]["tables"][0].get("rows", [])
    return [{k.split("[")[-1].rstrip("]"): v for k, v in row.items()} for row in rows]


def main():
    token = get_token()

    # 1. Dealer outstanding — ADDCOLUMNS to get measures per dealer row
    try:
        dealer_outstanding = run_dax(token, """
EVALUATE
ADDCOLUMNS(
    FILTER('dealer outstanding', 'dealer outstanding'[Is Dealer Match] = TRUE()),
    "primary_sales_90d", [Primary Sales (Last 90 Days)],
    "secondary_units_90d", [Secondary Units (Last 90 Days)],
    "sec_primary_ratio", [Sec./Primary Ratio]
)
""")
    except Exception as e:
        print(f"Warning: measure fetch failed ({e}), retrying without measures")
        dealer_outstanding = run_dax(token, """
EVALUATE
FILTER('dealer outstanding', 'dealer outstanding'[Is Dealer Match] = TRUE())
""")

    # 2. Daily collection (last 365 days so user can browse any month)
    daily_collection = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    FILTER('Daily Collection', 'Daily Collection'[posting_date] >= TODAY() - 365),
    "posting_date", 'Daily Collection'[posting_date],
    "party_name", 'Daily Collection'[party_name],
    "paid_amount", 'Daily Collection'[paid_amount],
    "payment_type", 'Daily Collection'[payment_type],
    "Dealer Region", 'Daily Collection'[Dealer Region]
)
""")

    # 3. Cohort — fetch raw fields, replicate PBI Collection Amount DAX logic in Python
    cohort_raw = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    FILTER(
        'invoice collection date',
        'invoice collection date'[Is Dealer Match] = TRUE()
    ),
    "customer_name", 'invoice collection date'[customer_name],
    "invoice_amount", 'invoice collection date'[invoice_amount],
    "paid_amount", 'invoice collection date'[paid_amount],
    "balance_amount", 'invoice collection date'[balance_amount],
    "erp_status", 'invoice collection date'[erp_status],
    "invoice_date", 'invoice collection date'[invoice_date],
    "last_payment_date", 'invoice collection date'[last_payment_date]
)
""")
    print(f"  cohort raw rows: {len(cohort_raw)}")

    from datetime import datetime

    MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

    def fmt_month(dt_str):
        """'2025-08-15' → ('Aug 2025', 202508)"""
        if not dt_str:
            return None, None
        try:
            dt = datetime.fromisoformat(str(dt_str)[:10])
            label = f"{MONTH_NAMES[dt.month-1]} {dt.year}"
            sort = dt.year * 100 + dt.month
            return label, sort
        except Exception:
            return None, None

    agg = {}   # (dealer, sale_month, coll_month) → amount
    sm_sort_map, cm_sort_map = {}, {}

    for r in cohort_raw:
        dealer = r.get('customer_name') or ''
        inv_amt = r.get('invoice_amount') or 0
        paid = r.get('paid_amount') or 0
        bal = r.get('balance_amount') or 0
        erp = r.get('erp_status') or ''
        inv_date = r.get('invoice_date')
        lpd = r.get('last_payment_date')

        sm_label, sm_sort = fmt_month(inv_date)
        if not sm_label:
            continue

        is_resolved = erp in ('Paid', 'Credit Note Issued')
        is_genuine_partial = (not is_resolved) and paid > 0 and bool(lpd)

        # Compute resolved bucket
        lpd_label, lpd_sort = fmt_month(lpd)
        inv_dt = datetime.fromisoformat(str(inv_date)[:10]) if inv_date else None
        lpd_dt = datetime.fromisoformat(str(lpd)[:10]) if lpd else None

        paid_before_inv = bool(lpd_dt and inv_dt and lpd_dt < inv_dt and (is_resolved or paid > 0))

        if is_resolved and not lpd:
            bucket = 'Pending'
        elif paid_before_inv:
            bucket = 'paid before invoice'
        elif is_resolved:
            bucket = lpd_label
        elif is_genuine_partial:
            bucket = lpd_label
        else:
            bucket = 'Pending'

        # Sort for bucket
        if bucket == 'Pending':
            b_sort = 999997
        elif bucket == 'paid before invoice':
            b_sort = 999999
        else:
            b_sort = lpd_sort or 0

        sm_sort_map[sm_label] = sm_sort
        cm_sort_map[bucket] = b_sort

        # Distribute amounts
        if is_resolved:
            key = (dealer, sm_label, bucket)
            agg[key] = agg.get(key, 0) + inv_amt
        elif is_genuine_partial:
            # paid portion → collection bucket
            key = (dealer, sm_label, bucket)
            agg[key] = agg.get(key, 0) + paid
            # balance → Pending
            key2 = (dealer, sm_label, 'Pending')
            agg[key2] = agg.get(key2, 0) + bal
            cm_sort_map['Pending'] = 999997
        else:
            key = (dealer, sm_label, 'Pending')
            agg[key] = agg.get(key, 0) + inv_amt
            cm_sort_map['Pending'] = 999997

    cohort = [
        {'customer_name': k[0], 'Sale Month': k[1], 'Sale Month Sort': sm_sort_map[k[1]],
         'Collection Month': k[2], 'Collection Month Sort': cm_sort_map[k[2]], 'sub_total': v}
        for k, v in agg.items()
    ]
    print(f"  (aggregated → {len(cohort)} pivot rows)")

    os.makedirs("data", exist_ok=True)
    with open("data/dealer_outstanding.json", "w", encoding="utf-8") as f:
        json.dump(dealer_outstanding, f)
    with open("data/daily_collection.json", "w", encoding="utf-8") as f:
        json.dump(daily_collection, f)
    with open("data/cohort.json", "w", encoding="utf-8") as f:
        json.dump(cohort, f)

    print(f"Dealer outstanding: {len(dealer_outstanding)} rows")
    print(f"Daily collection:   {len(daily_collection)} rows")
    print(f"Cohort:             {len(cohort)} rows")


if __name__ == "__main__":
    main()
