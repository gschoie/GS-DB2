"""기존 뉴스의 기업 별칭을 표준 기업명으로 빠르게 정규화한다."""

from db import connect, initialize
from parser import extract_companies
from telegram_importer import link_companies


def run() -> int:
    initialize()
    changed = 0
    with connect() as conn:
        conn.execute("INSERT INTO companies(name) VALUES('한국항공우주') ON CONFLICT(name) DO NOTHING")
        canonical_id = conn.execute("SELECT id FROM companies WHERE name='한국항공우주'").fetchone()["id"]
        old = conn.execute("SELECT id FROM companies WHERE name='KAI'").fetchone()
        if old:
            conn.execute("INSERT OR IGNORE INTO news_companies(news_id,company_id) SELECT news_id,? FROM news_companies WHERE company_id=?", (canonical_id, old["id"]))
            conn.execute("DELETE FROM news_companies WHERE company_id=?", (old["id"],))
        conn.execute("UPDATE news_articles SET company_name=replace(company_name,'KAI','한국항공우주') WHERE company_name LIKE '%KAI%'")
        rows = conn.execute("SELECT id,title FROM news_articles WHERE title LIKE '%KAI%' OR title LIKE '%KF-21%' OR title LIKE '%KF21%' OR title LIKE '%보라매%' OR title LIKE '%삼성重%'").fetchall()
        for row in rows:
            names = extract_companies(row["title"])
            if not names:
                continue
            conn.execute("UPDATE news_articles SET company_name=?,confidence=0.85,needs_review=0 WHERE id=?", (", ".join(names), row["id"]))
            conn.execute("DELETE FROM news_companies WHERE news_id=?", (row["id"],))
            link_companies(conn, "news_companies", "news_id", row["id"], names)
            changed += 1
        conn.commit()
    print(f"뉴스 기업명 정규화: {changed:,}건")
    return changed


if __name__ == "__main__":
    run()
