#!/usr/bin/env python3
import argparse
from app import create_app
from database import get_db
from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser(description="Add a user to the WMS database")
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("role")
    parser.add_argument("--email", default="")
    parser.add_argument("--phone", default="")

    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db()

        exist = db.execute("SELECT id FROM users WHERE username=?", (args.username,)).fetchone()
        if exist:
            print(f"User '{args.username}' already exists (id={exist['id']})")
            return

        try:
            db.execute(
                "INSERT INTO users(username,password,role,email,phone) VALUES (?,?,?,?,?)",
                (args.username, generate_password_hash(args.password), args.role, args.email or None, args.phone or None)
            )
        except Exception:
            db.execute(
                "INSERT INTO users(username,password,role) VALUES (?,?,?)",
                (args.username, generate_password_hash(args.password), args.role)
            )

        db.commit()
        print(f"User '{args.username}' added with role '{args.role}'")


if __name__ == '__main__':
    main()
