from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Centre, CentreTest, DiagnosticTest, User

TESTS = {
    "Complete Blood Count": "Hemoglobin, RBC, WBC and platelet counts",
    "Lipid Profile": "Total cholesterol, HDL, LDL and triglycerides",
    "HbA1c": "Average blood sugar over the last 3 months",
    "Thyroid Profile": "T3, T4 and TSH",
    "Vitamin D": "25-hydroxy vitamin D",
    "Liver Function Test": "Bilirubin, SGOT, SGPT, ALP",
}

CENTRES = {
    ("CityCare Diagnostics", "Delhi"): {
        "Complete Blood Count": "350.00", "Lipid Profile": "600.00", "HbA1c": "450.00", "Thyroid Profile": "550.00",
    },
    ("Sunrise Pathology", "Delhi"): {
        "Complete Blood Count": "300.00", "Vitamin D": "900.00", "Liver Function Test": "700.00",
    },
    ("HealthFirst Labs", "Mumbai"): {
        "Complete Blood Count": "400.00", "Lipid Profile": "650.00", "Thyroid Profile": "600.00", "Vitamin D": "950.00",
    },
    ("Green Valley Labs", "Bengaluru"): {
        "HbA1c": "420.00", "Lipid Profile": "580.00", "Liver Function Test": "680.00",
    },
    ("Metro Diagnostics", "Meerut"): {
        "Complete Blood Count": "250.00", "Thyroid Profile": "450.00", "Vitamin D": "800.00",
    },
}


def seed_catalog(db: Session) -> None:
    tests: dict[str, DiagnosticTest] = {}
    for name, description in TESTS.items():
        test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
        if test is None:
            test = DiagnosticTest(name=name, description=description)
            db.add(test)
        tests[name] = test

    for (name, location), prices in CENTRES.items():
        centre = db.scalar(select(Centre).where(Centre.name == name, Centre.location == location))
        if centre is None:
            centre = Centre(name=name, location=location)
            db.add(centre)
        db.flush()
        for test_name, price in prices.items():
            db.flush()
            exists = db.scalar(
                select(CentreTest.id).where(CentreTest.centre_id == centre.id, CentreTest.test_id == tests[test_name].id)
            )
            if exists is None:
                db.add(CentreTest(centre_id=centre.id, test_id=tests[test_name].id, price=Decimal(price)))
    db.commit()
    print(f"Catalog ready: {len(TESTS)} tests, {len(CENTRES)} centres.")


def ensure_admin(db: Session) -> None:
    if not settings.admin_email or not settings.admin_password:
        print("ADMIN_EMAIL / ADMIN_PASSWORD not set: skipping admin user.")
        return
    if len(settings.admin_password) < 8:
        raise SystemExit("ADMIN_PASSWORD must be at least 8 characters.")

    email = settings.admin_email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        db.add(User(email=email, hashed_password=hash_password(settings.admin_password), is_admin=True))
        print(f"Created admin user {email}.")
    elif not user.is_admin:
        user.is_admin = True
        print(f"Promoted existing user {email} to admin.")
    else:
        print(f"Admin user {email} already exists.")
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        seed_catalog(db)
        ensure_admin(db)


if __name__ == "__main__":
    main()
