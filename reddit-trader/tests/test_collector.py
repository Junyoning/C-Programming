"""네트워크 없이 가짜 Reddit 객체로 수집 로직을 검증한다."""
from types import SimpleNamespace

import prawcore
import pytest

from collector.main import collect_once
from collector.reddit_client import comment_to_dict, submission_to_dict
from collector.storage import Storage


def make_comment(cid, body="nice", author="bob", score=1):
    return SimpleNamespace(
        id=cid, parent_id="t3_p1", body=body, score=score, created_utc=1_700_000_100.0,
        author=SimpleNamespace(name=author) if author else None,
    )


class FakeCommentForest:
    def __init__(self, comments):
        self._comments = comments
        self.replace_more_calls = []

    def replace_more(self, limit):
        self.replace_more_calls.append(limit)

    def list(self):
        return list(self._comments)


def make_submission(pid, sub="WallStreetBets", score=10, author="alice", comments=()):
    return SimpleNamespace(
        id=pid, subreddit=SimpleNamespace(display_name=sub), title=f"$TSLA to the moon {pid}",
        selftext="DD inside", url=f"https://reddit.com/{pid}", permalink=f"/r/{sub}/comments/{pid}/",
        link_flair_text="DD", created_utc=1_700_000_000.9, score=score, upvote_ratio=0.9,
        num_comments=len(comments), is_self=True,
        author=SimpleNamespace(name=author) if author else None,
        comments=FakeCommentForest(list(comments)),
    )


class FakeSubreddit:
    def __init__(self, posts):
        self.posts = posts

    def new(self, limit):
        return iter(self.posts[:limit])

    hot = rising = new

    def top(self, time_filter, limit):
        return iter(self.posts[:limit])


class FakeReddit:
    def __init__(self, data, broken=()):
        self.data = data
        self.broken = set(broken)

    def subreddit(self, name):
        if name in self.broken:
            raise prawcore.exceptions.Forbidden(SimpleNamespace(status_code=403))
        return FakeSubreddit(self.data.get(name, []))


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()


def test_submission_to_dict_handles_deleted_author():
    d = submission_to_dict(make_submission("p1", author=None))
    assert d["author"] == "[deleted]"
    assert d["subreddit"] == "wallstreetbets"
    assert d["created_utc"] == 1_700_000_000
    assert d["permalink"].startswith("https://www.reddit.com/r/")


def test_comment_to_dict():
    d = comment_to_dict(make_comment("c1", author=None), "p1", "stocks")
    assert d == {"id": "c1", "post_id": "p1", "subreddit": "stocks", "parent_id": "t3_p1",
                 "body": "nice", "author": "[deleted]", "score": 1, "created_utc": 1_700_000_100}


def test_recollect_updates_score_and_keeps_first_seen(storage):
    reddit = FakeReddit({"wsb": [make_submission("p1", score=10)]})
    first = collect_once(reddit, storage, ["wsb"], clock=lambda: 1000)
    assert first["posts_new"] == 1

    reddit.data["wsb"] = [make_submission("p1", score=500), make_submission("p2")]
    second = collect_once(reddit, storage, ["wsb"], clock=lambda: 2000)
    assert second["posts_seen"] == 2 and second["posts_new"] == 1

    row = storage.conn.execute("SELECT * FROM posts WHERE id='p1'").fetchone()
    assert row["score"] == 500
    assert row["first_seen_utc"] == 1000
    assert row["last_updated_utc"] == 2000

    snaps = storage.conn.execute(
        "SELECT collected_utc, score FROM post_snapshots WHERE post_id='p1' ORDER BY collected_utc"
    ).fetchall()
    assert [tuple(s) for s in snaps] == [(1000, 10), (2000, 500)]


def test_comments_collected_with_limit(storage):
    post = make_submission("p1", comments=[make_comment(f"c{i}") for i in range(5)])
    reddit = FakeReddit({"wsb": [post]})
    summary = collect_once(reddit, storage, ["wsb"], comments=3, clock=lambda: 1000)
    assert summary["comments_new"] == 3
    assert post.comments.replace_more_calls == [0]
    assert storage.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 3


def test_comments_skipped_by_default(storage):
    post = make_submission("p1", comments=[make_comment("c1")])
    collect_once(FakeReddit({"wsb": [post]}), storage, ["wsb"], clock=lambda: 1000)
    assert post.comments.replace_more_calls == []


def test_one_failing_subreddit_does_not_stop_others(storage):
    reddit = FakeReddit({"stocks": [make_submission("p1", sub="stocks")]}, broken={"private_sub"})
    summary = collect_once(reddit, storage, ["private_sub", "stocks"], clock=lambda: 1000)
    assert summary["errors"] == 1
    assert summary["posts_new"] == 1


def test_stats(storage):
    reddit = FakeReddit({"wsb": [make_submission("p1", comments=[make_comment("c1")])]})
    collect_once(reddit, storage, ["wsb"], comments=10, clock=lambda: 1000)
    (row,) = storage.stats()
    assert (row["subreddit"], row["posts"], row["comments"]) == ("wallstreetbets", 1, 1)


def test_auth_error_stops_collection(storage):
    class AuthFailReddit(FakeReddit):
        def subreddit(self, name):
            raise prawcore.exceptions.ResponseException(SimpleNamespace(status_code=401))

    with pytest.raises(prawcore.exceptions.ResponseException):
        collect_once(AuthFailReddit({}), storage, ["wsb", "stocks"], clock=lambda: 1000)
