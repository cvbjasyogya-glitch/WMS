from app import create_app
from database import get_db

app = create_app()

with app.app_context():
    db = get_db()

    try:
        db.execute("ALTER TABLE products ADD COLUMN color TEXT")
        print("color column added")
    except:
        print("color already exists")

    try:
        db.execute("ALTER TABLE products ADD COLUMN series TEXT")
        print("series column added")
    except:
        print("series already exists")

    db.commit()