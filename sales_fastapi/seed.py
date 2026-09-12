"""Seed demo data: a demo user plus representative Ahmednagar (Mahindra Accelo)
sales contacts. Run with:  python -m sales_fastapi.seed
"""

from __future__ import annotations

from .database import SessionLocal, init_db
from .models import Contact, User
from .services import classify_contact

DEMO_EMAIL = "demo@kalisoftai.com"

SEED_CONTACTS: list[dict] = [
    {
        "company": "Mahindra Accelo Ltd. (Mahindra & Mahindra group) – Supa, Ahmednagar",
        "name": "Mahindra Accelo – General Enquiries",
        "email": "info@mahindraaccelo.com",
        "phone": "22 2493 5185 / 5186",
        "address": "F-221, Gat No. 167 K/2, Additional Supa Parner Industrial Park, Supa MIDC, Ahmednagar, Maharashtra – 414301",
        "linkedin_company": "https://www.linkedin.com/company/mahindra-accelo",
        "linkedin_profiles": [
            "Smaranika Mohapatra – Assistant Manager (Procurement & SCM), Mahindra Accelo, Ahmednagar",
            "Tushar Ithape – Supply Chain Management, Mahindra Accelo, Ahmednagar",
            "Vishal Karad – Project Design & Procurement execution, Mahindra Accelo, Supa (Ahmednagar)",
            "Ganesh Pagire – Mahindra Accelo, Ahmednagar",
        ],
        "purchase_contact_name": "Smaranika Mohapatra",
        "purchase_contact_role": "Assistant Manager (Procurement & SCM)",
        "purchase_contact_email": "info@mahindraaccelo.com",
        "purchase_contact_phone": "",
        "context": "Automotive metal forming / SCM procurement, Supa MIDC Ahmednagar",
        "tags": ["automotive", "scm", "ahmednagar", "midc"],
    },
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if user is None:
            user = User(
                google_sub="seed-demo",
                email=DEMO_EMAIL,
                name="Demo User",
                domain="kalisoftai.com",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        created = 0
        for item in SEED_CONTACTS:
            exists = (
                db.query(Contact)
                .filter(Contact.user_id == user.id, Contact.email == item["email"])
                .first()
            )
            if exists:
                continue
            verdict = classify_contact(item["email"], item["context"])
            db.add(
                Contact(
                    user_id=user.id,
                    domain=verdict["domain"],
                    intent=verdict["intent"],
                    source="seed",
                    **item,
                )
            )
            created += 1
        db.commit()
        print(f"Seed complete. user_id={user.id}, contacts_created={created}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
