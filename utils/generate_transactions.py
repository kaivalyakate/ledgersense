"""
LedgerSense Synthetic Transaction Generator
=============================================
Generates realistic, messy accounting transaction data for multi-location
F&B and construction businesses -- matching LiveFlow's actual ICP.

Produces three tiers of transactions:
  1. Easy/obvious      (~60%) - clear vendor -> category mapping
  2. Ambiguous          (~30%) - same vendor, different correct category
                                  depending on amount/memo/context
  3. Planted anomalies  (~10%) - duplicates, outlier amounts, round-number
                                  entries, off-hours payroll, etc.

Output: a transactions.csv with a hidden `true_category` (ground truth,
used later to score your agent) and an `anomaly_type` column (empty for
normal rows) so you can measure both categorization accuracy AND
anomaly recall separately.

Usage:
    python generate_transactions.py --n 800 --seed 42 --out transactions.csv
"""

import argparse
import csv
import random
import uuid
from datetime import date, timedelta

from faker import Faker

fake = Faker()

# ---------------------------------------------------------------------------
# Chart of accounts -- tuned for a multi-location restaurant group +
# a construction company, since that's LiveFlow's actual customer base.
# ---------------------------------------------------------------------------
CATEGORIES = [
    "Cost of Goods Sold",
    "Payroll",
    "Rent",
    "Utilities",
    "Travel",
    "Meals & Entertainment",
    "Office Supplies",
    "Software & Subscriptions",
    "Equipment",
    "Repairs & Maintenance",
    "Marketing",
    "Insurance",
    "Professional Fees",
    "Bank Fees",
    "Materials & Supplies",  # construction-specific
    "Subcontractor Payments",  # construction-specific
]

ENTITIES = [
    {"id": "ent_001", "name": "Crumbtown Bakery & Cafe - Downtown", "type": "restaurant"},
    {"id": "ent_002", "name": "Crumbtown Bakery & Cafe - Uptown", "type": "restaurant"},
    {"id": "ent_003", "name": "Crumbtown Bakery & Cafe - Riverside", "type": "restaurant"},
    {"id": "ent_004", "name": "Ironclad Builders LLC", "type": "construction"},
]

# ---------------------------------------------------------------------------
# Vendor pools. "obvious" vendors map cleanly to one category.
# "ambiguous" vendors can legitimately belong to >1 category depending on
# context -- this is what should drag the agent's confidence down and
# trigger the review queue / explain-on-challenge flow.
# ---------------------------------------------------------------------------
OBVIOUS_VENDORS = {
    "Cost of Goods Sold": ["Sysco Foods", "US Foods", "Restaurant Depot", "Local Farms Co-op"],
    "Payroll": ["ADP Payroll", "Gusto Payroll Services", "Paychex Inc"],
    "Rent": ["Westfield Property Management", "Downtown Realty Holdings"],
    "Utilities": ["ConEd", "National Grid", "PSE&G", "Verizon Fios"],
    "Travel": ["Delta Air Lines", "Uber Trip", "Marriott Hotels", "Enterprise Rent-A-Car"],
    "Software & Subscriptions": ["AWS", "QuickBooks Online", "Toast POS", "Slack", "GitHub", "Microsoft 365"],
    "Insurance": ["State Farm Commercial", "Hartford Insurance Group"],
    "Bank Fees": ["Chase Business Banking Fee", "Wire Transfer Fee - JPM"],
    "Marketing": ["Meta Ads", "Google Ads", "Yelp Ads"],
    "Materials & Supplies": ["Home Depot Pro", "Ferguson Building Materials", "84 Lumber"],
    "Subcontractor Payments": ["Apex Electrical Contracting", "Reliable Plumbing Co", "Summit Roofing LLC"],
    "Professional Fees": ["Marcum LLP Accounting", "Goldfarb & Associates Legal"],
}

