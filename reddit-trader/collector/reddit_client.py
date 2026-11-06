"""PRAW로 Reddit에서 게시글/댓글을 가져와 dict로 변환한다.

PRAW는 Reddit API 요청 한도(rate limit)를 자동으로 지켜주므로 별도의 sleep이 필요 없다.
"""
from __future__ import annotations

import logging
from typing import Iterator

import praw

from collector.config import Settings

log = logging.getLogger(__name__)

SORTS = ("new", "hot", "rising", "top")


def create_reddit(settings: Settings) -> praw.Reddit:
    reddit = praw.Reddit(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        user_agent=settings.user_agent,
    )
    reddit.read_only = True  # 읽기 전용: 로그인 비밀번호 불필요
    return reddit


def _author_name(obj) -> str:
    # 삭제된 계정은 author가 None
    return obj.author.name if getattr(obj, "author", None) is not None else "[deleted]"


def submission_to_dict(sub) -> dict:
    return {
        "id": sub.id,
        "subreddit": sub.subreddit.display_name.lower(),
        "title": sub.title,
        "selftext": sub.selftext or "",
        "author": _author_name(sub),
        "url": sub.url,
        "permalink": f"https://www.reddit.com{sub.permalink}",
        "flair": sub.link_flair_text,
        "created_utc": int(sub.created_utc),
        "score": sub.score,
        "upvote_ratio": sub.upvote_ratio,
        "num_comments": sub.num_comments,
        "is_self": int(bool(sub.is_self)),
    }


def comment_to_dict(comment, post_id: str, subreddit: str) -> dict:
    return {
        "id": comment.id,
        "post_id": post_id,
        "subreddit": subreddit,
        "parent_id": comment.parent_id,
        "body": comment.body,
        "author": _author_name(comment),
        "score": comment.score,
        "created_utc": int(comment.created_utc),
    }


def fetch_submissions(reddit: praw.Reddit, subreddit: str, sort: str = "new",
                      limit: int = 100, time_filter: str = "day") -> Iterator:
    """서브레딧의 게시글을 가져온다. Reddit API는 한 목록당 최대 약 1000개까지만 제공한다."""
    if sort not in SORTS:
        raise ValueError(f"sort는 {SORTS} 중 하나여야 합니다: {sort!r}")
    sr = reddit.subreddit(subreddit)
    if sort == "top":
        return sr.top(time_filter=time_filter, limit=limit)
    return getattr(sr, sort)(limit=limit)


def fetch_comments(submission, limit: int) -> list:
    """게시글의 댓글을 추천순으로 최대 limit개 가져온다 (게시글당 API 요청 1회 추가)."""
    if limit <= 0:
        return []
    submission.comment_sort = "top"
    # "더 보기(MoreComments)"는 펼치지 않는다: 펼칠 때마다 API 요청이 추가로 발생함
    submission.comments.replace_more(limit=0)
    return submission.comments.list()[:limit]
