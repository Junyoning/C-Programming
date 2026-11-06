"""SQLite 저장소.

테이블
- posts           : 게시글 (같은 글을 다시 수집하면 점수/댓글 수만 갱신)
- comments        : 댓글
- post_snapshots  : 수집 시점마다 점수/댓글 수를 기록 -> 나중에 "그 시점에 알 수 있던 정보"만으로
                    백테스트할 수 있게 해준다 (미래 정보 누출 방지).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id               TEXT PRIMARY KEY,
    subreddit        TEXT NOT NULL,
    title            TEXT NOT NULL,
    selftext         TEXT,
    author           TEXT,
    url              TEXT,
    permalink        TEXT,
    flair            TEXT,
    created_utc      INTEGER NOT NULL,
    score            INTEGER,
    upvote_ratio     REAL,
    num_comments     INTEGER,
    is_self          INTEGER,
    first_seen_utc   INTEGER NOT NULL,
    last_updated_utc INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_sub_created ON posts (subreddit, created_utc);

CREATE TABLE IF NOT EXISTS comments (
    id               TEXT PRIMARY KEY,
    post_id          TEXT NOT NULL REFERENCES posts(id),
    subreddit        TEXT NOT NULL,
    parent_id        TEXT,
    body             TEXT,
    author           TEXT,
    score            INTEGER,
    created_utc      INTEGER NOT NULL,
    first_seen_utc   INTEGER NOT NULL,
    last_updated_utc INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments (post_id);
CREATE INDEX IF NOT EXISTS idx_comments_created ON comments (created_utc);

CREATE TABLE IF NOT EXISTS post_snapshots (
    post_id       TEXT NOT NULL REFERENCES posts(id),
    collected_utc INTEGER NOT NULL,
    score         INTEGER,
    upvote_ratio  REAL,
    num_comments  INTEGER,
    PRIMARY KEY (post_id, collected_utc)
);
"""

POST_FIELDS = (
    "id", "subreddit", "title", "selftext", "author", "url", "permalink", "flair",
    "created_utc", "score", "upvote_ratio", "num_comments", "is_self",
)
COMMENT_FIELDS = (
    "id", "post_id", "subreddit", "parent_id", "body", "author", "score", "created_utc",
)
# 재수집 시 갱신할 컬럼 (본문이 수정/삭제될 수 있으므로 텍스트도 갱신)
POST_UPDATABLE = ("title", "selftext", "flair", "score", "upvote_ratio", "num_comments")
COMMENT_UPDATABLE = ("body", "score")


def _upsert_sql(table: str, fields: tuple[str, ...], updatable: tuple[str, ...]) -> str:
    cols = ", ".join(fields + ("first_seen_utc", "last_updated_utc"))
    params = ", ".join(f":{f}" for f in fields) + ", :now, :now"
    updates = ", ".join(f"{f} = excluded.{f}" for f in updatable)
    return (
        f"INSERT INTO {table} ({cols}) VALUES ({params}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}, last_updated_utc = excluded.last_updated_utc"
    )


class Storage:
    def __init__(self, db_path: Path | str):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _existing_ids(self, table: str, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT id FROM {table} WHERE id IN ({placeholders})", ids
        ).fetchall()
        return {row["id"] for row in rows}

    def upsert_posts(self, posts: Iterable[dict], now: int) -> int:
        """게시글을 저장하고 스냅샷을 남긴다. 새로 추가된 글 수를 반환."""
        posts = list(posts)
        existing = self._existing_ids("posts", [p["id"] for p in posts])
        with self.conn:
            self.conn.executemany(
                _upsert_sql("posts", POST_FIELDS, POST_UPDATABLE),
                [{**{f: p.get(f) for f in POST_FIELDS}, "now": now} for p in posts],
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO post_snapshots "
                "(post_id, collected_utc, score, upvote_ratio, num_comments) "
                "VALUES (?, ?, ?, ?, ?)",
                [(p["id"], now, p.get("score"), p.get("upvote_ratio"), p.get("num_comments"))
                 for p in posts],
            )
        return len({p["id"] for p in posts} - existing)

    def upsert_comments(self, comments: Iterable[dict], now: int) -> int:
        """댓글을 저장한다. 새로 추가된 댓글 수를 반환."""
        comments = list(comments)
        existing = self._existing_ids("comments", [c["id"] for c in comments])
        with self.conn:
            self.conn.executemany(
                _upsert_sql("comments", COMMENT_FIELDS, COMMENT_UPDATABLE),
                [{**{f: c.get(f) for f in COMMENT_FIELDS}, "now": now} for c in comments],
            )
        return len({c["id"] for c in comments} - existing)

    def stats(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT p.subreddit,
                   COUNT(*)                              AS posts,
                   (SELECT COUNT(*) FROM comments c
                     WHERE c.subreddit = p.subreddit)    AS comments,
                   datetime(MIN(p.created_utc), 'unixepoch') AS oldest_utc,
                   datetime(MAX(p.created_utc), 'unixepoch') AS newest_utc
            FROM posts p
            GROUP BY p.subreddit
            ORDER BY posts DESC
            """
        ).fetchall()