# vendor -> list of (category, weight) it could plausibly belong to,
# disambiguated only by amount range / memo, not by name alone.
AMBIGUOUS_VENDORS = {
    "Amazon": [
        ("Office Supplies", (15, 200), ["paper", "pens", "printer ink", "folders"]),
        ("Equipment", (200, 3000), ["mixer", "POS tablet", "commercial blender", "tools"]),
        ("Materials & Supplies", (100, 1500), ["hardware", "fasteners", "site supplies"]),
    ],
    "Costco Wholesale": [
        ("Cost of Goods Sold", (200, 1800), ["bulk ingredients", "produce", "beverages"]),
        ("Office Supplies", (30, 150), ["paper goods", "cleaning supplies"]),
        ("Meals & Entertainment", (50, 300), ["staff lunch", "team event catering"]),
    ],
    "Home Depot": [
        ("Repairs & Maintenance", (50, 800), ["repair parts", "paint", "hardware fix"]),
        ("Materials & Supplies", (200, 4000), ["lumber", "concrete", "site materials"]),
        ("Equipment", (300, 2500), ["power tools", "generator"]),
    ],
    "Shell Gas Station": [
        ("Travel", (40, 120), ["fuel - business trip"]),
        ("Repairs & Maintenance", (40, 120), ["fuel - delivery vehicle"]),
    ],
    "Square Payment": [
        ("Cost of Goods Sold", (50, 600), ["vendor payment via Square"]),
        ("Subcontractor Payments", (300, 5000), ["contractor invoice via Square"]),
    ],
}

ANOMALY_TYPES = [
    "duplicate",
    "outlier_amount",
    "round_number_manual",
    "off_hours_payroll",
    "split_transaction",
]


def weighted_amount(low, high):
    return round(random.uniform(low, high), 2)


def random_date(start_days_ago=365, end_days_ago=0):
    delta = random.randint(end_days_ago, start_days_ago)
    return date.today() - timedelta(days=delta)


CATEGORY_MEMOS = {
    "Cost of Goods Sold": ["weekly food order", "produce delivery", "bulk ingredient restock", "beverage order"],
    "Payroll": ["biweekly payroll run", "payroll - hourly staff", "payroll - salaried staff"],
    "Rent": ["monthly lease payment", "rent - storefront", "rent - warehouse space"],
    "Utilities": ["monthly electric bill", "water & sewer", "internet & phone service"],
    "Travel": ["business trip - flight", "client visit - rideshare", "conference travel"],
    "Software & Subscriptions": ["monthly subscription", "annual license renewal", "cloud hosting charge"],
    "Insurance": ["monthly premium", "quarterly liability premium", "workers comp premium"],
    "Bank Fees": ["monthly account fee", "wire transfer fee", "overdraft fee"],
    "Marketing": ["ad campaign spend", "social media ads", "local promo campaign"],
    "Materials & Supplies": ["job site materials", "building supply restock", "hardware order"],
    "Subcontractor Payments": ["subcontractor invoice", "trade contractor payment", "milestone payment"],
    "Professional Fees": ["monthly retainer", "tax prep services", "legal consultation"],
}


def make_obvious_transaction(entity):
    category = random.choice(list(OBVIOUS_VENDORS.keys()))
    vendor = random.choice(OBVIOUS_VENDORS[category])
    memo = random.choice(CATEGORY_MEMOS.get(category, ["payment"]))
    amount = -weighted_amount(20, 2500)
    if category == "Payroll":
        amount = -weighted_amount(3000, 18000)
    elif category == "Rent":
        amount = -weighted_amount(2500, 9000)
    return {
        "id": str(uuid.uuid4()),
        "date": random_date().isoformat(),
        "entity_id": entity["id"],
        "vendor_name": vendor,
        "description": f"{vendor} - {memo}",
        "amount": amount,
        "true_category": category,
        "anomaly_type": "",
        "tier": "obvious",
    }


def make_ambiguous_transaction(entity):
    vendor = random.choice(list(AMBIGUOUS_VENDORS.keys()))
    category, (low, high), memos = random.choice(AMBIGUOUS_VENDORS[vendor])
    amount = -weighted_amount(low, high)
    memo = random.choice(memos)
    return {
        "id": str(uuid.uuid4()),
        "date": random_date().isoformat(),
        "entity_id": entity["id"],
        "vendor_name": vendor,
        "description": f"{vendor} - {memo}",
        "amount": amount,
        "true_category": category,
        "anomaly_type": "",
        "tier": "ambiguous",
    }


