# NHL Database Schemas

**Database:** `nhl_betting` on `localhost:5432`

---

## Core Game Data

### `games` — 5,936 rows
| Column | Type | Description |
|--------|------|-------------|
| game_id | int PK | NHL API game ID |
| season | int | e.g. 20242025 |
| game_type | int | 2=regular, 3=playoff |
| game_date | text | YYYY-MM-DD |
| game_state | text | OFF, LIVE, FUT |
| venue | text | Arena name |
| home_team_id / away_team_id | int | FK → teams |
| home_score / away_score | int | Final scores |
| home_sog / away_sog | int | Shots on goal |
| winning_goalie_id / losing_goalie_id | int | FK → players |
| decide_by | text | REG, OT, SO |

### `schedules` — 5,936 rows
| Column | Type | Description |
|--------|------|-------------|
| game_id | int PK | FK → games |
| season, game_type, game_date | — | Same as games |
| home_team_id / away_team_id | int | FK → teams |
| venue | text | Arena |
| neutral_site | int | 0/1 |

### `teams` — 34 rows
| Column | Type | Description |
|--------|------|-------------|
| team_id | int PK | NHL team ID |
| tri_code | text | e.g. TOR, NYR |
| team_name | text | Full name |
| conference_name / division_name | text | Conference/division |
| active | int | 0/1 |

### `players` — 2,312 rows
| Column | Type | Description |
|--------|------|-------------|
| player_id | int PK | NHL player ID |
| first_name / last_name | text | Name |
| position_code | text | C, L, R, D, G |
| height_in / weight_lb | int | Physical |
| birth_date | text | YYYY-MM-DD |
| current_team_id | int | FK → teams |

---

## Game-Level Stats

### `game_team_stats` — 11,058 rows
Per-team stats for each game. **Key table for Corsi/possession derivation.**
| Column | Type | Description |
|--------|------|-------------|
| game_id | int PK | FK → games |
| team_id | int PK | FK → teams |
| shots_on_goal | int | SOG |
| **shots_attempted** | **int** | **= Corsi For proxy** |
| blocked_shots | int | Blocks by this team |
| faceoff_win_pct | float | Faceoff % |
| hits | int | Hits |
| takeaways / giveaways | int | Puck control |
| power_play_goals / power_play_opportunities | int | PP stats |
| pim | int | Penalty minutes |
| toi_minutes | float | Time on ice |
| score | int | Goals scored |
| won | int | 0/1 |

### `player_stats` — 199,006 rows
Per-player per-game skater stats.
| Column | Type | Description |
|--------|------|-------------|
| game_id / player_id | int PK | Composite key |
| team_id | int | FK → teams |
| position_code | text | C, L, R, D |
| toi_minutes | float | Ice time |
| goals / assists / points | int | Scoring |
| plus_minus | int | +/- |
| shots | int | SOG |
| hits / blocked_shots | int | Physical |
| takeaways / giveaways | int | Puck control |
| power_play_goals / power_play_points | int | PP production |
| faceoff_win_pct | float | FO % |

### `period_scores` — 36,342 rows
| Column | Type | Description |
|--------|------|-------------|
| game_id / team_id / period_number | int PK | Composite key |
| period_descriptor | text | REG, OT |
| goals | int | Goals in period |

### `lineup_absences` — 11,051 rows
Missing players per team per game.
| Column | Type | Description |
|--------|------|-------------|
| game_id / team_id | int PK | Composite key |
| fwd_missing / def_missing | int | Count missing |
| fwd_missing_toi / def_missing_toi | float | Missing player avg TOI |
| total_missing / total_missing_toi | int/float | Totals |
| top_missing_player_id | int | Biggest absence |

---

## Goalie Stats

### `goalie_stats` — 22,114 rows
Core goalie box score stats.
| Column | Type | Description |
|--------|------|-------------|
| game_id / player_id | int PK | Composite key |
| team_id | int | FK → teams |
| shots_against / saves / goals_against | int | Core stats |
| save_pct | float | Save percentage |
| even_strength_saves / power_play_saves / shorthanded_saves | int | By strength |
| decision | text | W, L, O |
| started / pulled | int | 0/1 flags |
| toi_minutes | float | Time on ice |

### `goalie_advanced` — 9,481 rows
| Column | Type | Description |
|--------|------|-------------|
| game_id / player_id | int PK | Composite key |
| games_started / quality_start | int | Start info |
| goals_against / goals_against_avg | int/float | GA stats |
| goals_for / goals_for_avg | int/float | Run support |
| shots_against_per60 | float | Workload rate |
| complete_games / incomplete_games | int | Pull detection |
| time_on_ice | text | MM:SS format |

### `goalie_saves_by_strength` — 9,957 rows
EV/PP/SH save splits.
| Column | Type | Description |
|--------|------|-------------|
| game_id / player_id | int PK | Composite key |
| ev_saves / ev_shots / ev_save_pct | int/float | Even strength |
| pp_saves / pp_shots / pp_save_pct | int/float | Power play |
| sh_saves / sh_shots / sh_save_pct | int/float | Shorthanded |
| total_saves / total_shots / total_save_pct | int/float | Totals |

### `goalie_starts` — 9,212 rows
Starter vs reliever splits.
| Column | Type | Description |
|--------|------|-------------|
| game_id / player_id | int PK | Composite key |
| games_started / games_relieved | int | Role |
| started_saves / started_shots / started_save_pct | int/float | As starter |
| relieved_saves / relieved_shots / relieved_save_pct | int/float | As reliever |

---

## Betting Odds

### `saves_odds` — 44,464 rows
Goalie saves over/under lines. **Primary table for our strategies.**
| Column | Type | Description |
|--------|------|-------------|
| id | int PK | Auto-increment |
| event_id / event_date | int/text | Game reference |
| player_name / player_team | text | Goalie info |
| book_name | text | Sportsbook (consensus, fanduel, etc.) |
| line | float | Saves line (e.g. 25.5) |
| over_odds / under_odds | int | American odds |
| opening_line / opening_over_odds | float/int | Opening values |
| fair_probability / market_ev | float | Derived values |

### `sog_odds` — 173,985 rows
Shots on goal player props.
| Column | Type | Description |
|--------|------|-------------|
| Same schema as saves_odds | — | But for SOG market |
| player_position | text | Position filter |

### `player_odds` — 212,387 rows
Multi-market player props (goals, assists, points, etc.).
| Column | Type | Description |
|--------|------|-------------|
| market | text | goals, assists, points, etc. |
| Same schema as saves_odds | — | With position field |

### `team_odds` — 22,934 rows
Team-level odds (spreads, totals, moneylines).
| Column | Type | Description |
|--------|------|-------------|
| market | text | spread, total, moneyline |
| team_name | text | Team |
| line / over_odds / under_odds | float/int | Odds |

---

## Other

### `standings` — 7,616 rows
Daily team standings snapshots.
| Column | Type | Description |
|--------|------|-------------|
| standing_date / team_id | text/int PK | Composite |
| points / wins / losses / ot_losses | int | Record |
| goals_for / goals_against / goal_diff | int | Goal stats |
| conference_rank / division_rank / league_rank | int | Rankings |
| points_pct | float | Points percentage |

### `injuries` — 26 rows / `injuries_live` — 94 rows
Injury reports from NHL API and ESPN scraper.

### `kanban_tasks` / `kanban_events` — Internal task tracking (11/10 rows)
### `model_runs` / `predictions` / `live_game_snapshots` / `api_snapshots` — Empty or infrastructure tables
