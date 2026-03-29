from app import create_app
from database import get_db
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    db = get_db()

    print("==== DATABASE ====")
    path = db.execute("PRAGMA database_list").fetchone()[2]
    print(path)

    print("\n==== LIST USER ====")
    users = db.execute("SELECT id, username, role FROM users").fetchall()

    for u in users:
        print(dict(u))

    print("\n==== RESET USER PERTAMA JADI ADMIN ====")

    if users:
        user_id = users[0]["id"]

        db.execute("""
        UPDATE users SET password=?, role='admin'
        WHERE id=?
        """, (
            generate_password_hash("admin123"),
            user_id
        ))

        db.commit()

        print("RESET USER ID:", user_id)
        print("LOGIN:")
        print("username:", users[0]["username"])
        print("password: admin123")

    else:
        print("TIDAK ADA USER DI DATABASE!")