def make_anomaly_transaction(entity, base_pool):
    anomaly_type = random.choice(ANOMALY_TYPES)
    base = make_obvious_transaction(entity) if random.random() < 0.5 else make_ambiguous_transaction(entity)
    base["anomaly_type"] = anomaly_type
    base["tier"] = "anomaly"

    if anomaly_type == "duplicate" and base_pool:
        # clone a real prior transaction with a near-identical timestamp
        original = random.choice(base_pool)
        dup = dict(original)
        dup["id"] = str(uuid.uuid4())
        dup["anomaly_type"] = "duplicate"
        dup["tier"] = "anomaly"
        # shift date by 0-1 days to mimic a double-charge
        d = date.fromisoformat(original["date"]) + timedelta(days=random.choice([0, 1]))
        dup["date"] = d.isoformat()
        return dup

    elif anomaly_type == "outlier_amount":
        base["amount"] = round(base["amount"] * random.uniform(6, 12), 2)
        base["description"] += " [unusually large vs vendor history]"

    elif anomaly_type == "round_number_manual":
        sign = -1
        base["amount"] = sign * random.choice([500, 1000, 1500, 2000, 2500, 5000])
        base["vendor_name"] = "Manual Journal Entry"
        base["description"] = "Manual adjustment - " + random.choice(
            ["year-end correction", "reclass entry", "owner draw adjustment", "misc accrual reversal"]
        )

    elif anomaly_type == "off_hours_payroll":
        base["true_category"] = "Payroll"
        base["vendor_name"] = "ADP Payroll"
        base["amount"] = -weighted_amount(2000, 9000)
        base["description"] = "Payroll run - processed Saturday (off-cycle)"
        # force a weekend date
        d = random_date()
        while d.weekday() < 5:
            d = random_date()
        base["date"] = d.isoformat()

    elif anomaly_type == "split_transaction":
        base["description"] += " [1 of 2 - possible split to avoid approval threshold]"
        base["amount"] = round(base["amount"] * 0.5, 2)

    return base


def generate(n, seed=42):
    random.seed(seed)
    Faker.seed(seed)

    rows = []
    n_obvious = int(n * 0.60)
    n_ambiguous = int(n * 0.30)
    n_anomaly = n - n_obvious - n_ambiguous

    for _ in range(n_obvious):
        entity = random.choice(ENTITIES)
        rows.append(make_obvious_transaction(entity))

    for _ in range(n_ambiguous):
        entity = random.choice(ENTITIES)
        rows.append(make_ambiguous_transaction(entity))

    for _ in range(n_anomaly):
        entity = random.choice(ENTITIES)
        rows.append(make_anomaly_transaction(entity, rows))

    random.shuffle(rows)
    return rows


def write_csv(rows, out_path):
    fieldnames = [
        "id", "date", "entity_id", "vendor_name", "description",
        "amount", "true_category", "anomaly_type", "tier",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_entities_csv(out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "type"])
        writer.writeheader()
        writer.writerows(ENTITIES)


def write_categories_csv(out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["category"])
        for c in CATEGORIES:
            writer.writerow([c])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic LedgerSense transaction data.")
    parser.add_argument("--n", type=int, default=800, help="Number of transactions to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--out", type=str, default="transactions.csv", help="Output CSV path")
    args = parser.parse_args()

    rows = generate(args.n, seed=args.seed)
    write_csv(rows, args.out)
    write_entities_csv("entities.csv")
    write_categories_csv("categories.csv")

    tiers = {}
    anomalies = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        if r["anomaly_type"]:
            anomalies[r["anomaly_type"]] = anomalies.get(r["anomaly_type"], 0) + 1

    print(f"Generated {len(rows)} transactions -> {args.out}")
    print(f"Tier breakdown: {tiers}")
    print(f"Anomaly breakdown: {anomalies}")
    print(f"Also wrote entities.csv and categories.csv")
