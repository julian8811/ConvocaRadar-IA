from sqlalchemy import inspect, text
from app.db.session import SessionLocal

def repair(value):
    if not isinstance(value, str) or not any(x in value for x in ("Ã", "Â", "â")):
        return value
    try:
        fixed = value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return fixed if "�" not in fixed else value

with SessionLocal() as db:
    inspector = inspect(db.bind)
    changed = 0
    for table in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns(table) if c["name"] != "id" and str(c["type"]).lower().startswith(("character", "text", "varchar"))]
        if not columns or "id" not in [c["name"] for c in inspector.get_columns(table)]:
            continue
        rows = db.execute(text(f"select id, {', '.join(columns)} from {table}")).mappings().all()
        for row in rows:
            updates = {col: repair(row[col]) for col in columns if repair(row[col]) != row[col]}
            if updates:
                assignments = ", ".join(f"{col} = :{col}" for col in updates)
                updates["id"] = row["id"]
                db.execute(text(f"update {table} set {assignments} where id = :id"), updates)
                changed += 1
    db.commit()
    print(f"normalized_rows={changed}")
