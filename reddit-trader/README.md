# reddit-trader

Reddit 주식 커뮤니티 글을 기반으로 한 자동매매 프로젝트입니다.

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | Reddit 데이터 수집기 (`collector/`) | ✅ |
| 2 | 티커 추출 / 감성 분석 | ⏳ |
| 3 | 주가 데이터 수집 | ⏳ |
| 4 | 전략 + 백테스트 | ⏳ |
| 5 | 리스크 관리 | ⏳ |
| 6 | 모의투자 | ⏳ |
| 7 | 모니터링 / 실거래 | ⏳ |

## 1단계: Reddit 수집기

### 1. Reddit API 키 발급

1. https://www.reddit.com/prefs/apps 에 로그인한 뒤 **create another app...** 를 누릅니다.
2. 이름은 자유롭게 입력하고 타입은 **script**를 선택합니다. redirect uri에는 `http://localhost:8080` 을 넣습니다.
3. 앱 이름 아래 보이는 짧은 문자열이 `client_id`, **secret** 항목이 `client_secret` 입니다.
4. Reddit의 [Data API 약관](https://support.reddithelp.com/hc/en-us/articles/16160319875092)을 확인하세요. 비상업적 개인 용도는 무료이고, 요청 한도는 분당 약 100회입니다.

### 2. 설치

```bash
cd reddit-trader
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # 그다음 .env 에 키 입력
```

### 3. 실행

```bash
# 1회 수집 (.env 의 SUBREDDITS 대상, 최신글 100개씩)
python -m collector collect

# 10분마다 반복 수집 (데이터 축적용, Ctrl+C로 중지)
python -m collector collect --interval 600

# 특정 서브레딧의 인기글 50개 + 글마다 댓글 20개
python -m collector collect -s wallstreetbets stocks --sort hot --limit 50 --comments 20

# 하루 동안의 추천순 상위글
python -m collector collect --sort top --time-filter day

# 쌓인 데이터 확인
python -m collector stats
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `-s, --subreddits` | `.env` 의 `SUBREDDITS` | 수집할 서브레딧 |
| `--sort` | `new` | `new` / `hot` / `rising` / `top` |
| `--limit` | `100` | 서브레딧당 게시글 수 (Reddit은 목록당 최대 약 1000개까지만 제공) |
| `--comments` | `0` | 게시글당 댓글 수. **글마다 API 요청이 1회 추가**되므로 늘리면 수집이 느려집니다 |
| `--time-filter` | `day` | `--sort top` 일 때 기간 |
| `--interval` | `0` | 반복 간격(초). 0이면 1회만 실행 |

> 💡 과거 Reddit 데이터는 나중에 구하기 어렵습니다. 4단계에서 백테스트를 하려면
> `--interval 600` 으로 **지금부터 꾸준히** 쌓아두는 것이 좋습니다.
> 서버나 상시 켜둔 PC에서 `nohup`, `tmux`, cron, 작업 스케줄러 등으로 돌리세요.

### 4. 저장 구조 (SQLite: `data/reddit.db`)

- **posts**: 게시글. 같은 글을 다시 수집하면 점수, 댓글 수, 본문이 갱신되고 `first_seen_utc`(처음 본 시각)는 유지됩니다.
- **comments**: 댓글 (`post_id` 로 게시글과 연결)
- **post_snapshots**: 수집할 때마다 (점수, 추천율, 댓글 수)를 시각과 함께 기록합니다.
  백테스트에서 "그 시점에 실제로 알 수 있었던 값"만 쓰기 위한 테이블입니다 (미래 정보 누출 방지).

```sql
-- 예: 최근 24시간 동안 wallstreetbets 에서 추천이 많은 글
SELECT title, score, num_comments, datetime(created_utc, 'unixepoch') AS created
FROM posts
WHERE subreddit = 'wallstreetbets' AND created_utc > strftime('%s', 'now', '-1 day')
ORDER BY score DESC LIMIT 20;
```

### 5. 테스트

```bash
pytest
```

테스트는 가짜 Reddit 객체를 사용하므로 API 키나 네트워크 없이도 실행됩니다.

## 주의

- `.env`(API 키)와 `data/*.db` 는 `.gitignore` 에 포함되어 있습니다. 절대 커밋하지 마세요.
- 이 프로젝트는 학습용입니다. 실제 투자 손실의 책임은 본인에게 있습니다.
