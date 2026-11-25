#!/usr/bin/env python3
"""Fetch a private ESPN basketball league and publish an explicitly selected snapshot."""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

LEAGUE = 56429990
today = dt.datetime.now(dt.timezone.utc).date()
YEAR = int(os.environ.get('ESPN_SEASON', str(today.year + (today.month >= 10))))
ROOT = f'https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{YEAR}/segments/0/leagues/{LEAGUE}'

def fetch(views, filters=None, params=None):
    s2, swid = os.environ.get('ESPN_S2'), os.environ.get('ESPN_SWID')
    if not s2 or not swid:
        raise RuntimeError('缺少 ESPN_S2 或 ESPN_SWID，未进行同步。')
    headers = {'Cookie': f'espn_s2={s2}; SWID={swid}', 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    if filters:
        headers['x-fantasy-filter'] = json.dumps(filters, separators=(',', ':'))
    url = ROOT + '?' + urllib.parse.urlencode([('view', v) for v in views] + list((params or {}).items()))
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)

def snapshot(league, player_data, scoreboard=None):
    current = league.get('status', {}).get('currentMatchupPeriod')
    if current is None:
        raise ValueError('ESPN 没有返回当前对阵周期')
    teams = []
    for t in league.get('teams', []):
        overall = t.get('record', {}).get('overall', {})
        teams.append({'id': t['id'], 'name': t.get('name') or (str(t.get('location', '')) + ' ' + str(t.get('nickname', ''))).strip() or f"球队 {t['id']}", 'wins': overall.get('wins', 0), 'losses': overall.get('losses', 0), 'ties': overall.get('ties', 0), 'points_for': overall.get('pointsFor'), 'standing': t.get('playoffSeed')})
    if len(teams) != 8:
        raise ValueError('ESPN 没有返回预期的八支球队；保留旧数据。')
    matchups = []
    score_games = { (m.get('home', {}).get('teamId'), m.get('away', {}).get('teamId')): m for m in (scoreboard or {}).get('schedule', []) }
    for m in league.get('schedule', []):
        if m.get('matchupPeriodId') != current or 'home' not in m or 'away' not in m:
            continue
        detailed = score_games.get((m['home'].get('teamId'), m['away'].get('teamId')), {})
        def side(s, detail):
            p = detail.get('totalProjectedPointsLive')
            return {'team_id': s.get('teamId'), 'score': s.get('totalPointsLive', s.get('totalPoints')), 'projected': p if isinstance(p, (int, float)) and p >= 0 else None}
        matchups.append({'home': side(m['home'], detailed.get('home', {})), 'away': side(m['away'], detailed.get('away', {}))})
    players = []
    for item in player_data.get('players', []):
        p = item.get('player', {})
        if not p.get('fullName'):
            continue
        stat = next((s for s in p.get('stats', []) if s.get('seasonId') == YEAR and str(s.get('id', '')).startswith('00')), {})
        recent = next((s for s in p.get('stats', []) if s.get('seasonId') == YEAR and str(s.get('id', '')).startswith('02')), {})
        players.append({'recent_average': recent.get('appliedAverage'), 'recent_games': recent.get('stats', {}).get('42'), 'id': p.get('id'), 'name': p['fullName'], 'position_id': p.get('defaultPositionId'), 'status': item.get('status'), 'injury': p.get('injuryStatus'), 'season_average': stat.get('appliedAverage')})
    return {'updated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'season': YEAR, 'matchup_period': current, 'teams': teams, 'matchups': matchups, 'players': players, 'notice': '数据来自 ESPN，预计得分和近 15 天数据仅在 ESPN 返回时显示。推荐仅供参考。'}

def main():
    league = fetch(['mTeam', 'mMatchup', 'mScoreboard', 'mSettings'])
    players = fetch(['kona_player_info'], {'players': {'filterStatus': {'value': ['FREEAGENT', 'WAIVERS']}, 'limit': 100, 'sortPercOwned': {'sortPriority': 1, 'sortAsc': False}}})
    current = league.get('status', {}).get('currentMatchupPeriod')
    scoring = league.get('scoringPeriodId') or league.get('status', {}).get('currentScoringPeriod')
    try:
        scoreboard = fetch(['mMatchupScore', 'mScoreboard'], {'schedule': {'filterMatchupPeriodIds': {'value': [current]}}}, {'scoringPeriodId': scoring} if scoring else None)
    except Exception:
        scoreboard = {}
    data = snapshot(league, players, scoreboard)
    out = Path(__file__).parent / 'site' / 'data.json'
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(out)
    print('同步成功：', len(data['teams']), '支球队，', len(data['players']), '名可用球员。')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('同步失败，未替换已有数据。', type(exc).__name__, file=sys.stderr)
        sys.exit(1)
