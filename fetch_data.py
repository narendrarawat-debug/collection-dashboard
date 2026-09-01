import os
import json
import requests

TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
DATASET_ID = "1a2f4bf9-37a6-4f06-acc2-285e76fccdfe"

def get_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://analysis.windows.net/powerbi/api/.default",
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]


def run_dax(token, query):
    url = f"https://api.powerbi.com/v1.0/myorg/datasets/{DATASET_ID}/executeQueries"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}}
    r = requests.post(url, headers=headers, json=body)
    r.raise_for_status()
    rows = r.json()["results"][0]["tables"][0].get("rows", [])
    # strip table prefix from column names  e.g. "dealer outstanding[party]" -> "party"
    cleaned = []
    for row in rows:
        cleaned.append({k.split("[")[-1].rstrip("]"): v for k, v in row.items()})
    return cleaned


def main():
    token = get_token()

    # 1. Dealer outstanding
    dealer_outstanding = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    FILTER('dealer outstanding', 'dealer outstanding'[Is Dealer Match] = TRUE()),
    "customer_name", 'dealer outstanding'[customer_name],
    "territory", 'dealer outstanding'[territory],
    "customer_group", 'dealer outstanding'[customer_group],
    "0_30", 'dealer outstanding'[0-30],
    "31_60", 'dealer outstanding'[31-60],
    "61_90", 'dealer outstanding'[61-90],
    "91_120", 'dealer outstanding'[91-120],
    "121_150", 'dealer outstanding'[121-150],
    "151_above", 'dealer outstanding'[151-Above],
    "total_outstanding", 'dealer outstanding'[total_outstanding],
    "is_sse_eligible", 'dealer outstanding'[is_sse_eligible],
    "Is Recovery Dealer", 'dealer outstanding'[Is Recovery Dealer]
)
ORDER BY 'dealer outstanding'[total_outstanding] DESC
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
ORDER BY 'Daily Collection'[posting_date] DESC
""")

    # 3. Sales vs collection cohort (invoice level)
    cohort = run_dax(token, """
EVALUATE
SELECTCOLUMNS(
    'invoice level sales',
    "invoice_code", 'invoice level sales'[invoice_code],
    "customer_name", 'invoice level sales'[customer_name],
    "invoice_at", 'invoice level sales'[invoice_at],
    "sub_total", 'invoice level sales'[sub_total],
    "Sale Month", 'invoice level sales'[Sale Month],
    "Sale Month Sort", 'invoice level sales'[Sale Month Sort],
    "Collection Month", 'invoice level sales'[Collection Month],
    "Collection Month Sort", 'invoice level sales'[Collection Month Sort]
)
""")

    os.makedirs("data", exist_ok=True)
    with open("data/dealer_outstanding.json", "w") as f:
        json.dump(dealer_outstanding, f)
    with open("data/daily_collection.json", "w") as f:
        json.dump(daily_collection, f)
    with open("data/cohort.json", "w") as f:
        json.dump(cohort, f)

    print(f"Dealer outstanding: {len(dealer_outstanding)} rows")
    print(f"Daily collection: {len(daily_collection)} rows")
    print(f"Cohort: {len(cohort)} rows")


if __name__ == "__main__":
    main()
