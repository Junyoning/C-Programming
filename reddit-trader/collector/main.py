"""수집기 실행 진입점.

사용 예
    python -m collector collect                          # 1회 수집
    python -m collector collect --interval 600           # 10분마다 반복 수집
    python -m collector collect -s wallstreetbets --sort hot --limit 50 --comments 20
    python -m collector stats                            # DB에 쌓인 데이터 요약
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Callable

import prawcore

from collector.config import ConfigError, load_db_path, load_settings
from collector.reddit_client import (
    SORTS,
    comment_to_dict,
    create_reddit,
    fetch_comments,
    fetch_submissions,
    submission_to_dict,
)
from collector.storage import Storage

log = logging.getLogger("collector")

# 서브레딧 하나가 실패해도(비공개 전환, 일시적 장애 등) 나머지는 계속 수집한다.
RECOVERABLE_ERRORS = (prawcore.exceptions.PrawcoreException,)


def _is_auth_error(exc: Exception) -> bool:
    """401(잘못된 키) 오류는 다른 서브레딧에서도 똑같이 실패하므로 즉시 중단한다."""
    if isinstance(exc, prawcore.exceptions.OAuthException):
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 401


def collect_once(reddit, storage: Storage, subreddits: list[str], sort: str = "new",
                 limit: int = 100, comments: int = 0, time_filter: str = "day",
                 clock: Callable[[], float] = time.time) -> dict:
    """모든 서브레딧을 한 번씩 수집하고 요약 정보를 반환한다."""
    summary = {"posts_seen": 0, "posts_new": 0, "comments_new": 0, "errors": 0}

    for name in subreddits:
        try:
            submissions = list(fetch_submissions(reddit, name, sort, limit, time_filter))
        except RECOVERABLE_ERRORS as exc:
            if _is_auth_error(exc):
                raise
            summary["errors"] += 1
            log.error("r/%s 게시글 수집 실패: %s", name, exc)
            continue

        now = int(clock())
        posts = [submission_to_dict(s) for s in submissions]
        new_posts = storage.upsert_posts(posts, now)
        summary["posts_seen"] += len(posts)
        summary["posts_new"] += new_posts

        new_comments = 0
        if comments > 0:
            for sub, post in zip(submissions, posts):
                try:
                    rows = [comment_to_dict(c, post["id"], post["subreddit"])
                            for c in fetch_comments(sub, comments)]
                except RECOVERABLE_ERRORS as exc:
                    summary["errors"] += 1
                    log.warning("게시글 %s 댓글 수집 실패: %s", post["id"], exc)
                    continue
                new_comments += storage.upsert_comments(rows, int(clock()))
        summary["comments_new"] += new_comments

        log.info("r/%-15s 게시글 %3d개 (신규 %3d) | 신규 댓글 %4d",
                 name, len(posts), new_posts, new_comments)

    return summary


def cmd_collect(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("%s", exc)
        return 1

    subreddits = args.subreddits or settings.subreddits
    reddit = create_reddit(settings)
    log.info("수집 대상: %s | 정렬=%s, 개수=%d, 댓글=%d, DB=%s",
             ", ".join(subreddits), args.sort, args.limit, args.comments, settings.db_path)

    with Storage(settings.db_path) as storage:
        while True:
            started = time.time()
            try:
                summary = collect_once(reddit, storage, subreddits, args.sort, args.limit,
                                       args.comments, args.time_filter)
            except RECOVERABLE_ERRORS as exc:
                # collect_once 가 다시 던지는 오류는 인증 오류뿐: 반복해도 해결되지 않으므로 종료
                log.error("Reddit 인증/응답 오류: %s (.env 의 키 값을 확인하세요)", exc)
                return 1
            log.info("완료: 게시글 %d개 확인, 신규 게시글 %d, 신규 댓글 %d, 오류 %d (%.1f초)",
                     summary["posts_seen"], summary["posts_new"], summary["comments_new"],
                     summary["errors"], time.time() - started)

            if args.interval <= 0:
                return 0
            wait = max(0.0, args.interval - (time.time() - started))
            log.info("%.0f초 후 다시 수집합니다 (중지: Ctrl+C)", wait)
            time.sleep(wait)


def cmd_stats(args: argparse.Namespace) -> int:
    db_path = load_db_path()
    if not db_path.exists():
        print(f"DB가 아직 없습니다: {db_path}")
        return 1
    with Storage(db_path) as storage:
        rows = storage.stats()
    if not rows:
        print("수집된 게시글이 없습니다.")
        return 0
    print(f"{'subreddit':<16}{'posts':>8}{'comments':>10}  {'oldest (UTC)':<20}{'newest (UTC)':<20}")
    for r in rows:
        print(f"{r['subreddit']:<16}{r['posts']:>8}{r['comments']:>10}  "
              f"{r['oldest_utc']:<20}{r['newest_utc']:<20}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="collector", description="Reddit 주식 게시글 수집기")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그 출력")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="게시글/댓글 수집")
    c.add_argument("-s", "--subreddits", nargs="+", help="수집할 서브레딧 (기본: .env 의 SUBREDDITS)")
    c.add_argument("--sort", choices=SORTS, default="new", help="정렬 방식 (기본: new)")
    c.add_argument("--limit", type=int, default=100, help="서브레딧당 게시글 수 (기본: 100, 최대 약 1000)")
    c.add_argument("--comments", type=int, default=0,
                   help="게시글당 수집할 댓글 수 (기본: 0). 게시글마다 API 요청이 1회 추가됨")
    c.add_argument("--time-filter", default="day",
                   choices=("hour", "day", "week", "month", "year", "all"),
                   help="--sort top 일 때 기간 (기본: day)")
    c.add_argument("--interval", type=int, default=0,
                   help="반복 수집 간격(초). 0이면 1회만 실행 (기본: 0)")
    c.set_defaults(func=cmd_collect)

    s = sub.add_parser("stats", help="DB에 쌓인 데이터 요약")
    s.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log.info("사용자가 중지했습니다.")
        return 0
