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

    # 2. Daily collection (last 90 days)
    daily_collection = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    FILTER('Daily Collection', 'Daily Collection'[posting_date] >= TODAY() - 90),
    "posting_date", 'Daily Collection'[posting_date],
    "party_name", 'Daily Collection'[party_name],
    "paid_amount", 'Daily Collection'[paid_amount],
    "payment_type", 'Daily Collection'[payment_type],
    "Dealer Region", 'Daily Collection'[Dealer Region]
)
""")

    # 3. Cohort — filter to Is Bike Invoice = TRUE, only columns needed for pivot
    try:
        cohort_raw = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    CALCULATETABLE(
        'invoice level sales',
        'invoice level sales'[Is Bike Invoice] = TRUE()
    ),
    "customer_name", 'invoice level sales'[customer_name],
    "sub_total", 'invoice level sales'[sub_total],
    "Sale Month", 'invoice level sales'[Sale Month],
    "Sale Month Sort", 'invoice level sales'[Sale Month Sort],
    "Collection Month", 'invoice level sales'[Collection Month],
    "Collection Month Sort", 'invoice level sales'[Collection Month Sort]
)
""")
    except Exception as e:
        print(f"Warning: cohort with Is Bike Invoice failed ({e}), retrying without filter")
        cohort_raw = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    'invoice level sales',
    "customer_name", 'invoice level sales'[customer_name],
    "sub_total", 'invoice level sales'[sub_total],
    "Sale Month", 'invoice level sales'[Sale Month],
    "Sale Month Sort", 'invoice level sales'[Sale Month Sort],
    "Collection Month", 'invoice level sales'[Collection Month],
    "Collection Month Sort", 'invoice level sales'[Collection Month Sort]
)
""")

    # Pre-aggregate to dealer × Sale Month × Collection Month to keep JSON small
    from collections import defaultdict
    agg = {}
    sm_sort_map, cm_sort_map = {}, {}
    for r in cohort_raw:
        sm, cm, dealer = r.get('Sale Month',''), r.get('Collection Month',''), r.get('customer_name','')
        key = (dealer, sm, cm)
        agg[key] = agg.get(key, 0) + (r.get('sub_total') or 0)
        sm_sort_map[sm] = r.get('Sale Month Sort', 0)
        cm_sort_map[cm] = r.get('Collection Month Sort', 0)
    cohort = [
        {'customer_name': k[0], 'Sale Month': k[1], 'Sale Month Sort': sm_sort_map[k[1]],
         'Collection Month': k[2], 'Collection Month Sort': cm_sort_map[k[2]], 'sub_total': v}
        for k, v in agg.items()
    ]
    print(f"  (aggregated {len(cohort_raw)} invoice rows → {len(cohort)} pivot rows)")

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
